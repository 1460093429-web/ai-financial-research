"""Pure live orchestration for metadata-complete Memory Cycle observations."""

from copy import deepcopy
from datetime import datetime, timezone
import re
from types import MappingProxyType
from typing import Any, Callable

from providers.memory_cycle_data import (
    SUPPORTED_FINANCIAL_FIELDS,
    SUPPORTED_FINANCIAL_TICKERS,
    SUPPORTED_MARKET_TICKERS,
    fetch_financial_observations,
    fetch_market_observations,
)
from services.memory_cycle_contract import (
    REQUIRED_METRIC_FIELDS,
    validate_metric_record,
)
from services.memory_cycle_production import (
    CANONICAL_METRIC_ORDER,
    FINANCIAL_METRIC_IDS,
    MARKET_METRIC_IDS,
    build_memory_cycle_production_metrics,
)


_ERROR_FIELDS = ("family", "ticker", "field", "code")
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_SAFE_ERROR_FAMILIES = frozenset(
    {"market_proxy", "company_financial", "production"}
)
_SECRET_PREFIXES = (
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
_SENSITIVE_IDENTITY_WORDS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_PRODUCTION_RESULT_FIELDS = (
    "metrics",
    "status",
    "expected_metric_count",
    "successful_metric_count",
    "stale_metric_count",
    "missing_metric_count",
    "unavailable_metric_count",
    "errors",
)
_FINANCIAL_LABELS = MappingProxyType(
    {
        "revenue": "Revenue",
        "gross_margin": "Gross Margin",
        "operating_margin": "Operating Margin",
    }
)
_CANONICAL_METRIC_IDENTITIES = tuple(
    (
        (
            MARKET_METRIC_IDS[ticker],
            f"{ticker} latest market price proxy",
        )
        if family == "market_proxy"
        else (
            FINANCIAL_METRIC_IDS[field],
            f"{ticker} {_FINANCIAL_LABELS[field]}",
        )
    )
    for family, ticker, field in CANONICAL_METRIC_ORDER
)
_UNSAFE_OUTPUT_MARKERS = (
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "bearer ",
    "credential",
    "password",
    "raw response",
    "raw_response",
    "response body",
    "response_body",
    "secret",
    "token=",
    "traceback",
    "file://",
)
_SECRET_VALUE = re.compile(
    r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{12,}(?![A-Za-z0-9_-])"
)
_LOCAL_PATH = re.compile(
    r"(?:^|\s)/(?:users|home|private|tmp|var|etc)(?:/|$)"
    r"|(?:^|\s)[A-Za-z]:\\users\\"
    r"|(?:^|\s)(?:~[/\\]|\.\.?[/\\])",
    re.IGNORECASE,
)


def _aware_time(value: Any, *, name: str) -> datetime:
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.endswith(("Z", "z")):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
    try:
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise ValueError(
            f"{name} must be a timezone-aware timestamp"
        ) from None


def _scope_copy(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _safe_identity(value: Any, *, upper: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _SAFE_IDENTITY.fullmatch(text) is None:
        return None
    lowered = text.casefold()
    if any(prefix in lowered for prefix in _SECRET_PREFIXES):
        return None
    if any(word in lowered for word in _SENSITIVE_IDENTITY_WORDS):
        return None
    if _SECRET_VALUE.search(text) is not None:
        return None
    if lowered.endswith((".env", ".key", ".pem", ".log")):
        return None
    return text.upper() if upper else text.lower()


def _safe_ticker(value: Any) -> str | None:
    ticker = _safe_identity(value, upper=True)
    if ticker is None or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker) is None:
        return None
    return ticker


def _has_unsafe_output_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.casefold()
    return (
        any(prefix in lowered for prefix in _SECRET_PREFIXES)
        or any(marker in lowered for marker in _UNSAFE_OUTPUT_MARKERS)
        or _SECRET_VALUE.search(value) is not None
        or _LOCAL_PATH.search(value) is not None
    )


def _safe_error(error: Any) -> dict[str, str | None] | None:
    if not isinstance(error, dict):
        return None
    family = _safe_identity(error.get("family"))
    code = _safe_identity(error.get("code"))
    if family not in _SAFE_ERROR_FAMILIES or code is None:
        return None
    return {
        "family": family,
        "ticker": _safe_ticker(error.get("ticker")),
        "field": _safe_identity(error.get("field")),
        "code": code,
    }


def _safe_errors(*groups: Any) -> list[dict[str, str | None]]:
    sanitized: set[tuple[str | None, ...]] = set()
    for group in groups:
        if not isinstance(group, (list, tuple)):
            continue
        for raw_error in group:
            error = _safe_error(raw_error)
            if error is not None:
                sanitized.add(tuple(error[field] for field in _ERROR_FIELDS))
    return [
        dict(zip(_ERROR_FIELDS, values))
        for values in sorted(
            sanitized,
            key=lambda item: (
                item[0] or "",
                item[1] or "",
                item[2] or "",
                item[3] or "",
            ),
        )
    ]


def _provider_failure(
    *, family: str, tickers: list[Any], fields: tuple[str, ...] | None = None
) -> dict[str, Any]:
    errors: list[dict[str, str | None]] = []
    for raw_ticker in tickers:
        ticker = _safe_ticker(raw_ticker)
        if fields is None:
            errors.append(
                {
                    "family": family,
                    "ticker": ticker,
                    "field": None,
                    "code": "fetch_failed",
                }
            )
        else:
            for field in fields:
                errors.append(
                    {
                        "family": family,
                        "ticker": ticker,
                        "field": field,
                        "code": "fetch_failed",
                    }
                )
    return {"observations": [], "errors": errors, "status": "error"}


def _validated_provider_result(
    value: Any,
    *,
    family: str,
    tickers: list[Any],
    fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _provider_failure(family=family, tickers=tickers, fields=fields)
    observations = value.get("observations")
    errors = value.get("errors")
    status = value.get("status")
    if (
        not isinstance(observations, list)
        or any(not isinstance(item, dict) for item in observations)
        or not isinstance(errors, list)
        or status not in {"ok", "partial", "empty", "error"}
    ):
        return _provider_failure(family=family, tickers=tickers, fields=fields)
    sanitized_errors = [_safe_error(error) for error in errors]
    if any(error is None or error["family"] != family for error in sanitized_errors):
        return _provider_failure(family=family, tickers=tickers, fields=fields)
    return {
        "observations": [dict(item) for item in observations],
        "errors": [error for error in sanitized_errors if error is not None],
        "status": status,
    }


def _valid_production_result(value: Any, *, evaluated_at: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(_PRODUCTION_RESULT_FIELDS):
        return False
    metrics = value.get("metrics")
    if not isinstance(metrics, list):
        return False
    if value.get("status") not in {"ok", "partial", "empty", "error"}:
        return False
    errors = value.get("errors")
    if not isinstance(errors, list):
        return False
    if not all(
        isinstance(value.get(field), int) and not isinstance(value.get(field), bool)
        for field in _PRODUCTION_RESULT_FIELDS[2:7]
    ):
        return False
    if any(value[field] < 0 for field in _PRODUCTION_RESULT_FIELDS[2:7]):
        return False
    expected = len(CANONICAL_METRIC_ORDER)
    if value["expected_metric_count"] != expected:
        return False
    if value["status"] == "error":
        return value == _internal_error_result()

    if len(metrics) != expected:
        return False
    if any(
        not isinstance(metric, dict)
        or set(metric) != set(REQUIRED_METRIC_FIELDS)
        or any(_has_unsafe_output_text(item) for item in metric.values())
        for metric in metrics
    ):
        return False
    try:
        if any(
            validate_metric_record(metric, evaluated_at=evaluated_at)
            for metric in metrics
        ):
            return False
    except Exception:
        return False
    if [
        (metric["metric_id"], metric["label"]) for metric in metrics
    ] != list(_CANONICAL_METRIC_IDENTITIES):
        return False
    if any(
        not isinstance(error, dict)
        or set(error) != set(_ERROR_FIELDS)
        or _safe_error(error) != error
        or any(_has_unsafe_output_text(item) for item in error.values())
        for error in errors
    ):
        return False

    statuses = [metric["status"] for metric in metrics]
    successful = sum(status in {"ok", "stale"} for status in statuses)
    stale = statuses.count("stale")
    missing = statuses.count("missing")
    unavailable = statuses.count("unavailable")
    if (
        value["successful_metric_count"],
        value["stale_metric_count"],
        value["missing_metric_count"],
        value["unavailable_metric_count"],
    ) != (successful, stale, missing, unavailable):
        return False
    if value["status"] == "ok" and (missing or unavailable):
        return False
    if value["status"] == "partial" and not (missing or unavailable):
        return False
    if value["status"] == "empty" and (
        successful or stale or unavailable or missing != expected or errors
    ):
        return False
    return True


def _internal_error_result() -> dict[str, Any]:
    return {
        "metrics": [],
        "status": "error",
        "expected_metric_count": len(CANONICAL_METRIC_ORDER),
        "successful_metric_count": 0,
        "stale_metric_count": 0,
        "missing_metric_count": 0,
        "unavailable_metric_count": 0,
        "errors": [
            {
                "family": "production",
                "ticker": None,
                "field": None,
                "code": "internal_error",
            }
        ],
    }


def build_live_memory_cycle_result(
    *,
    yahoo_quote_fetcher: Callable[[str], Any] | None = None,
    fmp_income_statement_fetcher: Callable[[str], Any] | None = None,
    retrieved_at: Any,
    evaluated_at: Any,
    fmp_quote_fetcher: Callable[[str], Any] | None = None,
    fmp_identity_fetcher: Callable[[str], Any] | None = None,
    market_tickers: Any = SUPPORTED_MARKET_TICKERS,
    financial_tickers: Any = SUPPORTED_FINANCIAL_TICKERS,
    market_observation_fetcher: Callable[..., Any] | None = None,
    financial_observation_fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch injected raw data and build the Phase 4.6 ten-slot result."""

    retrieval_time = _aware_time(retrieved_at, name="retrieved_at")
    evaluation_time = _aware_time(evaluated_at, name="evaluated_at")
    if evaluation_time < retrieval_time:
        raise ValueError("evaluated_at must not precede retrieved_at")
    market_scope = _scope_copy(market_tickers)
    financial_scope = _scope_copy(financial_tickers)

    try:
        if market_observation_fetcher is None:
            raw_market_result = fetch_market_observations(
                market_scope,
                yahoo_quote_fetcher=yahoo_quote_fetcher,
                fmp_quote_fetcher=fmp_quote_fetcher,
                retrieved_at=retrieved_at,
            )
        else:
            raw_market_result = market_observation_fetcher(
                market_scope, retrieved_at=retrieved_at
            )
    except Exception:
        raw_market_result = _provider_failure(
            family="market_proxy", tickers=market_scope
        )
    market_result = _validated_provider_result(
        raw_market_result,
        family="market_proxy",
        tickers=market_scope,
    )

    try:
        if financial_observation_fetcher is None:
            raw_financial_result = fetch_financial_observations(
                financial_scope,
                fmp_income_statement_fetcher=fmp_income_statement_fetcher,
                fmp_identity_fetcher=fmp_identity_fetcher,
                retrieved_at=retrieved_at,
            )
        else:
            raw_financial_result = financial_observation_fetcher(
                financial_scope, retrieved_at=retrieved_at
            )
    except Exception:
        raw_financial_result = _provider_failure(
            family="company_financial",
            tickers=financial_scope,
            fields=SUPPORTED_FINANCIAL_FIELDS,
        )
    financial_result = _validated_provider_result(
        raw_financial_result,
        family="company_financial",
        tickers=financial_scope,
        fields=SUPPORTED_FINANCIAL_FIELDS,
    )

    market_observations = market_result.get("observations", [])
    financial_observations = financial_result.get("observations", [])
    if not isinstance(market_observations, list):
        market_observations = []
    if not isinstance(financial_observations, list):
        financial_observations = []
    provider_errors = _safe_errors(
        market_result.get("errors", []), financial_result.get("errors", [])
    )

    try:
        production_result = build_memory_cycle_production_metrics(
            market_observations=[dict(item) for item in market_observations],
            financial_observations=[
                dict(item) for item in financial_observations
            ],
            evaluated_at=evaluated_at,
        )
    except Exception:
        return _internal_error_result()
    if not _valid_production_result(production_result, evaluated_at=evaluated_at):
        return _internal_error_result()

    result = deepcopy(production_result)
    production_errors = result.get("errors", [])
    result["errors"] = _safe_errors(provider_errors, production_errors)
    if result.get("status") != "error" and result["errors"]:
        result["status"] = "partial"
    return result
