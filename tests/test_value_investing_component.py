"""UI regression tests for the Value Investing component."""

from copy import deepcopy

import pytest

from components import value_investing
from services.value_investing import build_value_investing_view_model, load_value_investing_snapshot
from test_fmp_financial_normalization import _raw
from test_value_investing_service import EVALUATED_AT, RETRIEVED_AT, _fetcher


class _Context:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def __enter__(self):
        self.events.append(("enter", self.name))
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.events.append(("exit", self.name))
        return False


def _spy(monkeypatch):
    events = []
    monkeypatch.setattr(value_investing.st, "subheader", lambda value: events.append(("subheader", value)))
    monkeypatch.setattr(value_investing.st, "caption", lambda value: events.append(("caption", value)))
    monkeypatch.setattr(value_investing.st, "info", lambda value: events.append(("info", value)))
    monkeypatch.setattr(value_investing.st, "warning", lambda value: events.append(("warning", value)))
    monkeypatch.setattr(value_investing.st, "metric", lambda *, label, value: events.append(("metric", label, value)))
    monkeypatch.setattr(
        value_investing.st, "container",
        lambda **kwargs: events.append(("container", kwargs)) or _Context(events, "container"),
    )
    return events


def _view(language="English", *, raw=None, evaluated_at=EVALUATED_AT):
    snapshot = load_value_investing_snapshot(
        "MU", fmp_json_fetcher=_fetcher(raw=raw),
        retrieved_at=RETRIEVED_AT, evaluated_at=evaluated_at,
    )
    return build_value_investing_view_model(snapshot, language=language)


def _metric_events(events):
    return {(event[1], event[2]) for event in events if event[0] == "metric"}


def test_component_rows_copy_sections_metrics_quality_and_do_not_mutate():
    view = _view()
    before = deepcopy(view)
    rows = value_investing.build_value_investing_component_rows(view)
    assert view == before
    assert rows["sections"] == view["sections"]
    assert rows["sections"] is not view["sections"]
    assert rows["data_quality"] == view["data_quality"]


@pytest.mark.parametrize("invalid", (None, [], "bad", 1))
def test_component_rows_handle_invalid_input(invalid):
    rows = value_investing.build_value_investing_component_rows(invalid)
    assert rows["sections"] == []
    assert rows["status"] == "error"


def test_render_shows_identity_source_currency_retrieval_and_separate_period_dates(monkeypatch):
    events = _spy(monkeypatch)
    value_investing.render_value_investing_dashboard(_view(), language="English")
    captions = [event[1] for event in events if event[0] == "caption"]
    assert any("MU | Micron Technology, Inc." in item for item in captions)
    assert any("Source: FMP" in item and "Currency: USD" in item for item in captions)
    assert any(f"Retrieved at: {RETRIEVED_AT}" in item for item in captions)
    assert any("TTM ended: 2026-03-31" in item for item in captions)
    assert any("Annual ended: 2025-12-31" in item for item in captions)


@pytest.mark.parametrize(
    ("label", "value"),
    (
        ("Revenue", "1,000.00 USD"),
        ("Gross Margin", "50.00%"),
        ("Inventory", "90.00 USD"),
        ("Free Cash Flow", "260.00 USD"),
        ("Net Debt", "-18.00 USD"),
        ("P/E", "10.00x"),
    ),
)
def test_values_have_one_explicit_unit_and_no_double_scaling(monkeypatch, label, value):
    events = _spy(monkeypatch)
    value_investing.render_value_investing_dashboard(_view(), language="English")
    assert (label, value) in _metric_events(events)


def test_metric_metadata_distinguishes_ttm_latest_balance_annual_and_current(monkeypatch):
    events = _spy(monkeypatch)
    value_investing.render_value_investing_dashboard(_view(), language="English")
    captions = [event[1] for event in events if event[0] == "caption"]
    assert any("Period: TTM | Data date: 2026-03-31" in item for item in captions)
    assert any("Period: Latest balance sheet | Data date: 2026-03-31" in item for item in captions)
    assert any("Period: Annual | Data date: 2025-12-31" in item for item in captions)
    assert any("Period: Current" in item for item in captions)


def test_reported_and_derived_evidence_labels_are_visible(monkeypatch):
    events = _spy(monkeypatch)
    value_investing.render_value_investing_dashboard(_view(), language="English")
    captions = [event[1] for event in events if event[0] == "caption"]
    assert any("Evidence: Reported" in item for item in captions)
    assert any("Evidence: Derived" in item for item in captions)


@pytest.mark.parametrize(
    ("language", "missing", "unavailable"),
    (
        ("中文", "数据缺失", "暂不可用"),
        ("English", "Missing", "Unavailable"),
        ("Español", "Faltante", "No disponible"),
        ("unknown", "Missing", "Unavailable"),
    ),
)
def test_missing_and_unavailable_are_localized_and_never_render_zero(monkeypatch, language, missing, unavailable):
    events = _spy(monkeypatch)
    view = _view(language)
    view["sections"][0]["metrics"][0].update(status="missing", normalized_value=None)
    view["sections"][0]["metrics"][1].update(status="unavailable", normalized_value=None)
    value_investing.render_value_investing_dashboard(view, language=language)
    metric_values = [event[2] for event in events if event[0] == "metric"]
    assert missing in metric_values
    assert unavailable in metric_values
    assert "0" not in metric_values


def test_real_zero_value_renders_as_zero(monkeypatch):
    events = _spy(monkeypatch)
    view = _view()
    metric = view["sections"][2]["metrics"][0]
    metric.update(normalized_value=0.0, normalized_unit="USD", status="ok")
    value_investing.render_value_investing_dashboard(view, language="English")
    assert (metric["label"], "0.00 USD") in _metric_events(events)


@pytest.mark.parametrize(
    ("language", "title", "quality", "stale"),
    (
        ("中文", "价值投资", "数据质量", "数据过期天数: 380"),
        ("English", "Value Investing", "Data Quality", "Days stale: 380"),
        ("Español", "Inversión en valor", "Calidad de los datos", "Días de antigüedad: 380"),
    ),
)
def test_three_languages_and_stale_days_render(monkeypatch, language, title, quality, stale):
    events = _spy(monkeypatch)
    view = _view(language, evaluated_at="2027-04-15T12:10:00+00:00")
    value_investing.render_value_investing_dashboard(view, language=language)
    assert ("subheader", title) in events
    assert ("subheader", quality) in events
    assert ("warning", stale) in events


def test_error_view_is_isolated_and_does_not_render_sensitive_details(monkeypatch):
    events = _spy(monkeypatch)
    view = build_value_investing_view_model({
        "ticker": "MU", "company_name": "MU", "source": "FMP", "retrieved_at": RETRIEVED_AT,
        "evaluated_at": EVALUATED_AT, "currency": None, "periods": {}, "metrics": {},
        "quality": {"errors": [{"code": "fetch_failed"}]}, "status": "error",
    }, language="English")
    value_investing.render_value_investing_dashboard(view, language="English")
    assert ("warning", "Financial data is incomplete.") in events
    serialized = str(events).casefold()
    assert "traceback" not in serialized
    assert "api_key" not in serialized
    assert "/users/" not in serialized


def test_component_does_not_modify_view_model_or_session_state(monkeypatch):
    events = _spy(monkeypatch)
    view = _view()
    before = deepcopy(view)
    value_investing.render_value_investing_dashboard(view, language="English")
    assert view == before
    assert events
