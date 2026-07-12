import builtins
import ast
import inspect

import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()
import financials
from providers import yahoo_news as yahoo_news_provider


class YahooStock:
    def __init__(self, get_news_result=None, news=None, get_news_error=None):
        self.get_news_result = get_news_result
        self.news = news or []
        self.get_news_error = get_news_error
        self.get_news_calls = []

    def get_news(self, *args, **kwargs):
        self.get_news_calls.append((args, kwargs))
        if self.get_news_error:
            raise self.get_news_error
        return self.get_news_result


class FmpResponse:
    def __init__(self, ok=True, status_code=200, text="", payload=None):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def isolate_news_tests(monkeypatch):
    for cached in (
        dashboard.get_cached_company_news,
        dashboard.get_cached_watchlist_news,
        dashboard.get_cached_market_news,
        dashboard.get_cached_yahoo_news,
        dashboard.get_cached_watchlist_yahoo_news,
        dashboard.get_cached_trendforce_news,
    ):
        cached.clear()
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
        cached.clear()


def yahoo_item(title, timestamp="2026-07-13T00:00:00Z"):
    return {
        "content": {
            "title": title,
            "summary": f"Summary for {title}",
            "pubDate": timestamp,
            "canonicalUrl": {"url": f"https://finance.yahoo.com/{title}"},
            "provider": {"displayName": "Yahoo Publisher"},
        }
    }


def test_yahoo_provider_and_dashboard_cached_wrapper_signatures_are_characterized():
    assert str(inspect.signature(yahoo_news_provider.fetch_yahoo_news)) == "(ticker, limit=10)"
    assert str(inspect.signature(dashboard.get_cached_yahoo_news)) == "(ticker, limit=10)"


def test_yahoo_provider_does_not_import_dashboard():
    tree = ast.parse(inspect.getsource(yahoo_news_provider))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert "dashboard" not in imported_roots


def test_yahoo_cached_wrapper_delegates_after_debug_counters(monkeypatch):
    events = []
    expected = [{"title": "provider result", "source": "Yahoo/yfinance"}]
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: events.append("cacheable"))
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: events.append(name))
    monkeypatch.setattr(
        dashboard,
        "_provider_fetch_yahoo_news",
        lambda ticker, limit: events.append((ticker, limit)) or expected,
    )

    assert dashboard.get_cached_yahoo_news("nvda", 3) == expected
    assert events == ["cacheable", "yfinance_news", ("nvda", 3)]


def test_yahoo_provider_type_error_retries_get_news_without_arguments(monkeypatch):
    class TypeErrorStock:
        news = []

        def __init__(self):
            self.calls = []

        def get_news(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            if kwargs:
                raise TypeError("count unsupported")
            return [yahoo_item("retry")]

    stock = TypeErrorStock()
    monkeypatch.setattr(yahoo_news_provider.yf, "Ticker", lambda ticker: stock)

    result = yahoo_news_provider.fetch_yahoo_news("mu", 2)

    assert [item["title"] for item in result] == ["retry"]
    assert stock.calls == [((), {"count": 2}), ((), {})]


def test_yahoo_cached_provider_normalizes_ticker_limit_source_and_counters(monkeypatch):
    stock = YahooStock(get_news_result=[yahoo_item("one"), yahoo_item("two"), yahoo_item("three")])
    ticker_calls = []
    api_calls = []
    cache_calls = []
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: ticker_calls.append(ticker) or stock)
    monkeypatch.setattr(dashboard, "track_api_call", api_calls.append)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    result = dashboard.get_cached_yahoo_news("nvda", limit=2)

    assert ticker_calls == ["NVDA"]
    assert stock.get_news_calls == [((), {"count": 2})]
    assert [item["title"] for item in result] == ["one", "two"]
    assert all(item["source"] == "Yahoo/yfinance" for item in result)
    assert all(item["ticker"] == "NVDA" for item in result)
    assert api_calls == ["yfinance_news"]
    assert cache_calls == [True]


def test_yahoo_empty_get_news_uses_stock_news_property(monkeypatch):
    stock = YahooStock(get_news_result=[], news=[yahoo_item("property")])
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: stock)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)

    result = dashboard.get_cached_yahoo_news("MU", 10)

    assert [item["title"] for item in result] == ["property"]


def test_yahoo_get_news_exception_uses_property_and_property_exception_propagates(monkeypatch):
    fallback_stock = YahooStock(get_news_error=RuntimeError("get_news failed"), news=[yahoo_item("fallback")])
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: fallback_stock)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    assert [item["title"] for item in dashboard.get_cached_yahoo_news("MU", 10)] == ["fallback"]

    dashboard.get_cached_yahoo_news.clear()

    class BrokenStock:
        def get_news(self, *args, **kwargs):
            raise RuntimeError("get_news failed")

        @property
        def news(self):
            raise RuntimeError("news property failed")

    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: BrokenStock())
    with pytest.raises(RuntimeError, match="news property failed"):
        dashboard.get_cached_yahoo_news("NVDA", 10)


def test_yahoo_empty_and_none_ticker_current_behavior(monkeypatch):
    calls = []
    stock = YahooStock(get_news_result=[])
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: calls.append(ticker) or stock)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)

    assert dashboard.get_cached_yahoo_news("", 2) == []
    assert calls == [""]
    with pytest.raises(AttributeError):
        dashboard.get_cached_yahoo_news(None, 2)


def test_yahoo_cached_function_reuses_same_key_without_provider_call(monkeypatch):
    stock = YahooStock(get_news_result=[yahoo_item("cached")])
    ticker_calls = []
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda ticker: ticker_calls.append(ticker) or stock)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)

    first = dashboard.get_cached_yahoo_news("NVDA", 1)
    second = dashboard.get_cached_yahoo_news("NVDA", 1)

    assert first == second
    assert ticker_calls == ["NVDA"]
    assert callable(dashboard.get_cached_yahoo_news.clear)


def test_fmp_company_news_normal_response_schema_limit_and_metadata(monkeypatch):
    payload = [
        {"title": "one", "text": "text one", "publishedDate": "2026-07-13", "url": "u1", "publisher": "P1"},
        {"title": "two", "text": "text two", "publishedDate": "2026-07-12", "url": "u2", "site": "Site2"},
        {"title": "three"},
    ]
    calls = []
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda endpoint, api_key, **params: calls.append((endpoint, api_key, params)) or payload)
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: pytest.fail("Yahoo fallback must not run"))

    result = financials.fetch_company_news("nvda", limit=2)

    assert calls == [("news/stock", "test-key", {"symbols": "NVDA", "limit": 2})]
    assert result == [
        {"title": "one", "text": "text one", "published_date": "2026-07-13", "url": "u1", "publisher": "P1", "source": "FMP", "ticker": "NVDA"},
        {"title": "two", "text": "text two", "published_date": "2026-07-12", "url": "u2", "publisher": "Site2", "source": "FMP", "ticker": "NVDA"},
    ]


@pytest.mark.parametrize("fmp_result", [[], {}, None])
def test_fmp_company_news_empty_or_unusable_response_uses_yfinance_fallback(monkeypatch, fmp_result):
    stock = YahooStock(news=[yahoo_item("fallback")])
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: fmp_result)
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: stock)

    result = financials.fetch_company_news("mu", limit=1)

    assert result[0]["source"] == "yfinance fallback"
    assert result[0]["ticker"] == "MU"
    assert result[0]["title"] == "fallback"


def test_missing_fmp_key_and_fmp_exception_use_yfinance_fallback(monkeypatch):
    stock = YahooStock(news=[yahoo_item("fallback")])
    monkeypatch.setattr(
        financials,
        "get_fmp_api_key",
        lambda: (_ for _ in ()).throw(ValueError("FMP_API_KEY is missing")),
    )
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: stock)
    assert financials.fetch_company_news("NVDA", 1)[0]["source"] == "yfinance fallback"

    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("FMP failed")))
    assert financials.fetch_company_news("NVDA", 1)[0]["source"] == "yfinance fallback"


def test_fmp_non_200_response_uses_yfinance_fallback_without_real_network(monkeypatch):
    stock = YahooStock(news=[yahoo_item("fallback")])
    calls = []
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(
        financials.requests,
        "get",
        lambda url, **kwargs: calls.append((url, kwargs)) or FmpResponse(ok=False, status_code=503, text="upstream unavailable"),
    )
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: stock)

    result = financials.fetch_company_news("NVDA", 1)

    assert result[0]["source"] == "yfinance fallback"
    assert calls[0][1]["timeout"] == 15
    assert calls[0][1]["params"] == {"symbols": "NVDA", "limit": 1, "apikey": "test-key"}


def test_fmp_company_news_missing_fields_are_preserved_as_unavailable(monkeypatch):
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: [{}])
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: pytest.fail("non-empty FMP list prevents fallback"))

    result = financials.fetch_company_news("NVDA", 5)

    assert result == [{
        "title": None,
        "text": None,
        "published_date": None,
        "url": None,
        "publisher": None,
        "source": "FMP",
        "ticker": "NVDA",
    }]


def test_fmp_dashboard_cached_wrappers_preserve_success_error_counters_and_cache(monkeypatch):
    provider_calls = []
    api_calls = []
    cache_calls = []
    expected = [{"title": "FMP", "source": "FMP", "ticker": "NVDA"}]
    monkeypatch.setattr(dashboard, "fetch_company_news", lambda ticker, limit: provider_calls.append((ticker, limit)) or expected)
    monkeypatch.setattr(dashboard, "track_api_call", api_calls.append)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    assert dashboard.get_cached_company_news("NVDA", 5) == expected
    assert dashboard.get_cached_company_news("NVDA", 5) == expected
    assert provider_calls == [("NVDA", 5)]
    assert api_calls == ["fmp_company_news"]
    assert cache_calls == [True]

    dashboard.get_cached_company_news.clear()
    monkeypatch.setattr(dashboard, "fetch_company_news", lambda *args: (_ for _ in ()).throw(RuntimeError("failed")))
    assert dashboard.get_cached_company_news("MU", 3) == []


def test_fmp_general_news_wrapper_current_empty_and_exception_behavior(monkeypatch):
    api_calls = []
    cache_calls = []
    monkeypatch.setattr(dashboard, "fetch_general_news", lambda limit: [])
    monkeypatch.setattr(dashboard, "track_api_call", api_calls.append)
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))
    assert dashboard.get_cached_market_news(4) == []
    assert api_calls == ["fmp_market_news"]
    assert cache_calls == [True]

    dashboard.get_cached_market_news.clear()
    monkeypatch.setattr(dashboard, "fetch_general_news", lambda limit: (_ for _ in ()).throw(RuntimeError("failed")))
    assert dashboard.get_cached_market_news(4) == []


def test_trendforce_cached_wrapper_caches_empty_result_and_counts_once(monkeypatch):
    provider_calls = []
    cache_calls = []
    monkeypatch.setattr(dashboard, "get_trendforce_news", lambda limit: provider_calls.append(limit) or [])
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    assert dashboard.get_cached_trendforce_news(20) == []
    assert dashboard.get_cached_trendforce_news(20) == []
    assert provider_calls == [20]
    assert cache_calls == [True]
    assert callable(dashboard.get_cached_trendforce_news.clear)


def test_trendforce_cached_wrapper_current_provider_exception_propagates(monkeypatch):
    cache_calls = []
    monkeypatch.setattr(dashboard, "get_trendforce_news", lambda limit: (_ for _ in ()).throw(RuntimeError("provider failed")))
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: cache_calls.append(True))

    with pytest.raises(RuntimeError, match="provider failed"):
        dashboard.get_cached_trendforce_news(20)
    assert cache_calls == [True]
