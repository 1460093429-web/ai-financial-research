import builtins
from copy import deepcopy
import os

import pytest

from components import memory_cycle
from fixtures.memory_cycle_mvp import FIXTURE_EVALUATED_AT, MEMORY_CYCLE_MVP_FIXTURES
from services.memory_cycle_view_model import build_memory_cycle_view_model


class _Context:
    def __init__(self, events, name="context"):
        self.events = events
        self.name = name

    def __enter__(self):
        self.events.append(("enter", self.name))
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.events.append(("exit", self.name))
        return False


class _Column(_Context):
    def metric(self, *, label, value):
        self.events.append(("column_metric", label, value))


def _install_streamlit_spy(monkeypatch):
    events = []
    monkeypatch.setattr(memory_cycle.st, "title", lambda value: events.append(("title", value)))
    monkeypatch.setattr(memory_cycle.st, "subheader", lambda value: events.append(("subheader", value)))
    monkeypatch.setattr(memory_cycle.st, "caption", lambda value: events.append(("caption", value)))
    monkeypatch.setattr(memory_cycle.st, "info", lambda value: events.append(("info", value)))
    monkeypatch.setattr(memory_cycle.st, "warning", lambda value: events.append(("warning", value)))
    monkeypatch.setattr(
        memory_cycle.st,
        "metric",
        lambda *, label, value: events.append(("metric", label, value)),
    )
    monkeypatch.setattr(
        memory_cycle.st,
        "container",
        lambda **kwargs: events.append(("container", kwargs)) or _Context(events, "container"),
    )
    monkeypatch.setattr(
        memory_cycle.st,
        "expander",
        lambda label, **kwargs: events.append(("expander", label, kwargs)) or _Context(events, "expander"),
    )
    monkeypatch.setattr(
        memory_cycle.st,
        "columns",
        lambda count: events.append(("columns", count)) or [_Column(events, f"column-{index}") for index in range(count)],
    )
    return events


def _view(language="en"):
    return build_memory_cycle_view_model(
        MEMORY_CYCLE_MVP_FIXTURES,
        evaluated_at=FIXTURE_EVALUATED_AT,
        language=language,
    )


def _metric(**overrides):
    metric = {
        "label": "Operating Margin",
        "display_value": "24",
        "unit": "%",
        "status": "ok",
        "confidence": "medium",
        "as_of": "2025-01-31",
        "source": "Reviewed fixture",
        "source_type": "company_reported",
        "is_fallback": False,
        "is_estimate": False,
        "staleness_days": 0,
        "badge": "",
        "notes": "Reviewed evidence.",
        "evidence_available": True,
    }
    metric.update(overrides)
    return metric


def test_component_rows_preserve_all_seven_sections_and_metric_order_without_mutation():
    view = _view("en")
    before = deepcopy(view)

    rows = memory_cycle.build_memory_cycle_component_rows(view)

    assert [section["section_id"] for section in rows["sections"]] == [
        "company_financials",
        "pricing_signals",
        "demand_signals",
        "supply_discipline",
        "inventory_health",
        "market_proxies",
        "unavailable_data",
    ]
    assert [item["label"] for item in rows["sections"][0]["metrics"]] == [
        "MU Revenue",
        "MU Gross Margin",
        "MU Operating Margin",
        "SNDK Revenue",
        "SNDK Gross Margin",
        "SNDK Operating Margin",
    ]
    assert view == before
    assert rows["sections"] is not view["sections"]


def test_component_rows_pass_quality_summary_warnings_and_latest_date():
    view = _view("en")

    rows = memory_cycle.build_memory_cycle_component_rows(view)

    assert rows["quality_summary"] == view["quality_summary"]
    assert rows["quality_summary"] is not view["quality_summary"]
    assert rows["warnings"] == view["warnings"]
    assert rows["latest_as_of"] == "2025-02-14"


@pytest.mark.parametrize("value", [None, "invalid", 1, [], set()])
def test_component_rows_handle_empty_or_non_dict_input(value):
    assert memory_cycle.build_memory_cycle_component_rows(value) == {
        "sections": [],
        "quality_summary": {},
        "warnings": [],
        "latest_as_of": None,
    }


def test_component_rows_safely_handle_missing_sections_metrics_and_non_dict_metrics():
    rows = memory_cycle.build_memory_cycle_component_rows(
        {"sections": [{"section_id": "a"}, {"section_id": "b", "metrics": [None, _metric()]}]}
    )

    assert rows["sections"][0]["metrics"] == []
    assert rows["sections"][1]["metrics"] == [_metric()]


def test_dashboard_renders_all_quality_summary_values_and_warnings(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_dashboard(_view("en"), language="en")

    summary = [event for event in events if event[0] == "column_metric"]
    assert summary == [
        ("column_metric", "Available metrics", 16),
        ("column_metric", "Missing metrics", 0),
        ("column_metric", "Stale metrics", 0),
        ("column_metric", "Unavailable metrics", 5),
        ("column_metric", "Proxy metrics", 4),
        ("column_metric", "News signals", 6),
        ("column_metric", "Most recent data date", "2025-02-14"),
    ]
    assert [event[1] for event in events if event[0] == "warning"][:3] == _view("en")["warnings"]


def test_normal_and_real_zero_values_render_with_units(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_metric(_metric(), language="en")
    memory_cycle.render_memory_cycle_metric(_metric(display_value="0"), language="en")

    values = [event[2] for event in events if event[0] == "metric"]
    assert values == ["24 %", "0 %"]


@pytest.mark.parametrize(
    ("language", "status", "expected"),
    [
        ("en", "missing", "Missing"),
        ("zh", "missing", "数据缺失"),
        ("es", "missing", "Faltante"),
        ("en", "unavailable", "Unavailable"),
        ("zh", "unavailable", "暂不可用"),
        ("es", "unavailable", "No disponible"),
    ],
)
def test_missing_and_unavailable_never_render_none_as_zero(monkeypatch, language, status, expected):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_metric(
        _metric(display_value=None, status=status, unit="USD millions"),
        language=language,
    )

    value = next(event[2] for event in events if event[0] == "metric")
    assert value == expected
    assert value != "0"


def test_stale_metric_displays_badge_days_confidence_source_and_date(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_metric(
        _metric(status="stale", staleness_days=12, confidence="low"),
        language="en",
    )

    captions = [event[1] for event in events if event[0] == "caption"]
    warnings = [event[1] for event in events if event[0] == "warning"]
    assert "Badge: Stale" in captions
    assert "Status: Stale | Confidence: low" in captions
    assert "Data date: 2025-01-31 | Source: Reviewed fixture" in captions
    assert "Source type: company_reported" in captions
    assert "Days stale: 12" in warnings


@pytest.mark.parametrize(
    ("overrides", "badge", "notice"),
    [
        ({"source_type": "proxy", "is_estimate": True}, "Proxy · Estimate", "market proxy"),
        ({"source_type": "news_signal"}, "News signal", "news signal"),
        ({"is_fallback": True}, "Fallback", None),
        ({"is_estimate": True}, "Estimate", None),
    ],
)
def test_special_badges_and_proxy_news_limitations_are_explicit(monkeypatch, overrides, badge, notice):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_metric(_metric(**overrides), language="en")

    assert ("caption", f"Badge: {badge}") in events
    info = [event[1] for event in events if event[0] == "info"]
    if notice:
        assert any(notice in message for message in info)
    else:
        assert info == []


def test_incomplete_evidence_is_warned_and_missing_notes_are_safe(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_metric(
        _metric(evidence_available=False, notes=None),
        language="zh",
    )

    assert ("warning", "缺少完整证据") in events
    assert ("expander", "备注", {"expanded": False}) in events
    assert ("caption", "N/A") in events


def test_non_dict_metric_and_missing_quality_summary_do_not_crash(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)
    view = {
        "sections": [{"section_id": "company_financials", "metrics": [_metric()]}],
        "warnings": [],
    }

    memory_cycle.render_memory_cycle_metric(None, language="en")
    memory_cycle.render_memory_cycle_dashboard(view, language="en")

    assert ("metric", "N/A", "Missing") in events
    summary_values = [event[2] for event in events if event[0] == "column_metric"]
    assert summary_values == ["N/A"] * 7


@pytest.mark.parametrize(
    ("language", "title", "quality", "source"),
    [
        ("zh", "存储周期监控", "数据质量", "来源"),
        ("en", "Memory Cycle Monitor", "Data quality", "Source"),
        ("es", "Monitor del ciclo de memoria", "Calidad de los datos", "Fuente"),
    ],
)
def test_dashboard_and_card_labels_are_localized(monkeypatch, language, title, quality, source):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_dashboard(_view(language), language=language)

    assert events[0] == ("title", title)
    assert ("subheader", quality) in events
    assert any(event[0] == "caption" and event[1].startswith(f"{source}:") is False and f"{source}:" in event[1] for event in events)


def test_unknown_language_falls_back_to_english(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_dashboard(_view("en"), language="fr")

    assert events[0] == ("title", "Memory Cycle Monitor")
    assert ("subheader", "Data quality") in events


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("zh", "暂无可展示的存储周期数据。"),
        ("en", "No memory-cycle data is available."),
        ("es", "No hay datos disponibles del ciclo de memoria."),
    ],
)
def test_empty_dashboard_displays_localized_message(monkeypatch, language, message):
    events = _install_streamlit_spy(monkeypatch)

    memory_cycle.render_memory_cycle_dashboard(None, language=language)

    assert ("info", message) in events
    assert not any(event[0] == "columns" for event in events)


def test_rendering_call_order_is_stable(monkeypatch):
    events = _install_streamlit_spy(monkeypatch)
    view = _view("en")

    memory_cycle.render_memory_cycle_dashboard(view, language="en")

    event_names = [event[0] for event in events]
    assert event_names[:4] == ["title", "subheader", "columns", "column_metric"]
    rendered_sections = [event[1] for event in events if event[0] == "subheader"][1:]
    assert rendered_sections == [section["title"] for section in view["sections"]]
    rendered_metrics = [event[1] for event in events if event[0] == "metric"]
    expected_metrics = [metric["label"] for section in view["sections"] for metric in section["metrics"]]
    assert rendered_metrics == expected_metrics


def test_rendering_is_isolated_from_external_clients_secrets_environment_and_files(monkeypatch):
    import openai
    import requests
    import yfinance

    events = _install_streamlit_spy(monkeypatch)
    fail = lambda *args, **kwargs: pytest.fail("external access must not run")
    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(yfinance, "Ticker", fail)
    monkeypatch.setattr(openai, "OpenAI", fail)
    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(os, "getenv", fail)

    memory_cycle.render_memory_cycle_dashboard(_view("en"), language="en")

    assert events
    forbidden = {"requests", "yfinance", "openai", "ib_insync", "dashboard", "os", "environ"}
    assert forbidden.isdisjoint(memory_cycle.__dict__)


def test_component_does_not_add_score_or_cycle_phase():
    rows = memory_cycle.build_memory_cycle_component_rows(_view("en"))

    assert "score" not in rows
    assert "cycle_phase" not in rows
    assert "phase" not in rows
