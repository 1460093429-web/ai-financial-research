"""Metadata-preserving provider wrappers for the Memory Cycle pipeline.

All external acquisition is supplied by the caller.  This module owns no
client, configuration, cache, persistence, or current-time source.
"""

from datetime import date, datetime, timezone
import math
from numbers import Real
import re
from typing import Any, Callable


SUPPORTED_MARKET_TICKERS = ("MU", "SNDK", "SMH", "SOXX")
SUPPORTED_FINANCIAL_TICKERS = ("MU", "SNDK")
SUPPORTED_FINANCIAL_FIELDS = (
    "revenue",
    "gross_margin",
    "operating_margin",
)
MARKET_METRIC_KIND = "latest_price"
SNDK_MIN_FINANCIAL_DATE = "2025-01-01"

_ERROR_FIELDS = ("family", "ticker", "field", "code")
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SAFE_CIK = re.compile(r"^\d{10}$")
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
_STATEMENT_ERROR_PRIORITY = (
    "statement_identity_mismatch",
    "ticker_identity_mismatch",
    "missing_as_of",
    "invalid_as_of",
    "legacy_statement",
    "missing_period_metadata",
    "unsupported_period",
    "period_year_mismatch",
    "missing_currency",
    "unsupported_currency",
    "invalid_response",
)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _number(value: Any) -> Real | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            return None
        return value if finite else None
    if isinstance(value, str) and value.strip():
        try:
            converted = float(value.strip())
        except ValueError:
            return None
        return converted if math.isfinite(converted) else None
    return None


def _timestamp(value: Any, *, allow_epoch: bool) -> tuple[datetime | None, str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, Real) and not isinstance(value, bool):
        numeric = _number(value)
        if not allow_epoch or numeric is None or float(numeric) <= 0:
            return None, "invalid"
        try:
            parsed = datetime.fromtimestamp(float(numeric), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None, "invalid"
    elif isinstance(value, str):
        candidate = value.strip()
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", candidate) is not None:
            return None, "invalid"
        if candidate.endswith(("Z", "z")):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None, "invalid"
    else:
        return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "naive"
    try:
        normalized = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None, "invalid"
    return normalized, "ok"


def _required_timestamp(value: Any, *, name: str) -> tuple[datetime, str]:
    parsed, status = _timestamp(value, allow_epoch=False)
    if parsed is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return parsed, parsed.isoformat()


def _safe_identity(value: Any, *, upper: bool = False) -> str | None:
    text = _text(value)
    if text is None or _SAFE_IDENTITY.fullmatch(text) is None:
        return None
    lowered = text.casefold()
    if any(prefix in lowered for prefix in _SECRET_PREFIXES):
        return None
    if any(word in lowered for word in _SENSITIVE_IDENTITY_WORDS):
        return None
    if re.fullmatch(r"(?:AKIA|ASIA)[A-Z0-9]{16}", text.upper()) is not None:
        return None
    if lowered.endswith((".env", ".key", ".pem", ".log")):
        return None
    return text.upper() if upper else text.lower()


def _safe_ticker(value: Any) -> str | None:
    ticker = _safe_identity(value, upper=True)
    if ticker is None or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker) is None:
        return None
    return ticker


def _currency(value: Any) -> str | None:
    text = _text(value)
    if text is None or _SAFE_CURRENCY.fullmatch(text) is None:
        return None
    return text


def _error(
    family: str, ticker: Any, field: Any, code: str
) -> dict[str, str | None]:
    return {
        "family": family,
        "ticker": _safe_ticker(ticker),
        "field": _safe_identity(field),
        "code": code,
    }


def _sorted_errors(
    errors: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    unique = {
        tuple(error.get(key) for key in _ERROR_FIELDS)
        for error in errors
    }
    return [
        dict(zip(_ERROR_FIELDS, values))
        for values in sorted(
            unique,
            key=lambda item: (
                item[0] or "",
                item[1] or "",
                item[2] or "",
                item[3] or "",
            ),
        )
    ]


def _result(
    observations: list[dict[str, Any]],
    errors: list[dict[str, str | None]],
) -> dict[str, Any]:
    safe_errors = _sorted_errors(errors)
    if observations and not safe_errors:
        status = "ok"
    elif observations:
        status = "partial"
    elif safe_errors:
        status = "error"
    else:
        status = "empty"
    return {
        "observations": [dict(observation) for observation in observations],
        "errors": safe_errors,
        "status": status,
    }


def _requested_tickers(
    tickers: Any, supported: tuple[str, ...], *, family: str
) -> tuple[list[str], list[dict[str, str | None]]]:
    if tickers is None:
        raw_tickers: list[Any] = []
    elif isinstance(tickers, str):
        raw_tickers = [tickers]
    else:
        try:
            raw_tickers = list(tickers)
        except TypeError:
            raw_tickers = [tickers]
    accepted: set[str] = set()
    errors: list[dict[str, str | None]] = []
    for raw_ticker in raw_tickers:
        ticker = _safe_ticker(raw_ticker)
        if ticker not in supported:
            errors.append(_error(family, ticker, None, "unsupported_ticker"))
        else:
            accepted.add(ticker)
    return [ticker for ticker in supported if ticker in accepted], errors


def _quote_row(payload: Any, ticker: str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        nested = payload.get("data")
        rows = nested if isinstance(nested, (list, tuple)) else [payload]
    elif isinstance(payload, (list, tuple)):
        rows = payload
    else:
        return None
    candidates = [row for row in rows if isinstance(row, dict)]
    exact = [
        row
        for row in candidates
        if _safe_identity(row.get("symbol"), upper=True) == ticker
    ]
    if len(exact) == 1:
        return exact[0]
    if not exact and len(candidates) == 1 and candidates[0].get("symbol") is None:
        return candidates[0]
    return None


def _normalize_market_quote(
    *,
    ticker: str,
    raw_quote: Any,
    retrieved_at: Any,
    source: Any,
    source_field: Any,
    market_time_field: Any,
    source_document: Any,
    is_fallback: bool,
    fallback_from: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one provider-specific raw quote without inventing metadata."""

    if not isinstance(raw_quote, dict):
        return None, "fetch_failed"
    source_text = _text(source)
    if source_text is None:
        return None, "missing_source"
    source_field_text = _text(source_field)
    if source_field_text is None:
        return None, "missing_source_field"
    source_document_text = _text(source_document)
    if source_document_text is None:
        return None, "missing_source_document"
    market_time_field_text = _text(market_time_field)
    if market_time_field_text is None:
        return None, "missing_market_timestamp"

    raw_symbol = raw_quote.get("symbol")
    if raw_symbol is not None and _safe_identity(raw_symbol, upper=True) != ticker:
        return None, "ticker_identity_mismatch"

    if source_field_text not in raw_quote or raw_quote.get(source_field_text) is None:
        return None, "missing_value"
    value = _number(raw_quote.get(source_field_text))
    if value is None or float(value) <= 0:
        return None, "invalid_value"

    raw_currency = raw_quote.get("currency")
    if _text(raw_currency) is None:
        return None, "missing_currency"
    currency = _currency(raw_currency)
    if currency is None:
        return None, "unsupported_currency"

    raw_market_time = raw_quote.get(market_time_field_text)
    market_time, market_time_status = _timestamp(
        raw_market_time, allow_epoch=True
    )
    if market_time_status == "missing":
        return None, "missing_market_timestamp"
    if market_time_status == "naive":
        return None, "naive_market_timestamp"
    if market_time is None:
        return None, "invalid_market_timestamp"
    retrieval_time, retrieval_text = _required_timestamp(
        retrieved_at, name="retrieved_at"
    )
    if market_time > retrieval_time:
        return None, "invalid_market_timestamp"

    fallback_source = _text(fallback_from)
    if is_fallback and fallback_source is None:
        return None, "invalid_fallback_metadata"
    if not is_fallback and fallback_source is not None:
        return None, "invalid_fallback_metadata"

    return (
        {
            "ticker": ticker,
            "value": value,
            "metric_kind": MARKET_METRIC_KIND,
            "unit": currency,
            "currency": currency,
            "as_of": market_time.isoformat(),
            "retrieved_at": retrieval_text,
            "source": source_text,
            "source_field": source_field_text,
            "source_document": source_document_text,
            "provenance": None,
            "is_fallback": is_fallback,
            "fallback_from": fallback_source,
        },
        None,
    )


def fetch_market_observations(
    tickers: Any,
    *,
    yahoo_quote_fetcher: Callable[[str], Any],
    retrieved_at: Any,
    fmp_quote_fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch caller-injected quote payloads and return market observations."""

    _, retrieval_text = _required_timestamp(retrieved_at, name="retrieved_at")
    requested, errors = _requested_tickers(
        tickers, SUPPORTED_MARKET_TICKERS, family="market_proxy"
    )
    observations: list[dict[str, Any]] = []

    for ticker in requested:
        primary_code = "fetch_failed"
        try:
            primary_payload = yahoo_quote_fetcher(ticker)
        except Exception:
            primary_payload = None
        primary_row = _quote_row(primary_payload, ticker)
        if primary_row is not None:
            primary_observation, primary_code = _normalize_market_quote(
                ticker=ticker,
                raw_quote=primary_row,
                retrieved_at=retrieval_text,
                source="Yahoo Finance",
                source_field="regularMarketPrice",
                market_time_field="regularMarketTime",
                source_document="quote",
                is_fallback=False,
                fallback_from=None,
            )
            if primary_observation is not None:
                observations.append(primary_observation)
                continue

        if fmp_quote_fetcher is None:
            errors.append(
                _error("market_proxy", ticker, None, primary_code or "fetch_failed")
            )
            continue

        fallback_code = "fetch_failed"
        try:
            fallback_payload = fmp_quote_fetcher(ticker)
        except Exception:
            fallback_payload = None
        fallback_row = _quote_row(fallback_payload, ticker)
        if fallback_row is not None:
            fallback_observation, fallback_code = _normalize_market_quote(
                ticker=ticker,
                raw_quote=fallback_row,
                retrieved_at=retrieval_text,
                source="FMP",
                source_field="price",
                market_time_field="timestamp",
                source_document="quote",
                is_fallback=True,
                fallback_from="Yahoo Finance",
            )
            if fallback_observation is not None:
                observations.append(fallback_observation)
                continue
        errors.append(
            _error("market_proxy", ticker, None, fallback_code or "fetch_failed")
        )

    return _result(observations, errors)


def fetch_fmp_market_observations(
    tickers: Any,
    *,
    fmp_quote_fetcher: Callable[[str], Any],
    retrieved_at: Any,
) -> dict[str, Any]:
    """Return FMP quotes as primary market proxy observations."""

    _, retrieval_text = _required_timestamp(retrieved_at, name="retrieved_at")
    requested, errors = _requested_tickers(
        tickers, SUPPORTED_MARKET_TICKERS, family="market_proxy"
    )
    observations: list[dict[str, Any]] = []
    for ticker in requested:
        code = "fetch_failed"
        try:
            payload = fmp_quote_fetcher(ticker)
        except Exception:
            payload = None
        row = _quote_row(payload, ticker)
        if row is not None:
            observation, code = _normalize_market_quote(
                ticker=ticker,
                raw_quote=row,
                retrieved_at=retrieval_text,
                source="FMP",
                source_field="price",
                market_time_field="timestamp",
                source_document="quote",
                is_fallback=False,
                fallback_from=None,
            )
            if observation is not None:
                observations.append(observation)
                continue
        errors.append(_error("market_proxy", ticker, None, code or "fetch_failed"))
    return _result(observations, errors)


def _payload_rows(payload: Any, *, nested_key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        nested = payload.get(nested_key)
        rows = nested if isinstance(nested, (list, tuple)) else [payload]
    elif isinstance(payload, (list, tuple)):
        rows = payload
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _sndk_identity_cik(payload: Any) -> str | None:
    rows = _payload_rows(payload, nested_key="data")
    matching_ciks: set[str] = set()
    for row in rows:
        if _safe_identity(row.get("symbol"), upper=True) != "SNDK":
            continue
        name = _text(
            row.get("companyName")
            or row.get("company_name")
            or row.get("name")
        )
        cik = _text(row.get("cik"))
        if (
            name is not None
            and re.search(r"\bsan\s*disk\b", name, re.IGNORECASE)
            and cik is not None
            and _SAFE_CIK.fullmatch(cik) is not None
        ):
            matching_ciks.add(cik)
    if len(matching_ciks) != 1:
        return None
    return next(iter(matching_ciks))


def _statement_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def _statement_year(row: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_year = row.get("fiscalYear")
    source_field = "fiscalYear"
    if raw_year is None or (isinstance(raw_year, str) and not raw_year.strip()):
        raw_year = row.get("calendarYear")
        source_field = "calendarYear"
    if isinstance(raw_year, bool):
        return None, None
    if isinstance(raw_year, int):
        year = str(raw_year)
    elif isinstance(raw_year, str):
        year = raw_year.strip()
    else:
        return None, None
    if re.fullmatch(r"(?:19|20)\d{2}", year) is None:
        return None, None
    return year, source_field


def _statement_metadata(
    row: dict[str, Any],
    *,
    ticker: str,
    retrieval_time: datetime,
    expected_cik: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if _safe_identity(row.get("symbol"), upper=True) != ticker:
        return None, "ticker_identity_mismatch"
    if ticker == "SNDK" and _text(row.get("cik")) != expected_cik:
        return None, "statement_identity_mismatch"
    raw_date = row.get("date")
    if raw_date is None or (isinstance(raw_date, str) and not raw_date.strip()):
        return None, "missing_as_of"
    period_end = _statement_date(raw_date)
    if period_end is None:
        return None, "invalid_as_of"
    if datetime.combine(period_end, datetime.min.time(), tzinfo=timezone.utc) > retrieval_time:
        return None, "invalid_as_of"
    if ticker == "SNDK" and period_end < date.fromisoformat(
        SNDK_MIN_FINANCIAL_DATE
    ):
        return None, "legacy_statement"

    period = _text(row.get("period"))
    if period is None:
        return None, "missing_period_metadata"
    period = period.upper()
    if period not in {"Q1", "Q2", "Q3", "Q4", "FY"}:
        return None, "unsupported_period"
    year, year_source = _statement_year(row)
    if year is None:
        return None, "missing_period_metadata"
    if year_source == "calendarYear" and year != str(period_end.year):
        return None, "period_year_mismatch"
    raw_currency = row.get("reportedCurrency")
    if _text(raw_currency) is None:
        return None, "missing_currency"
    currency = _currency(raw_currency)
    if currency is None:
        return None, "unsupported_currency"

    period_type = "annual" if period == "FY" else "quarterly"
    fiscal_period = year if period_type == "annual" else f"{year} {period}"
    return (
        {
            "period_end": period_end,
            "as_of": period_end.isoformat(),
            "currency": currency,
            "period_type": period_type,
            "fiscal_period": fiscal_period,
        },
        None,
    )


def _select_statement(
    payload: Any,
    *,
    ticker: str,
    retrieval_time: datetime,
    expected_cik: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    rows = _payload_rows(payload, nested_key="statements")
    if not rows:
        return None, None, "empty_response"
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rejected_codes: list[str] = []
    for row in rows:
        metadata, code = _statement_metadata(
            row,
            ticker=ticker,
            retrieval_time=retrieval_time,
            expected_cik=expected_cik,
        )
        if metadata is None:
            rejected_codes.append(code or "invalid_response")
        else:
            candidates.append((row, metadata))
    if not candidates:
        priority = {code: index for index, code in enumerate(_STATEMENT_ERROR_PRIORITY)}
        selected_code = min(
            set(rejected_codes) or {"invalid_response"},
            key=lambda code: (priority.get(code, len(priority)), code),
        )
        return None, None, selected_code
    latest_date = max(metadata["period_end"] for _, metadata in candidates)
    latest = [
        (row, metadata)
        for row, metadata in candidates
        if metadata["period_end"] == latest_date
    ]
    if len(latest) != 1:
        return None, None, "ambiguous_statement"
    row, metadata = latest[0]
    return row, metadata, None


def _financial_errors(
    ticker: str, code: str
) -> list[dict[str, str | None]]:
    return [
        _error("company_financial", ticker, field, code)
        for field in SUPPORTED_FINANCIAL_FIELDS
    ]


def _field_observations(
    row: dict[str, Any],
    metadata: dict[str, Any],
    *,
    ticker: str,
    retrieved_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str | None]]]:
    mappings = (
        ("revenue", "revenue", metadata["currency"], metadata["currency"]),
        ("gross_margin", "grossProfitRatio", "ratio", None),
        ("operating_margin", "operatingIncomeRatio", "ratio", None),
    )
    unsupported_aliases = {
        "gross_margin": ("grossProfitMargin", "grossMarginPercent"),
        "operating_margin": (
            "operatingProfitMargin",
            "operatingMarginPercent",
        ),
    }
    provenance = (
        "FMP income statement; SanDisk profile name and CIK matched; "
        "exact SNDK statement symbol and CIK; statement date policy applied"
        if ticker == "SNDK"
        else "FMP income statement; exact MU statement symbol"
    )
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str | None]] = []
    for field, source_field, unit, currency in mappings:
        if source_field not in row or row.get(source_field) is None or (
            isinstance(row.get(source_field), str)
            and not row.get(source_field).strip()
        ):
            aliases = unsupported_aliases.get(field, ())
            code = (
                "unsupported_source_field"
                if any(alias in row for alias in aliases)
                else "missing_value"
            )
            errors.append(_error("company_financial", ticker, field, code))
            continue
        value = _number(row.get(source_field))
        if value is None:
            errors.append(
                _error("company_financial", ticker, field, "invalid_value")
            )
            continue
        observations.append(
            {
                "ticker": ticker,
                "field": field,
                "value": value,
                "unit": unit,
                "currency": currency,
                "fiscal_period": metadata["fiscal_period"],
                "period_type": metadata["period_type"],
                "as_of": metadata["as_of"],
                "retrieved_at": retrieved_at,
                "source": "FMP",
                "source_field": source_field,
                "source_document": "income_statement",
                "source_reference": None,
                "provenance": provenance,
                "is_fallback": False,
                "fallback_from": None,
            }
        )
    return observations, errors


def fetch_financial_observations(
    tickers: Any,
    *,
    fmp_income_statement_fetcher: Callable[[str], Any],
    retrieved_at: Any,
    fmp_identity_fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch caller-injected statement payloads and return field observations."""

    retrieval_time, retrieval_text = _required_timestamp(
        retrieved_at, name="retrieved_at"
    )
    requested, errors = _requested_tickers(
        tickers, SUPPORTED_FINANCIAL_TICKERS, family="company_financial"
    )
    observations: list[dict[str, Any]] = []

    for ticker in requested:
        expected_cik: str | None = None
        if ticker == "SNDK":
            if fmp_identity_fetcher is None:
                errors.extend(_financial_errors(ticker, "identity_unverified"))
                continue
            try:
                identity_payload = fmp_identity_fetcher(ticker)
            except Exception:
                identity_payload = None
            expected_cik = _sndk_identity_cik(identity_payload)
            if expected_cik is None:
                errors.extend(_financial_errors(ticker, "identity_unverified"))
                continue

        try:
            statement_payload = fmp_income_statement_fetcher(ticker)
        except Exception:
            errors.extend(_financial_errors(ticker, "fetch_failed"))
            continue
        row, metadata, code = _select_statement(
            statement_payload,
            ticker=ticker,
            retrieval_time=retrieval_time,
            expected_cik=expected_cik,
        )
        if row is None or metadata is None:
            errors.extend(_financial_errors(ticker, code or "invalid_response"))
            continue
        field_observations, field_errors = _field_observations(
            row,
            metadata,
            ticker=ticker,
            retrieved_at=retrieval_text,
        )
        observations.extend(field_observations)
        errors.extend(field_errors)

    return _result(observations, errors)
