import ast
import builtins
from copy import deepcopy
import importlib
import inspect
import math
from pathlib import Path

import pytest

from services.memory_cycle_adapters import (
    adapt_company_financial_metric,
    adapt_market_proxy_metric,
    adapt_memory_cycle_metrics,
    adapt_news_signal_metric,
    build_unavailable_metric,
)
from services.memory_cycle_contract import (
    NEWS_SIGNAL_VALUES,
    REQUIRED_METRIC_FIELDS,
    validate_metric_record,
)


EVALUATED_AT = "2026-07-14T00:00:00+00:00"


def _company_input(**overrides):
    values = {
        "ticker": "MU",
        "metric_id": "company_revenue",
        "label": "Revenue",
        "value": 8.05,
        "unit": "USD billion",
        "currency": "USD",
        "currency_required": True,
        "fiscal_period": "quarterly",
        "as_of": "2026-06-30",
        "retrieved_at": "2026-07-01T10:00:00+00:00",
        "source": "Micron Form 10-Q",
        "source_field": "Revenue",
        "source_document": "Micron FY2026 Q3 Form 10-Q",
        "provenance": None,
        "frequency": "event_driven",
        "evaluated_at": EVALUATED_AT,
        "is_fallback": False,
        "confidence": "medium",
    }
    values.update(overrides)
    return values


def _market_input(**overrides):
    values = {
        "metric_id": "memory_company_equity_trend",
        "label": "Memory company equity trend",
        "value": 4.25,
        "unit": "%",
        "as_of": "2026-07-13",
        "retrieved_at": "2026-07-13T22:00:00+00:00",
        "source": "Yahoo Finance",
        "method": "Five-session adjusted-close return for MU",
        "frequency": "daily",
        "evaluated_at": EVALUATED_AT,
        "is_fallback": False,
        "confidence": "medium",
    }
    values.update(overrides)
    return values


def _news_input(**overrides):
    values = {
        "metric_id": "dram_price_direction",
        "label": "DRAM price direction",
        "value": "improving",
        "citation": "TrendForce: DRAM contract pricing update / https://example.test/dram",
        "source": "TrendForce",
        "as_of": "2026-07-13",
        "retrieved_at": "2026-07-13T22:30:00+00:00",
        "method": "Directional classification of the cited public article",
        "frequency": "event_driven",
        "evaluated_at": EVALUATED_AT,
        "is_fallback": False,
        "confidence": "medium",
    }
    values.update(overrides)
    return values


def _assert_contract(record, *, evaluated_at=EVALUATED_AT):
    assert tuple(record) == REQUIRED_METRIC_FIELDS
    assert validate_metric_record(record, evaluated_at=evaluated_at) == []


# Company financial adapter: cases 1-14.
def test_01_complete_mu_revenue_is_adapted():
    record = adapt_company_financial_metric(**_company_input())
    _assert_contract(record)
    assert record["metric_id"] == "company_revenue"
    assert record["value"] == 8.05
    assert record["source_type"] == "company_reported"
    assert record["status"] == "ok"


def test_02_complete_sndk_gross_margin_is_adapted():
    record = adapt_company_financial_metric(
        **_company_input(
            ticker="SNDK",
            metric_id="gross_margin",
            label="Gross margin",
            value=36.5,
            unit="%",
            currency=None,
            currency_required=False,
            fiscal_period="annual",
            source="SanDisk Form 10-K",
            source_field="Gross margin",
            source_document=None,
            provenance="SanDisk FY2026 Form 10-K, gross-margin line",
        )
    )
    _assert_contract(record)
    assert record["value"] == 36.5
    assert "Company: SNDK" in record["notes"]
    assert "Fiscal period: annual" in record["notes"]


def test_03_missing_fiscal_period_returns_missing():
    record = adapt_company_financial_metric(**_company_input(fiscal_period=None))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_04_missing_unit_returns_missing():
    record = adapt_company_financial_metric(**_company_input(unit=None))
    assert record["status"] == "missing"
    assert record["unit"] is None


def test_05_required_currency_missing_returns_missing():
    record = adapt_company_financial_metric(**_company_input(currency=None))
    assert record["status"] == "missing"
    assert "currency" in record["notes"]


def test_06_missing_source_field_returns_missing():
    record = adapt_company_financial_metric(**_company_input(source_field=None))
    assert record["status"] == "missing"


def test_07_missing_provenance_returns_missing():
    record = adapt_company_financial_metric(
        **_company_input(source_document=None, provenance=None)
    )
    assert record["status"] == "missing"


def test_07b_missing_company_source_returns_missing():
    record = adapt_company_financial_metric(**_company_input(source=None))
    assert record["status"] == "missing"
    assert record["source"] == "unavailable"


def test_07c_missing_company_observation_time_returns_missing():
    record = adapt_company_financial_metric(**_company_input(as_of=None))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_07d_unsupported_company_is_not_silently_accepted():
    record = adapt_company_financial_metric(**_company_input(ticker="XYZ"))
    assert record["status"] == "missing"


@pytest.mark.parametrize(
    ("value", "description"),
    [
        (math.nan, "nan"),
        (math.inf, "positive infinity"),
        (-math.inf, "negative infinity"),
        ("", "empty string"),
        (True, "boolean true"),
        (False, "boolean false"),
    ],
)
def test_08_to_11_invalid_company_values_never_become_valid(value, description):
    record = adapt_company_financial_metric(**_company_input(value=value))
    assert description
    assert record["status"] == "missing"
    assert record["value"] is None


def test_12_real_zero_company_value_is_preserved():
    record = adapt_company_financial_metric(**_company_input(value=0))
    _assert_contract(record)
    assert record["value"] == 0
    assert record["status"] == "ok"


@pytest.mark.parametrize("fiscal_period", [None, "", "unknown", "FY2026"])
def test_13_annual_or_quarterly_is_never_guessed(fiscal_period):
    record = adapt_company_financial_metric(
        **_company_input(fiscal_period=fiscal_period)
    )
    assert record["status"] == "missing"
    assert record["value"] is None


def test_13b_explicit_annual_and_quarterly_are_retained_in_notes():
    annual = adapt_company_financial_metric(
        **_company_input(fiscal_period="annual")
    )
    quarterly = adapt_company_financial_metric(
        **_company_input(fiscal_period="quarterly")
    )
    assert "Fiscal period: annual" in annual["notes"]
    assert "Fiscal period: quarterly" in quarterly["notes"]


def test_14_company_input_dictionary_is_not_modified():
    values = _company_input()
    before = deepcopy(values)
    adapt_company_financial_metric(**values)
    assert values == before


def test_14b_complete_but_source_audit_unavailable_metric_stays_unavailable():
    record = adapt_company_financial_metric(
        **_company_input(
            metric_id="manufacturer_inventory",
            label="Inventory",
            source_field="Inventory",
        )
    )
    _assert_contract(record)
    assert record["status"] == "unavailable"
    assert record["value"] is None


def test_14c_audited_frequency_mismatch_returns_missing_without_relabeling():
    record = adapt_company_financial_metric(
        **_company_input(frequency="quarterly")
    )
    assert record["status"] == "missing"
    assert record["frequency"] == "event_driven"


# Market proxy adapter: cases 15-20.
def test_15_mu_equity_trend_is_marked_proxy():
    record = adapt_market_proxy_metric(**_market_input())
    _assert_contract(record)
    assert record["source_type"] == "proxy"
    assert record["is_estimate"] is True


def test_16_smh_trend_is_marked_proxy():
    record = adapt_market_proxy_metric(
        **_market_input(
            metric_id="semiconductor_etf_trend",
            label="SMH trend",
            source="Yahoo Finance: SMH",
            method="Five-session adjusted-close return for SMH",
        )
    )
    _assert_contract(record)
    assert record["source_type"] == "proxy"


def test_17_proxy_is_not_labeled_direct_industry_fundamental():
    record = adapt_market_proxy_metric(**_market_input())
    assert record["source_type"] != "direct"
    assert "not a direct memory price" in record["notes"]
    assert "company fundamental" in record["notes"]


def test_18_proxy_notes_contain_the_explicit_method():
    record = adapt_market_proxy_metric(**_market_input())
    assert record["notes"].startswith("Method: Five-session adjusted-close return")
    assert "Proxy:" in record["notes"]


@pytest.mark.parametrize(
    "missing_field", ["as_of", "retrieved_at", "evaluated_at"]
)
def test_19_missing_proxy_timestamp_returns_missing(missing_field):
    record = adapt_market_proxy_metric(**_market_input(**{missing_field: None}))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_20_equity_proxy_does_not_create_cycle_conclusions():
    record = adapt_market_proxy_metric(**_market_input(value=25.0))
    assert set(record) == set(REQUIRED_METRIC_FIELDS)
    assert "cycle_phase" not in record
    assert "expansion" not in record
    assert "cycle-phase observation" in record["notes"]


def test_20b_proxy_high_confidence_is_capped_at_medium():
    record = adapt_market_proxy_metric(**_market_input(confidence="high"))
    assert record["confidence"] == "medium"
    assert "capped at medium" in record["notes"]


# News signal adapter: cases 21-32.
@pytest.mark.parametrize(
    ("metric_id", "label", "value"),
    [
        ("dram_price_direction", "DRAM price direction", "improving"),
        ("nand_price_direction", "NAND price direction", "stable"),
        ("hbm_demand", "HBM demand", "strong"),
    ],
)
def test_21_to_23_valid_news_signals_are_adapted(metric_id, label, value):
    record = adapt_news_signal_metric(
        **_news_input(metric_id=metric_id, label=label, value=value)
    )
    _assert_contract(record)
    assert record["value"] == value
    assert record["source_type"] == "news_signal"


def test_24_news_notes_include_citation_marker():
    record = adapt_news_signal_metric(**_news_input())
    assert "Citation:" in record["notes"]


def test_25_news_notes_include_method_marker():
    record = adapt_news_signal_metric(**_news_input())
    assert "Method:" in record["notes"]


def test_26_missing_news_citation_returns_missing():
    record = adapt_news_signal_metric(**_news_input(citation=None))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_27_missing_news_method_returns_missing():
    record = adapt_news_signal_metric(**_news_input(method=None))
    assert record["status"] == "missing"


@pytest.mark.parametrize("value", [12.5, 10, "12.5%", "$4.20", True])
def test_28_precise_or_nonqualitative_news_values_are_rejected(value):
    record = adapt_news_signal_metric(**_news_input(value=value))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_29_news_signal_unit_is_always_none():
    record = adapt_news_signal_metric(**_news_input())
    assert record["unit"] is None


@pytest.mark.parametrize(
    "source",
    [
        "Daily Brief",
        "Technology & Semiconductor Daily News Brief",
        "今日科技与半导体要点",
    ],
)
def test_30_daily_brief_is_not_an_independent_source(source):
    record = adapt_news_signal_metric(**_news_input(source=source))
    assert record["status"] == "missing"
    assert record["source"] == "unavailable"


@pytest.mark.parametrize(
    "value",
    [
        "improving",
        "stable",
        "weakening",
        "strong",
        "mixed",
        "weak",
        "disciplined",
        "neutral",
        "aggressive",
    ],
)
def test_31_qualitative_news_whitelist_is_enforced_for_supported_values(value):
    assert value in NEWS_SIGNAL_VALUES
    record = adapt_news_signal_metric(**_news_input(value=value))
    _assert_contract(record)
    assert record["value"] == value


@pytest.mark.parametrize("value", ["unknown", "bullish-ish", "likely 8%", object()])
def test_32_unknown_qualitative_values_are_safely_rejected(value):
    record = adapt_news_signal_metric(**_news_input(value=value))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_32b_explicit_unavailable_news_signal_returns_unavailable():
    record = adapt_news_signal_metric(**_news_input(value="unavailable"))
    _assert_contract(record)
    assert record["status"] == "unavailable"
    assert record["source"] == "unavailable"


# Unavailable adapter: cases 33-37.
def _unavailable_record():
    return build_unavailable_metric(
        metric_id="dram_spot_price",
        label="DRAM spot price level",
        notes="Unavailable: no approved redistributable direct series.",
    )


def test_33_unavailable_value_is_none():
    assert _unavailable_record()["value"] is None


def test_34_unavailable_status_is_explicit():
    assert _unavailable_record()["status"] == "unavailable"


def test_35_unavailable_source_is_explicit():
    assert _unavailable_record()["source"] == "unavailable"


def test_36_unavailable_confidence_is_low():
    assert _unavailable_record()["confidence"] == "low"


def test_37_missing_or_unavailable_never_becomes_zero():
    records = [
        _unavailable_record(),
        adapt_company_financial_metric(**_company_input(value=None)),
        adapt_news_signal_metric(**_news_input(citation=None)),
    ]
    assert all(record["value"] is None for record in records)


def test_37b_unavailable_uses_the_audited_contract_shape():
    record = _unavailable_record()
    _assert_contract(record)
    assert record["source_type"] == "direct"
    assert record["frequency"] == "daily"
    assert record["is_fallback"] is False


# Time, staleness, and fallback: cases 38-44.
def test_38_as_of_and_retrieved_at_remain_distinct():
    record = adapt_company_financial_metric(**_company_input())
    assert record["as_of"] == "2026-06-30"
    assert record["retrieved_at"] == "2026-07-01T10:00:00+00:00"
    assert record["as_of"] != record["retrieved_at"]


def test_39_evaluated_at_is_injected_and_changes_staleness():
    early = adapt_market_proxy_metric(
        **_market_input(evaluated_at="2026-07-14T00:00:00+00:00")
    )
    late = adapt_market_proxy_metric(
        **_market_input(evaluated_at="2026-07-18T00:00:00+00:00")
    )
    assert early["staleness_days"] == 1
    assert late["staleness_days"] == 5
    assert early["status"] == "ok"
    assert late["status"] == "stale"


def test_40_daily_staleness_threshold_is_reused():
    record = adapt_market_proxy_metric(
        **_market_input(
            as_of="2026-07-10",
            retrieved_at="2026-07-11T00:00:00+00:00",
            evaluated_at="2026-07-14T00:00:00+00:00",
        )
    )
    _assert_contract(record)
    assert record["staleness_days"] == 4
    assert record["status"] == "stale"


def test_41_quarterly_staleness_threshold_is_reused():
    record = adapt_company_financial_metric(
        **_company_input(
            metric_id="injected_quarterly_revenue",
            label="Injected quarterly revenue",
            frequency="quarterly",
            as_of="2026-01-01",
            retrieved_at="2026-01-02T00:00:00+00:00",
            evaluated_at="2026-05-17T00:00:00+00:00",
        )
    )
    _assert_contract(record, evaluated_at="2026-05-17T00:00:00+00:00")
    assert record["staleness_days"] == 136
    assert record["status"] == "stale"


def test_42_fallback_does_not_reset_observation_age():
    direct = adapt_market_proxy_metric(
        **_market_input(
            as_of="2026-07-08",
            retrieved_at="2026-07-09T00:00:00+00:00",
            is_fallback=False,
        )
    )
    fallback = adapt_market_proxy_metric(
        **_market_input(
            as_of="2026-07-08",
            retrieved_at="2026-07-09T00:00:00+00:00",
            is_fallback=True,
        )
    )
    assert direct["staleness_days"] == fallback["staleness_days"] == 6
    assert direct["status"] == fallback["status"] == "stale"
    assert fallback["is_fallback"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("as_of", "2026-07-13T10:00:00"),
        ("retrieved_at", "2026-07-13T22:00:00"),
        ("evaluated_at", "2026-07-14T00:00:00"),
    ],
)
def test_43_naive_time_of_day_is_rejected(field, value):
    record = adapt_market_proxy_metric(**_market_input(**{field: value}))
    assert record["status"] == "missing"
    assert record["value"] is None


def test_43b_timezone_aware_offsets_are_accepted():
    record = adapt_market_proxy_metric(
        **_market_input(
            as_of="2026-07-13T08:00:00+08:00",
            retrieved_at="2026-07-13T22:00:00+08:00",
            evaluated_at="2026-07-14T08:00:00+08:00",
        )
    )
    _assert_contract(record, evaluated_at="2026-07-14T08:00:00+08:00")
    assert record["status"] == "ok"


def test_44_date_only_timestamps_are_safe():
    record = adapt_market_proxy_metric(
        **_market_input(
            as_of="2026-07-12",
            retrieved_at="2026-07-13",
            evaluated_at="2026-07-14",
        )
    )
    _assert_contract(record, evaluated_at="2026-07-14")
    assert record["staleness_days"] == 2


def test_44b_evaluation_before_retrieval_returns_missing():
    record = adapt_market_proxy_metric(
        **_market_input(
            retrieved_at="2026-07-14T12:00:00+00:00",
            evaluated_at="2026-07-14T00:00:00+00:00",
        )
    )
    assert record["status"] == "missing"


# Batch adapter: cases 45-49.
def _batch_specs():
    return [
        {"adapter": "company_financial", **_company_input()},
        {"adapter": "market_proxy", **_market_input()},
        {"adapter": "news_signal", **_news_input()},
    ]


def test_45_batch_preserves_order():
    records = adapt_memory_cycle_metrics(_batch_specs())
    assert [record["metric_id"] for record in records] == [
        "company_revenue",
        "memory_company_equity_trend",
        "dram_price_direction",
    ]


def test_46_batch_does_not_modify_input_list():
    items = _batch_specs()
    before = deepcopy(items)
    adapt_memory_cycle_metrics(items)
    assert items == before


def test_47_batch_does_not_modify_input_dicts():
    item = {"adapter": "company_financial", **_company_input()}
    before = deepcopy(item)
    adapt_memory_cycle_metrics([item])
    assert item == before


@pytest.mark.parametrize("items", [None, {}, "company_financial", 1, object()])
def test_48_non_list_or_tuple_batch_input_returns_empty(items):
    assert adapt_memory_cycle_metrics(items) == []


@pytest.mark.parametrize(
    "item",
    [
        None,
        1,
        "bad",
        {},
        {"adapter": "unknown"},
        {"adapter": {}},
        {"adapter": "company_financial", "extra": 1},
    ],
)
def test_49_invalid_batch_item_is_safe_and_keeps_position(item):
    records = adapt_memory_cycle_metrics([item])
    assert len(records) == 1
    assert records[0]["status"] == "unavailable"
    assert tuple(records[0]) == REQUIRED_METRIC_FIELDS


def test_49b_tuple_batch_input_is_supported():
    records = adapt_memory_cycle_metrics(tuple(_batch_specs()))
    assert len(records) == 3


# Isolation and no-I/O guarantees: cases 50-56.
def _module_source():
    module = importlib.import_module("services.memory_cycle_adapters")
    return Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")


def test_50_adapter_module_does_not_import_requests():
    tree = ast.parse(_module_source())
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "requests" not in imports


def test_51_adapter_module_does_not_import_yfinance():
    assert "yfinance" not in _module_source()
    assert "yf.Ticker" not in _module_source()


def test_52_adapter_module_does_not_import_openai():
    assert "openai" not in _module_source().lower()


def test_53_adapter_module_does_not_import_ibkr_clients():
    source = _module_source().lower()
    assert "ib_insync" not in source
    assert "ibkr" not in source


def test_54_adapter_module_does_not_read_secrets_or_environment():
    source = _module_source()
    assert "st.secrets" not in source
    assert "os.environ" not in source
    assert "getenv(" not in source


def test_55_adapter_module_has_no_file_io_calls():
    tree = ast.parse(_module_source())
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "open" not in called_names
    assert not ({"read_text", "write_text", "read_bytes", "write_bytes"} & called_attributes)


def test_56_adapter_module_does_not_import_or_modify_dashboard():
    tree = ast.parse(_module_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "dashboard" not in imported
    assert all(not name.startswith("dashboard.") for name in imported)


def test_56b_runtime_adaptation_does_not_touch_network_ai_or_files(monkeypatch):
    import requests
    import yfinance

    def forbidden(*args, **kwargs):
        raise AssertionError("external I/O is forbidden")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(yfinance, "Ticker", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)

    records = [
        adapt_company_financial_metric(**_company_input()),
        adapt_market_proxy_metric(**_market_input()),
        adapt_news_signal_metric(**_news_input()),
        _unavailable_record(),
    ]
    assert all(tuple(record) == REQUIRED_METRIC_FIELDS for record in records)


def test_all_public_adapters_return_exactly_the_existing_15_field_contract():
    records = [
        adapt_company_financial_metric(**_company_input()),
        adapt_market_proxy_metric(**_market_input()),
        adapt_news_signal_metric(**_news_input()),
        _unavailable_record(),
    ]
    assert len(REQUIRED_METRIC_FIELDS) == 15
    assert all(tuple(record) == REQUIRED_METRIC_FIELDS for record in records)
