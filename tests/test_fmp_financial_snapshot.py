"""Tests for the pure UI-facing shared FMP financial snapshot."""

from copy import deepcopy

import pytest

from services.fmp_financial_normalization import normalize_fmp_financial_data
from services.fmp_financial_snapshot import build_fmp_financial_snapshot
from test_fmp_financial_normalization import CIKS, QUARTERS, _balance, _cashflow, _income, _raw


EVALUATED_AT = "2026-04-15T12:10:00+00:00"


def _snapshot(symbol="MU", raw=None):
    normalized = normalize_fmp_financial_data(raw or _raw(symbol))
    return build_fmp_financial_snapshot(normalized, evaluated_at=EVALUATED_AT)


def _metric(snapshot, name):
    return snapshot["metrics"][name]


def test_snapshot_identity_quality_period_currency_and_source_are_explicit():
    result = _snapshot()
    assert result["ticker"] == "MU"
    assert result["company_name"] == "Micron Technology, Inc."
    assert result["source"] == "FMP"
    assert result["retrieved_at"] == "2026-04-15T12:00:00+00:00"
    assert result["evaluated_at"] == EVALUATED_AT
    assert result["currency"] == "USD"
    assert result["status"] == "ok"
    assert result["periods"]["ttm_end"] == "2026-03-31"
    assert result["periods"]["balance_end"] == "2026-03-31"
    assert result["periods"]["annual_end"] == "2025-12-31"
    assert result["quality"]["successful_metric_count"] > 0


@pytest.mark.parametrize(
    ("name", "expected", "unit", "period_type"),
    (
        ("revenue", 1_000.0, "USD", "ttm"),
        ("gross_profit", 500.0, "USD", "ttm"),
        ("gross_margin", 50.0, "percent", "ttm"),
        ("operating_income", 250.0, "USD", "ttm"),
        ("operating_margin", 25.0, "percent", "ttm"),
        ("net_income", 200.0, "USD", "ttm"),
        ("net_margin", 20.0, "percent", "ttm"),
        ("ebitda", 300.0, "USD", "ttm"),
        ("diluted_eps", 10.0, "USD per share", "ttm"),
        ("operating_cash_flow", 360.0, "USD", "ttm"),
        ("capex", 100.0, "USD", "ttm"),
        ("free_cash_flow", 260.0, "USD", "ttm"),
        ("inventory", 90.0, "USD", "latest_balance"),
        ("cash", 50.0, "USD", "latest_balance"),
        ("total_debt", 32.0, "USD", "latest_balance"),
        ("net_debt", -18.0, "USD", "latest_balance"),
        ("equity", 190.0, "USD", "latest_balance"),
        ("assets", 490.0, "USD", "latest_balance"),
        ("shares_outstanding", 10.0, "shares", "current"),
    ),
)
def test_snapshot_core_metrics_use_correct_flow_or_point_in_time_semantics(
    name, expected, unit, period_type
):
    metric = _metric(_snapshot(), name)
    assert metric["normalized_value"] == pytest.approx(expected)
    assert metric["normalized_unit"] == unit
    assert metric["period_type"] == period_type
    assert metric["source"] == "FMP"
    assert metric["status"] in {"ok", "stale"}
    assert metric["retrieved_at"] == "2026-04-15T12:00:00+00:00"


def test_snapshot_growth_and_return_formulas_use_correct_periods_and_averages():
    result = _snapshot()
    assert _metric(result, "revenue_qoq")["normalized_value"] == pytest.approx(400 / 300 - 1)
    assert _metric(result, "revenue_yoy")["normalized_value"] == pytest.approx(400 / 80 - 1)
    assert _metric(result, "inventory_qoq")["normalized_value"] == pytest.approx(90 / 80 - 1)
    assert _metric(result, "inventory_yoy")["normalized_value"] == pytest.approx(90 / 58 - 1)
    assert _metric(result, "roe")["normalized_value"] == pytest.approx(200 / ((158 + 190) / 2))
    assert _metric(result, "roa")["normalized_value"] == pytest.approx(200 / ((458 + 490) / 2))
    assert _metric(result, "roic")["derived"] is True
    assert "average invested capital" in _metric(result, "roic")["method"]


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("pe", 10.0),
        ("ps", 1.0),
        ("pb", 1_000 / 190),
        ("ev_ebitda", 980 / 300),
    ),
)
def test_valuation_multiples_use_current_numerator_and_ttm_or_latest_denominator(
    name, expected
):
    metric = _metric(_snapshot(), name)
    assert metric["normalized_value"] == pytest.approx(expected)
    assert metric["normalized_unit"] == "multiple"
    assert metric["derived"] is True


@pytest.mark.parametrize(
    ("mutate", "metric_name"),
    (
        (lambda raw: [row.update(epsdiluted=-1.0) for row in raw["income_quarterly"][:4]], "pe"),
        (lambda raw: raw["balance_quarterly"][0].update(totalStockholdersEquity=0.0), "pb"),
        (lambda raw: [row.update(ebitda=-1.0) for row in raw["income_quarterly"][:4]], "ev_ebitda"),
        (lambda raw: raw["quote"][0].update(currency="EUR"), "ps"),
    ),
)
def test_invalid_denominators_or_currency_make_multiples_unavailable(mutate, metric_name):
    raw = _raw()
    mutate(raw)
    metric = _metric(_snapshot(raw=raw), metric_name)
    assert metric["status"] == "unavailable"
    assert metric["normalized_value"] is None


def test_roic_is_unavailable_when_tax_rate_or_average_capital_is_not_verifiable():
    raw = _raw()
    for row in raw["income_quarterly"][:4]:
        row["incomeBeforeTax"] = 0.0
    result = _snapshot(raw=raw)
    assert _metric(result, "roic")["status"] == "unavailable"
    assert _metric(result, "roic")["normalized_value"] is None


def test_incomplete_ttm_never_substitutes_one_quarter_and_keeps_balance_points():
    raw = _raw()
    raw["income_quarterly"] = raw["income_quarterly"][:3]
    raw["cashflow_quarterly"] = raw["cashflow_quarterly"][:3]
    result = _snapshot(raw=raw)
    assert _metric(result, "revenue")["status"] == "unavailable"
    assert _metric(result, "free_cash_flow")["status"] == "unavailable"
    assert _metric(result, "inventory")["normalized_value"] == 90.0
    assert "continuous quarters" in _metric(result, "revenue")["notes"]


def test_missing_is_never_zero_but_real_zero_is_retained():
    raw = _raw()
    raw["balance_quarterly"][0].pop("inventory")
    raw["cashflow_quarterly"][0]["capitalExpenditure"] = 0.0
    raw["cashflow_quarterly"][0]["freeCashFlow"] = raw["cashflow_quarterly"][0]["operatingCashFlow"]
    result = _snapshot(raw=raw)
    assert _metric(result, "inventory")["normalized_value"] is None
    assert _metric(result, "inventory")["status"] in {"missing", "unavailable"}
    assert normalize_fmp_financial_data(raw)["statements"]["cashflow"]["quarterly"][0]["fields"]["capex"]["normalized_value"] == 0.0


def test_stale_metrics_show_whole_staleness_days_without_changing_period_end():
    result = build_fmp_financial_snapshot(
        normalize_fmp_financial_data(_raw()),
        evaluated_at="2027-04-15T12:10:00+00:00",
    )
    revenue = _metric(result, "revenue")
    assert revenue["status"] == "stale"
    assert revenue["staleness_days"] == 380
    assert revenue["period_end"] == "2026-03-31"


def test_snapshot_does_not_mutate_input_or_reuse_nested_objects():
    normalized = normalize_fmp_financial_data(_raw())
    original = deepcopy(normalized)
    first = build_fmp_financial_snapshot(normalized, evaluated_at=EVALUATED_AT)
    second = build_fmp_financial_snapshot(normalized, evaluated_at=EVALUATED_AT)
    assert normalized == original
    assert first == second
    assert first is not second
    assert first["metrics"] is not second["metrics"]
