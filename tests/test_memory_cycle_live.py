"""Regression coverage for the Phase 4.7 live orchestration boundary."""

import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from services.memory_cycle_contract import (
    REQUIRED_METRIC_FIELDS,
    validate_metric_record,
)
from services.memory_cycle_production import build_memory_cycle_production_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = PROJECT_ROOT / "services" / "memory_cycle_live.py"
RETRIEVED_AT = "2026-07-18T20:01:00+00:00"
EVALUATED_AT = "2026-07-18T20:10:00+00:00"
MARKET_TIME = 1_784_404_800
PRODUCTION_RESULT_FIELDS = {
    "metrics",
    "status",
    "expected_metric_count",
    "successful_metric_count",
    "stale_metric_count",
    "missing_metric_count",
    "unavailable_metric_count",
    "errors",
}
CANONICAL_METRIC_IDENTITIES = [
    ("mu_market_price_proxy", "MU latest market price proxy"),
    ("sndk_market_price_proxy", "SNDK latest market price proxy"),
    ("smh_market_price_proxy", "SMH latest market price proxy"),
    ("soxx_market_price_proxy", "SOXX latest market price proxy"),
    ("company_revenue", "MU Revenue"),
    ("gross_margin", "MU Gross Margin"),
    ("operating_margin", "MU Operating Margin"),
    ("company_revenue", "SNDK Revenue"),
    ("gross_margin", "SNDK Gross Margin"),
    ("operating_margin", "SNDK Operating Margin"),
]


def _live():
    return importlib.import_module("services.memory_cycle_live")


def _yahoo_quote(ticker):
    return {
        "symbol": ticker,
        "regularMarketPrice": {
            "MU": 123.45,
            "SNDK": 82.1,
            "SMH": 301.2,
            "SOXX": 250.4,
        }[ticker],
        "currency": "USD",
        "regularMarketTime": MARKET_TIME,
    }


def _statement(ticker):
    return [
        {
            "symbol": ticker,
            "cik": "0000000002" if ticker == "SNDK" else "0000000001",
            "date": "2026-05-29",
            "calendarYear": "2026",
            "period": "Q3",
            "reportedCurrency": "USD",
            "revenue": 9_300_000_000 if ticker == "MU" else 1_900_000_000,
            "grossProfitRatio": 0.452 if ticker == "MU" else 0.31,
            "operatingIncomeRatio": 0.301 if ticker == "MU" else 0.18,
        }
    ]


def _identity(ticker):
    return [
        {
            "symbol": ticker,
            "companyName": "SanDisk Corporation",
            "cik": "0000000002",
        }
    ]


def _build(**overrides):
    arguments = {
        "yahoo_quote_fetcher": _yahoo_quote,
        "fmp_income_statement_fetcher": _statement,
        "fmp_identity_fetcher": _identity,
        "retrieved_at": RETRIEVED_AT,
        "evaluated_at": EVALUATED_AT,
    }
    arguments.update(overrides)
    return _live().build_live_memory_cycle_result(**arguments)


def _empty_production_result():
    return build_memory_cycle_production_metrics(
        market_observations=[],
        financial_observations=[],
        evaluated_at=EVALUATED_AT,
    )


def _assert_safe_internal_error(result):
    assert result == {
        "metrics": [],
        "status": "error",
        "expected_metric_count": 10,
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


def test_live_module_imports_without_executing_work():
    assert _live().__name__ == "services.memory_cycle_live"


def test_live_module_has_no_ui_external_client_cache_or_file_imports():
    tree = ast.parse(LIVE_PATH.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(
        {
            "components",
            "config",
            "dashboard",
            "dotenv",
            "financials",
            "ib_insync",
            "openai",
            "os",
            "pathlib",
            "requests",
            "streamlit",
            "yfinance",
        }
    )


def test_live_source_has_no_hidden_clock_cache_session_score_or_cycle_phase():
    source = LIVE_PATH.read_text(encoding="utf-8")
    lowered = source.casefold()
    forbidden = (
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "session_state",
        "st.cache",
        "lru_cache",
        "load_dotenv",
        "st.secrets",
        "view_model",
        "components",
        "cycle_phase",
    )

    assert all(marker not in lowered for marker in forbidden)
    tree = ast.parse(source)
    assigned_names = {
        target.id.casefold()
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    assert not any("score" in name for name in assigned_names)


def test_all_complete_providers_return_ten_canonical_metrics_and_ok():
    calls = []

    result = _build(
        yahoo_quote_fetcher=lambda ticker: calls.append(("market", ticker))
        or _yahoo_quote(ticker),
        fmp_income_statement_fetcher=lambda ticker: calls.append(
            ("statement", ticker)
        )
        or _statement(ticker),
        fmp_identity_fetcher=lambda ticker: calls.append(("identity", ticker))
        or _identity(ticker),
    )

    assert calls == [
        ("market", "MU"),
        ("market", "SNDK"),
        ("market", "SMH"),
        ("market", "SOXX"),
        ("statement", "MU"),
        ("identity", "SNDK"),
        ("statement", "SNDK"),
    ]
    assert result["status"] == "ok"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 10
    assert len(result["metrics"]) == 10
    assert result["errors"] == []
    assert set(result) == PRODUCTION_RESULT_FIELDS
    assert [
        (metric["metric_id"], metric["label"]) for metric in result["metrics"]
    ] == CANONICAL_METRIC_IDENTITIES
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])
    assert all(
        validate_metric_record(metric, evaluated_at=EVALUATED_AT) == []
        for metric in result["metrics"]
    )


def test_live_passes_provider_observations_and_original_evaluation_time(monkeypatch):
    live = _live()
    captured = {}
    real_production = live.build_memory_cycle_production_metrics

    def fake_production(**kwargs):
        captured.update(kwargs)
        return real_production(**kwargs)

    monkeypatch.setattr(live, "build_memory_cycle_production_metrics", fake_production)

    result = _build()

    assert result["status"] == "ok"
    assert len(captured["market_observations"]) == 4
    assert len(captured["financial_observations"]) == 6
    assert captured["evaluated_at"] == EVALUATED_AT
    assert all(
        item["retrieved_at"] == RETRIEVED_AT
        for item in [
            *captured["market_observations"],
            *captured["financial_observations"],
        ]
    )


def test_one_market_ticker_failure_returns_partial_and_keeps_nine_metrics():
    def market(ticker):
        if ticker == "SMH":
            raise RuntimeError("market failed")
        return _yahoo_quote(ticker)

    result = _build(yahoo_quote_fetcher=market)

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 9
    assert result["missing_metric_count"] == 1
    assert any(
        error == {
            "family": "market_proxy",
            "ticker": "SMH",
            "field": None,
            "code": "fetch_failed",
        }
        for error in result["errors"]
    )


def test_one_financial_field_failure_keeps_siblings_and_other_company():
    def statements(ticker):
        rows = _statement(ticker)
        if ticker == "MU":
            rows[0].pop("grossProfitRatio")
        return rows

    result = _build(fmp_income_statement_fetcher=statements)

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 9
    assert result["missing_metric_count"] == 1
    assert {
        (error["ticker"], error["field"], error["code"])
        for error in result["errors"]
    } >= {("MU", "gross_margin", "missing_value")}


def test_market_family_failure_keeps_all_six_financial_metrics():
    result = _build(
        yahoo_quote_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError("all market failed")
        )
    )

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 6
    assert result["missing_metric_count"] == 4


def test_financial_family_failure_keeps_all_four_market_metrics():
    result = _build(
        fmp_income_statement_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError("all financial failed")
        )
    )

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 4
    assert result["missing_metric_count"] == 6


def test_all_nonempty_fetches_failing_is_partial_not_empty():
    result = _build(
        yahoo_quote_fetcher=lambda ticker: (_ for _ in ()).throw(RuntimeError()),
        fmp_income_statement_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError()
        ),
    )

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 0
    assert result["missing_metric_count"] == 10


def test_explicit_empty_scope_returns_empty_with_fixed_slots_and_no_fetch():
    result = _build(
        market_tickers=[],
        financial_tickers=[],
        yahoo_quote_fetcher=lambda ticker: pytest.fail("market must not run"),
        fmp_income_statement_fetcher=lambda ticker: pytest.fail(
            "financials must not run"
        ),
        fmp_identity_fetcher=lambda ticker: pytest.fail("identity must not run"),
    )

    assert result["status"] == "empty"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 0
    assert len(result["metrics"]) == 10
    assert result["errors"] == []


def test_valid_fmp_fallback_can_still_return_ok_with_low_confidence_lineage():
    result = _build(
        yahoo_quote_fetcher=lambda ticker: (_ for _ in ()).throw(RuntimeError()),
        fmp_quote_fetcher=lambda ticker: [
            {
                "symbol": ticker,
                "price": _yahoo_quote(ticker)["regularMarketPrice"],
                "currency": "USD",
                "timestamp": MARKET_TIME,
            }
        ],
    )

    market_metrics = result["metrics"][:4]
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert all(metric["is_fallback"] is True for metric in market_metrics)
    assert all(metric["confidence"] == "low" for metric in market_metrics)
    assert all("Fallback from: Yahoo Finance" in metric["notes"] for metric in market_metrics)


def test_provider_and_production_errors_are_sanitized_deduplicated_and_sorted(
    monkeypatch,
):
    live = _live()
    unsafe = {
        "family": "market_proxy",
        "ticker": "MU",
        "field": None,
        "code": "fetch_failed",
        "traceback": "Authorization sk-secret /Users/person/.env",
    }
    monkeypatch.setattr(
        live,
        "fetch_market_observations",
        lambda *args, **kwargs: {
            "observations": [],
            "errors": [unsafe, dict(unsafe)],
            "status": "error",
        },
    )
    monkeypatch.setattr(
        live,
        "fetch_financial_observations",
        lambda *args, **kwargs: {
            "observations": [],
            "errors": [],
            "status": "empty",
        },
    )
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: {
            **_empty_production_result(),
            "status": "partial",
            "errors": [
                {
                    "family": unsafe["family"],
                    "ticker": unsafe["ticker"],
                    "field": unsafe["field"],
                    "code": unsafe["code"],
                }
            ],
        },
    )

    result = _build()

    assert result["status"] == "partial"
    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": "MU",
            "field": None,
            "code": "fetch_failed",
        }
    ]
    serialized = json.dumps(result)
    assert "traceback" not in serialized
    assert "sk-secret" not in serialized
    assert "/Users/" not in serialized


def test_live_sanitizes_secret_like_values_in_every_error_field(monkeypatch):
    live = _live()
    monkeypatch.setattr(
        live,
        "fetch_market_observations",
        lambda *args, **kwargs: {
            "observations": [],
            "errors": [
                {
                    "family": "ghp_FAKE123",
                    "ticker": "AKIAABCDEFGHIJKLMNOP",
                    "field": "sk-secret",
                    "code": "xoxb-secret",
                }
            ],
            "status": "error",
        },
    )

    result = _build(financial_tickers=[])

    serialized = json.dumps(result)
    assert "ghp_" not in serialized
    assert "AKIA" not in serialized
    assert "sk-secret" not in serialized
    assert "xoxb" not in serialized


@pytest.mark.parametrize(
    "malformed_market_result",
    (
        None,
        {"observations": [None], "errors": [], "status": "ok"},
        {"observations": {}, "errors": [], "status": "ok"},
        {"observations": [], "errors": {}, "status": "error"},
    ),
)
def test_malformed_market_provider_envelope_keeps_financial_family(
    monkeypatch, malformed_market_result
):
    live = _live()
    monkeypatch.setattr(
        live,
        "fetch_market_observations",
        lambda *args, **kwargs: malformed_market_result,
    )

    result = _build()

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 6
    assert result["missing_metric_count"] == 4
    assert {
        (error["family"], error["code"]) for error in result["errors"]
    } >= {("market_proxy", "fetch_failed")}


def test_malformed_financial_provider_envelope_keeps_market_family(monkeypatch):
    live = _live()
    monkeypatch.setattr(
        live,
        "fetch_financial_observations",
        lambda *args, **kwargs: None,
    )

    result = _build()

    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 4
    assert result["missing_metric_count"] == 6
    assert {
        (error["family"], error["code"]) for error in result["errors"]
    } >= {("company_financial", "fetch_failed")}


def test_unexpected_production_exception_returns_only_safe_internal_error(
    monkeypatch,
):
    live = _live()
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("response_body https://host.test?apikey=secret")
        ),
    )

    result = _build()

    assert result == {
        "metrics": [],
        "status": "error",
        "expected_metric_count": 10,
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
    assert "apikey" not in json.dumps(result)


def test_malformed_production_result_returns_safe_internal_error(monkeypatch):
    live = _live()
    monkeypatch.setattr(
        live, "build_memory_cycle_production_metrics", lambda **kwargs: {}
    )

    result = _build()

    assert result["status"] == "error"
    assert result["expected_metric_count"] == 10
    assert result["errors"] == [
        {
            "family": "production",
            "ticker": None,
            "field": None,
            "code": "internal_error",
        }
    ]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda result: result.update({"debug": "sk_live_FAKESECRET"}),
        lambda result: result["metrics"][0].pop("notes"),
        lambda result: result["metrics"][0].update({"debug": "traceback"}),
        lambda result: result["metrics"].reverse(),
        lambda result: result["metrics"].__setitem__(
            1, deepcopy(result["metrics"][0])
        ),
        lambda result: result.update({"successful_metric_count": 1}),
    ),
)
def test_malformed_production_shape_returns_safe_internal_error(monkeypatch, mutate):
    live = _live()
    malformed = _empty_production_result()
    mutate(malformed)
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: malformed,
    )

    result = _build()

    _assert_safe_internal_error(result)
    serialized = json.dumps(result)
    assert "sk_live_" not in serialized
    assert "traceback" not in serialized.casefold()


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "sk_live_FAKESECRET",
        "sk_test_FAKESECRET",
        "rk_live_FAKESECRET",
        "rk_test_FAKESECRET",
        "whsec_FAKESECRET",
        "prefix_sk_live_FAKE",
        "access_token=FAKE",
        "token=FAKE",
        "raw response: FAKE",
        "raw_response=FAKE",
        "AKIAABCDEFGHIJKLMNOP",
        "AIzaSyA234567890123456789",
        "Traceback: provider failed",
        "/Users/person/private.env",
    ),
)
def test_unsafe_production_metric_text_returns_safe_internal_error(
    monkeypatch, unsafe_text
):
    live = _live()
    malformed = _empty_production_result()
    malformed["metrics"][0]["notes"] = unsafe_text
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: malformed,
    )

    result = _build()

    _assert_safe_internal_error(result)
    assert unsafe_text not in json.dumps(result)


def test_production_mapping_key_order_is_not_part_of_the_contract(monkeypatch):
    live = _live()
    reordered = _empty_production_result()
    reordered["metrics"] = [
        dict(reversed(tuple(metric.items()))) for metric in reordered["metrics"]
    ]
    reordered = dict(reversed(tuple(reordered.items())))
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: reordered,
    )

    result = _build(market_tickers=[], financial_tickers=[])

    assert result["status"] == "empty"
    assert set(result) == PRODUCTION_RESULT_FIELDS


@pytest.mark.parametrize(
    "unsafe_identity",
    (
        "sk_live_FAKE",
        "sk_test_FAKE",
        "rk_live_FAKE",
        "rk_test_FAKE",
        "whsec_FAKE",
    ),
)
def test_extended_secret_prefixes_are_rejected_from_provider_errors(
    monkeypatch, unsafe_identity
):
    live = _live()
    monkeypatch.setattr(
        live,
        "fetch_market_observations",
        lambda *args, **kwargs: {
            "observations": [],
            "errors": [
                {
                    "family": "market_proxy",
                    "ticker": "MU",
                    "field": None,
                    "code": unsafe_identity,
                }
            ],
            "status": "error",
        },
    )

    result = _build(financial_tickers=[])

    assert unsafe_identity not in json.dumps(result)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda result: result.update(
            {"metrics": [deepcopy(_empty_production_result()["metrics"][0])]}
        ),
        lambda result: result.update({"successful_metric_count": 1}),
        lambda result: result.update({"missing_metric_count": 1}),
        lambda result: result.update({"errors": []}),
        lambda result: result["errors"][0].update(
            {"traceback": "/Users/person/private.env"}
        ),
        lambda result: result.update(
            {
                "errors": [
                    {
                        "family": "production",
                        "ticker": None,
                        "field": None,
                        "code": "fetch_failed",
                    }
                ]
            }
        ),
    ),
)
def test_malformed_production_error_envelope_returns_safe_internal_error(
    monkeypatch, mutate
):
    live = _live()
    malformed = _empty_production_result()
    malformed.update(
        {
            "metrics": [],
            "status": "error",
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
    )
    mutate(malformed)
    monkeypatch.setattr(
        live,
        "build_memory_cycle_production_metrics",
        lambda **kwargs: malformed,
    )

    result = _build()

    _assert_safe_internal_error(result)


@pytest.mark.parametrize(
    ("time_name", "overrides"),
    [
        ("retrieved_at", {"retrieved_at": "2026-07-18T20:01:00"}),
        ("evaluated_at", {"evaluated_at": "2026-07-18T20:10:00"}),
    ],
)
def test_naive_injected_times_fail_before_provider_calls(time_name, overrides):
    calls = []

    with pytest.raises(ValueError, match=time_name):
        _build(
            yahoo_quote_fetcher=lambda ticker: calls.append(ticker),
            fmp_income_statement_fetcher=lambda ticker: calls.append(ticker),
            **overrides,
        )

    assert calls == []


@pytest.mark.parametrize(
    ("time_name", "overrides"),
    [
        (
            "retrieved_at",
            {"retrieved_at": "0001-01-01T00:00:00+14:00"},
        ),
        (
            "evaluated_at",
            {"evaluated_at": "9999-12-31T23:59:59-14:00"},
        ),
    ],
)
def test_non_normalizable_injected_times_fail_before_provider_calls(
    time_name, overrides
):
    calls = []

    with pytest.raises(ValueError, match=time_name):
        _build(
            yahoo_quote_fetcher=lambda ticker: calls.append(("market", ticker)),
            fmp_income_statement_fetcher=lambda ticker: calls.append(
                ("financial", ticker)
            ),
            fmp_identity_fetcher=lambda ticker: calls.append(("identity", ticker)),
            **overrides,
        )

    assert calls == []


@pytest.mark.parametrize("missing_name", ("retrieved_at", "evaluated_at"))
def test_required_live_times_cannot_be_omitted(missing_name):
    arguments = {
        "yahoo_quote_fetcher": _yahoo_quote,
        "fmp_income_statement_fetcher": _statement,
        "retrieved_at": RETRIEVED_AT,
        "evaluated_at": EVALUATED_AT,
    }
    arguments.pop(missing_name)

    with pytest.raises(TypeError, match=missing_name):
        _live().build_live_memory_cycle_result(**arguments)


def test_live_does_not_modify_scope_inputs_and_returns_fresh_results():
    market_tickers = ["SOXX", "MU", "SMH", "SNDK"]
    financial_tickers = ["SNDK", "MU"]
    original_market = deepcopy(market_tickers)
    original_financial = deepcopy(financial_tickers)

    first = _build(
        market_tickers=market_tickers,
        financial_tickers=financial_tickers,
    )
    second = _build(
        market_tickers=market_tickers,
        financial_tickers=financial_tickers,
    )

    assert market_tickers == original_market
    assert financial_tickers == original_financial
    assert first == second
    assert first is not second
    assert first["metrics"] is not second["metrics"]
    assert first["metrics"][0] is not second["metrics"][0]


def test_live_has_no_cache_and_calls_injected_fetchers_each_time():
    calls = []

    def market(ticker):
        calls.append(("market", ticker))
        return _yahoo_quote(ticker)

    def financial(ticker):
        calls.append(("financial", ticker))
        return _statement(ticker)

    _build(yahoo_quote_fetcher=market, fmp_income_statement_fetcher=financial)
    _build(yahoo_quote_fetcher=market, fmp_income_statement_fetcher=financial)

    assert calls.count(("market", "MU")) == 2
    assert calls.count(("financial", "MU")) == 2
