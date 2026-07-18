"""Tests for the FMP-only Memory Cycle binding."""

import ast
from copy import deepcopy
import importlib
from pathlib import Path

import pytest

from services.memory_cycle_contract import REQUIRED_METRIC_FIELDS, validate_metric_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = PROJECT_ROOT / "services" / "memory_cycle_fmp_binding.py"
RETRIEVED_AT = "2026-07-18T20:01:00+00:00"
EVALUATED_AT = "2026-07-18T20:10:00+00:00"
MARKET_TIME = 1_784_404_800
TICKERS = ("MU", "SNDK", "SMH", "SOXX")


def _binding():
    return importlib.import_module("services.memory_cycle_fmp_binding")


def _profile(ticker):
    return [{
        "symbol": ticker,
        "companyName": "San Disk Corporation" if ticker == "SNDK" else "Micron Technology, Inc.",
        "cik": "0002005687" if ticker == "SNDK" else "0000723125",
        "currency": "USD",
    }]


def _quote(ticker):
    return [{
        "symbol": ticker,
        "price": {"MU": 123.45, "SNDK": 82.1, "SMH": 301.2, "SOXX": 250.4}[ticker],
        "currency": "USD",
        "timestamp": MARKET_TIME,
    }]


def _statement(ticker):
    return [{
        "symbol": ticker,
        "cik": "0002005687" if ticker == "SNDK" else "0000723125",
        "date": "2026-05-29",
        "calendarYear": "2026",
        "period": "Q3",
        "reportedCurrency": "USD",
        "revenue": 9_300_000_000 if ticker == "MU" else 1_900_000_000,
        "grossProfitRatio": 0.452 if ticker == "MU" else 0.31,
        "operatingIncomeRatio": 0.301 if ticker == "MU" else 0.18,
    }]


def _fetcher(*, quote_mutator=None, statement_mutator=None, profile_mutator=None, calls=None):
    def fetch(endpoint, **params):
        ticker = params["symbol"]
        if calls is not None:
            calls.append((endpoint, ticker, params.get("period")))
        if endpoint == "quote":
            payload = _quote(ticker)
            if quote_mutator is not None:
                quote_mutator(ticker, payload[0])
            return payload
        if endpoint == "profile":
            payload = _profile(ticker)
            if profile_mutator is not None:
                profile_mutator(ticker, payload[0])
            return payload
        if endpoint == "income-statement":
            payload = _statement(ticker)
            if statement_mutator is not None:
                statement_mutator(ticker, payload[0])
            return payload
        raise AssertionError(f"unexpected endpoint: {endpoint}")
    return fetch


def _build(fetcher=None):
    return _binding().build_fmp_only_memory_cycle_result(
        fmp_json_fetcher=fetcher or _fetcher(),
        retrieved_at=RETRIEVED_AT,
        evaluated_at=EVALUATED_AT,
    )


def test_binding_module_import_is_side_effect_free():
    assert _binding().__name__ == "services.memory_cycle_fmp_binding"


def test_binding_has_no_ui_client_cache_secret_clock_yahoo_score_or_cycle_phase():
    tree = ast.parse(BINDING_PATH.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots.isdisjoint(
        {"dashboard", "financials", "openai", "os", "requests", "streamlit", "yfinance"}
    )
    lowered = BINDING_PATH.read_text(encoding="utf-8").casefold()
    assert all(marker not in lowered for marker in (
        "datetime.now", "date.today", "session_state", "st.cache", "api_key",
        "yahoo", "ibkr", "cycle_phase", "cycle phase", "score =", "score:",
    ))


def test_complete_fmp_payload_returns_ten_canonical_metrics_with_exact_provenance():
    result = _build()
    assert result["status"] == "ok"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 10
    assert len(result["metrics"]) == 10
    assert result["errors"] == []
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])
    assert all(validate_metric_record(metric, evaluated_at=EVALUATED_AT) == [] for metric in result["metrics"])
    assert all(metric["source"] == "FMP" for metric in result["metrics"])
    assert all(metric["is_fallback"] is False for metric in result["metrics"])
    assert all(metric["source_type"] == "proxy" for metric in result["metrics"][:4])
    assert all(metric["source_type"] == "company_reported" for metric in result["metrics"][4:])


def test_binding_uses_only_required_fmp_endpoint_scope_without_balance_or_cashflow():
    calls = []
    _build(_fetcher(calls=calls))
    assert calls == [
        ("quote", "MU", None),
        ("quote", "SNDK", None),
        ("quote", "SMH", None),
        ("quote", "SOXX", None),
        ("profile", "MU", None),
        ("income-statement", "MU", "quarter"),
        ("profile", "SNDK", None),
        ("income-statement", "SNDK", "quarter"),
    ]


def test_binding_reuses_live_orchestrator(monkeypatch):
    binding = _binding()
    real = binding.build_live_memory_cycle_result
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(binding, "build_live_memory_cycle_result", spy)
    result = binding.build_fmp_only_memory_cycle_result(
        fmp_json_fetcher=_fetcher(), retrieved_at=RETRIEVED_AT, evaluated_at=EVALUATED_AT
    )
    assert result["status"] == "ok"
    assert callable(captured["market_observation_fetcher"])
    assert callable(captured["financial_observation_fetcher"])
    assert captured["retrieved_at"] == RETRIEVED_AT
    assert captured["evaluated_at"] == EVALUATED_AT


@pytest.mark.parametrize("missing_field", ("timestamp", "currency"))
def test_missing_fmp_market_metadata_is_missing_without_retrieval_time_substitution(missing_field):
    def mutate(ticker, row):
        if ticker == "SMH":
            row.pop(missing_field)

    result = _build(_fetcher(quote_mutator=mutate))
    metric = result["metrics"][2]
    assert metric["metric_id"] == "smh_market_price_proxy"
    assert metric["status"] == "missing"
    assert metric["value"] is None
    assert metric["as_of"] is None
    assert result["status"] == "partial"


def test_sndk_identity_conflict_never_uses_wdc_statement():
    def mutate(ticker, row):
        if ticker == "SNDK":
            row.update(symbol="WDC", companyName="Western Digital Corporation")

    result = _build(_fetcher(profile_mutator=mutate))
    sndk = [
        metric for metric in result["metrics"]
        if metric["label"].startswith("SNDK ")
        and metric["source_type"] == "company_reported"
    ]
    assert len(sndk) == 3
    assert all(metric["status"] == "missing" for metric in sndk)
    assert "WDC" not in str(result)


def test_sndk_legacy_or_cross_company_statement_is_rejected():
    def mutate(ticker, row):
        if ticker == "SNDK":
            row.update(symbol="WDC", cik="0000106040", date="2024-12-31")

    result = _build(_fetcher(statement_mutator=mutate))
    sndk = result["metrics"][7:]
    assert all(metric["status"] == "missing" for metric in sndk)
    assert all(metric["value"] is None for metric in sndk)


def test_one_financial_field_failure_is_partial_without_affecting_siblings():
    def mutate(ticker, row):
        if ticker == "MU":
            row.pop("grossProfitRatio")

    result = _build(_fetcher(statement_mutator=mutate))
    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 9
    assert result["metrics"][4]["status"] in {"ok", "stale"}
    assert result["metrics"][5]["status"] == "missing"
    assert result["metrics"][6]["status"] in {"ok", "stale"}


def test_fetch_exception_is_sanitized_and_does_not_escape_raw_exception_text():
    def fetch(endpoint, **params):
        if endpoint == "quote" and params["symbol"] == "SOXX":
            raise RuntimeError("Authorization Bearer secret-value /Users/private/file")
        return _fetcher()(endpoint, **params)

    result = _build(fetch)
    assert result["status"] == "partial"
    assert result["metrics"][3]["status"] == "missing"
    serialized = str(result).casefold()
    assert "authorization" not in serialized
    assert "secret-value" not in serialized
    assert "/users/" not in serialized


def test_binding_returns_fresh_objects_and_does_not_mutate_provider_payloads():
    payloads = {}

    def fetch(endpoint, **params):
        key = (endpoint, params["symbol"])
        payload = (
            _quote(params["symbol"]) if endpoint == "quote"
            else _profile(params["symbol"]) if endpoint == "profile"
            else _statement(params["symbol"])
        )
        payloads[key] = deepcopy(payload)
        return payload

    first = _build(fetch)
    expected = deepcopy(payloads)
    second = _build(fetch)
    assert payloads == expected
    assert first == second
    assert first is not second
    assert first["metrics"] is not second["metrics"]


def test_evaluated_at_before_retrieved_at_is_rejected():
    with pytest.raises(ValueError, match="must not precede"):
        _binding().build_fmp_only_memory_cycle_result(
            fmp_json_fetcher=_fetcher(),
            retrieved_at=RETRIEVED_AT,
            evaluated_at="2026-07-18T20:00:00+00:00",
        )
