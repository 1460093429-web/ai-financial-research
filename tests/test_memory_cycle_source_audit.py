import builtins

import pytest

from services.memory_cycle_contract import (
    AVAILABILITY_CLASSES,
    COMPANY_COVERAGE,
    DISALLOWED_EXACT_PRICE_ALIASES,
    EXACT_MEMORY_PRICE_METRICS,
    FREQUENCIES,
    METRIC_AVAILABILITY,
    SOURCE_AUDIT,
    SOURCE_FAMILY_CLASSIFICATION,
    SOURCE_TYPES,
    build_metric_record,
    validate_metric_record,
)


def test_all_audited_metrics_use_known_classification_and_sources():
    assert METRIC_AVAILABILITY
    for metric_id, audit in METRIC_AVAILABILITY.items():
        assert audit["availability"] in AVAILABILITY_CLASSES, metric_id
        assert audit["source_type"] in SOURCE_TYPES, metric_id
        assert audit["frequency"] in FREQUENCIES, metric_id
        assert set(audit["sources"]) <= set(SOURCE_AUDIT), metric_id
        assert audit["notes"], metric_id

    for source_name, source in SOURCE_AUDIT.items():
        assert set(source["allowed_metric_families"]) <= set(SOURCE_FAMILY_CLASSIFICATION), source_name
        for family in source["allowed_metric_families"]:
            classification = SOURCE_FAMILY_CLASSIFICATION[family]
            assert classification["availability"] in source["availability_classes"], source_name


def test_source_family_not_transport_determines_a_b_c_d_classification():
    assert SOURCE_FAMILY_CLASSIFICATION["equity_price"] == {
        "availability": "A",
        "source_type": "direct",
    }
    assert SOURCE_FAMILY_CLASSIFICATION["company_statement"] == {
        "availability": "B",
        "source_type": "company_reported",
    }
    assert SOURCE_FAMILY_CLASSIFICATION["news"] == {
        "availability": "C",
        "source_type": "news_signal",
    }
    assert SOURCE_FAMILY_CLASSIFICATION["cycle_proxy"] == {
        "availability": "D",
        "source_type": "proxy",
    }

    for source_name in ("yahoo_yfinance", "fmp"):
        audit = SOURCE_AUDIT[source_name]
        assert "equity_price" in audit["allowed_metric_families"]
        assert "company_statement" in audit["allowed_metric_families"]
        assert "news" in audit["allowed_metric_families"]
        assert audit["provides_company_financials"] is True
        assert audit["provides_product_specific_memory_fundamentals"] is False
        assert audit["provides_exact_memory_pricing"] is False


def test_financials_snapshot_is_partial_company_reported_coverage():
    audit = SOURCE_AUDIT["financials_module"]

    assert audit["production_company_coverage"] == ("MU", "SNDK")
    assert audit["field_level_provenance"] is False
    assert audit["provides_company_financials"] is True
    assert METRIC_AVAILABILITY["company_revenue"]["source_type"] == "company_reported"
    assert METRIC_AVAILABILITY["company_revenue"]["frequency"] == "event_driven"
    assert METRIC_AVAILABILITY["gross_margin"]["source_type"] == "company_reported"
    assert METRIC_AVAILABILITY["gross_margin"]["frequency"] == "event_driven"
    assert "period may be annual" in audit["notes"]


def test_company_coverage_does_not_overstate_unverified_companies():
    assert COMPANY_COVERAGE["MU"]["production_structured"] is True
    assert COMPANY_COVERAGE["SNDK"]["production_structured"] is True

    for ticker in ("000660.KS", "005930.KS", "285A.T"):
        assert COMPANY_COVERAGE[ticker]["production_structured"] is False
        assert COMPANY_COVERAGE[ticker]["confidence"] == "low"


def test_trendforce_is_public_news_not_a_memory_price_database():
    audit = SOURCE_AUDIT["trendforce_public_news"]

    assert audit["availability_classes"] == ("C",)
    assert audit["allowed_metric_families"] == ("news_direction",)
    assert audit["provides_exact_memory_pricing"] is False
    assert "not the licensed TrendForce price database" in audit["notes"]


def test_daily_brief_is_transformation_layer_not_structured_metric_source():
    audit = SOURCE_AUDIT["daily_brief"]

    assert audit["availability_classes"] == ("C",)
    assert audit["allowed_metric_families"] == ("news_direction",)
    assert audit["provides_product_specific_memory_fundamentals"] is False
    assert "underlying articles remain the facts" in audit["notes"]
    assert "generated_at is not an observation time" in audit["notes"]


def test_exact_dram_nand_hbm_and_storage_prices_are_unavailable():
    expected_exact_metrics = {
        "dram_spot_price",
        "dram_contract_price",
        "nand_spot_price",
        "nand_contract_price",
        "hbm_price",
        "enterprise_ssd_price",
        "client_ssd_price",
        "wafer_component_price",
        "dram_spot_price_mom",
        "dram_spot_price_yoy",
        "dram_contract_price_mom",
        "dram_contract_price_yoy",
        "nand_spot_price_mom",
        "nand_spot_price_yoy",
        "nand_contract_price_mom",
        "nand_contract_price_yoy",
        "hbm_price_mom",
        "hbm_price_yoy",
        "enterprise_ssd_price_mom",
        "enterprise_ssd_price_yoy",
        "client_ssd_price_mom",
        "client_ssd_price_yoy",
        "wafer_component_price_mom",
        "wafer_component_price_yoy",
    }
    assert EXACT_MEMORY_PRICE_METRICS == expected_exact_metrics
    for metric_id in expected_exact_metrics:
        audit = METRIC_AVAILABILITY[metric_id]
        assert audit["availability"] == "E"
        assert audit["source_type"] == "direct"
        assert audit["sources"] == ()

        record = build_metric_record(
            metric_id=metric_id,
            label=metric_id,
            value=None,
            source="unavailable",
            source_type=audit["source_type"],
            frequency=audit["frequency"],
            confidence="low",
            status="unavailable",
            notes=audit["notes"],
        )
        assert record["value"] is None
        assert validate_metric_record(record) == []


def test_news_can_only_supply_qualitative_memory_price_direction():
    for metric_id in ("dram_price_direction", "nand_price_direction", "hbm_price_direction"):
        audit = METRIC_AVAILABILITY[metric_id]
        assert audit["availability"] == "C"
        assert audit["source_type"] == "news_signal"
        assert audit["frequency"] == "event_driven"
        assert audit["sources"] == ("trendforce_public_news", "daily_brief")


def test_market_and_macro_data_are_proxies_when_used_for_memory_cycle():
    for metric_id in (
        "memory_company_equity_trend",
        "semiconductor_etf_trend",
        "semiconductor_etf_flow",
    ):
        audit = METRIC_AVAILABILITY[metric_id]
        assert audit["availability"] == "D"
        assert audit["source_type"] == "proxy"

    assert "A" in SOURCE_AUDIT["macro_and_factor_modules"]["availability_classes"]
    assert "D" in SOURCE_AUDIT["macro_and_factor_modules"]["availability_classes"]
    assert METRIC_AVAILABILITY["semiconductor_etf_flow"]["sources"] == ("etf_news_monitor",)
    assert METRIC_AVAILABILITY["margin_direction"]["availability"] == "E"
    assert METRIC_AVAILABILITY["margin_direction"]["sources"] == ()


def test_watchlist_ibkr_and_local_csv_are_not_industry_fundamental_sources():
    assert SOURCE_AUDIT["watchlist"]["configuration_only"] is True
    for source_name in ("watchlist", "ibkr", "local_csv"):
        audit = SOURCE_AUDIT[source_name]
        assert audit["provides_product_specific_memory_fundamentals"] is False
        assert audit["provides_exact_memory_pricing"] is False
    assert SOURCE_AUDIT["ibkr"]["availability_classes"] == ("A", "D", "E")
    assert SOURCE_AUDIT["ibkr"]["observation_time_conditional"] is True
    assert "equity_price" in SOURCE_AUDIT["ibkr"]["allowed_metric_families"]
    assert SOURCE_AUDIT["local_csv"]["approved_memory_source"] is False


@pytest.mark.parametrize("source", ["DRAM", "DRAM_portfolio.csv", "/tmp/DRAM_trades.csv"])
def test_dram_security_and_backtest_names_cannot_be_product_price_aliases(source):
    assert DISALLOWED_EXACT_PRICE_ALIASES == {
        "DRAM",
        "DRAM_portfolio.csv",
        "DRAM_trades.csv",
    }
    record = build_metric_record(
        metric_id="dram_spot_price",
        label="DRAM spot price",
        value=27.76,
        unit="USD",
        as_of="2026-07-12",
        retrieved_at="2026-07-13",
        source=source,
        source_type="direct",
        frequency="daily",
        confidence="high",
    )

    errors = validate_metric_record(record)

    assert "exact memory price levels or changes are unavailable in the current source audit" in errors
    assert "security or backtest aliases cannot be used as exact memory-price sources" in errors


def test_manual_valuation_assumptions_are_not_approved_observed_data():
    audit = SOURCE_AUDIT["mu_valuation_manual_assumptions"]

    assert audit["approved_memory_source"] is False
    assert audit["allowed_metric_families"] == ("user_scenario",)
    assert audit["provides_product_specific_memory_fundamentals"] is False
    assert audit["has_observation_time"] is False


def test_legacy_supply_chain_analyzer_is_not_production_coverage():
    audit = SOURCE_AUDIT["legacy_supply_chain_analyzer"]

    assert audit["production"] is False
    assert audit["tested"] is False
    assert audit["availability_classes"] == ("E",)
    assert audit["allowed_metric_families"] == ()
    assert audit["provides_product_specific_memory_fundamentals"] is False


def test_currently_unintegrated_company_reported_metrics_remain_unavailable():
    unavailable_company_metrics = {
        "dram_bit_supply_growth",
        "nand_bit_supply_growth",
        "wafer_starts_or_capacity",
        "capacity_utilization",
        "hbm_capacity",
        "manufacturer_inventory",
        "inventory_days",
        "free_cash_flow",
        "company_capex",
        "management_guidance",
        "dram_revenue",
        "nand_revenue",
        "hbm_revenue",
        "bit_shipment_growth",
        "asp_change",
        "production_growth",
        "supply_growth_guidance",
    }

    for metric_id in unavailable_company_metrics:
        audit = METRIC_AVAILABILITY[metric_id]
        assert audit["availability"] == "E", metric_id
        assert audit["source_type"] == "company_reported", metric_id
        assert audit["sources"] == (), metric_id


def test_known_e_metric_cannot_be_relabelled_direct_or_given_a_value():
    invalid = build_metric_record(
        metric_id="manufacturer_inventory",
        label="Manufacturer inventory",
        value=1,
        unit="USD",
        as_of="2026-06-30",
        retrieved_at="2026-07-13T00:00:00Z",
        source="Yahoo",
        source_type="direct",
        frequency="quarterly",
        confidence="medium",
    )
    valid = build_metric_record(
        metric_id="manufacturer_inventory",
        label="Manufacturer inventory",
        value=None,
        source="unavailable",
        source_type="company_reported",
        frequency="quarterly",
        confidence="low",
        status="unavailable",
        notes="No current verified filing adapter.",
    )

    errors = validate_metric_record(invalid)

    assert "source_type does not match the current metric audit" in errors
    assert "audited E metrics must use status=unavailable and value=None" in errors
    assert "audited E metrics must use source=unavailable" in errors
    assert validate_metric_record(valid) == []


def test_known_metric_frequency_is_bound_to_the_current_audit():
    record = build_metric_record(
        metric_id="manufacturer_inventory",
        label="Manufacturer inventory",
        value=None,
        source="unavailable",
        source_type="company_reported",
        frequency="daily",
        confidence="low",
        status="unavailable",
        notes="No current verified filing adapter.",
    )

    assert "frequency does not match the current metric audit" in validate_metric_record(record)


def test_unavailable_exact_metrics_have_separate_qualitative_news_signals():
    qualitative_signals = {
        "dram_price_direction",
        "nand_price_direction",
        "hbm_price_direction",
        "enterprise_ssd_price_direction",
        "client_ssd_price_direction",
        "wafer_component_price_direction",
        "dram_supply_direction",
        "nand_supply_direction",
        "hbm_capacity_direction",
        "advanced_packaging_capacity_direction",
        "manufacturer_expansion_plans",
        "production_cuts_or_supply_discipline",
        "ai_server_accelerator_demand",
        "hbm_demand",
        "channel_inventory",
        "customer_inventory",
        "management_guidance_direction",
    }

    for metric_id in qualitative_signals:
        audit = METRIC_AVAILABILITY[metric_id]
        assert audit["availability"] == "C", metric_id
        assert audit["source_type"] == "news_signal", metric_id
        assert audit["sources"], metric_id


def test_user_requested_atomic_metrics_keep_independent_provenance_slots():
    required_atomic_metrics = {
        "ai_server_accelerator_demand",
        "hbm_demand",
        "manufacturer_expansion_plans",
        "production_cuts_or_supply_discipline",
        "channel_inventory",
        "customer_inventory",
        "dram_revenue",
        "nand_revenue",
        "hbm_revenue",
        "inventory_qoq",
        "inventory_yoy",
        "bit_shipment_growth",
        "asp_change",
        "production_growth",
        "supply_growth_guidance",
    }

    assert required_atomic_metrics <= set(METRIC_AVAILABILITY)


def test_unavailable_cycle_phase_prevents_premature_numeric_scoring():
    audit = METRIC_AVAILABILITY["cycle_phase"]

    assert audit["availability"] == "E"
    assert audit["source_type"] == "proxy"
    assert audit["sources"] == ()
    assert "Do not calculate" in audit["notes"]
    for metric_id in (
        "pricing_strength",
        "demand_strength",
        "supply_discipline",
        "inventory_health",
        "capex_risk",
    ):
        assert METRIC_AVAILABILITY[metric_id]["availability"] == "E"
        assert METRIC_AVAILABILITY[metric_id]["sources"] == ()


def test_source_audit_has_no_memory_pricing_secret_or_configured_provider():
    audit = SOURCE_AUDIT["environment_and_secrets"]

    assert audit["availability_classes"] == ("E",)
    assert audit["configuration_only"] is True
    assert audit["allowed_metric_families"] == ()
    assert audit["provides_exact_memory_pricing"] is False


def test_source_audit_helpers_do_not_access_network_secrets_or_files(monkeypatch):
    import openai
    import os
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(os, "getenv", lambda *args, **kwargs: pytest.fail("real secrets must not be read"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("production files must not be read or written"))

    record = build_metric_record(
        metric_id="dram_spot_price",
        label="DRAM spot price",
        status="unavailable",
        notes=METRIC_AVAILABILITY["dram_spot_price"]["notes"],
    )

    assert record["status"] == "unavailable"
    assert record["value"] is None
