"""Tests for the side-effect-free shared FMP raw data boundary."""

import ast
from copy import deepcopy
import inspect
from pathlib import Path

import pytest

from providers import fmp_financial_data as provider


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_PATH = ROOT / "providers" / "fmp_financial_data.py"
RETRIEVED_AT = "2026-04-15T12:00:00+00:00"


def _profile(symbol="MU"):
    return [{
        "symbol": symbol,
        "companyName": "Micron Technology, Inc." if symbol == "MU" else "SanDisk Corporation",
        "cik": "0000723125" if symbol == "MU" else "0002005687",
        "currency": "USD",
    }]


def _quote(symbol="MU"):
    return [{
        "symbol": symbol,
        "name": "Micron Technology, Inc." if symbol == "MU" else "SanDisk Corporation",
        "price": 100.0,
        "currency": "USD",
        "timestamp": 1_765_800_000,
        "marketCap": 100_000_000_000,
    }]


def _statement(symbol="MU", period="Q1", date="2026-03-31"):
    return [{
        "symbol": symbol,
        "cik": "0000723125" if symbol == "MU" else "0002005687",
        "date": date,
        "calendarYear": date[:4],
        "period": period,
        "reportedCurrency": "USD",
        "revenue": 100.0,
    }]


def _fetcher(calls, failures=()):
    def fetch(endpoint, **params):
        calls.append((endpoint, dict(params)))
        if endpoint in failures:
            raise RuntimeError("Traceback /Users/person/.env?apikey=FAKE")
        symbol = params["symbol"]
        if endpoint == "profile":
            return _profile(symbol)
        if endpoint == "quote":
            return _quote(symbol)
        period = "Q1" if params.get("period") == "quarter" else "FY"
        return _statement(symbol, period=period)

    return fetch


def test_module_import_has_no_external_or_stateful_dependencies():
    tree = ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({
        "config", "dotenv", "openai", "os", "pathlib", "requests",
        "streamlit", "yfinance", "ib_insync",
    })


def test_source_has_no_io_hidden_clock_cache_or_client_creation():
    source = PROVIDER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "datetime.now", "date.today", "time.time", "open(", "requests.",
        "os.environ", "load_dotenv", "st.secrets", "session_state",
        "st.cache", "yfinance", "openai", "IBKR",
    )
    assert all(marker not in source for marker in forbidden)


def test_public_signatures_require_injected_fetcher_and_retrieval_time():
    financial = inspect.signature(provider.fetch_fmp_financial_data).parameters
    quotes = inspect.signature(provider.fetch_fmp_quote_payloads).parameters
    assert tuple(financial) == (
        "symbol", "fmp_json_fetcher", "retrieved_at", "include_annual",
        "include_balance", "include_cashflow",
    )
    assert tuple(quotes) == ("symbols", "fmp_json_fetcher", "retrieved_at")


def test_complete_financial_fetch_preserves_raw_endpoint_shapes_and_metadata():
    calls = []
    result = provider.fetch_fmp_financial_data(
        "mu", fmp_json_fetcher=_fetcher(calls), retrieved_at=RETRIEVED_AT
    )

    assert result["symbol"] == "MU"
    assert result["source"] == "FMP"
    assert result["retrieved_at"] == RETRIEVED_AT
    assert result["identity"][0]["symbol"] == "MU"
    assert result["quote"][0]["currency"] == "USD"
    assert result["income_quarterly"][0]["period"] == "Q1"
    assert result["income_annual"][0]["period"] == "FY"
    assert result["balance_quarterly"][0]["symbol"] == "MU"
    assert result["cashflow_annual"][0]["period"] == "FY"
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert [endpoint for endpoint, _ in calls] == [
        "profile", "quote", "income-statement", "income-statement",
        "balance-sheet-statement", "balance-sheet-statement",
        "cash-flow-statement", "cash-flow-statement",
    ]
    assert calls[2][1]["period"] == "quarter"
    assert calls[3][1]["period"] == "annual"


def test_optional_scope_avoids_unrequested_statement_endpoints():
    calls = []
    result = provider.fetch_fmp_financial_data(
        "MU",
        fmp_json_fetcher=_fetcher(calls),
        retrieved_at=RETRIEVED_AT,
        include_annual=False,
        include_balance=False,
        include_cashflow=False,
    )
    assert [endpoint for endpoint, _ in calls] == [
        "profile", "quote", "income-statement"
    ]
    assert result["income_annual"] == []
    assert result["balance_quarterly"] == []
    assert result["cashflow_quarterly"] == []


def test_single_endpoint_failure_is_sanitized_and_preserves_siblings():
    calls = []
    result = provider.fetch_fmp_financial_data(
        "MU",
        fmp_json_fetcher=_fetcher(calls, failures={"balance-sheet-statement"}),
        retrieved_at=RETRIEVED_AT,
    )
    assert result["status"] == "partial"
    assert result["income_quarterly"]
    assert result["cashflow_quarterly"]
    assert result["balance_quarterly"] == []
    assert {error["endpoint"] for error in result["errors"]} == {
        "balance-sheet-statement"
    }
    assert all(set(error) == {"family", "ticker", "endpoint", "code"} for error in result["errors"])
    assert "Traceback" not in str(result)
    assert "/Users/" not in str(result)
    assert "apikey" not in str(result).casefold()


@pytest.mark.parametrize("retrieved_at", (None, "", "2026-04-15T12:00:00"))
def test_retrieval_time_must_be_explicit_and_timezone_aware_before_fetch(retrieved_at):
    calls = []
    with pytest.raises(ValueError, match="retrieved_at"):
        provider.fetch_fmp_financial_data(
            "MU", fmp_json_fetcher=_fetcher(calls), retrieved_at=retrieved_at
        )
    assert calls == []


@pytest.mark.parametrize("symbol", ("", "MU?apikey=FAKE", "WDC/SNDK", None))
def test_unsafe_symbol_is_rejected_before_fetch_without_echo(symbol):
    calls = []
    with pytest.raises(ValueError, match="symbol"):
        provider.fetch_fmp_financial_data(
            symbol, fmp_json_fetcher=_fetcher(calls), retrieved_at=RETRIEVED_AT
        )
    assert calls == []


def test_raw_payload_and_inputs_are_not_modified_and_outputs_are_fresh():
    payload = _statement()
    original = deepcopy(payload)

    def fetch(endpoint, **params):
        if endpoint == "profile":
            return _profile()
        if endpoint == "quote":
            return _quote()
        return payload

    first = provider.fetch_fmp_financial_data(
        "MU", fmp_json_fetcher=fetch, retrieved_at=RETRIEVED_AT
    )
    second = provider.fetch_fmp_financial_data(
        "MU", fmp_json_fetcher=fetch, retrieved_at=RETRIEVED_AT
    )
    assert payload == original
    assert first == second
    assert first is not second
    assert first["income_quarterly"] is not second["income_quarterly"]
    assert first["income_quarterly"][0] is not payload[0]


def test_quote_payload_batch_is_canonical_partial_and_does_not_mutate_input():
    symbols = ["SOXX", "MU", "SNDK", "SMH"]
    original = list(symbols)

    def fetch(endpoint, **params):
        assert endpoint == "quote"
        if params["symbol"] == "SMH":
            raise RuntimeError("secret response body")
        return _quote(params["symbol"])

    result = provider.fetch_fmp_quote_payloads(
        symbols, fmp_json_fetcher=fetch, retrieved_at=RETRIEVED_AT
    )
    assert symbols == original
    assert list(result["payloads"]) == ["MU", "SNDK", "SMH", "SOXX"]
    assert result["payloads"]["MU"][0]["symbol"] == "MU"
    assert result["payloads"]["SMH"] == []
    assert result["status"] == "partial"
    assert result["errors"] == [{
        "family": "fmp_financial",
        "ticker": "SMH",
        "endpoint": "quote",
        "code": "fetch_failed",
    }]
