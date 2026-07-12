import builtins
import inspect

import pytest

from components import news_diagnostics_demo
from components.news_diagnostics import build_news_schema_diagnostics_rows
from components.news_diagnostics_demo import (
    build_mock_news_diagnostics_envelopes,
    render_mock_news_diagnostics_demo,
)
from services.news_schema import NEWS_SCHEMA_KEYS


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import openai
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def test_mock_builder_returns_expected_static_scenarios():
    envelopes = build_mock_news_diagnostics_envelopes()

    assert isinstance(envelopes, list)
    assert len(envelopes) == 6
    assert [item.get("_normalized", {}).get("provider") for item in envelopes[:4]] == [
        "yahoo", "trendforce", "fmp", "yahoo",
    ]
    assert envelopes[3]["source"] == "yfinance fallback"
    assert envelopes[3]["_normalized"]["is_fallback"] is True
    assert "_normalized" not in envelopes[4]
    assert set(envelopes[5]["_normalized"]) < set(NEWS_SCHEMA_KEYS)


def test_complete_mock_envelopes_keep_legacy_and_full_normalized_fields():
    for envelope in build_mock_news_diagnostics_envelopes()[:4]:
        assert envelope["title"]
        assert envelope["source"]
        assert "_normalized" in envelope
        assert set(envelope["_normalized"]) == set(NEWS_SCHEMA_KEYS)


def test_mock_builder_returns_fresh_data():
    first = build_mock_news_diagnostics_envelopes()
    second = build_mock_news_diagnostics_envelopes()

    assert first == second
    assert first is not second
    assert first[0] is not second[0]
    assert first[0]["_normalized"] is not second[0]["_normalized"]


def test_mock_envelopes_are_accepted_by_diagnostics_rows():
    envelopes = build_mock_news_diagnostics_envelopes()

    rows = build_news_schema_diagnostics_rows(envelopes)

    assert len(rows) == len(envelopes)
    assert [row["Title"] for row in rows] == [item["title"] for item in envelopes]
    assert rows[4]["Schema Status"] == "missing"
    assert rows[5]["Schema Status"] == "available"


def test_disabled_demo_does_not_build_or_render(monkeypatch):
    monkeypatch.setattr(
        news_diagnostics_demo,
        "build_mock_news_diagnostics_envelopes",
        lambda: pytest.fail("disabled demo must not build mock envelopes"),
    )
    monkeypatch.setattr(
        news_diagnostics_demo,
        "render_news_schema_diagnostics_if_enabled",
        lambda *args, **kwargs: pytest.fail("disabled demo must not render"),
    )

    assert render_mock_news_diagnostics_demo() is None


def test_enabled_demo_passes_static_envelopes_and_language(monkeypatch):
    envelopes = [{"title": "Static demo"}]
    calls = []
    monkeypatch.setattr(
        news_diagnostics_demo,
        "build_mock_news_diagnostics_envelopes",
        lambda: envelopes,
    )
    monkeypatch.setattr(
        news_diagnostics_demo,
        "render_news_schema_diagnostics_if_enabled",
        lambda value, **kwargs: calls.append((value, kwargs)) or "rendered",
    )

    result = render_mock_news_diagnostics_demo(enabled=True, language="es")

    assert result == "rendered"
    assert calls == [(envelopes, {"enabled": True, "language": "es"})]


def test_demo_has_no_provider_cache_network_openai_or_environment_dependencies():
    source = inspect.getsource(news_diagnostics_demo)

    for forbidden in (
        "from providers", "import providers", "cache_data(", "cache_resource(",
        "OpenAI(", "requests.", "yfinance.", "os.environ", "os.getenv",
    ):
        assert forbidden not in source
