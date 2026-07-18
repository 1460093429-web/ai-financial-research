"""Regression tests for FMP identity, period, unit, TTM, and sign semantics."""

from copy import deepcopy
import math

import pytest

from services.fmp_financial_normalization import (
    build_ttm_statement,
    normalize_fmp_financial_data,
    normalize_monetary_value,
)


RETRIEVED_AT = "2026-04-15T12:00:00+00:00"
CIKS = {"MU": "0000723125", "SNDK": "0002005687"}


def _income(symbol, date, year, period, factor):
    return {
        "symbol": symbol,
        "cik": CIKS[symbol],
        "date": date,
        "calendarYear": str(year),
        "period": period,
        "reportedCurrency": "USD",
        "revenue": 100.0 * factor,
        "grossProfit": 50.0 * factor,
        "grossProfitRatio": 0.5,
        "operatingIncome": 25.0 * factor,
        "operatingIncomeRatio": 0.25,
        "netIncome": 20.0 * factor,
        "netIncomeRatio": 0.2,
        "ebitda": 30.0 * factor,
        "incomeBeforeTax": 24.0 * factor,
        "incomeTaxExpense": 4.8 * factor,
        "eps": 0.9 * factor,
        "epsdiluted": 1.0 * factor,
        "weightedAverageShsOut": 10.0,
        "weightedAverageShsOutDil": 10.0,
    }


def _balance(symbol, date, year, period, factor):
    return {
        "symbol": symbol,
        "cik": CIKS[symbol],
        "date": date,
        "calendarYear": str(year),
        "period": period,
        "reportedCurrency": "USD",
        "inventory": 50.0 + 10.0 * factor,
        "cashAndCashEquivalentsAndShortTermInvestments": 30.0 + 5.0 * factor,
        "cashAndCashEquivalents": 20.0 + 5.0 * factor,
        "shortTermInvestments": 10.0,
        "totalDebt": 40.0 - 2.0 * factor,
        "totalStockholdersEquity": 150.0 + 10.0 * factor,
        "totalAssets": 450.0 + 10.0 * factor,
    }


def _cashflow(symbol, date, year, period, factor, capex=None, fcf=None):
    ocf = 40.0 + 20.0 * factor
    raw_capex = -(10.0 * factor) if capex is None else capex
    derived_fcf = ocf + raw_capex
    return {
        "symbol": symbol,
        "cik": CIKS[symbol],
        "date": date,
        "calendarYear": str(year),
        "period": period,
        "reportedCurrency": "USD",
        "operatingCashFlow": ocf,
        "capitalExpenditure": raw_capex,
        "freeCashFlow": derived_fcf if fcf is None else fcf,
    }


QUARTERS = (
    ("2026-03-31", 2026, "Q1", 4),
    ("2025-12-31", 2025, "Q4", 3),
    ("2025-09-30", 2025, "Q3", 2),
    ("2025-06-30", 2025, "Q2", 1),
    ("2025-03-31", 2025, "Q1", 0.8),
)


def _raw(symbol="MU"):
    return {
        "symbol": symbol,
        "identity": [{
            "symbol": symbol,
            "companyName": "Micron Technology, Inc." if symbol == "MU" else "SanDisk Corporation",
            "cik": CIKS[symbol],
            "currency": "USD",
        }],
        "quote": [{
            "symbol": symbol,
            "name": "Micron Technology, Inc." if symbol == "MU" else "SanDisk Corporation",
            "price": 100.0,
            "currency": "USD",
            "timestamp": 1_765_800_000,
            "marketCap": 1_000.0,
            "enterpriseValue": 980.0,
            "sharesOutstanding": 10.0,
        }],
        "income_quarterly": [_income(symbol, *quarter) for quarter in QUARTERS],
        "income_annual": [_income(symbol, "2025-12-31", 2025, "FY", 10)],
        "balance_quarterly": [_balance(symbol, *quarter) for quarter in QUARTERS],
        "balance_annual": [_balance(symbol, "2025-12-31", 2025, "FY", 3)],
        "cashflow_quarterly": [_cashflow(symbol, *quarter) for quarter in QUARTERS],
        "cashflow_annual": [_cashflow(symbol, "2025-12-31", 2025, "FY", 10)],
        "retrieved_at": RETRIEVED_AT,
        "source": "FMP",
        "errors": [],
        "status": "ok",
    }


def _codes(result):
    return {error["code"] for error in result["errors"]}


@pytest.mark.parametrize("symbol", ("MU", "SNDK"))
def test_exact_identity_and_statement_metadata_are_preserved(symbol):
    result = normalize_fmp_financial_data(_raw(symbol))
    assert result["identity"] == {
        "symbol": symbol,
        "company_name": "Micron Technology, Inc." if symbol == "MU" else "SanDisk Corporation",
        "cik": CIKS[symbol],
        "currency": "USD",
    }
    latest = result["statements"]["income"]["quarterly"][0]
    assert latest["ticker"] == symbol
    assert latest["statement_type"] == "income"
    assert latest["period_type"] == "quarterly"
    assert latest["period"] == "Q1"
    assert latest["period_end"] == "2026-03-31"
    assert latest["retrieved_at"] == RETRIEVED_AT
    assert latest["currency"] == "USD"
    assert latest["fields"]["revenue"]["source_field"] == "revenue"
    assert latest["fields"]["revenue"]["raw_value"] == 400.0
    assert latest["fields"]["revenue"]["normalized_unit"] == "USD"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    (
        (lambda raw: raw["identity"][0].update(symbol="WDC"), "identity_mismatch"),
        (lambda raw: raw["quote"][0].update(symbol="WDC"), "quote_identity_mismatch"),
        (lambda raw: raw["income_quarterly"][0].update(symbol="WDC"), "statement_identity_mismatch"),
        (lambda raw: raw["income_quarterly"][0].update(cik="0000000001"), "statement_identity_mismatch"),
    ),
)
def test_identity_conflicts_are_rejected_without_cross_company_data(mutate, expected):
    raw = _raw("SNDK")
    mutate(raw)
    result = normalize_fmp_financial_data(raw)
    assert expected in _codes(result)
    if expected == "identity_mismatch":
        assert result["statements"]["income"]["quarterly"] == []


def test_sndk_never_accepts_wdc_or_legacy_history():
    raw = _raw("SNDK")
    raw["income_quarterly"].append(
        _income("SNDK", "2024-12-31", 2024, "Q4", 1)
    )
    raw["balance_quarterly"].append(
        _balance("SNDK", "2024-12-31", 2024, "Q4", 1)
    )
    result = normalize_fmp_financial_data(raw)
    assert all(
        row["period_end"] >= "2025-01-01"
        for group in result["statements"].values()
        for rows in group.values()
        for row in rows
    )
    assert "legacy_statement" in _codes(result)
    serialized = str(result)
    assert "WDC" not in serialized


@pytest.mark.parametrize("period", ("TTM", "LTM", "unknown", ""))
def test_unsupported_provider_periods_are_rejected(period):
    raw = _raw()
    raw["income_quarterly"][0]["period"] = period
    result = normalize_fmp_financial_data(raw)
    assert "unsupported_period" in _codes(result)
    assert len(result["statements"]["income"]["quarterly"]) == 4


@pytest.mark.parametrize("field", ("date", "reportedCurrency"))
def test_missing_shared_period_metadata_rejects_one_row_not_siblings(field):
    raw = _raw()
    raw["income_quarterly"][0].pop(field)
    result = normalize_fmp_financial_data(raw)
    assert len(result["statements"]["income"]["quarterly"]) == 4
    assert ("missing_period_end" if field == "date" else "missing_currency") in _codes(result)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    (
        (2_000_000.0, "USD", 2_000_000.0),
        (2_000.0, "USD thousands", 2_000_000.0),
        (2.0, "USD millions", 2_000_000.0),
        (0.002, "USD billions", 2_000_000.0),
        (0.0, "USD", 0.0),
    ),
)
def test_monetary_units_convert_once_to_full_currency(value, unit, expected):
    normalized = normalize_monetary_value(value, raw_unit=unit, currency="USD")
    assert normalized["raw_value"] == value
    assert normalized["raw_unit"] == unit
    assert normalized["normalized_value"] == expected
    assert normalized["normalized_unit"] == "USD"


@pytest.mark.parametrize("value", (None, True, math.nan, math.inf, "123.45", ""))
def test_invalid_numeric_values_are_rejected_without_string_coercion(value):
    assert normalize_monetary_value(value, raw_unit="USD", currency="USD") is None


def test_unknown_unit_and_currency_conflict_are_rejected():
    assert normalize_monetary_value(2.0, raw_unit="unknown", currency="USD") is None
    assert normalize_monetary_value(2.0, raw_unit="EUR millions", currency="USD") is None


def test_reported_margins_convert_ratio_to_percent_once_and_are_not_derived():
    result = normalize_fmp_financial_data(_raw())
    fields = result["statements"]["income"]["quarterly"][0]["fields"]
    assert fields["gross_margin"]["normalized_value"] == 50.0
    assert fields["gross_margin"]["normalized_unit"] == "percent"
    assert fields["gross_margin"]["derived"] is False
    assert fields["operating_margin"]["normalized_value"] == 25.0
    assert fields["net_margin"]["normalized_value"] == 20.0


@pytest.mark.parametrize(
    ("ratio_field", "output_field", "numerator_field", "expected"),
    (
        ("grossProfitRatio", "gross_margin", "grossProfit", 50.0),
        ("operatingIncomeRatio", "operating_margin", "operatingIncome", 25.0),
        ("netIncomeRatio", "net_margin", "netIncome", 20.0),
    ),
)
def test_missing_reported_margin_is_derived_from_same_row_only(
    ratio_field, output_field, numerator_field, expected
):
    raw = _raw()
    raw["income_quarterly"][0].pop(ratio_field)
    result = normalize_fmp_financial_data(raw)
    metric = result["statements"]["income"]["quarterly"][0]["fields"][output_field]
    assert metric["normalized_value"] == expected
    assert metric["derived"] is True
    assert set(metric["source_fields"]) == {numerator_field, "revenue"}


def test_zero_revenue_keeps_real_zero_but_margins_are_unavailable():
    raw = _raw()
    row = raw["income_quarterly"][0]
    row.update(revenue=0.0)
    row.pop("grossProfitRatio")
    result = normalize_fmp_financial_data(raw)
    fields = result["statements"]["income"]["quarterly"][0]["fields"]
    assert fields["revenue"]["normalized_value"] == 0.0
    assert "gross_margin" not in fields


def test_continuous_four_quarters_build_income_and_cashflow_ttm():
    normalized = normalize_fmp_financial_data(_raw())
    income = build_ttm_statement(
        normalized["statements"]["income"]["quarterly"], statement_type="income"
    )
    cashflow = build_ttm_statement(
        normalized["statements"]["cashflow"]["quarterly"], statement_type="cashflow"
    )
    assert income["status"] == "ok"
    assert income["record"]["period_type"] == "ttm"
    assert income["record"]["period_end"] == "2026-03-31"
    assert income["record"]["fields"]["revenue"]["normalized_value"] == 1_000.0
    assert income["record"]["fields"]["gross_profit"]["normalized_value"] == 500.0
    assert income["record"]["fields"]["operating_income"]["normalized_value"] == 250.0
    assert income["record"]["fields"]["net_income"]["normalized_value"] == 200.0
    assert income["record"]["fields"]["diluted_eps"]["normalized_value"] == 10.0
    assert cashflow["record"]["fields"]["operating_cash_flow"]["normalized_value"] == 360.0
    assert cashflow["record"]["fields"]["capex"]["normalized_value"] == 100.0
    assert cashflow["record"]["fields"]["free_cash_flow"]["normalized_value"] == 260.0


@pytest.mark.parametrize(
    "mutator",
    (
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
        lambda rows: rows[1].update(currency="EUR"),
        lambda rows: rows[1].update(ticker="SNDK"),
        lambda rows: rows[1].update(period_type="annual"),
        lambda rows: rows[1].update(period_end=rows[0]["period_end"]),
        lambda rows: rows[1].update(period="Q2", fiscal_year="2024"),
    ),
)
def test_ttm_is_unavailable_for_incomplete_duplicate_or_mixed_quarters(mutator):
    rows = normalize_fmp_financial_data(_raw())["statements"]["income"]["quarterly"][:4]
    mutator(rows)
    result = build_ttm_statement(rows, statement_type="income")
    assert result["status"] == "unavailable"
    assert result["record"] is None


@pytest.mark.parametrize(
    ("capex", "fcf", "expected_code", "expected_capex"),
    (
        (-40.0, 120.0, "free_cash_flow_conflict", 40.0),
        (40.0, 200.0, "positive_capex_sign", None),
        (0.0, 160.0, None, 0.0),
    ),
)
def test_capex_sign_and_provider_fcf_conflict_are_explicit(
    capex, fcf, expected_code, expected_capex
):
    raw = _raw()
    raw["cashflow_quarterly"][0].update(
        capitalExpenditure=capex, freeCashFlow=fcf
    )
    result = normalize_fmp_financial_data(raw)
    latest = result["statements"]["cashflow"]["quarterly"][0]
    if expected_capex is None:
        assert "capex" not in latest["fields"]
    else:
        assert latest["fields"]["capex"]["normalized_value"] == expected_capex
    if expected_code:
        assert expected_code in _codes(result)


def test_normalization_does_not_mutate_raw_and_returns_fresh_objects():
    raw = _raw()
    original = deepcopy(raw)
    first = normalize_fmp_financial_data(raw)
    second = normalize_fmp_financial_data(raw)
    assert raw == original
    assert first == second
    assert first is not second
    assert first["statements"] is not second["statements"]
