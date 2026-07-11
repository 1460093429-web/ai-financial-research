import inspect

import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()


class MarkdownRecorder:
    def __init__(self):
        self.calls = []

    def markdown(self, body, **kwargs):
        self.calls.append((body, kwargs))


class MetricRecorder:
    def __init__(self):
        self.calls = []

    def metric(self, *args):
        self.calls.append(args)


@pytest.fixture
def forbid_external_access(monkeypatch):
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: pytest.fail("OpenAI must not run"))


def test_component_function_signatures_are_characterized():
    assert str(inspect.signature(dashboard.render_snapshot_card)) == "(container, snapshot)"
    assert str(inspect.signature(dashboard.render_metric_row)) == "(metrics)"


@pytest.mark.parametrize(
    ("language", "expected_labels"),
    [
        ("English", ("Source", "today", "Market cap", "Revenue", "Net margin")),
        ("中文", ("来源", "今日", "市值", "营收", "净利率")),
        ("Español", ("Fuente", "hoy", "Capitalización", "Ingresos", "Margen neto")),
    ],
)
def test_snapshot_card_preserves_html_semantics_and_language_labels(
    monkeypatch, forbid_external_access, language, expected_labels
):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": language})
    container = MarkdownRecorder()
    snapshot = {
        "ticker": "NVDA",
        "name": "NVIDIA",
        "source": "test-source",
        "price": 123.456,
        "change_pct": 1.25,
        "market_cap": 1_500_000,
        "revenue": 2_500_000,
        "net_margin": 0.125,
    }

    result = dashboard.render_snapshot_card(container, snapshot)

    assert result is None
    assert len(container.calls) == 1
    body, kwargs = container.calls[0]
    assert kwargs == {"unsafe_allow_html": True}
    assert '<div class="stock-card">' in body
    assert '<div class="ticker">NVDA</div>' in body
    assert '<div class="company">NVIDIA</div>' in body
    assert '<div class="price">$123.46</div>' in body
    assert 'style="color:#22c55e">+1.25%' in body
    assert "$1.5M" in body
    assert "$2.5M" in body
    assert "12.5%" in body
    for label in expected_labels:
        assert label in body


def test_snapshot_card_preserves_missing_values_and_negative_color(monkeypatch, forbid_external_access):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "English"})
    container = MarkdownRecorder()
    snapshot = {
        "ticker": "MU",
        "name": "Micron",
        "source": "unavailable",
        "price": None,
        "change_pct": -2.5,
        "market_cap": None,
        "revenue": None,
        "net_margin": None,
    }

    dashboard.render_snapshot_card(container, snapshot)

    body, _ = container.calls[0]
    assert 'style="color:#ef4444">-2.50%' in body
    assert body.count("N/A") == 4


def test_metric_row_preserves_streamlit_call_order_and_delta_defaults(monkeypatch, forbid_external_access):
    columns = [MetricRecorder(), MetricRecorder(), MetricRecorder()]
    column_calls = []

    def fake_columns(count):
        column_calls.append(count)
        return columns

    monkeypatch.setattr(dashboard.st, "columns", fake_columns)
    metrics = [("Price", "$100"), ("Change", "2%", "+1%"), ("Volume", "10M", 0)]

    result = dashboard.render_metric_row(metrics)

    assert result is None
    assert column_calls == [3]
    assert [column.calls for column in columns] == [
        [("Price", "$100", None)],
        [("Change", "2%", "+1%")],
        [("Volume", "10M", 0)],
    ]
