"""Tests for the shared-snapshot Value Investing service and view model."""

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from services.value_investing import (
    build_value_investing_view_model,
    load_value_investing_snapshot,
)
from test_fmp_financial_normalization import _raw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = PROJECT_ROOT / "services" / "value_investing.py"
RETRIEVED_AT = "2026-04-15T12:00:00+00:00"
EVALUATED_AT = "2026-04-15T12:10:00+00:00"


def _fetcher(symbol="MU", *, calls=None, raw=None):
    payload = deepcopy(raw or _raw(symbol))

    def fetch(endpoint, **params):
        if calls is not None:
            calls.append((endpoint, params["symbol"], params.get("period")))
        if endpoint == "profile":
            return deepcopy(payload["identity"])
        if endpoint == "quote":
            return deepcopy(payload["quote"])
        groups = {
            "income-statement": "income",
            "balance-sheet-statement": "balance",
            "cash-flow-statement": "cashflow",
        }
        prefix = groups[endpoint]
        suffix = "quarterly" if params["period"] == "quarter" else "annual"
        return deepcopy(payload[f"{prefix}_{suffix}"])

    return fetch


def _snapshot(symbol="MU", *, raw=None):
    return load_value_investing_snapshot(
        symbol,
        fmp_json_fetcher=_fetcher(symbol, raw=raw),
        retrieved_at=RETRIEVED_AT,
        evaluated_at=EVALUATED_AT,
    )


def test_service_source_has_no_ui_yfinance_news_fixture_cache_secret_or_hidden_clock():
    source = SERVICE_PATH.read_text(encoding="utf-8")
    lowered = source.casefold()
    assert all(marker not in lowered for marker in (
        "streamlit", "yfinance", "news", "fixture", "session_state", "st.cache",
        "api_key", "os.environ", "st.secrets", "datetime.now", "date.today",
    ))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "dashboard" not in imported


def test_loader_uses_shared_fmp_provider_normalization_and_snapshot_scope():
    calls = []
    snapshot = load_value_investing_snapshot(
        "MU",
        fmp_json_fetcher=_fetcher(calls=calls),
        retrieved_at=RETRIEVED_AT,
        evaluated_at=EVALUATED_AT,
    )
    assert calls == [
        ("profile", "MU", None),
        ("quote", "MU", None),
        ("income-statement", "MU", "quarter"),
        ("income-statement", "MU", "annual"),
        ("balance-sheet-statement", "MU", "quarter"),
        ("balance-sheet-statement", "MU", "annual"),
        ("cash-flow-statement", "MU", "quarter"),
        ("cash-flow-statement", "MU", "annual"),
    ]
    assert snapshot["source"] == "FMP"
    assert snapshot["status"] == "ok"


@pytest.mark.parametrize("symbol", ("MU", "SNDK"))
def test_loader_preserves_exact_company_identity_without_wdc_mapping(symbol):
    snapshot = _snapshot(symbol)
    assert snapshot["ticker"] == symbol
    assert snapshot["cik"] == ("0000723125" if symbol == "MU" else "0002005687")
    assert "WDC" not in str(snapshot)


def test_provider_failure_returns_safe_error_snapshot_without_exception_text():
    def failed(*args, **kwargs):
        raise RuntimeError("Authorization secret /Users/private/raw-response")

    snapshot = load_value_investing_snapshot(
        "MU", fmp_json_fetcher=failed,
        retrieved_at=RETRIEVED_AT, evaluated_at=EVALUATED_AT,
    )
    assert snapshot["status"] == "error"
    assert snapshot["ticker"] == "MU"
    assert snapshot["metrics"] == {}
    serialized = str(snapshot).casefold()
    assert "authorization" not in serialized
    assert "secret" not in serialized
    assert "/users/" not in serialized
    assert "traceback" not in serialized


def test_view_model_has_data_quality_and_five_financial_sections():
    view = build_value_investing_view_model(_snapshot(), language="English")
    assert view["title"] == "Value Investing"
    assert view["ticker"] == "MU"
    assert view["data_quality"]["source"] == "FMP"
    assert [section["section_id"] for section in view["sections"]] == [
        "income_profitability", "cash_flow", "balance_sheet", "returns", "valuation"
    ]


@pytest.mark.parametrize(
    ("metric_id", "period_type", "period_end", "unit"),
    (
        ("revenue", "ttm", "2026-03-31", "USD"),
        ("gross_margin", "ttm", "2026-03-31", "percent"),
        ("inventory", "latest_balance", "2026-03-31", "USD"),
        ("annual_revenue", "annual", "2025-12-31", "USD"),
        ("pe", "current_over_financial_period", "2026-03-31", "multiple"),
    ),
)
def test_view_model_keeps_period_end_and_unit_explicit(metric_id, period_type, period_end, unit):
    view = build_value_investing_view_model(_snapshot(), language="English")
    metric = view["metrics_by_id"][metric_id]
    assert metric["period_type"] == period_type
    assert metric["period_end"] == period_end
    assert metric["normalized_unit"] == unit
    assert metric["source"] == "FMP"


def test_retrieval_time_is_separate_from_all_financial_period_dates():
    view = build_value_investing_view_model(_snapshot(), language="English")
    assert view["data_quality"]["retrieved_at"] == RETRIEVED_AT
    assert view["data_quality"]["retrieved_at"] != view["periods"]["ttm_end"]
    assert view["periods"] == {
        "ttm_end": "2026-03-31",
        "balance_end": "2026-03-31",
        "annual_end": "2025-12-31",
    }


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    (
        ("gross_margin", 50.0),
        ("operating_margin", 25.0),
        ("net_margin", 20.0),
        ("free_cash_flow", 260.0),
        ("net_debt", -18.0),
        ("pe", 10.0),
        ("ps", 1.0),
        ("pb", 1_000 / 190),
        ("ev_ebitda", 980 / 300),
        ("roe", 200 / ((158 + 190) / 2)),
        ("roa", 200 / ((458 + 490) / 2)),
    ),
)
def test_view_model_passes_shared_snapshot_formulas_without_recalculation(metric_id, expected):
    metric = build_value_investing_view_model(_snapshot(), language="English")["metrics_by_id"][metric_id]
    assert metric["normalized_value"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("mutate", "metric_id"),
    (
        (lambda raw: [row.update(epsdiluted=-1.0) for row in raw["income_quarterly"][:4]], "pe"),
        (lambda raw: raw["balance_quarterly"][0].update(totalStockholdersEquity=0.0), "pb"),
        (lambda raw: [row.update(ebitda=-1.0) for row in raw["income_quarterly"][:4]], "ev_ebitda"),
        (lambda raw: [row.update(incomeBeforeTax=0.0) for row in raw["income_quarterly"][:4]], "roic"),
    ),
)
def test_view_model_keeps_invalid_ratios_unavailable_not_zero(mutate, metric_id):
    raw = _raw()
    mutate(raw)
    metric = build_value_investing_view_model(_snapshot(raw=raw), language="English")["metrics_by_id"][metric_id]
    assert metric["status"] == "unavailable"
    assert metric["normalized_value"] is None


def test_missing_value_is_not_coerced_to_zero_and_real_zero_is_preserved():
    raw = _raw()
    raw["balance_quarterly"][0].pop("inventory")
    raw["cashflow_quarterly"][0]["capitalExpenditure"] = 0.0
    raw["cashflow_quarterly"][0]["freeCashFlow"] = raw["cashflow_quarterly"][0]["operatingCashFlow"]
    view = build_value_investing_view_model(_snapshot(raw=raw), language="English")
    assert view["metrics_by_id"]["inventory"]["normalized_value"] is None
    assert view["metrics_by_id"]["capex"]["normalized_value"] == 60.0


def test_stale_status_and_days_pass_through_view_model():
    snapshot = load_value_investing_snapshot(
        "MU", fmp_json_fetcher=_fetcher(), retrieved_at=RETRIEVED_AT,
        evaluated_at="2027-04-15T12:10:00+00:00",
    )
    metric = build_value_investing_view_model(snapshot, language="English")["metrics_by_id"]["revenue"]
    assert metric["status"] == "stale"
    assert metric["staleness_days"] == 380


@pytest.mark.parametrize(
    ("language", "title", "income", "missing", "derived", "ttm"),
    (
        ("中文", "价值投资", "利润与盈利能力", "数据缺失", "派生计算", "TTM"),
        ("English", "Value Investing", "Income and Profitability", "Missing", "Derived", "TTM"),
        ("Español", "Inversión en valor", "Ingresos y rentabilidad", "Faltante", "Derivado", "TTM"),
        ("unknown", "Value Investing", "Income and Profitability", "Missing", "Derived", "TTM"),
    ),
)
def test_view_model_localizes_labels_with_english_fallback(language, title, income, missing, derived, ttm):
    view = build_value_investing_view_model(_snapshot(), language=language)
    assert view["title"] == title
    assert view["sections"][0]["title"] == income
    assert view["text"]["statuses"]["missing"] == missing
    assert view["text"]["evidence"]["derived"] == derived
    assert view["text"]["periods"]["ttm"] == ttm


def test_service_does_not_mutate_snapshot_and_returns_fresh_view_models():
    snapshot = _snapshot()
    before = deepcopy(snapshot)
    first = build_value_investing_view_model(snapshot, language="English")
    second = build_value_investing_view_model(snapshot, language="English")
    assert snapshot == before
    assert first == second
    assert first is not second
    assert first["sections"] is not second["sections"]
