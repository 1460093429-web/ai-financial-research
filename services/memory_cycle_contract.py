"""Pure data contract and audited capability registry for Memory Cycle planning.

This module intentionally performs no provider calls, file access, secret lookup,
cache access, or Streamlit rendering. It records what the repository can and
cannot currently support; it is not a production data pipeline.
"""

import math
from datetime import date, datetime, timezone
from numbers import Real
from typing import Any, Literal, TypedDict


SourceType = Literal["direct", "company_reported", "news_signal", "proxy"]
Frequency = Literal["daily", "weekly", "monthly", "quarterly", "event_driven"]
Confidence = Literal["high", "medium", "low"]
MetricStatus = Literal["ok", "stale", "missing", "unavailable"]


SOURCE_TYPES = frozenset({"direct", "company_reported", "news_signal", "proxy"})
FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "event_driven"})
CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})
METRIC_STATUSES = frozenset({"ok", "stale", "missing", "unavailable"})
AVAILABILITY_CLASSES = frozenset({"A", "B", "C", "D", "E"})
NEWS_SIGNAL_VALUES = frozenset({
    "improving",
    "stable",
    "weakening",
    "strong",
    "mixed",
    "weak",
    "disciplined",
    "neutral",
    "aggressive",
    "elevated",
    "deteriorating",
    "expanding",
    "contracting",
    "tightening",
    "easing",
    "increasing",
    "decreasing",
    "positive",
    "negative",
})

REQUIRED_METRIC_FIELDS = (
    "metric_id",
    "label",
    "value",
    "unit",
    "as_of",
    "retrieved_at",
    "source",
    "source_type",
    "frequency",
    "is_fallback",
    "is_estimate",
    "staleness_days",
    "confidence",
    "status",
    "notes",
)

# Conservative Phase 4 planning defaults. A different threshold needs an
# explicit contract revision and matching tests.
STALE_AFTER_DAYS = {
    "daily": 3,
    "weekly": 14,
    "monthly": 45,
    "quarterly": 135,
    "event_driven": 30,
}


class MemoryCycleMetric(TypedDict):
    metric_id: str
    label: str
    value: Any
    unit: str | None
    as_of: str | None
    retrieved_at: str | None
    source: str
    source_type: SourceType
    frequency: Frequency
    is_fallback: bool
    is_estimate: bool
    staleness_days: int | None
    confidence: Confidence
    status: MetricStatus
    notes: str | None


def _parse_timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
        else:
            parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    else:
        return None
    return parsed.astimezone(timezone.utc)


def _is_missing_or_invalid_value(value) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Real):
        return not math.isfinite(value)
    return True


def calculate_staleness_days(as_of, reference_at) -> int | None:
    """Return whole days from observation to an injected evaluation reference."""
    observation = _parse_timestamp(as_of)
    reference = _parse_timestamp(reference_at)
    if observation is None or reference is None or reference < observation:
        return None
    return int((reference - observation).total_seconds() // 86400)


def _evaluation_reference(retrieved_at, evaluated_at=None):
    retrieval = _parse_timestamp(retrieved_at)
    reference = retrieval if evaluated_at is None else _parse_timestamp(evaluated_at)
    if retrieval is None or reference is None or reference < retrieval:
        return None
    return reference


def derive_metric_status(
    value,
    *,
    as_of,
    retrieved_at,
    frequency,
    unavailable=False,
    evaluated_at=None,
) -> MetricStatus:
    """Derive a conservative status without inventing a value or timestamp."""
    if unavailable:
        return "unavailable"
    if _is_missing_or_invalid_value(value):
        return "missing"
    threshold = STALE_AFTER_DAYS.get(frequency)
    reference = _evaluation_reference(retrieved_at, evaluated_at)
    staleness = calculate_staleness_days(as_of, reference)
    if threshold is None or staleness is None:
        return "missing"
    return "stale" if staleness > threshold else "ok"


def build_metric_record(
    *,
    metric_id,
    label,
    value=None,
    unit=None,
    as_of=None,
    retrieved_at=None,
    source="unavailable",
    source_type="direct",
    frequency="event_driven",
    is_fallback=False,
    is_estimate=False,
    confidence="low",
    status=None,
    notes=None,
    evaluated_at=None,
) -> MemoryCycleMetric:
    """Build a fresh record; callers must validate untrusted values separately."""
    reference = _evaluation_reference(retrieved_at, evaluated_at)
    staleness = calculate_staleness_days(as_of, reference)
    resolved_status = status if status is not None else derive_metric_status(
        value,
        as_of=as_of,
        retrieved_at=retrieved_at,
        frequency=frequency,
        evaluated_at=evaluated_at,
    )
    return {
        "metric_id": metric_id,
        "label": label,
        "value": value,
        "unit": unit,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "source": source,
        "source_type": source_type,
        "frequency": frequency,
        "is_fallback": is_fallback,
        "is_estimate": is_estimate,
        "staleness_days": staleness,
        "confidence": confidence,
        "status": resolved_status,
        "notes": notes,
    }


def validate_metric_record(record, *, evaluated_at=None) -> list[str]:
    """Return contract violations; an empty list means the record is valid."""
    if not isinstance(record, dict):
        return ["metric must be a dictionary"]
    errors = [f"missing required field: {field}" for field in REQUIRED_METRIC_FIELDS if field not in record]
    if errors:
        return errors
    source_type = record["source_type"]
    frequency = record["frequency"]
    confidence = record["confidence"]
    status = record["status"]
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        errors.append("source_type is invalid")
    if not isinstance(frequency, str) or frequency not in FREQUENCIES:
        errors.append("frequency is invalid")
    if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
        errors.append("confidence is invalid")
    if not isinstance(status, str) or status not in METRIC_STATUSES:
        errors.append("status is invalid")
    if not isinstance(record["is_fallback"], bool):
        errors.append("is_fallback must be boolean")
    if not isinstance(record["is_estimate"], bool):
        errors.append("is_estimate must be boolean")
    if not isinstance(record["metric_id"], str) or not record["metric_id"].strip():
        errors.append("metric_id is required")
    if not isinstance(record["label"], str) or not record["label"].strip():
        errors.append("label is required")
    if not isinstance(record["source"], str) or not record["source"].strip():
        errors.append("source is required")
    if record["unit"] is not None and not isinstance(record["unit"], str):
        errors.append("unit must be text or None")
    if record["notes"] is not None and not isinstance(record["notes"], str):
        errors.append("notes must be text or None")

    value = record["value"]
    invalid_value = _is_missing_or_invalid_value(value)
    valid_status = isinstance(status, str) and status in METRIC_STATUSES
    valid_frequency = isinstance(frequency, str) and frequency in FREQUENCIES
    if valid_status and status in {"missing", "unavailable"} and value is not None:
        errors.append("missing or unavailable metrics must use value=None")
    if valid_status and status in {"ok", "stale"}:
        if invalid_value:
            errors.append("ok or stale metrics require a finite, non-empty, non-boolean value")
        if _parse_timestamp(record["as_of"]) is None:
            errors.append("ok or stale metrics require a valid as_of")
        if _parse_timestamp(record["retrieved_at"]) is None:
            errors.append("ok or stale metrics require a valid retrieved_at")

    as_of = record["as_of"]
    retrieved_at = record["retrieved_at"]
    observation = _parse_timestamp(as_of)
    retrieval = _parse_timestamp(retrieved_at)
    if as_of is not None and (not isinstance(as_of, str) or observation is None):
        errors.append("as_of must be an ISO date/time string or None")
    if retrieved_at is not None and (not isinstance(retrieved_at, str) or retrieval is None):
        errors.append("retrieved_at must be an ISO date/time string or None")
    if observation is not None and retrieval is not None and retrieval < observation:
        errors.append("retrieved_at must not precede as_of")
    staleness = record["staleness_days"]
    valid_staleness = staleness is None or (
        not isinstance(staleness, bool) and isinstance(staleness, int) and staleness >= 0
    )
    if not valid_staleness:
        errors.append("staleness_days must be a non-negative integer or None")
    expected_age = calculate_staleness_days(as_of, retrieved_at)
    if evaluated_at is not None:
        evaluation = _parse_timestamp(evaluated_at)
        if evaluation is None:
            errors.append("evaluated_at must be a valid timestamp")
        elif retrieval is not None and evaluation < retrieval:
            errors.append("evaluated_at must not precede retrieved_at")
        reference = _evaluation_reference(retrieved_at, evaluated_at)
        expected_age = calculate_staleness_days(as_of, reference)
    if valid_staleness and staleness != expected_age:
        reference_name = "supplied evaluation time" if evaluated_at is not None else "retrieval time"
        errors.append(f"staleness_days does not match the {reference_name}")
    if valid_status and valid_frequency:
        threshold = STALE_AFTER_DAYS[frequency]
        if status == "ok" and (staleness is None or staleness > threshold):
            errors.append("ok status is inconsistent with staleness_days")
        if status == "stale" and (staleness is None or staleness <= threshold):
            errors.append("stale status is inconsistent with staleness_days")

    source = record["source"]
    if source_type == "news_signal" and value is not None:
        notes_text = record["notes"].strip().casefold() if isinstance(record["notes"], str) else ""
        if not isinstance(value, str) or value.strip().casefold() not in NEWS_SIGNAL_VALUES:
            errors.append("news signal values must use a canonical qualitative label")
        if record["unit"] is not None:
            errors.append("news signal values must use unit=None")
        if "citation:" not in notes_text or "method:" not in notes_text:
            errors.append("news signals require citation and extraction-method notes")
        if isinstance(source, str) and source.strip().casefold() in {"uncited", "unknown", "unavailable"}:
            errors.append("news signals require a named evidence source")
    if source_type == "proxy" and not record["is_estimate"] and not (
        isinstance(record["notes"], str) and record["notes"].strip()
    ):
        errors.append("proxy metrics require is_estimate=True or explanatory notes")

    metric_id = record["metric_id"]
    metric_audit = METRIC_AVAILABILITY.get(metric_id) if isinstance(metric_id, str) else None
    if metric_audit is not None:
        if source_type != metric_audit["source_type"]:
            errors.append("source_type does not match the current metric audit")
        if frequency != metric_audit["frequency"]:
            errors.append("frequency does not match the current metric audit")
        if metric_audit["availability"] == "E":
            if status != "unavailable" or value is not None:
                errors.append("audited E metrics must use status=unavailable and value=None")
            if source != "unavailable":
                errors.append("audited E metrics must use source=unavailable")
    if isinstance(metric_id, str) and metric_id in EXACT_MEMORY_PRICE_METRICS:
        if status != "unavailable" or value is not None:
            errors.append("exact memory price levels or changes are unavailable in the current source audit")
        if isinstance(source, str):
            source_basename = source.replace("\\", "/").rsplit("/", 1)[-1]
            if source in DISALLOWED_EXACT_PRICE_ALIASES or source_basename in DISALLOWED_EXACT_PRICE_ALIASES:
                errors.append("security or backtest aliases cannot be used as exact memory-price sources")
    return errors


def is_metric_record_valid(record, *, evaluated_at=None) -> bool:
    return not validate_metric_record(record, evaluated_at=evaluated_at)


def _availability(availability, source_type, frequency, sources, notes):
    # sources are upstream evidence lineage. A derived D/proxy metric can therefore
    # cite an A market source, B statement source, or C news transformation.
    return {
        "availability": availability,
        "source_type": source_type,
        "frequency": frequency,
        "sources": tuple(sources),
        "notes": notes,
    }


# Classification belongs to the metric family, not merely to the transport.
# For example, FMP quotes are A/direct while FMP-carried statements are
# B/company_reported and FMP news is C/news_signal.
SOURCE_FAMILY_CLASSIFICATION = {
    "equity_price": {"availability": "A", "source_type": "direct"},
    "etf_price": {"availability": "A", "source_type": "direct"},
    "macro": {"availability": "A", "source_type": "direct"},
    "company_statement": {"availability": "B", "source_type": "company_reported"},
    "news": {"availability": "C", "source_type": "news_signal"},
    "company_news": {"availability": "C", "source_type": "news_signal"},
    "news_direction": {"availability": "C", "source_type": "news_signal"},
    "cycle_proxy": {"availability": "D", "source_type": "proxy"},
    "etf_flow_proxy": {"availability": "D", "source_type": "proxy"},
    "equity_snapshot_proxy": {"availability": "D", "source_type": "proxy"},
    "account_context": {"availability": "D", "source_type": "proxy"},
    "user_equity_price_fallback": {"availability": "D", "source_type": "proxy"},
    "broad_market_proxy": {"availability": "D", "source_type": "proxy"},
    "user_scenario": {"availability": "D", "source_type": "proxy"},
}


# This registry describes audited repository capabilities, not provider promises.
SOURCE_AUDIT = {
    "yahoo_yfinance": {
        "availability_classes": ("A", "B", "C", "D"),
        "allowed_metric_families": ("equity_price", "etf_price", "company_statement", "news"),
        "provides_company_financials": True,
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": False,
        "production": True,
        "notes": "Structured security prices and delayed company statements/news; no memory-product prices.",
    },
    "fmp": {
        "availability_classes": ("A", "B", "C", "D"),
        "allowed_metric_families": ("equity_price", "macro", "company_statement", "news"),
        "provides_company_financials": True,
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": False,
        "production": True,
        "notes": "Quotes/OHLCV are direct; company statements remain company-reported provenance.",
    },
    "financials_module": {
        "availability_classes": ("A", "B", "C"),
        "allowed_metric_families": ("equity_price", "company_statement", "company_news"),
        "provides_company_financials": True,
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": True,
        "production": True,
        "production_company_coverage": ("MU", "SNDK"),
        "field_level_provenance": False,
        "notes": "Snapshots can mix FMP and Yahoo fields under one source label; period may be annual.",
    },
    "trendforce_public_news": {
        "availability_classes": ("C",),
        "allowed_metric_families": ("news_direction",),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": False,
        "production": True,
        "notes": "Public HTML/RSS news only; not the licensed TrendForce price database.",
    },
    "daily_brief": {
        "availability_classes": ("C",),
        "allowed_metric_families": ("news_direction",),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": True,
        "production": True,
        "notes": "Citation-backed transformation layer; underlying articles remain the facts, generated_at is not an observation time, and numeric facts are not metrics.",
    },
    "macro_and_factor_modules": {
        "availability_classes": ("A", "D"),
        "allowed_metric_families": ("macro", "equity_price", "etf_price", "cycle_proxy"),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": False,
        "production": True,
        "notes": "Direct market series become proxies when used to infer the memory cycle.",
    },
    "etf_news_monitor": {
        "availability_classes": ("C", "D"),
        "allowed_metric_families": ("news", "etf_flow_proxy"),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": True,
        "production": True,
        "notes": "Article/manual evidence can support a dated semiconductor ETF flow proxy; static fallback is not current holdings data.",
    },
    "watchlist": {
        "availability_classes": ("E",),
        "allowed_metric_families": (),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": False,
        "has_retrieval_time": False,
        "production": True,
        "configuration_only": True,
        "notes": "Ticker selection state only; not a data source.",
    },
    "ibkr": {
        "availability_classes": ("A", "D", "E"),
        "allowed_metric_families": ("equity_price", "equity_snapshot_proxy", "account_context"),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "observation_time_conditional": True,
        "has_retrieval_time": False,
        "production": True,
        "notes": "A raw security snapshot is A only when price_time exists; cycle inference is D and missing price/time is E. No industry fundamentals or cross-market trend series.",
    },
    "local_csv": {
        "availability_classes": ("D", "E"),
        "allowed_metric_families": ("user_equity_price_fallback", "broad_market_proxy"),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": False,
        "has_retrieval_time": False,
        "production": True,
        "approved_memory_source": False,
        "notes": "User/derived files need explicit provenance; DRAM-named backtests are security data, not product prices.",
    },
    "mu_valuation_manual_assumptions": {
        "availability_classes": ("D", "E"),
        "allowed_metric_families": ("user_scenario",),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": False,
        "has_retrieval_time": False,
        "production": True,
        "approved_memory_source": False,
        "notes": "Editable UBS/Nomura/Goldman-style assumptions, not observed or company-reported data.",
    },
    "legacy_supply_chain_analyzer": {
        "availability_classes": ("E",),
        "allowed_metric_families": (),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": True,
        "has_retrieval_time": False,
        "production": False,
        "tested": False,
        "notes": "Parallel/manual yfinance analyzer; not an approved Dashboard source.",
    },
    "environment_and_secrets": {
        "availability_classes": ("E",),
        "allowed_metric_families": (),
        "provides_product_specific_memory_fundamentals": False,
        "provides_exact_memory_pricing": False,
        "has_observation_time": False,
        "has_retrieval_time": False,
        "production": True,
        "configuration_only": True,
        "notes": "No configured or licensed memory-pricing credential exists in the repository contract.",
    },
}


COMPANY_COVERAGE = {
    "MU": {"company": "Micron", "production_structured": True, "confidence": "medium", "notes": "Generic financial snapshot only; field-level provenance is incomplete."},
    "SNDK": {"company": "SanDisk", "production_structured": True, "confidence": "low", "notes": "Use identity/date-protected Yahoo financials or N/A; legacy-symbol risk."},
    "000660.KS": {"company": "SK hynix", "production_structured": False, "confidence": "low", "notes": "Legacy untested analyzer only; OTC aliases are fallback candidates."},
    "005930.KS": {"company": "Samsung Electronics", "production_structured": False, "confidence": "low", "notes": "No current production mapping or identity/currency tests."},
    "285A.T": {"company": "Kioxia", "production_structured": False, "confidence": "low", "notes": "No current production mapping or identity/currency tests."},
}


METRIC_AVAILABILITY = {
    # Exact product pricing and derived price rates are unavailable.
    "dram_spot_price": _availability("E", "direct", "daily", (), "No authorized structured DRAM spot-price source."),
    "dram_contract_price": _availability("E", "direct", "monthly", (), "No authorized structured DRAM contract-price source."),
    "nand_spot_price": _availability("E", "direct", "daily", (), "No authorized structured NAND spot-price source."),
    "nand_contract_price": _availability("E", "direct", "monthly", (), "No authorized structured NAND contract-price source."),
    "hbm_price": _availability("E", "direct", "monthly", (), "No standardized or licensed HBM price series."),
    "enterprise_ssd_price": _availability("E", "direct", "monthly", (), "No verified enterprise SSD price series."),
    "client_ssd_price": _availability("E", "direct", "monthly", (), "No verified client SSD price series."),
    "wafer_component_price": _availability("E", "direct", "monthly", (), "No verified wafer/component price series."),
    "dram_spot_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified DRAM spot-price series."),
    "dram_spot_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified DRAM spot-price series."),
    "dram_contract_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified DRAM contract-price series."),
    "dram_contract_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified DRAM contract-price series."),
    "nand_spot_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified NAND spot-price series."),
    "nand_spot_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified NAND spot-price series."),
    "nand_contract_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified NAND contract-price series."),
    "nand_contract_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified NAND contract-price series."),
    "hbm_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified HBM price series."),
    "hbm_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified HBM price series."),
    "enterprise_ssd_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified enterprise SSD price series."),
    "enterprise_ssd_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified enterprise SSD price series."),
    "client_ssd_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified client SSD price series."),
    "client_ssd_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified client SSD price series."),
    "wafer_component_price_mom": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified wafer/component price series."),
    "wafer_component_price_yoy": _availability("E", "direct", "monthly", (), "Cannot calculate without a verified wafer/component price series."),
    "dram_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative DRAM direction only; never an exact price."),
    "nand_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative NAND direction only; never an exact price."),
    "hbm_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative HBM direction only; never an exact price."),
    "enterprise_ssd_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative enterprise SSD price direction only."),
    "client_ssd_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative client SSD price direction only."),
    "wafer_component_price_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative wafer/component price direction only."),

    # Exact supply data is unavailable; separately named signals remain qualitative.
    "dram_bit_supply_growth": _availability("E", "company_reported", "quarterly", (), "Future company-reported metric; no current normalized series."),
    "nand_bit_supply_growth": _availability("E", "company_reported", "quarterly", (), "Future company-reported metric; no current normalized series."),
    "dram_supply_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative cited DRAM supply-growth direction only."),
    "nand_supply_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative cited NAND supply-growth direction only."),
    "wafer_starts_or_capacity": _availability("E", "company_reported", "quarterly", (), "Future company-reported metric; not extracted by current production modules."),
    "capacity_utilization": _availability("E", "company_reported", "quarterly", (), "No current verified field."),
    "hbm_capacity": _availability("E", "company_reported", "quarterly", (), "Future company-reported metric; no verified exact series."),
    "hbm_capacity_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Qualitative cited HBM capacity direction only."),
    "advanced_packaging_capacity_direction": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Directional TSV/CoWoS capacity signal only."),
    "manufacturer_expansion_plans": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Cited manufacturer expansion news only."),
    "production_cuts_or_supply_discipline": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "Cited production-cut or supply-discipline news only."),
    "node_transition_capacity_effect": _availability("C", "news_signal", "event_driven", ("trendforce_public_news", "daily_brief"), "No precise effective-capacity calculation."),
    "ai_server_accelerator_demand": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Directional cited AI server/accelerator demand signal only."),
    "hbm_demand": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Directional cited HBM demand signal only."),
    "data_center_server_demand": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Directional cited server-demand signal only."),
    "enterprise_ssd_demand": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Directional cited demand signal only."),
    "pc_smartphone_demand": _availability("E", "company_reported", "monthly", (), "No verified shipment or demand series and no approved proxy."),
    "pc_smartphone_demand_direction": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Qualitative cited PC/smartphone direction only."),
    "cloud_capex_reported": _availability("E", "company_reported", "quarterly", (), "No normalized company-reported cloud CapEx series."),
    "cloud_capex_news": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Cited cloud CapEx events only."),
    "cloud_capex_demand_proxy": _availability("D", "proxy", "event_driven", ("daily_brief",), "Cloud CapEx evidence used as an indirect AI/server-memory demand proxy."),
    "gpu_asic_ai_server_shipments": _availability("E", "company_reported", "quarterly", (), "No verified structured shipment series."),
    "customer_inventory_restocking": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Qualitative restocking signal only."),

    # Inventory and company financials.
    "manufacturer_inventory": _availability("E", "company_reported", "quarterly", (), "Future company-reported field; not extracted by current production financials."),
    "inventory_days": _availability("E", "company_reported", "quarterly", (), "Derived from company-reported inventory and matching COGS periods; not currently calculated."),
    "channel_inventory": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Qualitative cited channel-inventory signal only."),
    "customer_inventory": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Qualitative cited customer-inventory signal only."),
    "inventory_qoq": _availability("E", "company_reported", "quarterly", (), "Derived company financial metric; no normalized inventory history."),
    "inventory_yoy": _availability("E", "company_reported", "quarterly", (), "Derived company financial metric; no normalized inventory history."),
    "inventory_cycle_stage": _availability("E", "proxy", "quarterly", (), "Future derived label; unavailable until inputs are verified."),
    "company_revenue": _availability("B", "company_reported", "event_driven", ("financials_module",), "MU/SNDK generic coverage; current annual/quarterly period and per-field provenance must be verified."),
    "gross_margin": _availability("B", "company_reported", "event_driven", ("financials_module",), "MU/SNDK generic coverage with unverified annual/quarterly period."),
    "operating_margin": _availability("B", "company_reported", "event_driven", ("financials_module",), "MU/SNDK generic coverage with provenance and period limitations."),
    "free_cash_flow": _availability("E", "company_reported", "quarterly", (), "No verified absolute cross-company series in the production path."),
    "free_cash_flow_margin": _availability("B", "company_reported", "event_driven", ("financials_module",), "Limited current field; definition, period, and source require verification before display."),
    "company_capex": _availability("E", "company_reported", "quarterly", (), "Current production financials do not expose verified CapEx."),
    "management_guidance": _availability("E", "company_reported", "event_driven", (), "Future filing/call metric; no normalized company-reported adapter."),
    "management_guidance_direction": _availability("C", "news_signal", "event_driven", ("daily_brief",), "Current automation can provide cited qualitative guidance direction only."),
    "dram_revenue": _availability("E", "company_reported", "quarterly", (), "No verified DRAM segment-revenue series."),
    "nand_revenue": _availability("E", "company_reported", "quarterly", (), "No verified NAND segment-revenue series."),
    "hbm_revenue": _availability("E", "company_reported", "quarterly", (), "No verified HBM revenue series."),
    "bit_shipment_growth": _availability("E", "company_reported", "quarterly", (), "No normalized company disclosure series."),
    "asp_change": _availability("E", "company_reported", "quarterly", (), "No normalized company disclosure series."),
    "production_growth": _availability("E", "company_reported", "quarterly", (), "No normalized company disclosure series."),
    "supply_growth_guidance": _availability("E", "company_reported", "quarterly", (), "No normalized company disclosure series."),

    # Direct market data used only as cycle proxies.
    "memory_company_equity_trend": _availability("D", "proxy", "daily", ("yahoo_yfinance", "fmp"), "Company share-price proxy; not a memory-product price."),
    "semiconductor_etf_trend": _availability("D", "proxy", "daily", ("yahoo_yfinance", "fmp"), "SMH/SOXX market proxy, not industry fundamentals."),
    "semiconductor_etf_flow": _availability("D", "proxy", "event_driven", ("etf_news_monitor",), "Fund-flow proxy with source/date caveats."),
    "margin_direction": _availability("E", "proxy", "event_driven", (), "Future derived signal; the current production path has no verified multi-period margin trend."),
    "pricing_strength": _availability("E", "proxy", "event_driven", (), "Future explanatory label; current evidence has not been assembled into a tested signal."),
    "demand_strength": _availability("E", "proxy", "event_driven", (), "Future explanatory label; current evidence has not been assembled into a tested signal."),
    "supply_discipline": _availability("E", "proxy", "event_driven", (), "Future explanatory label; current evidence has not been assembled into a tested signal."),
    "inventory_health": _availability("E", "proxy", "quarterly", (), "Future explanatory label; required inputs are unavailable."),
    "capex_risk": _availability("E", "proxy", "quarterly", (), "Future explanatory label; required inputs are unavailable."),
    "cycle_phase": _availability("E", "proxy", "event_driven", (), "Do not calculate until pricing, inventory, supply, demand, and CapEx evidence is sufficient."),
}


EXACT_MEMORY_PRICE_METRICS = frozenset({
    "dram_spot_price",
    "dram_contract_price",
    "nand_spot_price",
    "nand_contract_price",
    "hbm_price",
    "enterprise_ssd_price",
    "client_ssd_price",
    "wafer_component_price",
    "dram_spot_price_mom",
    "dram_spot_price_yoy",
    "dram_contract_price_mom",
    "dram_contract_price_yoy",
    "nand_spot_price_mom",
    "nand_spot_price_yoy",
    "nand_contract_price_mom",
    "nand_contract_price_yoy",
    "hbm_price_mom",
    "hbm_price_yoy",
    "enterprise_ssd_price_mom",
    "enterprise_ssd_price_yoy",
    "client_ssd_price_mom",
    "client_ssd_price_yoy",
    "wafer_component_price_mom",
    "wafer_component_price_yoy",
})

# Explicit collision guard: these names are securities/files, not product prices.
DISALLOWED_EXACT_PRICE_ALIASES = frozenset({"DRAM", "DRAM_portfolio.csv", "DRAM_trades.csv"})
