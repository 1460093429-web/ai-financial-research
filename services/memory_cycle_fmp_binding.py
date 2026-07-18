"""FMP-only acquisition binding for the existing Memory Cycle live pipeline."""

from copy import deepcopy
from typing import Any, Callable

from providers.fmp_financial_data import (
    fetch_fmp_financial_data,
    fetch_fmp_quote_payloads,
)
from providers.memory_cycle_data import (
    SUPPORTED_FINANCIAL_TICKERS,
    SUPPORTED_MARKET_TICKERS,
    fetch_financial_observations,
    fetch_fmp_market_observations,
)
from services.memory_cycle_live import build_live_memory_cycle_result


def build_fmp_only_memory_cycle_result(
    *,
    fmp_json_fetcher: Callable[..., Any],
    retrieved_at: Any,
    evaluated_at: Any,
) -> dict[str, Any]:
    """Acquire the fixed Phase 4.7 scope from FMP and reuse live validation."""

    quotes = fetch_fmp_quote_payloads(
        SUPPORTED_MARKET_TICKERS,
        fmp_json_fetcher=fmp_json_fetcher,
        retrieved_at=retrieved_at,
    )

    def financial_fetcher(endpoint: str, **params: Any) -> Any:
        if endpoint == "quote":
            payloads = quotes.get("payloads", {})
            if isinstance(payloads, dict):
                return deepcopy(payloads.get(params.get("symbol"), []))
            return []
        return fmp_json_fetcher(endpoint, **params)

    financial_payloads = {
        ticker: fetch_fmp_financial_data(
            ticker,
            fmp_json_fetcher=financial_fetcher,
            retrieved_at=retrieved_at,
            include_annual=False,
            include_balance=False,
            include_cashflow=False,
        )
        for ticker in SUPPORTED_FINANCIAL_TICKERS
    }

    def quote_payload(ticker: str) -> list[dict[str, Any]]:
        payloads = quotes.get("payloads", {})
        value = payloads.get(ticker, []) if isinstance(payloads, dict) else []
        return deepcopy(value) if isinstance(value, list) else []

    def market_provider(tickers: Any, *, retrieved_at: Any) -> dict[str, Any]:
        return fetch_fmp_market_observations(
            tickers,
            fmp_quote_fetcher=quote_payload,
            retrieved_at=retrieved_at,
        )

    def statement_payload(ticker: str) -> list[dict[str, Any]]:
        envelope = financial_payloads.get(ticker, {})
        value = envelope.get("income_quarterly", []) if isinstance(envelope, dict) else []
        return deepcopy(value) if isinstance(value, list) else []

    def identity_payload(ticker: str) -> list[dict[str, Any]]:
        envelope = financial_payloads.get(ticker, {})
        value = envelope.get("identity", []) if isinstance(envelope, dict) else []
        return deepcopy(value) if isinstance(value, list) else []

    def financial_provider(tickers: Any, *, retrieved_at: Any) -> dict[str, Any]:
        return fetch_financial_observations(
            tickers,
            fmp_income_statement_fetcher=statement_payload,
            fmp_identity_fetcher=identity_payload,
            retrieved_at=retrieved_at,
        )

    return build_live_memory_cycle_result(
        retrieved_at=retrieved_at,
        evaluated_at=evaluated_at,
        market_observation_fetcher=market_provider,
        financial_observation_fetcher=financial_provider,
    )
