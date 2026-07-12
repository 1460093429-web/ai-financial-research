import ast
import builtins
import inspect

import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()
import financials
from providers import trendforce, yahoo_news
from services import news_schema


@pytest.fixture(autouse=True)
def isolate_aggregation_tests(monkeypatch):
    for cached in (
        dashboard.get_cached_company_news,
        dashboard.get_cached_watchlist_news,
        dashboard.get_cached_market_news,
        dashboard.get_cached_yahoo_news,
        dashboard.get_cached_watchlist_yahoo_news,
        dashboard.get_cached_trendforce_news,
    ):
        clear = getattr(cached, "clear", None)
        if clear:
            clear()
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))
    yield
    for cached in (
        dashboard.get_cached_company_news,
        dashboard.get_cached_watchlist_news,
        dashboard.get_cached_market_news,
        dashboard.get_cached_yahoo_news,
        dashboard.get_cached_watchlist_yahoo_news,
        dashboard.get_cached_trendforce_news,
    ):
        clear = getattr(cached, "clear", None)
        if clear:
            clear()


@pytest.mark.parametrize(
    ("item", "expected_source", "expected_publisher", "expected_summary"),
    [
        (
            {"source": "Yahoo/yfinance", "publisher": "Yahoo Publisher", "text": "Yahoo text"},
            "Yahoo/yfinance",
            "Yahoo Publisher",
            "Yahoo text",
        ),
        (
            {"source": "TrendForce", "site": "TrendForce", "summary": "Trend summary"},
            "TrendForce",
            "TrendForce",
            "Trend summary",
        ),
        (
            {"source": "FMP", "site": "FMP Site", "text": "FMP text"},
            "FMP",
            "FMP Site",
            "FMP text",
        ),
        (
            {"source": "yfinance fallback", "publisher": "Fallback Publisher", "text": "Fallback text"},
            "yfinance fallback",
            "Fallback Publisher",
            "Fallback text",
        ),
    ],
)
def test_legacy_items_use_current_source_publisher_and_summary_priority(
    item, expected_source, expected_publisher, expected_summary
):
    assert dashboard._news_item_source_name(item) == expected_source
    assert dashboard._news_item_publisher(item) == expected_publisher
    assert dashboard._news_item_summary_text(item) == expected_summary


def test_legacy_summary_source_and_publisher_fallback_order():
    item = {
        "summary": "summary",
        "text": "text",
        "description": "description",
        "source": "source",
        "source_type": "source_type",
        "site": "site",
        "publisher": "publisher",
        "source_name": "source_name",
    }

    assert dashboard._news_item_summary_text(item) == "summary"
    assert dashboard._news_item_source_name(item) == "source"
    assert dashboard._news_item_publisher(item) == "publisher"
    assert dashboard._news_item_summary_text({"text": "text", "description": "description"}) == "text"
    assert dashboard._news_item_summary_text({"description": "description"}) == "description"
    assert dashboard._news_item_source_name({"source_type": "type", "site": "site"}) == "type"
    assert dashboard._news_item_source_name({"site": "site"}) == "site"
    assert dashboard._news_item_publisher({"site": "site", "source_name": "name"}) == "site"
    assert dashboard._news_item_publisher({"source_name": "name"}) == "name"


def test_legacy_date_sorting_only_uses_published_date_then_published_date_camel_case():
    assert dashboard._news_sort_key({"published_date": "2026-07-13", "publishedDate": "2026-07-12"}) == "2026-07-13"
    assert dashboard._news_sort_key({"publishedDate": "2026-07-12"}) == "2026-07-12"
    assert dashboard._news_sort_key({"date": "2026-07-11", "timestamp": 1_700_000_000}) == ""
    items = [
        {"title": "older", "published_date": "2026-07-11"},
        {"title": "newer", "publishedDate": "2026-07-13"},
        {"title": "undated", "date": "2026-07-14"},
    ]
    assert [item["title"] for item in sorted(items, key=dashboard._news_sort_key, reverse=True)] == [
        "newer", "older", "undated"
    ]


@pytest.mark.parametrize(
    ("item", "expected_related"),
    [
        ({"related_tickers": "NVDA, MU", "ticker": "NVDA"}, "NVDA, MU"),
        ({"ticker": "MU", "related_ticker": "IGNORED"}, "MU"),
        ({"related_ticker": "SNDK"}, "Market"),
    ],
)
def test_news_card_current_related_ticker_dependency(monkeypatch, item, expected_related):
    captions = []
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "English"})
    monkeypatch.setattr(dashboard.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "caption", captions.append)
    monkeypatch.setattr(dashboard.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "link_button", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "divider", lambda: None)
    monkeypatch.setattr(dashboard, "render_news_translation", lambda value: None)
    monkeypatch.setattr(dashboard, "render_news_detailed_summary", lambda value: None)
    monkeypatch.setattr(dashboard, "yahoo_news_score_caption_parts", lambda value: ())
    legacy = {"title": "Title", "source": "FMP", **item}

    dashboard.render_standard_news_card(legacy)

    assert f"Related ticker: {expected_related}" in captions[0]


def test_news_card_accepts_legacy_items_and_preserves_display_fields(monkeypatch):
    events = []
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "English"})
    monkeypatch.setattr(dashboard.st, "markdown", lambda value: events.append(("markdown", value)))
    monkeypatch.setattr(dashboard.st, "caption", lambda value: events.append(("caption", value)))
    monkeypatch.setattr(dashboard.st, "write", lambda value: events.append(("write", value)))
    monkeypatch.setattr(dashboard.st, "link_button", lambda label, url: events.append(("link", label, url)))
    monkeypatch.setattr(dashboard.st, "divider", lambda: events.append(("divider",)))
    monkeypatch.setattr(dashboard, "render_news_translation", lambda item: events.append(("translation", item["title"])))
    monkeypatch.setattr(dashboard, "render_news_detailed_summary", lambda item: events.append(("detail", item["title"])))
    monkeypatch.setattr(dashboard, "yahoo_news_score_caption_parts", lambda item: ("score-a", "score-b"))
    item = {
        "title": "Yahoo title",
        "text": "Legacy text",
        "url": "https://example.com/item",
        "source": "Yahoo/yfinance",
        "publisher": "Publisher",
        "published_date": "2026-07-13",
        "ticker": "NVDA",
    }

    dashboard.render_standard_news_card(item)

    assert events == [
        ("markdown", "#### Yahoo title"),
        ("caption", "2026-07-13 | Publisher | Related ticker: NVDA | Yahoo/yfinance | score-a | score-b"),
        ("write", "Legacy text"),
        ("translation", "Yahoo title"),
        ("detail", "Yahoo title"),
        ("link", "Open article", "https://example.com/item"),
        ("divider",),
    ]


def test_watchlist_company_aggregation_preserves_ticker_order_legacy_items_and_exception_isolation(monkeypatch):
    calls = []
    cache_calls = []
    by_ticker = {
        "NVDA": [{"title": "NVDA FMP", "text": "n", "source": "FMP", "ticker": "NVDA"}],
        "SNDK": [{"title": "SNDK fallback", "text": "s", "source": "yfinance fallback", "ticker": "SNDK"}],
    }

    def fake_company_news(ticker, limit):
        calls.append((ticker, limit))
        if ticker == "MU":
            raise RuntimeError("unavailable")
        return by_ticker[ticker]

    monkeypatch.setattr(dashboard, "get_cached_company_news", fake_company_news)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    result = dashboard.get_cached_watchlist_news(("NVDA", "MU", "SNDK"), 7)

    assert [item["title"] for item in result] == ["NVDA FMP", "SNDK fallback"]
    assert [item["source"] for item in result] == ["FMP", "yfinance fallback"]
    assert calls == [("NVDA", 7), ("MU", 7), ("SNDK", 7)]
    assert cache_calls == [True]
    assert all("provider" not in item and "is_fallback" not in item for item in result)


def test_yahoo_watchlist_aggregation_preserves_mapping_order_and_empty_on_ticker_error(monkeypatch):
    calls = []
    cache_calls = []

    def fake_yahoo(ticker, limit):
        calls.append((ticker, limit))
        if ticker == "MU":
            raise RuntimeError("unavailable")
        return [{"title": ticker, "text": ticker, "source": "Yahoo/yfinance", "ticker": ticker}]

    monkeypatch.setattr(dashboard, "get_cached_yahoo_news", fake_yahoo)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    result = dashboard.get_cached_watchlist_yahoo_news(("NVDA", "MU", "SNDK"), 4)

    assert list(result) == ["NVDA", "MU", "SNDK"]
    assert result["MU"] == []
    assert result["NVDA"][0]["source"] == "Yahoo/yfinance"
    assert calls == [("NVDA", 4), ("MU", 4), ("SNDK", 4)]
    assert cache_calls == [True]


def test_cached_wrappers_return_legacy_items_without_schema_enrichment(monkeypatch):
    cache_calls = []
    company = [{"title": "FMP", "text": "text", "source": "FMP", "ticker": "NVDA"}]
    market = [{"title": "Market", "text": "text", "source": "FMP", "ticker": "Market"}]
    trendforce = [{
        "title": "TrendForce", "summary": "summary", "source": "TrendForce",
        "site": "TrendForce", "publisher": "TrendForce集邦咨询", "publishedDate": "2026-07-13",
    }]
    monkeypatch.setattr(dashboard, "fetch_company_news", lambda ticker, limit: company)
    monkeypatch.setattr(dashboard, "fetch_general_news", lambda limit: market)
    monkeypatch.setattr(dashboard, "get_trendforce_news", lambda limit: trendforce)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    results = (
        dashboard.get_cached_company_news("NVDA", 5),
        dashboard.get_cached_market_news(10),
        dashboard.get_cached_trendforce_news(20),
    )

    assert results == (company, market, trendforce)
    assert cache_calls == [True, True, True]
    for items in results:
        for item in items:
            assert "published_at" not in item
            assert "retrieved_at" not in item
            assert "is_fallback" not in item
            assert "fallback_from" not in item
            assert "provider" not in item


def test_cache_wrapper_signatures_show_ticker_and_limit_keys_but_no_language_key():
    assert str(inspect.signature(dashboard.get_cached_company_news)) == "(ticker, limit=5)"
    assert str(inspect.signature(dashboard.get_cached_watchlist_news)) == "(tickers, limit_per_ticker=20)"
    assert str(inspect.signature(dashboard.get_cached_market_news)) == "(limit=150)"
    assert str(inspect.signature(dashboard.get_cached_yahoo_news)) == "(ticker, limit=10)"
    assert str(inspect.signature(dashboard.get_cached_watchlist_yahoo_news)) == "(tickers, limit_per_ticker=10)"
    assert str(inspect.signature(dashboard.get_cached_trendforce_news)) == "(limit=20)"
    for cached in (
        dashboard.get_cached_company_news,
        dashboard.get_cached_watchlist_news,
        dashboard.get_cached_market_news,
        dashboard.get_cached_yahoo_news,
        dashboard.get_cached_watchlist_yahoo_news,
        dashboard.get_cached_trendforce_news,
    ):
        assert callable(cached.clear)


def test_production_modules_do_not_import_or_call_news_schema_adapter(monkeypatch):
    monkeypatch.setattr(news_schema, "normalize_news_item", lambda *args, **kwargs: pytest.fail("adapter is not connected"))
    monkeypatch.setattr(news_schema, "normalize_news_items", lambda *args, **kwargs: pytest.fail("adapter is not connected"))
    for module in (dashboard, yahoo_news, trendforce, financials):
        tree = ast.parse(inspect.getsource(module))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "services.news_schema" not in imports

    assert dashboard._news_item_summary_text({"text": "legacy"}) == "legacy"
