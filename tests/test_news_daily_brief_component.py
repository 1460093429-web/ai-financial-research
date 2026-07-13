import builtins
from copy import deepcopy

import pytest

from conftest import import_root_dashboard
from components import news_daily_brief
from components.news_daily_brief import render_news_daily_brief
from services.news_daily_brief import daily_brief_fingerprint, select_daily_brief_news


dashboard = import_root_dashboard()


LABELS = {
    "title": "Technology & Semiconductor Daily Brief",
    "generate": "Generate today's brief",
    "regenerate": "Regenerate",
    "articles_used": "Articles used",
    "sources": "Sources",
    "generated_at": "Generated at",
    "data_date": "Data date",
    "empty": "No important news",
    "missing_key": "Missing key",
    "error": "Generation failed",
    "candidates": "Candidate news",
    "idle": "Generate on demand",
    "unavailable": "Unavailable",
}


class Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture(autouse=True)
def isolate_component(monkeypatch):
    import openai
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))
    dashboard.get_cached_news_daily_brief.clear()
    yield
    dashboard.get_cached_news_daily_brief.clear()


def install_streamlit_spy(monkeypatch, *, clicked=False):
    events = []
    monkeypatch.setattr(news_daily_brief.st, "container", lambda **kwargs: events.append(("container", kwargs)) or Context())
    monkeypatch.setattr(news_daily_brief.st, "subheader", lambda value: events.append(("subheader", value)))
    monkeypatch.setattr(news_daily_brief.st, "write", lambda value: events.append(("write", value)))
    monkeypatch.setattr(news_daily_brief.st, "caption", lambda value: events.append(("caption", value)))
    monkeypatch.setattr(news_daily_brief.st, "warning", lambda value: events.append(("warning", value)))
    monkeypatch.setattr(news_daily_brief.st, "info", lambda value: events.append(("info", value)))
    monkeypatch.setattr(
        news_daily_brief.st,
        "button",
        lambda label, **kwargs: events.append(("button", label, kwargs)) or clicked,
    )
    return events


def test_ok_result_renders_one_combined_card_and_metadata(monkeypatch):
    events = install_streamlit_spy(monkeypatch)
    result = {
        "status": "ok",
        "brief": "One combined industry summary mentioning NVDA and MU in one paragraph.",
        "articles_used": 4,
        "sources_used": ["FMP", "TrendForce"],
        "generated_at": "2026-07-13T12:00:00+00:00",
        "data_date": "2026-07-13",
    }

    clicked = render_news_daily_brief(result, labels=LABELS, language="English")

    assert clicked is False
    assert [event for event in events if event[0] == "container"] == [("container", {"border": True})]
    assert [event for event in events if event[0] == "subheader"] == [("subheader", LABELS["title"])]
    assert [event for event in events if event[0] == "write"] == [("write", result["brief"])]
    assert "Articles used: 4" in next(event[1] for event in events if event[0] == "caption")
    assert "Sources: FMP, TrendForce" in next(event[1] for event in events if event[0] == "caption")
    assert not any(event[0] == "expander" for event in events)


@pytest.mark.parametrize(
    ("result", "event_type", "message"),
    [
        ({"status": "missing_key"}, "warning", LABELS["missing_key"]),
        ({"status": "empty"}, "info", LABELS["empty"]),
        ({"status": "error"}, "warning", LABELS["error"]),
    ],
)
def test_non_ok_states_render_safely(monkeypatch, result, event_type, message):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(result, labels=LABELS)

    assert (event_type, message) in events


def test_error_state_shows_at_most_three_fallback_candidate_titles(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(
        {"status": "error", "candidate_titles": ["one", "two", "three", "four"]},
        labels=LABELS,
    )

    caption = next(event[1] for event in events if event[0] == "caption")
    assert caption == "Candidate news: one · two · three"
    assert "four" not in caption


def test_generate_and_regenerate_require_explicit_button_click(monkeypatch):
    idle_events = install_streamlit_spy(monkeypatch, clicked=False)
    assert render_news_daily_brief(None, labels=LABELS) is False
    assert ("button", LABELS["generate"], {"key": "technology_daily_brief_zh"}) in idle_events

    result_events = install_streamlit_spy(monkeypatch, clicked=True)
    assert render_news_daily_brief({"status": "ok", "brief": "brief"}, labels=LABELS) is True
    assert ("button", LABELS["regenerate"], {"key": "technology_daily_brief_zh"}) in result_events


def test_component_does_not_mutate_result_or_labels(monkeypatch):
    install_streamlit_spy(monkeypatch)
    result = {"status": "ok", "brief": "brief", "sources_used": ["FMP"]}
    before_result = deepcopy(result)
    before_labels = deepcopy(LABELS)

    render_news_daily_brief(result, labels=LABELS, language="Español")

    assert result == before_result
    assert LABELS == before_labels


def test_dashboard_collection_reuses_existing_cached_news_boundaries(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "load_watchlist", lambda: ["NVDA", "MU"])
    monkeypatch.setattr(
        dashboard, "get_cached_watchlist_news",
        lambda tickers, limit: calls.append(("fmp", tickers, limit)) or [{"title": "FMP"}],
    )
    monkeypatch.setattr(
        dashboard, "get_cached_watchlist_yahoo_news",
        lambda tickers, limit: calls.append(("yahoo", tickers, limit)) or {
            "NVDA": [{"title": "Yahoo NVDA"}], "MU": [{"title": "Yahoo MU"}],
        },
    )
    monkeypatch.setattr(
        dashboard, "get_cached_trendforce_news",
        lambda limit: calls.append(("trendforce", limit)) or [{"title": "TrendForce"}],
    )
    monkeypatch.setattr(
        dashboard, "get_cached_market_news",
        lambda limit: calls.append(("market", limit)) or [{"title": "Market"}],
    )

    items = dashboard.collect_daily_brief_news()

    assert [item["title"] for item in items] == [
        "FMP", "Yahoo NVDA", "Yahoo MU", "TrendForce", "Market"
    ]
    assert calls == [
        ("fmp", ("NVDA", "MU"), 10),
        ("yahoo", ("NVDA", "MU"), 10),
        ("trendforce", 20),
        ("market", 50),
    ]


def test_dashboard_daily_brief_is_between_source_selector_and_news_list(monkeypatch):
    events = []
    monkeypatch.setattr(dashboard, "t", lambda key: key)
    monkeypatch.setattr(
        dashboard.st, "radio",
        lambda *args, **kwargs: events.append("source_selector") or "fmp_news_tab",
    )
    monkeypatch.setattr(dashboard.st, "spinner", lambda *args, **kwargs: Context())
    monkeypatch.setattr(dashboard, "render_news_daily_brief_section", lambda: events.append("daily_brief"))
    monkeypatch.setattr(dashboard, "render_fmp_news_section", lambda: events.append("news_list"))

    dashboard.render_news_section()

    assert events == ["source_selector", "daily_brief", "news_list"]


def test_dashboard_daily_brief_does_not_collect_until_button_request(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "English"})
    monkeypatch.setattr(dashboard, "render_news_daily_brief", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        dashboard, "collect_daily_brief_news",
        lambda: pytest.fail("news must not be collected before an explicit click"),
    )

    assert dashboard.render_news_daily_brief_section() is None


def test_dashboard_cached_wrapper_reuses_identical_cache_key(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = type("Message", (), {"content": "One combined semiconductor brief with demand drivers and export risk."})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    client = type("Client", (), {
        "chat": type("Chat", (), {"completions": Completions()})()
    })()
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: client)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    raw = [{
        "title": "AI chip demand", "text": "Semiconductor data center demand and capex.",
        "source": "FMP", "ticker": "NVDA", "published_date": "2026-07-13",
    }]
    candidates = select_daily_brief_news(raw, now="2026-07-13T12:00:00Z")
    candidate_json = __import__("json").dumps(candidates, ensure_ascii=False, sort_keys=True)
    fingerprint = daily_brief_fingerprint(candidates)

    first = dashboard.get_cached_news_daily_brief(
        candidate_json, "English", "2026-07-13", fingerprint, 0,
    )
    second = dashboard.get_cached_news_daily_brief(
        candidate_json, "English", "2026-07-13", fingerprint, 0,
    )

    assert first == second
    assert first["status"] == "ok"
    assert len(calls) == 1
