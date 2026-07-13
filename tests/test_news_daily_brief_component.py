import builtins
from copy import deepcopy
import json

import pytest

from conftest import import_root_dashboard
from components import news_daily_brief
from components.news_daily_brief import render_news_daily_brief
from services.news_daily_brief import daily_brief_fingerprint, select_daily_brief_news
from translations.news_ui import NEWS_DAILY_BRIEF_TEXT


dashboard = import_root_dashboard()


LABELS = {
    "title": "Technology & Semiconductor Daily Brief",
    "generate": "Generate today's brief",
    "regenerate": "Regenerate",
    "articles_used": "Articles used",
    "sources": "Sources",
    "generated_at": "Generated at",
    "data_date": "Data date",
    "related_tickers": "Related tickers",
    "article_count": "Articles",
    "empty": "No important events",
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
    monkeypatch.setattr(news_daily_brief.st, "markdown", lambda value: events.append(("markdown", value)))
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


def highlight(index):
    return {
        "title": f"Distinct event {index}",
        "summary": f"Summary {index} explains what happened, its industry impact, and a principal risk.",
        "kind": "company" if index % 2 else "event",
        "primary_ticker": "NVDA" if index == 1 else None,
        "related_tickers": ["NVDA"] if index == 1 else [],
        "sources": ["FMP", "Yahoo/yfinance"] if index == 1 else ["TrendForce"],
        "article_count": 2 if index == 1 else 1,
        "source_article_indices": [index - 1],
        "risk": "Execution risk",
    }


def result_with_items(count):
    return {
        "status": "ok",
        "items": [highlight(index) for index in range(1, count + 1)],
        "articles_used": count + 1,
        "sources_used": ["FMP", "Yahoo/yfinance", "TrendForce"],
        "generated_at": "2026-07-13T12:00:00+00:00",
        "data_date": "2026-07-13",
    }


def test_ok_result_renders_multiple_numbered_event_cards_and_metadata(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    clicked = render_news_daily_brief(result_with_items(3), labels=LABELS, language="English")

    assert clicked is False
    assert [event for event in events if event[0] == "subheader"] == [("subheader", LABELS["title"])]
    assert len([event for event in events if event[0] == "container"]) == 3
    assert [event[1] for event in events if event[0] == "markdown"] == [
        "#### 1. Distinct event 1", "#### 2. Distinct event 2", "#### 3. Distinct event 3",
    ]
    assert len([event for event in events if event[0] == "write"]) == 3
    captions = [event[1] for event in events if event[0] == "caption"]
    assert "Articles used: 4" in captions[0]
    assert "Related tickers: NVDA" in captions[1]
    assert "Sources: FMP, Yahoo/yfinance" in captions[1]
    assert "Articles: 2" in captions[1]


def test_component_renders_at_most_ten_cards(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(result_with_items(12), labels=LABELS)

    assert len([event for event in events if event[0] == "container"]) == 10
    assert not any("Distinct event 11" in event[1] for event in events if event[0] == "markdown")


def test_component_does_not_create_fixed_market_or_ticker_sections(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(result_with_items(4), labels=LABELS)

    headings = [event[1] for event in events if event[0] == "markdown"]
    assert all(heading not in ("Market", "NVDA", "MU", "AMD") for heading in headings)
    assert len(headings) == 4


def test_fewer_than_ten_items_render_safely(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(result_with_items(5), labels=LABELS)

    assert len([event for event in events if event[0] == "container"]) == 5


@pytest.mark.parametrize(
    ("result", "event_type", "message"),
    [
        ({"status": "missing_key", "items": []}, "warning", LABELS["missing_key"]),
        ({"status": "empty", "items": []}, "info", LABELS["empty"]),
        ({"status": "error", "items": []}, "warning", LABELS["error"]),
    ],
)
def test_non_ok_states_render_safely(monkeypatch, result, event_type, message):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(result, labels=LABELS)

    assert (event_type, message) in events


def test_error_state_shows_at_most_five_event_candidates(monkeypatch):
    events = install_streamlit_spy(monkeypatch)

    render_news_daily_brief(
        {"status": "error", "items": [], "candidate_titles": ["one", "two", "three", "four", "five", "six"]},
        labels=LABELS,
    )

    caption = next(event[1] for event in events if event[0] == "caption")
    assert caption == "Candidate news: one · two · three · four · five"
    assert "six" not in caption


def test_generate_and_regenerate_require_explicit_click(monkeypatch):
    idle_events = install_streamlit_spy(monkeypatch, clicked=False)
    assert render_news_daily_brief(None, labels=LABELS) is False
    assert ("button", LABELS["generate"], {"key": "technology_daily_brief_zh"}) in idle_events

    result_events = install_streamlit_spy(monkeypatch, clicked=True)
    assert render_news_daily_brief(result_with_items(3), labels=LABELS) is True
    assert ("button", LABELS["regenerate"], {"key": "technology_daily_brief_zh"}) in result_events


def test_component_does_not_mutate_result_or_labels(monkeypatch):
    install_streamlit_spy(monkeypatch)
    result = result_with_items(3)
    before_result = deepcopy(result)
    before_labels = deepcopy(LABELS)

    render_news_daily_brief(result, labels=LABELS, language="Español")

    assert result == before_result
    assert LABELS == before_labels


def test_all_three_languages_have_new_card_metadata_labels():
    for language in ("中文", "English", "Español"):
        labels = NEWS_DAILY_BRIEF_TEXT[language]
        assert labels["title"]
        assert labels["related_tickers"]
        assert labels["article_count"]


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

    assert [item["title"] for item in items] == ["FMP", "Yahoo NVDA", "Yahoo MU", "TrendForce", "Market"]
    assert calls == [
        ("fmp", ("NVDA", "MU"), 10), ("yahoo", ("NVDA", "MU"), 10),
        ("trendforce", 20), ("market", 50),
    ]


def test_dashboard_daily_brief_remains_between_source_selector_and_news_list(monkeypatch):
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


def test_dashboard_does_not_collect_before_button_request(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "English"})
    monkeypatch.setattr(dashboard, "render_news_daily_brief", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        dashboard, "collect_daily_brief_news",
        lambda: pytest.fail("news must not be collected before an explicit click"),
    )

    assert dashboard.render_news_daily_brief_section() is None


def test_dashboard_cached_wrapper_reuses_identical_multi_item_cache_key(monkeypatch):
    calls = []
    raw = [
        {
            "title": title,
            "text": text,
            "source": source,
            "ticker": ticker,
            "related_tickers": ticker,
            "published_date": "2026-07-13",
            "url": f"https://example.com/{index}",
        }
        for index, (title, text, source, ticker) in enumerate([
            ("Nvidia GPU launch", "Nvidia launched a semiconductor GPU product.", "FMP", "NVDA"),
            ("Micron HBM supply", "Micron HBM memory supply capacity changed.", "TrendForce", "MU"),
            ("Microsoft AI capex", "Microsoft increased AI data center capex.", "Yahoo/yfinance", "MSFT"),
        ])
    ]
    candidates = select_daily_brief_news(raw, now="2026-07-13T12:00:00Z")
    response_items = []
    for index, candidate in enumerate(candidates):
        ticker = candidate["related_tickers"][0]
        response_items.append({
            "title": f"Highlight: {candidate['title']}",
            "summary": (
                f"{candidate['summary']} This event has a distinct industry impact and a source-specific "
                "execution risk."
            ),
            "kind": "company",
            "primary_ticker": ticker,
            "related_tickers": [ticker],
            "source_article_indices": [index],
            "risk": "Execution risk",
        })

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = type("Message", (), {"content": json.dumps({"items": response_items})})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    client = type("Client", (), {
        "chat": type("Chat", (), {"completions": Completions()})()
    })()
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: client)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    candidate_json = json.dumps(candidates, ensure_ascii=False, sort_keys=True)
    fingerprint = daily_brief_fingerprint(candidates)

    first = dashboard.get_cached_news_daily_brief(candidate_json, "English", "2026-07-13", fingerprint, 0)
    second = dashboard.get_cached_news_daily_brief(candidate_json, "English", "2026-07-13", fingerprint, 0)

    assert first == second
    assert first["status"] == "ok"
    assert len(first["items"]) == 3
    assert len(calls) == 1
