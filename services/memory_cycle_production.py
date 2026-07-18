"""Pure Phase 4.6 validation and orchestration for Memory Cycle metrics.

The module accepts caller-injected observations.  It performs no fetching,
configuration lookup, persistence, caching, or rendering.
"""

from datetime import date, datetime, timezone
import math
from numbers import Real
import re
from types import MappingProxyType
from typing import Any

from services.memory_cycle_adapters import (
    adapt_company_financial_metric,
    adapt_market_proxy_metric,
    build_unavailable_metric,
)
from services.memory_cycle_contract import REQUIRED_METRIC_FIELDS, validate_metric_record


SUPPORTED_MARKET_TICKERS = ("MU", "SNDK", "SMH", "SOXX")
SUPPORTED_FINANCIAL_TICKERS = ("MU", "SNDK")
SUPPORTED_FINANCIAL_FIELDS = ("revenue", "gross_margin", "operating_margin")
MARKET_METRIC_KIND = "latest_price"

MARKET_METRIC_IDS = MappingProxyType(
    {
        "MU": "mu_market_price_proxy",
        "SNDK": "sndk_market_price_proxy",
        "SMH": "smh_market_price_proxy",
        "SOXX": "soxx_market_price_proxy",
    }
)
FINANCIAL_METRIC_IDS = MappingProxyType(
    {
        "revenue": "company_revenue",
        "gross_margin": "gross_margin",
        "operating_margin": "operating_margin",
    }
)

CANONICAL_METRIC_ORDER = (
    ("market_proxy", "MU", None),
    ("market_proxy", "SNDK", None),
    ("market_proxy", "SMH", None),
    ("market_proxy", "SOXX", None),
    ("company_financial", "MU", "revenue"),
    ("company_financial", "MU", "gross_margin"),
    ("company_financial", "MU", "operating_margin"),
    ("company_financial", "SNDK", "revenue"),
    ("company_financial", "SNDK", "gross_margin"),
    ("company_financial", "SNDK", "operating_margin"),
)

_ERROR_FIELDS = ("family", "ticker", "field", "code")
_SENSITIVE_MARKERS = (
    "authorization",
    "bearer ",
    "api_key",
    "apikey",
    "access_token",
    "token=",
    "secret",
    "password",
    "traceback",
    "response body",
    "response_body",
    "raw response",
    "raw_response",
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9])(?:api[-_]?key|access[-_]?token|token|credential|authorization|auth|"
    r"password|signature|sig|key)\s*[:=]",
    re.IGNORECASE,
)
_SENSITIVE_WHITESPACE_VALUE = re.compile(
    r"(?<![A-Za-z0-9])(?:api[\s_-]*key|access[\s_-]*token|token|credential|"
    r"authorization|auth|password|signature|sig|key)\s+[^;,\s]{4,}",
    re.IGNORECASE,
)
_SENSITIVE_LABEL = re.compile(
    r"(?<![A-Za-z0-9])(?:api[\s_.-]*key|access[\s_.-]*token|token|credential|"
    r"authorization|auth|password|signature|sig|key)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_LOCAL_PATH_MARKERS = ("/users/", "/home/", "file://", "c:\\users\\")
_SECRET_VALUE_PREFIXES = (
    "sk-",
    "sk_live_",
    "sk_test_",
    "rk_live_",
    "rk_test_",
    "whsec_",
    "ghp_",
    "gho_",
    "github_pat_",
    "glpat-",
    "xoxb-",
    "xoxp-",
)
_RELATIVE_PATH_PREFIXES = (
    "./",
    "../",
    ".\\",
    "..\\",
    "tmp/",
    "tmp\\",
    "temp/",
    "temp\\",
)
_FORBIDDEN_PRODUCTION_MARKERS = (
    "daily brief",
    "daily news brief",
    "news article",
    "news summary",
    "news",
    "article",
    "analyst",
    "analyst article",
    "analyst service",
    "estimate",
    "fixture",
    "demo",
    "synthetic",
    "mock data",
    "consensus estimate",
    "model estimate",
    "static fixture",
    "static test",
    "synthetic data",
    "demo data",
    "mock data",
    "open" "ai",
)
_FORBIDDEN_PRODUCTION_WORDS = (
    "test",
    "fake",
    "sample",
    "mock",
    "chatgpt",
    "gpt",
    "llm",
    "ai",
    "model",
    "valuation",
    "guidance",
    "forecast",
    "projected",
    "projection",
    "consensus",
)
_APPROVED_MARKET_SOURCE_EXACT = frozenset(
    {
        "ibkr",
        "interactive brokers",
        "yahoo",
        "yahoo finance",
        "yfinance",
        "fmp",
        "financial modeling prep",
        "financialmodelingprep",
    }
)
_APPROVED_FINANCIAL_SOURCE_EXACT = frozenset(
    {
        "fmp",
        "financial modeling prep",
        "financialmodelingprep",
        "yahoo",
        "yahoo finance",
        "yfinance",
        "sec",
        "sec edgar",
        "edgar",
        "sec filing",
        "micron",
        "micron technology",
        "sandisk",
    }
)
_MARKET_DOCUMENT_MARKERS = (
    "quote",
    "market data",
    "market_data",
    "price snapshot",
    "price response",
    "historical price",
    "historical_prices",
    "historical close",
    "ohlcv",
)
_FINANCIAL_DOCUMENT_MARKERS = (
    "income_statement",
    "income statement",
    "financial statement",
    "form 10-q",
    "form 10-k",
    "annual report",
    "quarterly report",
    "earnings release",
    "company filing",
    "sec filing",
)
_FINANCIAL_COMPANY_MARKERS = (
    ("MU", ("mu", "micron")),
    ("SNDK", ("sndk", "sandisk")),
)
_MARKET_TICKER_MARKERS = (
    ("MU", ("mu", "micron")),
    ("SNDK", ("sndk", "sandisk")),
    ("SMH", ("smh",)),
    ("SOXX", ("soxx",)),
)
_MARKET_PRICE_SOURCE_FIELDS = frozenset(
    {
        "regularMarketPrice",
        "postMarketPrice",
        "preMarketPrice",
        "price",
        "last",
        "lastPrice",
        "last_price",
        "close",
    }
)
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_FISCAL_QUARTERLY_LABEL = re.compile(
    r"^(?:(?:FY\s*)?(?:19|20)\d{2}[\s/_-]+Q[1-4]"
    r"|Q[1-4][\s/_-]+(?:FY\s*)?(?:19|20)\d{2})$",
    re.IGNORECASE,
)
_FISCAL_ANNUAL_LABEL = re.compile(
    r"^(?:FY\s*)?(?:19|20)\d{2}$",
    re.IGNORECASE,
)
_SOURCE_REFERENCE_HTTPS = re.compile(
    r"^https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?"
    r"(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$"
)
_SOURCE_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_VAGUE_FISCAL_LABELS = frozenset(
    {
        "latest",
        "recent",
        "current",
        "ttm",
        "unknown",
        "estimate",
        "consensus",
        "forecast",
        "projected",
        "guidance",
    }
)
_REVENUE_TO_USD_MILLIONS = MappingProxyType(
    {
        "USD": 1 / 1_000_000,
        "USD thousands": 1 / 1_000,
        "USD millions": 1,
        "USD billions": 1_000,
    }
)
_MARGIN_SOURCE_FIELDS = MappingProxyType(
    {
        "gross_margin": MappingProxyType(
            {
                "grossProfitRatio": "ratio",
                "grossProfitMargin": "ratio",
                "grossMarginPercent": "percent",
            }
        ),
        "operating_margin": MappingProxyType(
            {
                "operatingIncomeRatio": "ratio",
                "operatingProfitMargin": "ratio",
                "operatingMarginPercent": "percent",
            }
        ),
    }
)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _safe_metadata_text(value: Any) -> str | None:
    value = _text(value)
    if value is None or len(value) > 500:
        return None
    lowered = value.casefold()
    if not value.isprintable():
        return None
    if re.search(
        r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{12,}(?![A-Za-z0-9])",
        value,
        re.IGNORECASE,
    ) or re.search(
        r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{12,}(?![A-Za-z0-9_-])",
        value,
    ):
        return None
    if any(
        re.search(
            rf"(?<![a-z0-9]){re.escape(prefix)}",
            lowered,
        )
        is not None
        for prefix in _SECRET_VALUE_PREFIXES
    ):
        return None
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return None
    if _SENSITIVE_ASSIGNMENT.search(value):
        return None
    if _SENSITIVE_WHITESPACE_VALUE.search(value):
        return None
    if _SENSITIVE_LABEL.search(value):
        return None
    if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
        return None
    if any(character in value for character in "{}[]<>"):
        return None
    if "?" in value or "#" in value:
        return None
    if re.search(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s@]+@", value):
        return None
    if re.search(
        r"(?<![A-Za-z0-9:])/(?:users|home|private|tmp|var|etc)(?:[\\/]|$)",
        value,
        re.IGNORECASE,
    ):
        return None
    path_scan_value = re.sub(
        r"\bhttps://[A-Za-z0-9.-]+(?::[0-9]{1,5})?"
        r"(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    if "/" in path_scan_value or "\\" in path_scan_value:
        return None
    if re.search(
        r"(?<![A-Za-z0-9])/(?:[^/\s]+/)*[^/\s]+",
        path_scan_value,
    ):
        return None
    if re.search(r"(?<![\\])\\\\[^\\/\s]+[\\/][^\\/\s]+", value):
        return None
    if re.search(r"(?:^|\s)~[\\/]", value):
        return None
    if re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", value):
        return None
    if lowered.startswith(_RELATIVE_PATH_PREFIXES) or re.search(
        r"(?:^|\s)(?:\.\.?[\\/]|(?:tmp|temp)[\\/])",
        lowered,
    ):
        return None
    if re.search(r"(?:[^/\\\s]+[\\/])+[^/\\\s]+", path_scan_value):
        return None
    if re.search(
        r"(?<![A-Za-z0-9_.-])\.[A-Za-z0-9_.-]+",
        path_scan_value,
    ):
        return None
    if re.search(
        r"(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]+\."
        r"(?:cer|cfg|conf|crt|csv|dat|db|docx?|env|html?|ini|json|key|log|"
        r"parquet|pdf|pem|pickle|pkl|pyc?|sqlite3?|toml|tsv|txt|xlsx?|xml|"
        r"ya?ml|zip)(?![A-Za-z0-9])",
        path_scan_value,
        re.IGNORECASE,
    ):
        return None
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return None
    return value


def _verified_production_text(value: Any) -> str | None:
    value = _safe_metadata_text(value)
    if value is None:
        return None
    lowered = value.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PRODUCTION_MARKERS):
        return None
    if "open ai" in lowered:
        return None
    if any(
        re.search(
            rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])",
            lowered,
        )
        is not None
        for word in _FORBIDDEN_PRODUCTION_WORDS
    ):
        return None
    return value


def _verified_source_reference(value: Any) -> str | None:
    value = _verified_production_text(value)
    if value is None:
        return None
    if _SOURCE_REFERENCE_HTTPS.fullmatch(value) is not None:
        return value
    if _SOURCE_REFERENCE_ID.fullmatch(value) is not None:
        return value
    return None


def _verified_financial_evidence(value: Any) -> str | None:
    value = _verified_production_text(value)
    if value is None:
        return None
    lowered = value.casefold()
    if not any(marker in lowered for marker in _FINANCIAL_DOCUMENT_MARKERS):
        return None
    return value


def _verified_market_evidence(value: Any) -> str | None:
    value = _verified_production_text(value)
    if value is None:
        return None
    lowered = value.casefold()
    if any(marker in lowered for marker in _FINANCIAL_DOCUMENT_MARKERS):
        return None
    if not any(marker in lowered for marker in _MARKET_DOCUMENT_MARKERS):
        return None
    return value


def _verified_market_source(value: Any) -> str | None:
    value = _verified_production_text(value)
    if value is None or value.casefold() not in _APPROVED_MARKET_SOURCE_EXACT:
        return None
    return value


def _canonical_market_source(value: Any) -> str | None:
    value = _verified_market_source(value)
    if value is None:
        return None
    lowered = value.casefold()
    if lowered in ("ibkr", "interactive brokers"):
        return "ibkr"
    if lowered in ("yahoo", "yahoo finance", "yfinance"):
        return "yahoo"
    return "fmp"


def _verified_financial_source(value: Any) -> str | None:
    value = _verified_production_text(value)
    if value is None or value.casefold() not in _APPROVED_FINANCIAL_SOURCE_EXACT:
        return None
    return value


def _canonical_financial_source(value: Any) -> str | None:
    value = _verified_financial_source(value)
    if value is None:
        return None
    lowered = value.casefold()
    if lowered in ("fmp", "financial modeling prep", "financialmodelingprep"):
        return "fmp"
    if lowered in ("yahoo", "yahoo finance", "yfinance"):
        return "yahoo"
    if lowered in ("sec", "sec edgar", "edgar", "sec filing"):
        return "sec"
    if lowered in ("micron", "micron technology"):
        return "micron"
    return lowered


def _contains_company_marker(value: Any, marker: str) -> bool:
    value = _safe_metadata_text(value)
    if value is None:
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])",
        value.casefold(),
    ) is not None


def _financial_company_identity_mismatch(
    observation: dict[str, Any], ticker: str
) -> bool:
    identity_values = (
        observation.get("source"),
        observation.get("source_document"),
        observation.get("provenance"),
        observation.get("source_reference"),
        observation.get("fallback_from"),
    )
    return any(
        company_ticker != ticker
        and any(
            _contains_company_marker(value, marker)
            for value in identity_values
            for marker in markers
        )
        for company_ticker, markers in _FINANCIAL_COMPANY_MARKERS
    )


def _market_ticker_identity_mismatch(
    observation: dict[str, Any], ticker: str
) -> bool:
    evidence_values = (
        observation.get("source_document"),
        observation.get("provenance"),
    )
    return any(
        evidence_ticker != ticker
        and any(
            _contains_company_marker(value, marker)
            for value in evidence_values
            for marker in markers
        )
        for evidence_ticker, markers in _MARKET_TICKER_MARKERS
    )


def _evidence_declares_cadence(value: Any, cadence: str) -> bool:
    value = _safe_metadata_text(value)
    if value is None:
        return False
    lowered = value.casefold()
    if cadence == "quarterly":
        return (
            re.search(r"\b(?:form[\s/_-]*)?10[\s/_-]*q\b", lowered)
            is not None
            or re.search(r"(?<![a-z0-9])q[1-4](?![a-z0-9])", lowered)
            is not None
            or re.search(r"(?<![a-z0-9])quarterly(?![a-z0-9])", lowered)
            is not None
            or re.search(
                r"\b(?:first|second|third|fourth|[1-4](?:st|nd|rd|th))"
                r"[\s-]+quarter\b",
                lowered,
            )
            is not None
            or re.search(
                r"(?<![a-z0-9])(?:fy)?(?:19|20)\d{2}q[1-4](?![a-z0-9])",
                lowered,
            )
            is not None
            or re.search(
                r"(?<![a-z0-9])(?:[1-4]q|q[1-4])(?:fy)?(?:19|20)\d{2}"
                r"(?![a-z0-9])",
                lowered,
            )
            is not None
        )
    return (
        re.search(r"\b(?:form[\s/_-]*)?10[\s/_-]*k\b", lowered)
        is not None
        or re.search(r"(?<![a-z0-9])annual(?![a-z0-9])", lowered)
        is not None
        or re.search(r"\bfull[\s-]+year\b", lowered) is not None
    )


def _financial_period_evidence_mismatch(
    observation: dict[str, Any], period_type: str | None
) -> bool:
    if period_type not in {"quarterly", "annual"}:
        return False
    opposite = "annual" if period_type == "quarterly" else "quarterly"
    evidence_values = (
        observation.get("source_document"),
        observation.get("provenance"),
        observation.get("source_reference"),
    )
    return any(
        _evidence_declares_cadence(value, opposite) for value in evidence_values
    )


def _finite_number(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric_value)


def _valid_adapter_metric(
    metric: Any,
    *,
    evaluated_at: str,
    allowed_statuses: tuple[str, ...],
) -> bool:
    if not isinstance(metric, dict) or metric.get("status") not in allowed_statuses:
        return False
    if tuple(metric) != REQUIRED_METRIC_FIELDS:
        return False
    try:
        return not validate_metric_record(metric, evaluated_at=evaluated_at)
    except Exception:
        return False


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: Any) -> str | None:
    if _aware_datetime(value) is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return value.isoformat()


def _financial_observation_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware_datetime(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed_date = date.fromisoformat(text)
    except ValueError:
        return _aware_datetime(text)
    return datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        tzinfo=timezone.utc,
    )


def _financial_as_of_text(value: Any) -> str | None:
    if _financial_observation_time(value) is None:
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _raw_value_is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _evaluation_time(evaluated_at: Any) -> datetime:
    parsed = _aware_datetime(evaluated_at)
    if parsed is None:
        raise ValueError("evaluated_at must be an explicit timezone-aware ISO timestamp")
    return parsed


def _copy_observations(observations: Any) -> list[Any]:
    if observations is None:
        return []
    if isinstance(observations, dict):
        return [dict(observations)]
    return [dict(item) if isinstance(item, dict) else item for item in observations]


def _safe_identity(value: Any, *, upper: bool = False) -> str | None:
    value = _safe_metadata_text(value)
    if value is None or not _SAFE_IDENTITY.fullmatch(value):
        return None
    return value.upper() if upper else value.lower()


def _error(family: str, ticker: Any, field: Any, code: str) -> dict[str, Any]:
    safe_ticker = _safe_identity(ticker, upper=True)
    safe_field = _safe_identity(field)
    return {
        "family": family,
        "ticker": safe_ticker,
        "field": safe_field,
        "code": code,
    }


def _sorted_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        ({key: item.get(key) for key in _ERROR_FIELDS} for item in errors),
        key=lambda item: (
            item["family"],
            item["ticker"] or "",
            item["field"] or "",
            item["code"],
        ),
    )


def _value_code(observation: dict[str, Any]) -> str | None:
    if "value" not in observation or observation.get("value") is None:
        return "missing_value"
    value = observation.get("value")
    if isinstance(value, str) and not value.strip():
        return "missing_value"
    if not _finite_number(value):
        return "invalid_value"
    return None


def _market_label(ticker: str) -> str:
    return f"{ticker} latest market price proxy"


def _missing_market_metric(
    ticker: str,
    *,
    evaluated_at: str,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observation = observation or {}
    as_of = _timestamp_text(observation.get("as_of"))
    retrieved_at = _timestamp_text(observation.get("retrieved_at"))
    evaluation = _aware_datetime(evaluated_at)
    observation_time = _aware_datetime(observation.get("as_of"))
    retrieval_time = _aware_datetime(observation.get("retrieved_at"))
    if not (
        observation_time is not None
        and retrieval_time is not None
        and evaluation is not None
        and observation_time <= retrieval_time <= evaluation
    ):
        as_of = None
        retrieved_at = None
    identity_mismatch = _market_ticker_identity_mismatch(observation, ticker)
    source = _verified_market_source(observation.get("source")) or "unavailable"
    fallback_from = _verified_market_source(observation.get("fallback_from"))
    source_identity = _canonical_market_source(observation.get("source"))
    fallback_identity = _canonical_market_source(observation.get("fallback_from"))
    is_fallback = bool(
        observation.get("is_fallback") is True
        and source_identity is not None
        and fallback_identity is not None
        and source_identity != fallback_identity
    )
    if identity_mismatch:
        source = "unavailable"
        fallback_from = None
        is_fallback = False
    try:
        metric = adapt_market_proxy_metric(
            metric_id=MARKET_METRIC_IDS[ticker],
            label=_market_label(ticker),
            value=None,
            unit="USD",
            as_of=as_of,
            retrieved_at=retrieved_at,
            source=source,
            method="No complete production market observation was accepted",
            frequency="daily",
            evaluated_at=evaluated_at,
            is_fallback=is_fallback,
            confidence="low",
        )
        if not isinstance(metric, dict):
            raise TypeError("invalid adapter result")
    except Exception:
        return _unavailable_market_metric(ticker)
    notes = ["Missing: no complete production market observation was accepted."]
    currency = _safe_metadata_text(observation.get("currency"))
    source_field = _safe_metadata_text(observation.get("source_field"))
    source_document = _verified_market_evidence(observation.get("source_document"))
    provenance = _verified_market_evidence(observation.get("provenance"))
    if identity_mismatch:
        source_document = None
        provenance = None
    if currency is not None:
        notes.append(f"Reported currency: {currency}")
    if source_field in _MARKET_PRICE_SOURCE_FIELDS:
        notes.append(f"Source field: {source_field}")
    if source_document is not None:
        notes.append(f"Source document: {source_document}")
    if provenance is not None:
        notes.append(f"Provenance: {provenance}")
    if is_fallback:
        notes.append(f"Fallback from: {fallback_from}")
    metric["notes"] = "; ".join(notes)
    if not _valid_adapter_metric(
        metric,
        evaluated_at=evaluated_at,
        allowed_statuses=("missing",),
    ):
        return _unavailable_market_metric(ticker)
    return metric


def _unavailable_market_metric(ticker: str) -> dict[str, Any]:
    return build_unavailable_metric(
        metric_id=MARKET_METRIC_IDS[ticker],
        label=_market_label(ticker),
        source_type="proxy",
        frequency="daily",
        notes="Unavailable: the market observation could not be safely adapted.",
    )


def _market_validation_codes(
    observation: dict[str, Any], *, evaluation: datetime
) -> list[str]:
    codes: list[str] = []
    value_code = _value_code(observation)
    if value_code:
        codes.append(value_code)
    elif float(observation["value"]) <= 0:
        codes.append("invalid_value")

    metric_kind = _text(observation.get("metric_kind"))
    if metric_kind is None:
        codes.append("missing_metric_kind")
    elif metric_kind != MARKET_METRIC_KIND:
        codes.append("unsupported_metric_kind")

    unit = _text(observation.get("unit"))
    if unit is None:
        codes.append("missing_unit")
    elif unit != "USD":
        codes.append("invalid_unit")

    currency = _text(observation.get("currency"))
    if currency is None:
        codes.append("missing_currency")
    elif currency != "USD":
        codes.append("currency_unit_mismatch")

    as_of_raw = observation.get("as_of")
    as_of = _aware_datetime(as_of_raw)
    if _raw_value_is_missing(as_of_raw):
        codes.append("missing_price_time")
    elif as_of is None:
        codes.append("naive_price_time")

    retrieved_raw = observation.get("retrieved_at")
    retrieved_at = _aware_datetime(retrieved_raw)
    if _raw_value_is_missing(retrieved_raw):
        codes.append("missing_retrieved_at")
    elif retrieved_at is None:
        codes.append("naive_retrieved_at")

    if as_of is not None and retrieved_at is not None:
        if retrieved_at < as_of:
            codes.append("invalid_price_time")
        if evaluation < retrieved_at:
            codes.append("invalid_retrieved_at")

    source = _safe_metadata_text(observation.get("source"))
    if source is None:
        codes.append("missing_source")
    elif _verified_market_source(source) is None:
        codes.append("unsupported_source")
    source_field = _safe_metadata_text(observation.get("source_field"))
    if source_field is None:
        codes.append("missing_source_field")
    elif source_field not in _MARKET_PRICE_SOURCE_FIELDS:
        codes.append("unsupported_source_field")
    source_document_raw = observation.get("source_document")
    provenance_raw = observation.get("provenance")
    source_document = _verified_market_evidence(source_document_raw)
    provenance = _verified_market_evidence(provenance_raw)
    if (
        not _raw_value_is_missing(source_document_raw)
        and source_document is None
    ) or (
        not _raw_value_is_missing(provenance_raw)
        and provenance is None
    ):
        codes.append("unsupported_source_document")
    if source_document is None and provenance is None:
        codes.append("missing_source_document")
    if _market_ticker_identity_mismatch(
        observation, _safe_identity(observation.get("ticker"), upper=True) or ""
    ):
        codes.append("ticker_identity_mismatch")

    is_fallback = observation.get("is_fallback")
    source_identity = _canonical_market_source(observation.get("source"))
    fallback_identity = _canonical_market_source(observation.get("fallback_from"))
    if not isinstance(is_fallback, bool):
        codes.append("invalid_fallback_metadata")
    elif is_fallback and (
        source_identity is None
        or fallback_identity is None
        or source_identity == fallback_identity
    ):
        codes.append("invalid_fallback_metadata")
    elif not is_fallback and not _raw_value_is_missing(
        observation.get("fallback_from")
    ):
        codes.append("invalid_fallback_metadata")
    return list(dict.fromkeys(codes))


def _market_method(observation: dict[str, Any], ticker: str) -> str:
    source_document = _verified_market_evidence(observation.get("source_document"))
    provenance = _verified_market_evidence(observation.get("provenance"))
    parts = [
        f"Latest market price for {ticker}",
        "Currency: USD",
        f"Source field: {_safe_metadata_text(observation.get('source_field'))}",
    ]
    if source_document is not None:
        parts.append(f"Source document: {source_document}")
    if provenance is not None:
        parts.append(f"Provenance: {provenance}")
    if observation.get("is_fallback"):
        parts.append(
            f"Fallback from: {_verified_market_source(observation.get('fallback_from'))}"
        )
    return "; ".join(parts)


def _build_market_metric(
    ticker: str,
    observation: dict[str, Any],
    *,
    evaluated_at: str,
    evaluation: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if observation.get("error") is not None or observation.get("fetch_error") is not None:
        metric = _missing_market_metric(
            ticker, evaluated_at=evaluated_at, observation=observation
        )
        errors = [_error("market_proxy", ticker, None, "fetch_failed")]
        if metric.get("status") == "unavailable":
            errors.append(_error("market_proxy", ticker, None, "adapter_failed"))
        return metric, errors

    codes = _market_validation_codes(observation, evaluation=evaluation)
    if codes:
        metric = _missing_market_metric(
            ticker, evaluated_at=evaluated_at, observation=observation
        )
        errors = [
            _error("market_proxy", ticker, None, code) for code in codes
        ]
        if metric.get("status") == "unavailable":
            errors.append(_error("market_proxy", ticker, None, "adapter_failed"))
        return metric, errors

    try:
        metric = adapt_market_proxy_metric(
            metric_id=MARKET_METRIC_IDS[ticker],
            label=_market_label(ticker),
            value=observation["value"],
            unit="USD",
            as_of=_timestamp_text(observation["as_of"]),
            retrieved_at=_timestamp_text(observation["retrieved_at"]),
            source=_verified_market_source(observation["source"]),
            method=_market_method(observation, ticker),
            frequency="daily",
            evaluated_at=evaluated_at,
            is_fallback=observation["is_fallback"],
            confidence="low" if observation["is_fallback"] else "medium",
        )
        if not _valid_adapter_metric(
            metric,
            evaluated_at=evaluated_at,
            allowed_statuses=("ok", "stale"),
        ):
            raise TypeError("invalid adapter result")
    except Exception:
        return _unavailable_market_metric(ticker), [
            _error("market_proxy", ticker, None, "adapter_failed")
        ]
    return metric, []


def build_market_proxy_metrics(
    observations: Any,
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    """Validate injected latest-price observations and build four proxy slots."""

    evaluation = _evaluation_time(evaluated_at)
    evaluated_text = _timestamp_text(evaluated_at)
    copied = _copy_observations(observations)
    buckets: dict[str, list[dict[str, Any]]] = {
        ticker: [] for ticker in SUPPORTED_MARKET_TICKERS
    }
    errors: list[dict[str, Any]] = []

    for observation in copied:
        if not isinstance(observation, dict):
            errors.append(_error("market_proxy", None, None, "unsupported_ticker"))
            continue
        ticker = _safe_identity(observation.get("ticker"), upper=True)
        if ticker not in buckets:
            errors.append(
                _error("market_proxy", ticker, None, "unsupported_ticker")
            )
            continue
        buckets[ticker].append(observation)

    metrics: list[dict[str, Any]] = []
    for ticker in SUPPORTED_MARKET_TICKERS:
        bucket = buckets[ticker]
        if not bucket:
            metric = _missing_market_metric(ticker, evaluated_at=evaluated_text)
            metrics.append(metric)
            if metric.get("status") == "unavailable":
                errors.append(
                    _error("market_proxy", ticker, None, "adapter_failed")
                )
            continue
        if len(bucket) != 1:
            metric = _missing_market_metric(ticker, evaluated_at=evaluated_text)
            metrics.append(metric)
            errors.append(
                _error("market_proxy", ticker, None, "duplicate_observation")
            )
            if metric.get("status") == "unavailable":
                errors.append(
                    _error("market_proxy", ticker, None, "adapter_failed")
                )
            continue
        metric, metric_errors = _build_market_metric(
            ticker,
            bucket[0],
            evaluated_at=evaluated_text,
            evaluation=evaluation,
        )
        metrics.append(metric)
        errors.extend(metric_errors)

    return {"metrics": metrics, "errors": _sorted_errors(errors)}


def _financial_label(ticker: str, field: str) -> str:
    labels = {
        "revenue": "Revenue",
        "gross_margin": "Gross Margin",
        "operating_margin": "Operating Margin",
    }
    return f"{ticker} {labels[field]}"


def _financial_unit(field: str) -> str:
    return "USD millions" if field == "revenue" else "percent"


def _missing_financial_metric(
    ticker: str,
    field: str,
    *,
    evaluated_at: str,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observation = observation or {}
    evaluation = _aware_datetime(evaluated_at)
    observation_time = _financial_observation_time(observation.get("as_of"))
    retrieval_time = _aware_datetime(observation.get("retrieved_at"))
    if (
        observation_time is not None
        and retrieval_time is not None
        and evaluation is not None
        and observation_time <= retrieval_time <= evaluation
    ):
        as_of = _financial_as_of_text(observation.get("as_of"))
        retrieved_at = _timestamp_text(observation.get("retrieved_at"))
    else:
        as_of = None
        retrieved_at = None
    identity_mismatch = _financial_company_identity_mismatch(observation, ticker)
    source = _verified_financial_source(observation.get("source"))
    if identity_mismatch or source is None:
        source = "unavailable"
    source_field = _safe_metadata_text(observation.get("source_field"))
    if source_field is None or not _supported_financial_source_field(
        field, source_field
    ):
        source_field = "unavailable"
    source_document = _verified_financial_evidence(observation.get("source_document"))
    provenance = _verified_financial_evidence(observation.get("provenance"))
    fallback_from = _verified_financial_source(observation.get("fallback_from"))
    source_identity = _canonical_financial_source(observation.get("source"))
    fallback_identity = _canonical_financial_source(observation.get("fallback_from"))
    if identity_mismatch:
        source_document = None
        provenance = None
        fallback_from = None
    is_fallback = bool(
        observation.get("is_fallback") is True
        and source_identity is not None
        and fallback_identity is not None
        and source_identity != fallback_identity
        and not identity_mismatch
    )
    raw_unit = _safe_metadata_text(observation.get("unit"))
    raw_currency = _safe_metadata_text(observation.get("currency"))
    period_type = _text(observation.get("period_type"))
    fiscal_period = _safe_fiscal_period_text(observation.get("fiscal_period"))
    adapter_period_type = (
        period_type
        if period_type in {"quarterly", "annual"}
        and fiscal_period is not None
        and _valid_fiscal_period(fiscal_period, period_type)
        and not _financial_period_evidence_mismatch(observation, period_type)
        else None
    )
    try:
        metric = adapt_company_financial_metric(
            ticker=ticker,
            metric_id=FINANCIAL_METRIC_IDS[field],
            label=_financial_label(ticker, field),
            value=None,
            unit=raw_unit or _financial_unit(field),
            currency=raw_currency if field == "revenue" else None,
            currency_required=field == "revenue",
            fiscal_period=adapter_period_type,
            as_of=as_of,
            retrieved_at=retrieved_at,
            source=source,
            source_field=source_field,
            source_document=source_document,
            provenance=provenance
            or "No complete production financial observation was accepted",
            frequency="event_driven",
            evaluated_at=evaluated_at,
            is_fallback=is_fallback,
            confidence="low",
        )
        if not isinstance(metric, dict):
            raise TypeError("invalid adapter result")
    except Exception:
        return _unavailable_financial_metric(ticker, field)
    notes = ["Missing: no complete production financial observation was accepted."]
    if fiscal_period is not None and adapter_period_type is not None:
        notes.append(f"Fiscal period label: {fiscal_period}")
    if adapter_period_type is not None:
        notes.append(f"Period type: {period_type}")
    if raw_currency is not None:
        notes.append(f"Reported currency: {raw_currency}")
    if source_field != "unavailable":
        notes.append(f"Source field: {source_field}")
    if source_document is not None:
        notes.append(f"Source document: {source_document}")
    if provenance is not None:
        notes.append(f"Provenance: {provenance}")
    if is_fallback:
        notes.append(f"Fallback from: {fallback_from}")
    metric["notes"] = "; ".join(notes)
    if not _valid_adapter_metric(
        metric,
        evaluated_at=evaluated_at,
        allowed_statuses=("missing",),
    ):
        return _unavailable_financial_metric(ticker, field)
    return metric


def _unavailable_financial_metric(ticker: str, field: str) -> dict[str, Any]:
    return build_unavailable_metric(
        metric_id=FINANCIAL_METRIC_IDS[field],
        label=_financial_label(ticker, field),
        source_type="company_reported",
        frequency="event_driven",
        notes="Unavailable: the financial observation semantic could not be verified.",
    )


def _valid_fiscal_period(fiscal_period: str, period_type: str) -> bool:
    lowered = fiscal_period.casefold()
    if any(label in lowered for label in _VAGUE_FISCAL_LABELS):
        return False
    if period_type == "quarterly":
        return _FISCAL_QUARTERLY_LABEL.fullmatch(fiscal_period) is not None
    return _FISCAL_ANNUAL_LABEL.fullmatch(fiscal_period) is not None


def _safe_fiscal_period_text(value: Any) -> str | None:
    value = _text(value)
    if value is None:
        return None
    if _valid_fiscal_period(value, "quarterly") or _valid_fiscal_period(
        value, "annual"
    ):
        return value
    return None


def _supported_financial_source_field(field: str, source_field: str) -> bool:
    if field == "revenue":
        return source_field == "revenue"
    return source_field in _MARGIN_SOURCE_FIELDS[field]


def _financial_validation_codes(
    observation: dict[str, Any],
    *,
    ticker: str,
    field: str,
    evaluation: datetime,
) -> list[str]:
    codes: list[str] = []
    value_code = _value_code(observation)
    if value_code:
        codes.append(value_code)

    unit = _text(observation.get("unit"))
    if unit is None:
        codes.append("missing_unit")

    currency_raw = observation.get("currency")
    currency = _text(currency_raw)
    if field == "revenue":
        if _raw_value_is_missing(currency_raw):
            codes.append("missing_currency")
        elif currency != "USD":
            codes.append("currency_unit_mismatch")
        if unit is not None and unit not in _REVENUE_TO_USD_MILLIONS:
            codes.append("invalid_unit")
    elif not _raw_value_is_missing(currency_raw):
        codes.append("currency_unit_mismatch")

    fiscal_period = _text(observation.get("fiscal_period"))
    period_type = _text(observation.get("period_type"))
    if fiscal_period is None:
        codes.append("missing_fiscal_period")
    if period_type is None:
        codes.append("missing_period_type")
    elif period_type not in {"quarterly", "annual"}:
        codes.append("unsupported_period_type")
    if (
        fiscal_period is not None
        and period_type in {"quarterly", "annual"}
        and not _valid_fiscal_period(fiscal_period, period_type)
    ):
        codes.append("invalid_fiscal_period")
    if _financial_period_evidence_mismatch(observation, period_type):
        codes.append("period_evidence_mismatch")

    as_of_raw = observation.get("as_of")
    as_of = _financial_observation_time(as_of_raw)
    if _raw_value_is_missing(as_of_raw):
        codes.append("missing_as_of")
    elif as_of is None:
        codes.append("invalid_as_of")

    retrieved_raw = observation.get("retrieved_at")
    retrieved_at = _aware_datetime(retrieved_raw)
    if _raw_value_is_missing(retrieved_raw):
        codes.append("missing_retrieved_at")
    elif retrieved_at is None:
        codes.append("naive_retrieved_at")
    if as_of is not None and retrieved_at is not None:
        if retrieved_at < as_of or evaluation < retrieved_at:
            codes.append("invalid_retrieved_at")

    source = _safe_metadata_text(observation.get("source"))
    if source is None:
        codes.append("missing_source")
    elif _verified_financial_source(source) is None:
        codes.append("unsupported_source")
    source_field = _safe_metadata_text(observation.get("source_field"))
    if source_field is None:
        codes.append("missing_source_field")
    elif not _supported_financial_source_field(field, source_field):
        codes.append("unsupported_source_field")

    source_document_raw = observation.get("source_document")
    provenance_raw = observation.get("provenance")
    source_document = _verified_financial_evidence(source_document_raw)
    provenance = _verified_financial_evidence(provenance_raw)
    if (
        not _raw_value_is_missing(source_document_raw)
        and source_document is None
    ) or (
        not _raw_value_is_missing(provenance_raw)
        and provenance is None
    ):
        codes.append("unsupported_source_document")
    if source_document is None and provenance is None:
        codes.append("missing_source_document")

    source_reference_raw = observation.get("source_reference")
    if (
        not _raw_value_is_missing(source_reference_raw)
        and _verified_source_reference(source_reference_raw) is None
    ):
        codes.append("invalid_source_reference")
    if _financial_company_identity_mismatch(observation, ticker):
        codes.append("company_identity_mismatch")

    estimate_flag = observation.get("is_estimate")
    if estimate_flag is not None and estimate_flag is not False:
        codes.append("estimated_value_not_supported")

    if field != "revenue" and unit is not None and source_field is not None:
        representation = _MARGIN_SOURCE_FIELDS[field].get(source_field)
        if representation is not None and unit != representation:
            codes.append("ambiguous_margin_unit")
        elif representation is None and unit not in {"ratio", "percent"}:
            codes.append("ambiguous_margin_unit")
    elif field != "revenue" and unit not in {None, "ratio", "percent"}:
        codes.append("ambiguous_margin_unit")

    is_fallback = observation.get("is_fallback")
    source_identity = _canonical_financial_source(observation.get("source"))
    fallback_identity = _canonical_financial_source(observation.get("fallback_from"))
    if not isinstance(is_fallback, bool):
        codes.append("invalid_fallback_metadata")
    elif is_fallback and (
        source_identity is None
        or fallback_identity is None
        or source_identity == fallback_identity
    ):
        codes.append("invalid_fallback_metadata")
    elif not is_fallback and not _raw_value_is_missing(
        observation.get("fallback_from")
    ):
        codes.append("invalid_fallback_metadata")

    return list(dict.fromkeys(codes))


def _normalize_financial_value(
    observation: dict[str, Any], field: str
) -> tuple[float, str]:
    value = float(observation["value"])
    unit = _text(observation["unit"])
    if field == "revenue":
        return value * _REVENUE_TO_USD_MILLIONS[unit], "USD millions"
    representation = _MARGIN_SOURCE_FIELDS[field][_text(observation["source_field"])]
    return (value * 100 if representation == "ratio" else value), "percent"


def _financial_evidence(observation: dict[str, Any]) -> tuple[str | None, str | None]:
    source_document = _verified_financial_evidence(observation.get("source_document"))
    provenance = _verified_financial_evidence(observation.get("provenance"))
    evidence_parts = [
        source_document or provenance,
        f"Fiscal period label: {_safe_fiscal_period_text(observation.get('fiscal_period'))}",
        f"Period type: {_safe_metadata_text(observation.get('period_type'))}",
        f"Original unit: {_safe_metadata_text(observation.get('unit'))}",
    ]
    if source_document is not None and provenance is not None:
        evidence_parts.append(f"Provenance: {provenance}")
    source_reference = _verified_source_reference(observation.get("source_reference"))
    if source_reference is not None:
        evidence_parts.append(f"Source reference: {source_reference}")
    if observation.get("is_fallback"):
        evidence_parts.append(
            f"Fallback from: {_verified_financial_source(observation.get('fallback_from'))}"
        )
    evidence = "; ".join(part for part in evidence_parts if part)
    if source_document is not None:
        return evidence, None
    return None, evidence


def _build_financial_metric(
    ticker: str,
    field: str,
    observation: dict[str, Any],
    *,
    evaluated_at: str,
    evaluation: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if observation.get("error") is not None or observation.get("fetch_error") is not None:
        metric = _missing_financial_metric(
            ticker, field, evaluated_at=evaluated_at, observation=observation
        )
        errors = [_error("company_financial", ticker, field, "fetch_failed")]
        if metric.get("status") == "unavailable":
            errors.append(
                _error("company_financial", ticker, field, "adapter_failed")
            )
        return metric, errors

    codes = _financial_validation_codes(
        observation,
        ticker=ticker,
        field=field,
        evaluation=evaluation,
    )
    if codes:
        missing_builder = (
            _unavailable_financial_metric
            if "unsupported_source_field" in codes
            else None
        )
        used_missing_adapter = missing_builder is None
        metric = (
            _missing_financial_metric(
                ticker,
                field,
                evaluated_at=evaluated_at,
                observation=observation,
            )
            if used_missing_adapter
            else missing_builder(ticker, field)
        )
        errors = [
            _error("company_financial", ticker, field, code) for code in codes
        ]
        if used_missing_adapter and metric.get("status") == "unavailable":
            errors.append(
                _error("company_financial", ticker, field, "adapter_failed")
            )
        return metric, errors

    value, unit = _normalize_financial_value(observation, field)
    if not _finite_number(value):
        metric = _missing_financial_metric(
            ticker,
            field,
            evaluated_at=evaluated_at,
            observation=observation,
        )
        errors = [_error("company_financial", ticker, field, "invalid_value")]
        if metric.get("status") == "unavailable":
            errors.append(
                _error("company_financial", ticker, field, "adapter_failed")
            )
        return metric, errors
    source_document, provenance = _financial_evidence(observation)
    try:
        metric = adapt_company_financial_metric(
            ticker=ticker,
            metric_id=FINANCIAL_METRIC_IDS[field],
            label=_financial_label(ticker, field),
            value=value,
            unit=unit,
            currency="USD" if field == "revenue" else None,
            currency_required=field == "revenue",
            fiscal_period=_text(observation["period_type"]),
            as_of=_financial_as_of_text(observation["as_of"]),
            retrieved_at=_timestamp_text(observation["retrieved_at"]),
            source=_verified_financial_source(observation["source"]),
            source_field=_safe_metadata_text(observation["source_field"]),
            source_document=source_document,
            provenance=provenance,
            frequency="event_driven",
            evaluated_at=evaluated_at,
            is_fallback=observation["is_fallback"],
            confidence="low" if observation["is_fallback"] else "medium",
        )
        if not _valid_adapter_metric(
            metric,
            evaluated_at=evaluated_at,
            allowed_statuses=("ok", "stale"),
        ):
            raise TypeError("invalid adapter result")
    except Exception:
        return _unavailable_financial_metric(ticker, field), [
            _error("company_financial", ticker, field, "adapter_failed")
        ]
    return metric, []


def build_company_financial_metrics(
    observations: Any,
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    """Validate injected reported fields and build six company metric slots."""

    evaluation = _evaluation_time(evaluated_at)
    evaluated_text = _timestamp_text(evaluated_at)
    copied = _copy_observations(observations)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {
        (ticker, field): []
        for ticker in SUPPORTED_FINANCIAL_TICKERS
        for field in SUPPORTED_FINANCIAL_FIELDS
    }
    errors: list[dict[str, Any]] = []

    for observation in copied:
        if not isinstance(observation, dict):
            errors.append(
                _error("company_financial", None, None, "unsupported_ticker")
            )
            continue
        ticker = _safe_identity(observation.get("ticker"), upper=True)
        field = _safe_identity(observation.get("field"))
        if ticker not in SUPPORTED_FINANCIAL_TICKERS:
            errors.append(
                _error("company_financial", ticker, field, "unsupported_ticker")
            )
            continue
        if field not in SUPPORTED_FINANCIAL_FIELDS:
            errors.append(
                _error("company_financial", ticker, field, "unsupported_field")
            )
            continue
        buckets[(ticker, field)].append(observation)

    metrics: list[dict[str, Any]] = []
    for ticker in SUPPORTED_FINANCIAL_TICKERS:
        for field in SUPPORTED_FINANCIAL_FIELDS:
            bucket = buckets[(ticker, field)]
            if not bucket:
                metric = _missing_financial_metric(
                    ticker, field, evaluated_at=evaluated_text
                )
                metrics.append(metric)
                if metric.get("status") == "unavailable":
                    errors.append(
                        _error(
                            "company_financial",
                            ticker,
                            field,
                            "adapter_failed",
                        )
                    )
                continue
            if len(bucket) != 1:
                metric = _missing_financial_metric(
                    ticker, field, evaluated_at=evaluated_text
                )
                metrics.append(metric)
                errors.append(
                    _error(
                        "company_financial",
                        ticker,
                        field,
                        "duplicate_observation",
                    )
                )
                if metric.get("status") == "unavailable":
                    errors.append(
                        _error(
                            "company_financial",
                            ticker,
                            field,
                            "adapter_failed",
                        )
                    )
                continue
            metric, metric_errors = _build_financial_metric(
                ticker,
                field,
                bucket[0],
                evaluated_at=evaluated_text,
                evaluation=evaluation,
            )
            metrics.append(metric)
            errors.extend(metric_errors)

    return {"metrics": metrics, "errors": _sorted_errors(errors)}


def build_memory_cycle_production_metrics(
    *,
    market_observations: Any,
    financial_observations: Any,
    evaluated_at: str,
) -> dict[str, Any]:
    """Build the stable ten-slot production result from injected observations."""

    _evaluation_time(evaluated_at)
    try:
        copied_market = _copy_observations(market_observations)
        copied_financial = _copy_observations(financial_observations)
        no_input = not copied_market and not copied_financial

        market_result = build_market_proxy_metrics(
            copied_market, evaluated_at=evaluated_at
        )
        financial_result = build_company_financial_metrics(
            copied_financial, evaluated_at=evaluated_at
        )
        metrics = [
            *[dict(metric) for metric in market_result["metrics"]],
            *[dict(metric) for metric in financial_result["metrics"]],
        ]
        errors = _sorted_errors(
            [
                *[dict(error) for error in market_result["errors"]],
                *[dict(error) for error in financial_result["errors"]],
            ]
        )

        successful = sum(
            metric.get("status") in {"ok", "stale"} for metric in metrics
        )
        stale = sum(metric.get("status") == "stale" for metric in metrics)
        missing = sum(metric.get("status") == "missing" for metric in metrics)
        unavailable = sum(
            metric.get("status") == "unavailable" for metric in metrics
        )
        if no_input:
            status = "empty"
        elif missing == 0 and unavailable == 0:
            status = "ok"
        else:
            status = "partial"

        return {
            "metrics": metrics,
            "status": status,
            "expected_metric_count": len(CANONICAL_METRIC_ORDER),
            "successful_metric_count": successful,
            "stale_metric_count": stale,
            "missing_metric_count": missing,
            "unavailable_metric_count": unavailable,
            "errors": errors,
        }
    except Exception:
        return {
            "metrics": [],
            "status": "error",
            "expected_metric_count": len(CANONICAL_METRIC_ORDER),
            "successful_metric_count": 0,
            "stale_metric_count": 0,
            "missing_metric_count": 0,
            "unavailable_metric_count": 0,
            "errors": [
                _error("production", None, None, "internal_error")
            ],
        }
