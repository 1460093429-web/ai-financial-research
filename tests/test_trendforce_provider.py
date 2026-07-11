import builtins
from types import SimpleNamespace

import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()

CHINESE_URLS = [
    "https://www.trendforce.cn",
    "https://www.trendforce.cn/presscenter/news",
    "https://www.trendforce.cn/presscenter/news/Semiconductors",
    "https://www.trendforce.cn/presscenter",
]
ENGLISH_URLS = [
    "https://www.trendforce.com/presscenter/news",
    "https://www.trendforce.com/presscenter/news/Semiconductors",
    "https://www.trendforce.com/presscenter/rss.html",
]


class FakeResponse:
    def __init__(self, text="", content=b"", status_error=None, apparent_encoding="utf-8", encoding=None):
        self.text = text
        self.content = content
        self.status_error = status_error
        self.apparent_encoding = apparent_encoding
        self.encoding = encoding
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1
        if self.status_error:
            raise self.status_error


def item(number, url=None):
    return {
        "title": f"TrendForce article {number}",
        "publishedDate": "2026-07-12",
        "published_date": "2026-07-12",
        "category": "Semiconductors",
        "site": "TrendForce",
        "source": "TrendForce",
        "publisher": "TrendForce集邦咨询",
        "ticker": "SEMI",
        "related_ticker": "SEMI",
        "related_tickers": "SEMI",
        "summary": f"Summary {number}",
        "text": f"Summary {number}",
        "url": url or f"https://www.trendforce.com/presscenter/news/20260712-{number}.html",
        "sentiment": "中性",
        "credibility": "TrendForce",
    }


@pytest.fixture(autouse=True)
def forbid_unexpected_external_state(monkeypatch):
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(
        dashboard,
        "get_cached_trendforce_news",
        lambda *args, **kwargs: pytest.fail("cached wrapper must not run"),
    )
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def test_chinese_homepage_success_preserves_request_parser_and_debug_flow(monkeypatch):
    response = FakeResponse(text="chinese homepage", apparent_encoding="utf-8", encoding="legacy")
    request_calls = []
    soup_calls = []
    api_calls = []
    expected = [item(1), item(2)]

    def fake_get(url, **kwargs):
        request_calls.append((url, kwargs))
        return response

    def fake_soup(page_html, base_url, homepage=False):
        soup_calls.append((page_html, base_url, homepage))
        return expected

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", fake_soup)
    monkeypatch.setattr(
        dashboard,
        "_trendforce_items_from_regex",
        lambda *args, **kwargs: pytest.fail("regex fallback must not run when soup returns items"),
    )
    monkeypatch.setattr(
        dashboard.feedparser,
        "parse",
        lambda *args, **kwargs: pytest.fail("RSS must not run when Chinese HTML succeeds"),
    )
    monkeypatch.setattr(dashboard, "track_api_call", api_calls.append)

    result = dashboard.get_trendforce_news(limit=5)

    assert result == expected
    assert api_calls == ["trendforce_news"]
    assert request_calls == [
        (CHINESE_URLS[0], {"headers": {"User-Agent": "Mozilla/5.0"}, "timeout": 6})
    ]
    assert response.raise_calls == 1
    assert response.encoding == "utf-8"
    assert soup_calls == [("chinese homepage", CHINESE_URLS[0], True)]


def test_soup_none_uses_regex_fallback_without_feedparser(monkeypatch):
    response = FakeResponse(text="html without BeautifulSoup")
    regex_result = [item(1)]
    regex_calls = []
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", lambda *args, **kwargs: None)

    def fake_regex(page_html, base_url):
        regex_calls.append((page_html, base_url))
        return regex_result

    monkeypatch.setattr(dashboard, "_trendforce_items_from_regex", fake_regex)
    monkeypatch.setattr(
        dashboard.feedparser,
        "parse",
        lambda *args, **kwargs: pytest.fail("RSS must not run after regex succeeds"),
    )
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    assert dashboard.get_trendforce_news() == regex_result
    assert regex_calls == [("html without BeautifulSoup", CHINESE_URLS[0])]


def test_empty_soup_results_skip_regex_and_fall_through_to_english_html(monkeypatch):
    request_calls = []
    soup_calls = []
    english_result = [item(7)]

    def fake_get(url, **kwargs):
        request_calls.append(url)
        return FakeResponse(text=url)

    def fake_soup(page_html, base_url, homepage=False):
        soup_calls.append((base_url, homepage))
        return english_result if base_url == ENGLISH_URLS[0] else []

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", fake_soup)
    monkeypatch.setattr(
        dashboard,
        "_trendforce_items_from_regex",
        lambda *args, **kwargs: pytest.fail("empty soup list does not invoke regex in current behavior"),
    )
    monkeypatch.setattr(
        dashboard.feedparser,
        "parse",
        lambda *args, **kwargs: pytest.fail("RSS must not run after English HTML succeeds"),
    )
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    assert dashboard.get_trendforce_news() == english_result
    assert request_calls == CHINESE_URLS + [ENGLISH_URLS[0]]
    assert soup_calls[:4] == [
        (CHINESE_URLS[0], True),
        (CHINESE_URLS[1], False),
        (CHINESE_URLS[2], False),
        (CHINESE_URLS[3], False),
    ]
    assert soup_calls[4] == (ENGLISH_URLS[0], False)


def test_all_html_empty_falls_through_to_rss_and_preserves_metadata_order_and_duplicates(monkeypatch):
    request_calls = []
    parse_calls = []
    duplicate_url = "https://www.trendforce.com/presscenter/news/20260712-8.html"
    feed = SimpleNamespace(
        entries=[
            {
                "title": "Micron HBM expansion",
                "link": duplicate_url,
                "published": "12 July 2026",
                "category": "Semiconductors",
                "summary": "First summary",
            },
            {
                "title": "Duplicate Micron report",
                "link": duplicate_url,
                "updated": "2026-07-11",
                "description": "Second description",
            },
        ]
    )

    def fake_get(url, **kwargs):
        request_calls.append((url, kwargs))
        return FakeResponse(text="", content=b"rss-content")

    def fake_parse(content):
        parse_calls.append(content)
        return feed

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dashboard,
        "_trendforce_items_from_regex",
        lambda *args, **kwargs: pytest.fail("empty soup list does not invoke regex"),
    )
    monkeypatch.setattr(dashboard.feedparser, "parse", fake_parse)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    result = dashboard.get_trendforce_news(limit=10)

    assert [entry["title"] for entry in result] == ["Micron HBM expansion", "Duplicate Micron report"]
    assert [entry["url"] for entry in result] == [duplicate_url, duplicate_url]
    assert result[0]["published_date"] == "2026-07-12"
    assert result[1]["published_date"] == "2026-07-11"
    assert result[0]["summary"] == "First summary"
    assert result[1]["summary"] == "Second description"
    for entry in result:
        assert entry["source"] == "TrendForce"
        assert entry["site"] == "TrendForce"
        assert entry["publisher"] == "TrendForce集邦咨询"
        assert entry["category"] == "Semiconductors"
        assert entry["ticker"] == "MU"
    assert [call[0] for call in request_calls] == CHINESE_URLS + ENGLISH_URLS
    assert all(call[1]["timeout"] == 6 for call in request_calls)
    assert parse_calls == [b"rss-content"]


@pytest.mark.parametrize("limit, expected_count", [(2, 2), (20, 10), (0, 10)])
def test_limit_truncation_and_ten_item_cap(monkeypatch, limit, expected_count):
    source_items = [item(number) for number in range(1, 13)]
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: FakeResponse(text="html"))
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", lambda *args, **kwargs: source_items)
    monkeypatch.setattr(
        dashboard,
        "_trendforce_items_from_regex",
        lambda *args, **kwargs: pytest.fail("regex must not run"),
    )
    monkeypatch.setattr(
        dashboard.feedparser,
        "parse",
        lambda *args, **kwargs: pytest.fail("RSS must not run"),
    )
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    result = dashboard.get_trendforce_news(limit=limit)

    assert result == source_items[:expected_count]


def test_timeouts_status_errors_and_parser_errors_do_not_interrupt_source_sequence(monkeypatch):
    request_calls = []
    responses = {
        CHINESE_URLS[0]: TimeoutError("timeout"),
        CHINESE_URLS[1]: FakeResponse(status_error=RuntimeError("HTTP 503")),
        CHINESE_URLS[2]: FakeResponse(text="malformed"),
        CHINESE_URLS[3]: RuntimeError("connection failed"),
        ENGLISH_URLS[0]: FakeResponse(status_error=RuntimeError("HTTP 500")),
        ENGLISH_URLS[1]: FakeResponse(text="empty"),
        ENGLISH_URLS[2]: FakeResponse(content=b"empty-rss"),
    }

    def fake_get(url, **kwargs):
        request_calls.append((url, kwargs))
        result = responses[url]
        if isinstance(result, Exception):
            raise result
        return result

    def fake_soup(page_html, base_url, homepage=False):
        if page_html == "malformed":
            raise ValueError("parser failed")
        return []

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", fake_soup)
    monkeypatch.setattr(
        dashboard,
        "_trendforce_items_from_regex",
        lambda *args, **kwargs: pytest.fail("regex must not run when soup raises or returns []"),
    )
    monkeypatch.setattr(dashboard.feedparser, "parse", lambda content: SimpleNamespace(entries=[]))
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    assert dashboard.get_trendforce_news() == []
    assert [call[0] for call in request_calls] == CHINESE_URLS + ENGLISH_URLS
    assert all(call[1] == {"headers": {"User-Agent": "Mozilla/5.0"}, "timeout": 6} for call in request_calls)


def test_feedparser_is_not_called_for_non_rss_english_pages(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        return FakeResponse(text=url, content=b"not-rss")

    def fake_parse(content):
        calls.append(content)
        return SimpleNamespace(entries=[])

    monkeypatch.setattr(dashboard.requests, "get", fake_get)
    monkeypatch.setattr(dashboard, "_trendforce_items_from_soup", lambda *args, **kwargs: [])
    monkeypatch.setattr(dashboard, "_trendforce_items_from_regex", lambda *args, **kwargs: [])
    monkeypatch.setattr(dashboard.feedparser, "parse", fake_parse)
    monkeypatch.setattr(dashboard, "track_api_call", lambda name: None)

    assert dashboard.get_trendforce_news() == []
    assert calls == [b"not-rss"]
