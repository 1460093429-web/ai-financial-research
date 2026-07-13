"""Pure adapters for caller-injected Memory Cycle metric observations.

The adapters in this module do not fetch data.  They only validate explicit
metadata supplied by a caller and translate it into the 15-field contract in
``services.memory_cycle_contract``.
"""

import math
from numbers import Real

from services.memory_cycle_contract import (
    CONFIDENCE_LEVELS,
    FREQUENCIES,
    METRIC_AVAILABILITY,
    NEWS_SIGNAL_VALUES,
    SOURCE_TYPES,
    build_metric_record,
    calculate_staleness_days,
    validate_metric_record,
)


SUPPORTED_COMPANIES = frozenset({"MU", "SNDK"})
FISCAL_PERIODS = frozenset({"annual", "quarterly"})
_DAILY_BRIEF_SOURCE_MARKERS = (
    "daily brief",
    "daily news brief",
    "今日科技与半导体要点",
)


def _text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _finite_number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _contract_shape(metric_id, requested_source_type, requested_frequency):
    audit = METRIC_AVAILABILITY.get(metric_id)
    if audit:
        return audit["source_type"], audit["frequency"], audit["availability"]
    source_type = (
        requested_source_type
        if isinstance(requested_source_type, str) and requested_source_type in SOURCE_TYPES
        else "direct"
    )
    frequency = (
        requested_frequency
        if isinstance(requested_frequency, str) and requested_frequency in FREQUENCIES
        else "event_driven"
    )
    return source_type, frequency, None


def _timestamps_are_valid(as_of, retrieved_at, evaluated_at):
    as_of = _text(as_of)
    retrieved_at = _text(retrieved_at)
    evaluated_at = _text(evaluated_at)
    if not all((as_of, retrieved_at, evaluated_at)):
        return False
    if calculate_staleness_days(as_of, as_of) != 0:
        return False
    if calculate_staleness_days(retrieved_at, retrieved_at) != 0:
        return False
    if calculate_staleness_days(evaluated_at, evaluated_at) != 0:
        return False
    if calculate_staleness_days(as_of, retrieved_at) is None:
        return False
    return calculate_staleness_days(retrieved_at, evaluated_at) is not None


def build_unavailable_metric(
    *,
    metric_id,
    label,
    notes=None,
    source_type="direct",
    frequency="event_driven",
):
    """Return a valid contract record for a metric with no verified source."""

    metric_id = _text(metric_id) or "unavailable_metric"
    label = _text(label) or metric_id
    source_type, frequency, _ = _contract_shape(metric_id, source_type, frequency)
    notes = _text(notes) or "Unavailable: no verified source or observation."
    return build_metric_record(
        metric_id=metric_id,
        label=label,
        value=None,
        unit=None,
        as_of=None,
        retrieved_at=None,
        source="unavailable",
        source_type=source_type,
        frequency=frequency,
        is_fallback=False,
        is_estimate=False,
        confidence="low",
        status="unavailable",
        notes=notes,
    )


def _missing_metric(
    *,
    metric_id,
    label,
    unit,
    source,
    source_type,
    frequency,
    reasons,
    as_of=None,
    retrieved_at=None,
    evaluated_at=None,
    is_fallback=False,
    is_estimate=False,
):
    metric_id = _text(metric_id) or "missing_metric"
    label = _text(label) or metric_id
    source_type, frequency, availability = _contract_shape(
        metric_id, source_type, frequency
    )
    reason_text = "; ".join(str(reason) for reason in reasons if reason) or "invalid input"
    if availability == "E":
        return build_unavailable_metric(
            metric_id=metric_id,
            label=label,
            source_type=source_type,
            frequency=frequency,
            notes=f"Unavailable: {reason_text}",
        )

    safe_as_of = safe_retrieved_at = safe_evaluated_at = None
    if _timestamps_are_valid(as_of, retrieved_at, evaluated_at):
        safe_as_of = _text(as_of)
        safe_retrieved_at = _text(retrieved_at)
        safe_evaluated_at = _text(evaluated_at)

    return build_metric_record(
        metric_id=metric_id,
        label=label,
        value=None,
        unit=_text(unit),
        as_of=safe_as_of,
        retrieved_at=safe_retrieved_at,
        source=_text(source) or "unavailable",
        source_type=source_type,
        frequency=frequency,
        is_fallback=is_fallback if isinstance(is_fallback, bool) else False,
        is_estimate=bool(is_estimate),
        confidence="low",
        status="missing",
        notes=f"Missing: {reason_text}",
        evaluated_at=safe_evaluated_at,
    )


def _validated_record_or_missing(record, *, evaluated_at, missing_kwargs):
    errors = validate_metric_record(record, evaluated_at=evaluated_at)
    if not errors:
        return record
    return _missing_metric(reasons=errors, evaluated_at=evaluated_at, **missing_kwargs)


def adapt_company_financial_metric(
    *,
    ticker=None,
    metric_id=None,
    label=None,
    value=None,
    unit=None,
    currency=None,
    currency_required=False,
    fiscal_period=None,
    as_of=None,
    retrieved_at=None,
    source=None,
    source_field=None,
    source_document=None,
    provenance=None,
    frequency=None,
    evaluated_at=None,
    is_fallback=False,
    confidence="medium",
):
    """Adapt an explicitly sourced MU/SNDK financial observation.

    ``fiscal_period`` describes the reported period.  ``frequency`` remains
    the metric contract cadence; the adapter never derives one from the other.
    """

    ticker_text = _text(ticker)
    ticker_key = ticker_text.upper() if ticker_text else None
    metric_id_text = _text(metric_id)
    label_text = _text(label)
    unit_text = _text(unit)
    currency_text = _text(currency)
    fiscal_period_text = _text(fiscal_period)
    fiscal_period_key = fiscal_period_text.lower() if fiscal_period_text else None
    source_text = _text(source)
    source_field_text = _text(source_field)
    source_document_text = _text(source_document)
    provenance_text = _text(provenance)
    frequency_text = _text(frequency)
    source_type, contract_frequency, availability = _contract_shape(
        metric_id_text, "company_reported", frequency_text
    )

    if availability == "E":
        return build_unavailable_metric(
            metric_id=metric_id_text,
            label=label_text,
            source_type=source_type,
            frequency=contract_frequency,
            notes="Unavailable: the current source audit does not approve this metric for production use.",
        )

    errors = []
    if ticker_key not in SUPPORTED_COMPANIES:
        errors.append("ticker must explicitly identify MU or SNDK")
    if not metric_id_text:
        errors.append("metric_id is required")
    if not label_text:
        errors.append("label is required")
    if not _finite_number(value):
        errors.append("value must be a finite numeric observation")
    if not unit_text:
        errors.append("unit is required")
    if not isinstance(currency_required, bool):
        errors.append("currency_required must be boolean")
    elif currency_required and not currency_text:
        errors.append("currency is required for this monetary metric")
    if fiscal_period_key not in FISCAL_PERIODS:
        errors.append("fiscal_period must explicitly be annual or quarterly")
    if not source_text:
        errors.append("source is required")
    if not source_field_text:
        errors.append("source_field is required")
    if not (source_document_text or provenance_text):
        errors.append("source_document or provenance is required")
    if frequency_text not in FREQUENCIES:
        errors.append("frequency is required and must be a contract frequency")
    elif frequency_text != contract_frequency:
        errors.append(f"frequency must match the source audit: {contract_frequency}")
    if not _timestamps_are_valid(as_of, retrieved_at, evaluated_at):
        errors.append("as_of, retrieved_at, and evaluated_at must be explicit and ordered")
    if not isinstance(is_fallback, bool):
        errors.append("is_fallback must be boolean")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        errors.append("confidence must be low, medium, or high")

    missing_kwargs = {
        "metric_id": metric_id_text,
        "label": label_text,
        "unit": unit_text,
        "source": source_text,
        "source_type": source_type,
        "frequency": contract_frequency,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "is_fallback": is_fallback,
        "is_estimate": False,
    }
    if errors:
        return _missing_metric(
            reasons=errors, evaluated_at=evaluated_at, **missing_kwargs
        )

    evidence = source_document_text or provenance_text
    evidence_label = "Source document" if source_document_text else "Provenance"
    notes_parts = [
        f"Company: {ticker_key}",
        f"Fiscal period: {fiscal_period_key}",
        f"Unit: {unit_text}",
    ]
    if currency_text:
        notes_parts.append(f"Currency: {currency_text}")
    notes_parts.extend(
        [
            f"Source field: {source_field_text}",
            f"{evidence_label}: {evidence}",
            "Method: caller-injected company-reported field; no period, unit, currency, or source inference.",
        ]
    )
    record = build_metric_record(
        metric_id=metric_id_text,
        label=label_text,
        value=value,
        unit=unit_text,
        as_of=_text(as_of),
        retrieved_at=_text(retrieved_at),
        source=source_text,
        source_type=source_type,
        frequency=contract_frequency,
        is_fallback=is_fallback,
        is_estimate=False,
        confidence=confidence,
        notes="\n".join(notes_parts),
        evaluated_at=_text(evaluated_at),
    )
    return _validated_record_or_missing(
        record,
        evaluated_at=_text(evaluated_at),
        missing_kwargs=missing_kwargs,
    )


def adapt_market_proxy_metric(
    *,
    metric_id=None,
    label=None,
    value=None,
    unit=None,
    as_of=None,
    retrieved_at=None,
    source=None,
    method=None,
    frequency=None,
    evaluated_at=None,
    is_fallback=False,
    confidence="medium",
):
    """Adapt a market observation while retaining explicit proxy semantics."""

    metric_id_text = _text(metric_id)
    label_text = _text(label)
    unit_text = _text(unit)
    source_text = _text(source)
    method_text = _text(method)
    frequency_text = _text(frequency)
    source_type, contract_frequency, availability = _contract_shape(
        metric_id_text, "proxy", frequency_text
    )
    if availability == "E":
        return build_unavailable_metric(
            metric_id=metric_id_text,
            label=label_text,
            source_type=source_type,
            frequency=contract_frequency,
            notes="Unavailable: the current source audit does not approve this proxy metric for production use.",
        )

    errors = []
    if not metric_id_text:
        errors.append("metric_id is required")
    if not label_text:
        errors.append("label is required")
    if not _finite_number(value):
        errors.append("value must be a finite numeric observation")
    if not unit_text:
        errors.append("unit is required")
    if not source_text:
        errors.append("source is required")
    if not method_text:
        errors.append("method is required")
    if frequency_text not in FREQUENCIES:
        errors.append("frequency is required and must be a contract frequency")
    elif frequency_text != contract_frequency:
        errors.append(f"frequency must match the source audit: {contract_frequency}")
    if not _timestamps_are_valid(as_of, retrieved_at, evaluated_at):
        errors.append("as_of, retrieved_at, and evaluated_at must be explicit and ordered")
    if not isinstance(is_fallback, bool):
        errors.append("is_fallback must be boolean")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        errors.append("confidence must be low, medium, or high")

    missing_kwargs = {
        "metric_id": metric_id_text,
        "label": label_text,
        "unit": unit_text,
        "source": source_text,
        "source_type": source_type,
        "frequency": contract_frequency,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "is_fallback": is_fallback,
        "is_estimate": True,
    }
    if errors:
        return _missing_metric(
            reasons=errors, evaluated_at=evaluated_at, **missing_kwargs
        )

    effective_confidence = "medium" if confidence == "high" else confidence
    confidence_note = (
        " Requested high confidence was capped at medium for a proxy."
        if confidence == "high"
        else ""
    )
    notes = (
        f"Method: {method_text}. Proxy: market performance only; it is not a direct "
        "memory price, inventory, supply, demand, company fundamental, or cycle-phase "
        f"observation.{confidence_note}"
    )
    record = build_metric_record(
        metric_id=metric_id_text,
        label=label_text,
        value=value,
        unit=unit_text,
        as_of=_text(as_of),
        retrieved_at=_text(retrieved_at),
        source=source_text,
        source_type=source_type,
        frequency=contract_frequency,
        is_fallback=is_fallback,
        is_estimate=True,
        confidence=effective_confidence,
        notes=notes,
        evaluated_at=_text(evaluated_at),
    )
    return _validated_record_or_missing(
        record,
        evaluated_at=_text(evaluated_at),
        missing_kwargs=missing_kwargs,
    )


def adapt_news_signal_metric(
    *,
    metric_id=None,
    label=None,
    value=None,
    citation=None,
    source=None,
    as_of=None,
    retrieved_at=None,
    method=None,
    frequency=None,
    evaluated_at=None,
    is_fallback=False,
    confidence="medium",
):
    """Adapt a cited qualitative news signal without inventing a precise value."""

    metric_id_text = _text(metric_id)
    label_text = _text(label)
    value_text = _text(value)
    value_key = value_text.lower() if value_text else None
    citation_text = _text(citation)
    source_text = _text(source)
    method_text = _text(method)
    frequency_text = _text(frequency)
    source_type, contract_frequency, availability = _contract_shape(
        metric_id_text, "news_signal", frequency_text
    )
    if availability == "E" or value_key == "unavailable":
        return build_unavailable_metric(
            metric_id=metric_id_text,
            label=label_text,
            source_type=source_type,
            frequency=contract_frequency,
            notes="Unavailable: no independently cited qualitative observation was supplied.",
        )

    errors = []
    if not metric_id_text:
        errors.append("metric_id is required")
    if not label_text:
        errors.append("label is required")
    if value_key not in NEWS_SIGNAL_VALUES:
        errors.append("value must be a canonical qualitative news signal")
    if not citation_text:
        errors.append("citation is required")
    if not source_text:
        errors.append("source is required")
    elif any(marker in source_text.casefold() for marker in _DAILY_BRIEF_SOURCE_MARKERS):
        errors.append("Daily Brief is an aggregation, not an independent source")
    if not method_text:
        errors.append("method is required")
    if frequency_text not in FREQUENCIES:
        errors.append("frequency is required and must be a contract frequency")
    elif frequency_text != contract_frequency:
        errors.append(f"frequency must match the source audit: {contract_frequency}")
    if not _timestamps_are_valid(as_of, retrieved_at, evaluated_at):
        errors.append("as_of, retrieved_at, and evaluated_at must be explicit and ordered")
    if not isinstance(is_fallback, bool):
        errors.append("is_fallback must be boolean")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        errors.append("confidence must be low, medium, or high")

    missing_kwargs = {
        "metric_id": metric_id_text,
        "label": label_text,
        "unit": None,
        "source": source_text if not errors or source_text else "unavailable",
        "source_type": source_type,
        "frequency": contract_frequency,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "is_fallback": is_fallback,
        "is_estimate": False,
    }
    if errors:
        if source_text and any(
            marker in source_text.casefold() for marker in _DAILY_BRIEF_SOURCE_MARKERS
        ):
            missing_kwargs["source"] = "unavailable"
        return _missing_metric(
            reasons=errors, evaluated_at=evaluated_at, **missing_kwargs
        )

    effective_confidence = "medium" if confidence == "high" else confidence
    notes = (
        f"Citation: {citation_text}\n"
        f"Method: {method_text}; qualitative direction from the cited source, not a direct price series."
    )
    record = build_metric_record(
        metric_id=metric_id_text,
        label=label_text,
        value=value_key,
        unit=None,
        as_of=_text(as_of),
        retrieved_at=_text(retrieved_at),
        source=source_text,
        source_type=source_type,
        frequency=contract_frequency,
        is_fallback=is_fallback,
        is_estimate=False,
        confidence=effective_confidence,
        notes=notes,
        evaluated_at=_text(evaluated_at),
    )
    return _validated_record_or_missing(
        record,
        evaluated_at=_text(evaluated_at),
        missing_kwargs=missing_kwargs,
    )


_ADAPTERS = {
    "company_financial": adapt_company_financial_metric,
    "market_proxy": adapt_market_proxy_metric,
    "news_signal": adapt_news_signal_metric,
    "unavailable": build_unavailable_metric,
}


def adapt_memory_cycle_metrics(items):
    """Adapt ordered call specifications without mutating the input sequence.

    Each dictionary must contain an ``adapter`` key naming one of
    ``company_financial``, ``market_proxy``, ``news_signal``, or ``unavailable``.
    Invalid elements produce an unavailable placeholder in the same position.
    """

    if not isinstance(items, (list, tuple)):
        return []

    records = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            records.append(
                build_unavailable_metric(
                    metric_id=f"invalid_adapter_item_{index}",
                    label="Invalid adapter item",
                    notes="Unavailable: batch item must be a dictionary.",
                )
            )
            continue

        payload = dict(item)
        adapter_name = payload.pop("adapter", None)
        adapter = _ADAPTERS.get(adapter_name) if isinstance(adapter_name, str) else None
        if adapter is None:
            records.append(
                build_unavailable_metric(
                    metric_id=payload.get("metric_id") or f"invalid_adapter_item_{index}",
                    label=payload.get("label") or "Invalid adapter item",
                    notes="Unavailable: batch item has an unknown adapter.",
                )
            )
            continue
        try:
            records.append(adapter(**payload))
        except (TypeError, ValueError):
            records.append(
                build_unavailable_metric(
                    metric_id=payload.get("metric_id") or f"invalid_adapter_item_{index}",
                    label=payload.get("label") or "Invalid adapter item",
                    notes="Unavailable: batch adapter arguments are invalid.",
                )
            )
    return records


__all__ = [
    "adapt_company_financial_metric",
    "adapt_market_proxy_metric",
    "adapt_memory_cycle_metrics",
    "adapt_news_signal_metric",
    "build_unavailable_metric",
]
