"""Value Investing orchestration and view model over the shared FMP snapshot."""

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Callable

from providers.fmp_financial_data import fetch_fmp_financial_data
from services.fmp_financial_normalization import normalize_fmp_financial_data
from services.fmp_financial_snapshot import build_fmp_financial_snapshot
from translations.value_investing import value_investing_text


_SAFE_TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_SECTIONS = (
    (
        "income_profitability",
        (
            "revenue", "annual_revenue", "revenue_qoq", "revenue_yoy",
            "annual_revenue_yoy", "gross_profit", "gross_margin",
            "operating_income", "operating_margin", "net_income", "net_margin",
            "ebitda", "diluted_eps",
        ),
    ),
    ("cash_flow", ("operating_cash_flow", "capex", "free_cash_flow", "fcf_margin")),
    (
        "balance_sheet",
        (
            "cash", "total_debt", "net_debt", "inventory", "inventory_qoq",
            "inventory_yoy", "inventory_to_revenue", "equity", "assets",
        ),
    ),
    ("returns", ("roe", "roa", "roic")),
    (
        "valuation",
        (
            "price", "shares_outstanding", "market_cap", "enterprise_value",
            "pe", "ps", "pb", "ev_ebitda",
        ),
    ),
)


def _ticker(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ticker must be an exact safe symbol")
    result = value.strip().upper()
    if _SAFE_TICKER.fullmatch(result) is None:
        raise ValueError("ticker must be an exact safe symbol")
    return result


def _timestamp(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{name} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def _error_snapshot(
    ticker: str, *, retrieved_at: str, evaluated_at: str
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_name": ticker,
        "cik": None,
        "source": "FMP",
        "retrieved_at": retrieved_at,
        "evaluated_at": evaluated_at,
        "currency": None,
        "periods": {"ttm_end": None, "balance_end": None, "annual_end": None},
        "metrics": {},
        "quality": {
            "successful_metric_count": 0,
            "unavailable_metric_count": sum(len(metrics) for _, metrics in _SECTIONS),
            "stale_metric_count": 0,
            "total_metric_count": sum(len(metrics) for _, metrics in _SECTIONS),
            "normalization_status": "error",
            "errors": [{"code": "financial_data_unavailable"}],
            "ttm_income_status": "unavailable",
            "ttm_cashflow_status": "unavailable",
        },
        "status": "error",
    }


def load_value_investing_snapshot(
    symbol: Any,
    *,
    fmp_json_fetcher: Callable[..., Any],
    retrieved_at: Any,
    evaluated_at: Any,
) -> dict[str, Any]:
    """Acquire and build one shared FMP snapshot with safe failure isolation."""

    ticker = _ticker(symbol)
    retrieval_text = _timestamp(retrieved_at, name="retrieved_at")
    evaluation_text = _timestamp(evaluated_at, name="evaluated_at")
    if evaluation_text < retrieval_text:
        raise ValueError("evaluated_at must not precede retrieved_at")
    try:
        raw = fetch_fmp_financial_data(
            ticker,
            fmp_json_fetcher=fmp_json_fetcher,
            retrieved_at=retrieval_text,
        )
        normalized = normalize_fmp_financial_data(raw)
        return build_fmp_financial_snapshot(
            normalized, evaluated_at=evaluation_text
        )
    except Exception:
        return _error_snapshot(
            ticker, retrieved_at=retrieval_text, evaluated_at=evaluation_text
        )


def _empty_metric(metric_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "source_field": None,
        "source_fields": (),
        "raw_value": None,
        "raw_unit": None,
        "normalized_value": None,
        "normalized_unit": None,
        "display_value": None,
        "display_unit": None,
        "currency": None,
        "period_type": None,
        "period_end": None,
        "retrieved_at": snapshot.get("retrieved_at"),
        "source": "FMP",
        "derived": False,
        "proxy": False,
        "method": None,
        "notes": "",
        "status": "unavailable",
        "staleness_days": None,
    }


def _view_metric(
    metric_id: str,
    snapshot: dict[str, Any],
    text: dict[str, Any],
) -> dict[str, Any]:
    raw = snapshot.get("metrics", {}).get(metric_id)
    metric = deepcopy(raw) if isinstance(raw, dict) else _empty_metric(metric_id, snapshot)
    metric["metric_id"] = metric_id
    metric["label"] = text["metrics"][metric_id]
    period_type = metric.get("period_type")
    metric["period_label"] = text["periods"].get(period_type, text["statuses"]["unavailable"])
    evidence = "proxy" if metric.get("proxy") else "derived" if metric.get("derived") else "reported"
    metric["evidence"] = evidence
    metric["evidence_label"] = text["evidence"][evidence]
    if metric.get("status") not in {"ok", "stale", "missing", "unavailable"}:
        metric["status"] = "unavailable"
    return metric


def build_value_investing_view_model(
    snapshot: Any, *, language: Any = "English"
) -> dict[str, Any]:
    """Build a fresh localized view model without recomputing financial data."""

    source = deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    text = value_investing_text(language)
    metrics_by_id: dict[str, dict[str, Any]] = {}
    sections: list[dict[str, Any]] = []
    for section_id, metric_ids in _SECTIONS:
        section_metrics = []
        for metric_id in metric_ids:
            metric = _view_metric(metric_id, source, text)
            metrics_by_id[metric_id] = deepcopy(metric)
            section_metrics.append(metric)
        sections.append({
            "section_id": section_id,
            "title": text["sections"][section_id],
            "metrics": section_metrics,
        })
    quality = source.get("quality") if isinstance(source.get("quality"), dict) else {}
    periods = source.get("periods") if isinstance(source.get("periods"), dict) else {}
    return {
        "title": text["title"],
        "ticker": source.get("ticker"),
        "company_name": source.get("company_name") or source.get("ticker"),
        "cik": source.get("cik"),
        "source": source.get("source") or "FMP",
        "currency": source.get("currency"),
        "retrieved_at": source.get("retrieved_at"),
        "evaluated_at": source.get("evaluated_at"),
        "periods": deepcopy(periods),
        "data_quality": {
            "source": source.get("source") or "FMP",
            "currency": source.get("currency"),
            "retrieved_at": source.get("retrieved_at"),
            "successful_metric_count": quality.get("successful_metric_count", 0),
            "total_metric_count": quality.get("total_metric_count", len(metrics_by_id)),
            "stale_metric_count": quality.get("stale_metric_count", 0),
            "errors": deepcopy(quality.get("errors", [])) if isinstance(quality.get("errors"), list) else [],
        },
        "sections": sections,
        "metrics_by_id": metrics_by_id,
        "status": source.get("status") if source.get("status") in {"ok", "partial", "error"} else "error",
        "text": text,
    }
