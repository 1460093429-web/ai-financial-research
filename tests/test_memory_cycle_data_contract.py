import ast
import builtins
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect

import pytest

import services.memory_cycle_contract as memory_cycle_contract
from services.memory_cycle_contract import (
    CONFIDENCE_LEVELS,
    FREQUENCIES,
    METRIC_STATUSES,
    NEWS_SIGNAL_VALUES,
    REQUIRED_METRIC_FIELDS,
    SOURCE_TYPES,
    STALE_AFTER_DAYS,
    build_metric_record,
    calculate_staleness_days,
    derive_metric_status,
    is_metric_record_valid,
    validate_metric_record,
)


def _valid_record(**overrides):
    values = {
        "metric_id": "mu_gross_margin",
        "label": "Micron gross margin",
        "value": 36.5,
        "unit": "%",
        "as_of": "2026-06-30",
        "retrieved_at": "2026-07-10T12:00:00Z",
        "source": "Micron quarterly report via FMP",
        "source_type": "company_reported",
        "frequency": "quarterly",
        "is_fallback": False,
        "is_estimate": False,
        "confidence": "medium",
        "notes": "Fiscal period and transport source are retained separately.",
    }
    values.update(overrides)
    return build_metric_record(**values)


def test_metric_contract_has_all_required_fields_and_no_extras():
    record = _valid_record()

    assert tuple(record) == REQUIRED_METRIC_FIELDS
    assert set(record) == set(REQUIRED_METRIC_FIELDS)
    assert validate_metric_record(record) == []


def test_missing_value_remains_none_and_never_becomes_zero():
    record = build_metric_record(
        metric_id="dram_spot_price",
        label="DRAM spot price",
        value=None,
        source="unavailable",
        source_type="direct",
        frequency="daily",
        status="unavailable",
        notes="No authorized structured source.",
    )

    assert record["value"] is None
    assert record["status"] == "unavailable"
    assert is_metric_record_valid(record)


def test_numeric_zero_is_preserved_as_valid_data_not_treated_as_missing():
    record = _valid_record(value=0)

    assert record["value"] == 0
    assert record["value"] is not False
    assert record["status"] == "ok"
    assert validate_metric_record(record) == []


@pytest.mark.parametrize(
    "invalid_value",
    [float("nan"), float("inf"), float("-inf"), "", "   ", False, [], {}],
)
def test_invalid_or_empty_values_cannot_be_valid_observations(invalid_value):
    record = _valid_record(value=invalid_value)

    assert record["status"] == "missing"
    assert any("value=None" in error for error in validate_metric_record(record))


def test_observation_and_retrieval_times_remain_separate():
    record = _valid_record(
        as_of="2026-03-31T00:00:00Z",
        retrieved_at="2026-04-15T18:30:00Z",
    )

    assert record["as_of"] == "2026-03-31T00:00:00Z"
    assert record["retrieved_at"] == "2026-04-15T18:30:00Z"
    assert record["as_of"] != record["retrieved_at"]
    assert record["staleness_days"] == 15


@pytest.mark.parametrize(
    ("field", "allowed", "invalid"),
    [
        ("source_type", SOURCE_TYPES, "model_output"),
        ("frequency", FREQUENCIES, "realtime"),
        ("confidence", CONFIDENCE_LEVELS, "certain"),
        ("status", METRIC_STATUSES, "live"),
    ],
)
def test_contract_rejects_values_outside_each_enum(field, allowed, invalid):
    record = _valid_record(**{field: invalid})

    assert invalid not in allowed
    assert any(field in error for error in validate_metric_record(record))


def test_proxy_requires_estimate_flag_or_explanatory_notes():
    unmarked = _valid_record(
        source_type="proxy",
        is_estimate=False,
        notes=None,
    )
    marked_estimate = _valid_record(
        source_type="proxy",
        is_estimate=True,
        notes=None,
    )
    explained_proxy = _valid_record(
        source_type="proxy",
        is_estimate=False,
        notes="MU share price is a market proxy, not a DRAM product price.",
    )

    assert "proxy metrics require is_estimate=True or explanatory notes" in validate_metric_record(unmarked)
    assert validate_metric_record(marked_estimate) == []
    assert validate_metric_record(explained_proxy) == []


@pytest.mark.parametrize("precise_value", [4.25, "$4.25", "up 12.3%", "4.25 USD"])
def test_news_signal_accepts_direction_but_rejects_precise_numeric_value(precise_value):
    direction = _valid_record(
        metric_id="dram_price_direction",
        label="DRAM price direction",
        value="improving",
        unit=None,
        source="TrendForce public news",
        source_type="news_signal",
        frequency="event_driven",
        notes="Citation: article URL; method: qualitative direction extraction; HBM3E/DDR5 context allowed here.",
    )
    fabricated_price = _valid_record(
        metric_id="dram_price_direction",
        label="DRAM price direction",
        value=precise_value,
        unit="USD",
        source="TrendForce public news",
        source_type="news_signal",
        frequency="event_driven",
        notes="Citation: article URL; method: direction extraction.",
    )

    assert validate_metric_record(direction) == []
    assert any("canonical qualitative label" in error for error in validate_metric_record(fabricated_price))


def test_news_signal_requires_no_unit_named_source_and_evidence_notes():
    assert "improving" in NEWS_SIGNAL_VALUES
    record = _valid_record(
        metric_id="dram_price_direction",
        label="DRAM price direction",
        value="improving",
        unit="USD",
        source="uncited",
        source_type="news_signal",
        frequency="event_driven",
        notes=None,
    )

    errors = validate_metric_record(record)

    assert "news signal values must use unit=None" in errors
    assert "news signals require citation and extraction-method notes" in errors
    assert "news signals require a named evidence source" in errors

    incomplete_notes = _valid_record(
        metric_id="dram_price_direction",
        label="DRAM price direction",
        value="stable",
        unit=None,
        source="TrendForce public news",
        source_type="news_signal",
        frequency="event_driven",
        notes="Qualitative evidence exists but has no structured markers.",
    )
    assert "news signals require citation and extraction-method notes" in validate_metric_record(incomplete_notes)


@pytest.mark.parametrize("frequency", sorted(FREQUENCIES))
def test_stale_thresholds_use_observation_age_at_injected_reference(frequency):
    threshold = STALE_AFTER_DAYS[frequency]
    observation = datetime(2026, 1, 1, tzinfo=timezone.utc)
    at_limit = observation + timedelta(days=threshold)
    beyond_limit = observation + timedelta(days=threshold + 1)
    exactly_at_limit = derive_metric_status(
        1,
        as_of=observation,
        retrieved_at=at_limit,
        frequency=frequency,
    )
    over_limit = derive_metric_status(
        1,
        as_of=observation,
        retrieved_at=beyond_limit,
        frequency=frequency,
    )

    assert exactly_at_limit == "ok"
    assert over_limit == "stale"


@pytest.mark.parametrize(
    ("frequency", "as_of", "retrieved_at", "expected_days", "expected_status"),
    [
        ("daily", "2026-07-01", "2026-07-04", 3, "ok"),
        ("daily", "2026-07-01", "2026-07-05", 4, "stale"),
        ("weekly", "2026-06-01", "2026-06-16", 15, "stale"),
        ("monthly", "2026-01-01", "2026-02-16", 46, "stale"),
        ("quarterly", "2026-01-01", "2026-05-17", 136, "stale"),
        ("event_driven", "2026-01-01", "2026-02-01", 31, "stale"),
    ],
)
def test_staleness_and_status_are_deterministic(
    frequency,
    as_of,
    retrieved_at,
    expected_days,
    expected_status,
):
    assert calculate_staleness_days(as_of, retrieved_at) == expected_days
    assert derive_metric_status(
        "signal",
        as_of=as_of,
        retrieved_at=retrieved_at,
        frequency=frequency,
    ) == expected_status


def test_old_fallback_remains_stale_and_fallback_flag_is_preserved():
    record = _valid_record(
        value=105.0,
        as_of="2026-07-01",
        retrieved_at="2026-07-10",
        source_type="proxy",
        frequency="daily",
        is_fallback=True,
        is_estimate=True,
        notes="Fallback equity close; not a memory product price.",
    )

    assert record["status"] == "stale"
    assert record["is_fallback"] is True
    assert validate_metric_record(record) == []


def test_injected_evaluation_time_ages_cached_observation_without_rewriting_retrieval():
    record = _valid_record(
        value=105.0,
        as_of="2026-07-01T00:00:00Z",
        retrieved_at="2026-07-02T00:00:00Z",
        frequency="daily",
        evaluated_at="2026-07-10T00:00:00Z",
    )

    assert record["retrieved_at"] == "2026-07-02T00:00:00Z"
    assert record["staleness_days"] == 9
    assert record["status"] == "stale"
    assert validate_metric_record(record, evaluated_at="2026-07-10T00:00:00Z") == []


def test_evaluation_time_cannot_precede_original_retrieval():
    record = _valid_record(
        as_of="2026-07-01",
        retrieved_at="2026-07-05",
        frequency="daily",
        evaluated_at="2026-07-04",
    )

    assert record["staleness_days"] is None
    assert record["status"] == "missing"
    assert "evaluated_at must not precede retrieved_at" in validate_metric_record(
        record,
        evaluated_at="2026-07-04",
    )


def test_evaluation_order_is_validated_even_for_unavailable_null_record():
    record = build_metric_record(
        metric_id="inventory_days",
        label="Inventory days",
        value=None,
        retrieved_at="2026-07-05",
        source="unavailable",
        source_type="company_reported",
        frequency="quarterly",
        status="unavailable",
        notes="No verified inputs.",
    )

    errors = validate_metric_record(record, evaluated_at="2026-07-04")

    assert "evaluated_at must not precede retrieved_at" in errors


def test_unavailable_record_without_retrieval_remains_valid_with_batch_evaluation_time():
    record = build_metric_record(
        metric_id="inventory_days",
        label="Inventory days",
        value=None,
        source="unavailable",
        source_type="company_reported",
        frequency="quarterly",
        status="unavailable",
        notes="No verified inputs.",
    )

    assert validate_metric_record(record, evaluated_at="2026-07-13T00:00:00Z") == []


def test_explicit_status_cannot_bypass_stale_rules():
    forced_ok = _valid_record(
        as_of="2026-01-01",
        retrieved_at="2026-07-01",
        frequency="daily",
        status="ok",
    )
    forced_stale = _valid_record(
        as_of="2026-07-01",
        retrieved_at="2026-07-02",
        frequency="daily",
        status="stale",
    )

    assert "ok status is inconsistent with staleness_days" in validate_metric_record(forced_ok)
    assert "stale status is inconsistent with staleness_days" in validate_metric_record(forced_stale)


@pytest.mark.parametrize("tampered_days", [1, 999])
def test_staleness_must_match_observation_age_at_retrieval(tampered_days):
    record = _valid_record(as_of="2026-07-01", retrieved_at="2026-07-10")
    record["staleness_days"] = tampered_days
    record["status"] = "stale" if tampered_days > STALE_AFTER_DAYS["quarterly"] else "ok"

    assert "staleness_days does not match the retrieval time" in validate_metric_record(record)


@pytest.mark.parametrize(
    ("as_of", "retrieved_at"),
    [
        (None, "2026-07-10"),
        ("not-a-date", "2026-07-10"),
        ("2026-07-11", "2026-07-10"),
    ],
)
def test_missing_invalid_or_future_observation_cannot_be_ok(as_of, retrieved_at):
    assert derive_metric_status(
        1,
        as_of=as_of,
        retrieved_at=retrieved_at,
        frequency="daily",
    ) == "missing"


@pytest.mark.parametrize(
    ("field", "invalid", "expected_error"),
    [
        ("as_of", "not-a-date", "as_of must be an ISO date/time string or None"),
        ("retrieved_at", "not-a-date", "retrieved_at must be an ISO date/time string or None"),
        ("as_of", "2026-07-01T12:00:00", "as_of must be an ISO date/time string or None"),
        ("retrieved_at", "2026-07-01T12:00:00", "retrieved_at must be an ISO date/time string or None"),
        ("as_of", datetime(2026, 7, 1, tzinfo=timezone.utc), "as_of must be an ISO date/time string or None"),
    ],
)
def test_stored_timestamps_must_be_normalized_iso_strings(field, invalid, expected_error):
    record = _valid_record()
    record[field] = invalid
    record["status"] = "missing"
    record["value"] = None
    record["staleness_days"] = None

    assert expected_error in validate_metric_record(record)


def test_frequency_and_provenance_flags_are_retained_verbatim():
    record = _valid_record(
        frequency="event_driven",
        source="TrendForce public news",
        source_type="news_signal",
        value="stable",
        is_fallback=True,
        is_estimate=True,
        confidence="low",
    )

    assert record["frequency"] == "event_driven"
    assert record["source"] == "TrendForce public news"
    assert record["source_type"] == "news_signal"
    assert record["is_fallback"] is True
    assert record["is_estimate"] is True
    assert record["confidence"] == "low"


def test_builder_returns_fresh_record_without_mutating_caller_values():
    overrides = {
        "notes": "Filing evidence retained.",
        "source": "Company filing",
    }
    before = deepcopy(overrides)

    first = _valid_record(**overrides)
    second = _valid_record(notes="second")

    assert overrides == before
    assert first is not second
    assert first["notes"] == "Filing evidence retained."


def test_validator_handles_non_mapping_and_missing_fields_safely():
    assert validate_metric_record(None) == ["metric must be a dictionary"]
    errors = validate_metric_record({"metric_id": "only-one-field"})
    assert len(errors) == len(REQUIRED_METRIC_FIELDS) - 1
    assert "missing required field: value" in errors


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("source_type", []),
        ("frequency", {}),
        ("confidence", []),
        ("status", {}),
    ],
)
def test_validator_returns_errors_instead_of_raising_for_unhashable_enums(field, invalid):
    record = _valid_record()
    record[field] = invalid

    errors = validate_metric_record(record)

    assert any(field in error for error in errors)


def test_contract_module_has_only_pure_standard_library_imports_and_no_io_calls():
    tree = ast.parse(inspect.getsource(memory_cycle_contract))
    allowed_import_roots = {"datetime", "math", "numbers", "typing"}
    forbidden_calls = {
        "open", "__import__", "eval", "exec", "getenv", "load_dotenv",
        "read_text", "read_bytes", "write_text", "write_bytes",
    }
    import_roots = set()
    called_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert import_roots == allowed_import_roots
    assert called_names.isdisjoint(forbidden_calls)
    assert not any(
        name in memory_cycle_contract.__dict__
        for name in ("requests", "yfinance", "openai", "streamlit", "dashboard", "config")
    )


def test_contract_helpers_do_not_access_network_secrets_or_files(monkeypatch):
    import openai
    import os
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(os, "getenv", lambda *args, **kwargs: pytest.fail("real secrets must not be read"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("production files must not be read or written"))

    record = _valid_record()

    assert calculate_staleness_days(record["as_of"], record["retrieved_at"]) == 10
    assert validate_metric_record(record) == []
