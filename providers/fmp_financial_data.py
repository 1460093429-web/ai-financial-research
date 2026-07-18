"""Side-effect-free raw FMP acquisition boundary.

The caller owns credentials, HTTP, retries, and any cache.  This module only
invokes an injected JSON callable and returns fresh, sanitized envelopes.
"""

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Callable


_ERROR_FIELDS = ("family", "ticker", "endpoint", "code")
_SAFE_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_FINANCIAL_ENDPOINTS = (
    ("identity", "profile", None),
    ("quote", "quote", None),
    ("income_quarterly", "income-statement", "quarter"),
    ("income_annual", "income-statement", "annual"),
    ("balance_quarterly", "balance-sheet-statement", "quarter"),
    ("balance_annual", "balance-sheet-statement", "annual"),
    ("cashflow_quarterly", "cash-flow-statement", "quarter"),
    ("cashflow_annual", "cash-flow-statement", "annual"),
)
_CANONICAL_QUOTE_SYMBOLS = ("MU", "SNDK", "SMH", "SOXX")


def _aware_timestamp(value: Any, *, name: str) -> str:
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
        return parsed.astimezone(timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        raise ValueError(f"{name} must be a timezone-aware timestamp") from None


def _symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("symbol must be a safe ticker")
    normalized = value.strip().upper()
    if _SAFE_SYMBOL.fullmatch(normalized) is None:
        raise ValueError("symbol must be a safe ticker")
    return normalized


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        nested = payload.get("data")
        values = nested if isinstance(nested, (list, tuple)) else [payload]
    elif isinstance(payload, (list, tuple)):
        values = payload
    else:
        return []
    return [deepcopy(item) for item in values if isinstance(item, dict)]


def _error(ticker: str, endpoint: str, code: str) -> dict[str, str]:
    return {
        "family": "fmp_financial",
        "ticker": ticker,
        "endpoint": endpoint,
        "code": code,
    }


def _sorted_errors(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = {
        tuple(error[field] for field in _ERROR_FIELDS)
        for error in errors
    }
    return [
        dict(zip(_ERROR_FIELDS, values))
        for values in sorted(unique)
    ]


def _fetch_rows(
    *,
    ticker: str,
    endpoint: str,
    period: str | None,
    fmp_json_fetcher: Callable[..., Any],
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    params: dict[str, Any] = {"symbol": ticker, "limit": 8 if period == "quarter" else 4}
    if period is not None:
        params["period"] = period
    try:
        payload = fmp_json_fetcher(endpoint, **params)
    except Exception:
        return [], _error(ticker, endpoint, "fetch_failed")
    rows = _rows(payload)
    if not rows:
        return [], _error(ticker, endpoint, "empty_response")
    return rows, None


def _result_status(*, successes: int, errors: list[dict[str, str]]) -> str:
    if successes and not errors:
        return "ok"
    if successes:
        return "partial"
    if errors:
        return "error"
    return "empty"


def fetch_fmp_financial_data(
    symbol: Any,
    *,
    fmp_json_fetcher: Callable[..., Any],
    retrieved_at: Any,
    include_annual: bool = True,
    include_balance: bool = True,
    include_cashflow: bool = True,
) -> dict[str, Any]:
    """Return a raw FMP financial envelope using caller-owned acquisition."""

    ticker = _symbol(symbol)
    retrieval_text = _aware_timestamp(retrieved_at, name="retrieved_at")
    result: dict[str, Any] = {
        "symbol": ticker,
        "identity": [],
        "quote": [],
        "income_quarterly": [],
        "income_annual": [],
        "balance_quarterly": [],
        "balance_annual": [],
        "cashflow_quarterly": [],
        "cashflow_annual": [],
        "retrieved_at": retrieval_text,
        "source": "FMP",
        "errors": [],
        "status": "empty",
    }
    errors: list[dict[str, str]] = []
    successes = 0
    for output_key, endpoint, period in _FINANCIAL_ENDPOINTS:
        if period == "annual" and not include_annual:
            continue
        if output_key.startswith("balance_") and not include_balance:
            continue
        if output_key.startswith("cashflow_") and not include_cashflow:
            continue
        rows, error = _fetch_rows(
            ticker=ticker,
            endpoint=endpoint,
            period=period,
            fmp_json_fetcher=fmp_json_fetcher,
        )
        result[output_key] = rows
        if error is None:
            successes += 1
        else:
            errors.append(error)
    result["errors"] = _sorted_errors(errors)
    result["status"] = _result_status(successes=successes, errors=errors)
    return result


def fetch_fmp_quote_payloads(
    symbols: Any,
    *,
    fmp_json_fetcher: Callable[..., Any],
    retrieved_at: Any,
) -> dict[str, Any]:
    """Fetch raw FMP quote payloads in deterministic ticker order."""

    retrieval_text = _aware_timestamp(retrieved_at, name="retrieved_at")
    if symbols is None:
        raw_symbols: list[Any] = []
    elif isinstance(symbols, str):
        raw_symbols = [symbols]
    else:
        try:
            raw_symbols = list(symbols)
        except TypeError:
            raw_symbols = [symbols]
    tickers = {_symbol(item) for item in raw_symbols}
    ordered = [ticker for ticker in _CANONICAL_QUOTE_SYMBOLS if ticker in tickers]
    ordered.extend(sorted(tickers.difference(_CANONICAL_QUOTE_SYMBOLS)))
    payloads: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, str]] = []
    successes = 0
    for ticker in ordered:
        rows, error = _fetch_rows(
            ticker=ticker,
            endpoint="quote",
            period=None,
            fmp_json_fetcher=fmp_json_fetcher,
        )
        payloads[ticker] = rows
        if error is None:
            successes += 1
        else:
            errors.append(error)
    return {
        "payloads": payloads,
        "retrieved_at": retrieval_text,
        "source": "FMP",
        "errors": _sorted_errors(errors),
        "status": _result_status(successes=successes, errors=errors),
    }
