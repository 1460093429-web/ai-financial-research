import builtins
from copy import deepcopy
from datetime import date
import os

import pytest

from demos import memory_cycle_demo
from fixtures.memory_cycle_mvp import MEMORY_CYCLE_MVP_FIXTURES


def _statuses(view_model):
    return [metric["status"] for section in view_model["sections"] for metric in section["metrics"]]


def _source_types(view_model):
    return [metric["source_type"] for section in view_model["sections"] for metric in section["metrics"]]


def _install_streamlit_spy(monkeypatch, *, language="English", scenario="Full fixture"):
    events = []
    monkeypatch.setattr(
        memory_cycle_demo.st,
        "set_page_config",
        lambda **kwargs: events.append(("set_page_config", kwargs)),
    )
    monkeypatch.setattr(memory_cycle_demo.st, "title", lambda value: events.append(("title", value)))
    monkeypatch.setattr(memory_cycle_demo.st, "warning", lambda value: events.append(("warning", value)))
    monkeypatch.setattr(memory_cycle_demo.st, "caption", lambda value: events.append(("caption", value)))
    monkeypatch.setattr(memory_cycle_demo.st, "divider", lambda: events.append(("divider",)))

    def selectbox(label, options, **kwargs):
        result = language if tuple(options) == memory_cycle_demo.LANGUAGE_OPTIONS else scenario
        events.append(("selectbox", label, tuple(options), kwargs, result))
        return result

    monkeypatch.setattr(memory_cycle_demo.st, "selectbox", selectbox)
    return events


def test_demo_module_imports_without_starting_streamlit():
    assert callable(memory_cycle_demo.render_memory_cycle_demo)
    assert callable(memory_cycle_demo.build_demo_scenario)


def test_scenario_order_is_stable():
    assert memory_cycle_demo.SCENARIO_OPTIONS == (
        "Full fixture",
        "Empty data",
        "Missing-heavy",
        "Stale-heavy",
        "Unavailable-heavy",
        "Proxy/news-signal focused",
    )


def test_full_fixture_scenario_returns_all_records():
    demo = memory_cycle_demo.build_demo_scenario("Full fixture")

    assert len(demo["metrics"]) == 21
    assert demo["evaluated_at"] == memory_cycle_demo.DEMO_EVALUATED_AT
    assert [metric["status"] for metric in demo["metrics"]].count("stale") == 16


def test_empty_data_scenario_returns_empty_records():
    assert memory_cycle_demo.build_demo_scenario("Empty data")["metrics"] == []


def test_missing_heavy_scenario_contains_a_majority_of_missing_records():
    view = memory_cycle_demo.build_demo_view_model("Missing-heavy", language="en")

    statuses = _statuses(view)
    assert statuses.count("missing") == 12
    assert statuses.count("missing") > len(statuses) / 2


def test_stale_heavy_scenario_uses_fixed_time_and_contains_stale_records():
    demo = memory_cycle_demo.build_demo_scenario("Stale-heavy")
    view = memory_cycle_demo.build_demo_view_model("Stale-heavy", language="en")

    assert demo["evaluated_at"] == "2025-08-01T12:00:00Z"
    assert _statuses(view).count("stale") == 16
    assert view["evaluated_at"] == memory_cycle_demo.DEMO_EVALUATED_AT
    for metric in demo["metrics"]:
        if metric["status"] == "stale":
            expected = date.fromisoformat("2025-08-01") - date.fromisoformat(metric["as_of"][:10])
            assert metric["staleness_days"] == expected.days


def test_unavailable_heavy_scenario_contains_only_unavailable_records():
    view = memory_cycle_demo.build_demo_view_model("Unavailable-heavy", language="en")

    assert _statuses(view) == ["unavailable"] * 5


def test_proxy_news_focused_scenario_contains_both_source_types():
    view = memory_cycle_demo.build_demo_view_model(
        "Proxy/news-signal focused",
        language="en",
    )

    source_types = _source_types(view)
    assert source_types == ["news_signal"] * 6 + ["proxy"] * 4


def test_scenarios_do_not_modify_original_fixture():
    before = deepcopy(MEMORY_CYCLE_MVP_FIXTURES)

    for scenario in memory_cycle_demo.SCENARIO_OPTIONS:
        memory_cycle_demo.build_demo_scenario(scenario)

    assert MEMORY_CYCLE_MVP_FIXTURES == before


def test_each_scenario_call_returns_fresh_objects():
    first = memory_cycle_demo.build_demo_scenario("Full fixture")
    second = memory_cycle_demo.build_demo_scenario("Full fixture")

    assert first is not second
    assert first["metrics"] is not second["metrics"]
    assert all(left is not right for left, right in zip(first["metrics"], second["metrics"]))


def test_unknown_scenario_safely_falls_back_to_full_fixture():
    demo = memory_cycle_demo.build_demo_scenario("unknown")

    assert demo["scenario"] == "Full fixture"
    assert len(demo["metrics"]) == 21


@pytest.mark.parametrize(
    ("language", "expected"),
    [("中文", "zh"), ("English", "en"), ("Español", "es"), ("zh", "zh"), ("en", "en"), ("es", "es")],
)
def test_supported_languages_are_passed_to_view_model(language, expected):
    view = memory_cycle_demo.build_demo_view_model("Full fixture", language=language)

    assert view["language"] == expected


def test_unknown_language_safely_falls_back_to_english():
    view = memory_cycle_demo.build_demo_view_model("Full fixture", language="fr")

    assert view["language"] == "en"
    assert view["sections"][0]["title"] == "Company Financials"


def test_demo_calls_existing_component_renderer_with_selected_language(monkeypatch):
    events = _install_streamlit_spy(
        monkeypatch,
        language="Español",
        scenario="Proxy/news-signal focused",
    )
    rendered = []
    monkeypatch.setattr(
        memory_cycle_demo,
        "render_memory_cycle_dashboard",
        lambda view_model, *, language: rendered.append((view_model, language)),
    )

    memory_cycle_demo.render_memory_cycle_demo()

    assert rendered[0][1] == "es"
    assert set(_source_types(rendered[0][0])) == {"proxy", "news_signal"}
    assert events[0][0] == "set_page_config"


def test_demo_shows_static_notice_fixed_time_and_required_footer(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)
    monkeypatch.setattr(memory_cycle_demo, "render_memory_cycle_dashboard", lambda *args, **kwargs: None)

    memory_cycle_demo.render_memory_cycle_demo()

    assert ("title", "Memory Cycle Static Demo") in events
    assert any(event[0] == "warning" and "static test data" in event[1] for event in events)
    captions = [event[1] for event in events if event[0] == "caption"]
    assert "Fixture data date: 2025-01-31 – 2025-02-14" in captions
    assert f"Fixed evaluated_at: {memory_cycle_demo.DEMO_EVALUATED_AT}" in captions
    assert "Demo / test source: fixtures/memory_cycle_mvp.py" in captions
    assert "No real data is fetched." in captions
    assert captions[-3:] == [
        "This is static demo data.",
        "No real market data is being fetched.",
        "No cycle score or phase is calculated.",
    ]


@pytest.mark.parametrize(
    ("language", "warning"),
    [
        ("中文", "这是静态测试数据，不代表当前市场或最新财报。"),
        ("English", "This demo uses static test data and does not represent current market conditions or the latest filings."),
        ("Español", "Esta demostración utiliza datos de prueba estáticos y no representa el mercado actual ni los últimos informes."),
    ],
)
def test_static_data_warning_is_prominent_in_all_languages(monkeypatch, language, warning):
    events = _install_streamlit_spy(monkeypatch, language=language)
    monkeypatch.setattr(memory_cycle_demo, "render_memory_cycle_dashboard", lambda *args, **kwargs: None)

    memory_cycle_demo.render_memory_cycle_demo()

    assert ("warning", warning) in events


def test_demo_copy_makes_no_realtime_or_latest_data_claim(monkeypatch):
    events = _install_streamlit_spy(monkeypatch, language="中文")
    monkeypatch.setattr(memory_cycle_demo, "render_memory_cycle_dashboard", lambda *args, **kwargs: None)

    memory_cycle_demo.render_memory_cycle_demo()

    rendered_copy = " ".join(str(part) for event in events for part in event[1:])
    assert "实时" not in rendered_copy
    assert "最新数据" not in rendered_copy


def test_fixture_dates_remain_unchanged():
    dates = {metric["as_of"] for metric in MEMORY_CYCLE_MVP_FIXTURES if metric.get("as_of")}

    assert min(dates) == "2025-01-31"
    assert max(dates) == "2025-02-14"
    assert all(not value.startswith("2026") for value in dates)


def test_full_fixture_stale_cards_include_status_and_days(monkeypatch):
    _install_streamlit_spy(monkeypatch)
    rendered = []
    monkeypatch.setattr(
        memory_cycle_demo,
        "render_memory_cycle_dashboard",
        lambda view_model, *, language: rendered.append(view_model),
    )

    memory_cycle_demo.render_memory_cycle_demo()

    stale = [
        metric
        for section in rendered[0]["sections"]
        for metric in section["metrics"]
        if metric["status"] == "stale"
    ]
    assert len(stale) == 16
    assert all(isinstance(metric["staleness_days"], int) and metric["staleness_days"] > 0 for metric in stale)


def test_demo_does_not_copy_lower_level_component_renderers():
    assert "render_memory_cycle_metric" not in memory_cycle_demo.__dict__
    assert "render_memory_cycle_section" not in memory_cycle_demo.__dict__
    assert "build_memory_cycle_component_rows" not in memory_cycle_demo.__dict__


def test_demo_is_isolated_from_external_clients_state_environment_and_files(monkeypatch):
    import openai
    import requests
    import yfinance

    events = _install_streamlit_spy(monkeypatch)
    fail = lambda *args, **kwargs: pytest.fail("external or filesystem access must not run")
    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(yfinance, "Ticker", fail)
    monkeypatch.setattr(openai, "OpenAI", fail)
    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(os, "getenv", fail)
    monkeypatch.setattr(memory_cycle_demo, "render_memory_cycle_dashboard", lambda *args, **kwargs: None)

    memory_cycle_demo.render_memory_cycle_demo()

    assert events
    forbidden = {
        "requests",
        "yfinance",
        "openai",
        "ib_insync",
        "dashboard",
        "providers",
        "session_state",
        "cache",
        "secrets",
        "os",
        "environ",
    }
    assert forbidden.isdisjoint(memory_cycle_demo.__dict__)


def test_demo_uses_no_hidden_current_time_or_cycle_result():
    view = memory_cycle_demo.build_demo_view_model("Stale-heavy", language="en")

    time_names = set(memory_cycle_demo._fixed_staleness_days.__code__.co_names)
    assert {"today", "now", "utcnow"}.isdisjoint(time_names)
    assert "score" not in view
    assert "cycle_phase" not in view
    assert "phase" not in view
