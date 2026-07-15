from copy import deepcopy

from fixtures.memory_cycle_mvp import (
    FIXTURE_EVALUATED_AT,
    FIXTURE_NOTICE,
    FIXTURE_RETRIEVED_AT,
    MEMORY_CYCLE_MVP_FIXTURES,
    get_memory_cycle_mvp_fixtures,
)
from services.memory_cycle_contract import REQUIRED_METRIC_FIELDS, validate_metric_record


def test_fixtures_are_adapter_built_contract_records():
    assert len(MEMORY_CYCLE_MVP_FIXTURES) == 21
    for metric in MEMORY_CYCLE_MVP_FIXTURES:
        assert tuple(metric) == REQUIRED_METRIC_FIELDS
        assert validate_metric_record(metric, evaluated_at=FIXTURE_EVALUATED_AT) == []


def test_fixtures_use_fixed_times_and_are_explicitly_demo_only():
    assert FIXTURE_EVALUATED_AT == "2025-02-15T12:00:00Z"
    assert FIXTURE_RETRIEVED_AT == "2025-02-15T10:00:00Z"
    assert "TEST/DEMO FIXTURE" in FIXTURE_NOTICE
    assert all(
        "test/demo" in f"{metric['source']} {metric['notes']}".casefold()
        for metric in MEMORY_CYCLE_MVP_FIXTURES
    )
    assert all("2026-07-15" not in repr(metric) for metric in MEMORY_CYCLE_MVP_FIXTURES)


def test_fixture_inventory_covers_each_requested_evidence_class():
    company = [metric for metric in MEMORY_CYCLE_MVP_FIXTURES if metric["source_type"] == "company_reported" and metric["status"] != "unavailable"]
    proxies = [metric for metric in MEMORY_CYCLE_MVP_FIXTURES if metric["source_type"] == "proxy"]
    news = [metric for metric in MEMORY_CYCLE_MVP_FIXTURES if metric["source_type"] == "news_signal"]
    unavailable = [metric for metric in MEMORY_CYCLE_MVP_FIXTURES if metric["status"] == "unavailable"]

    assert {metric["label"].split()[0] for metric in company} == {"MU", "SNDK"}
    assert {metric["metric_id"] for metric in company} == {"company_revenue", "gross_margin", "operating_margin"}
    assert len(proxies) == 4
    assert len(news) == 6
    assert {metric["metric_id"] for metric in unavailable} == {
        "dram_spot_price",
        "nand_contract_price",
        "hbm_price",
        "dram_bit_supply_growth",
        "capacity_utilization",
    }


def test_fixture_factory_returns_fresh_records_without_mutating_static_fixture():
    before = deepcopy(MEMORY_CYCLE_MVP_FIXTURES)
    first = get_memory_cycle_mvp_fixtures()
    second = get_memory_cycle_mvp_fixtures()

    first[0]["label"] = "changed"

    assert second[0]["label"] == "MU Revenue"
    assert MEMORY_CYCLE_MVP_FIXTURES == before


def test_fixture_module_has_no_external_runtime_dependencies():
    # The module's globals are enough to characterize its execution boundary:
    # adapter functions and immutable static values, with no clients or paths.
    module_names = {value.__class__.__module__.split(".")[0] for value in MEMORY_CYCLE_MVP_FIXTURES}
    assert module_names == {"builtins"}
    assert not any(key in repr(MEMORY_CYCLE_MVP_FIXTURES).casefold() for key in ("api_key", "secret", "localhost", "ibkr"))

