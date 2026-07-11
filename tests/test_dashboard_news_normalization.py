import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: pytest.fail("OpenAI must not run"))


def test_yahoo_news_normalization_preserves_nested_field_priority_and_source():
    item = {
        "title": "legacy title",
        "summary": "legacy summary",
        "link": "https://legacy.example/item",
        "publisher": "Legacy Publisher",
        "providerPublishTime": 1,
        "relatedTickers": ["LEGACY"],
        "content": {
            "title": "Nested title",
            "summary": "Nested summary",
            "pubDate": 1_700_000_000,
            "canonicalUrl": {"url": "https://canonical.example/item"},
            "clickThroughUrl": {"url": "https://click.example/item"},
            "provider": {"displayName": "Nested Publisher"},
            "finance": {"stockTickers": ["mu", "NVDA", "mu"]},
        },
    }

    with pytest.warns(DeprecationWarning, match="utcfromtimestamp"):
        result = dashboard._normalize_yfinance_news_item(item, "NVDA")

    assert result == {
        "title": "Nested title",
        "text": "Nested summary",
        "published_date": "2023-11-14T22:13:20Z",
        "url": "https://canonical.example/item",
        "publisher": "Nested Publisher",
        "source": "Yahoo/yfinance",
        "ticker": "NVDA",
        "related_tickers": "MU, NVDA",
    }


@pytest.mark.parametrize("item", [None, [], "news", 1, {}])
def test_yahoo_news_normalization_rejects_non_mapping_or_missing_title(item):
    assert dashboard._normalize_yfinance_news_item(item, "MU") is None


def test_yahoo_news_normalization_preserves_empty_optional_fields_and_ticker_default():
    result = dashboard._normalize_yfinance_news_item({"title": "Title only"}, "MU")

    assert result == {
        "title": "Title only",
        "text": "",
        "published_date": None,
        "url": None,
        "publisher": None,
        "source": "Yahoo/yfinance",
        "ticker": "MU",
        "related_tickers": "MU",
    }


def test_yahoo_news_normalization_uses_flat_summary_url_publisher_and_date_string():
    item = {
        "title": "Flat title",
        "summary": "Flat summary",
        "url": "https://flat.example/item",
        "publisher": "Flat Publisher",
        "published": "2026-07-12T08:30:00Z",
        "tickers": "not-a-list",
    }

    result = dashboard._normalize_yfinance_news_item(item, "SNDK")

    assert result["text"] == "Flat summary"
    assert result["url"] == "https://flat.example/item"
    assert result["publisher"] == "Flat Publisher"
    assert result["published_date"] == "2026-07-12T08:30:00Z"
    assert result["related_tickers"] == "SNDK"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (0, None), (1_700_000_000, "2023-11-14T22:13:20Z"), ("2026/07/12", "2026/07/12")],
)
def test_yahoo_datetime_formatting_current_behavior(value, expected):
    if isinstance(value, (int, float)) and value:
        with pytest.warns(DeprecationWarning, match="utcfromtimestamp"):
            assert dashboard._format_yfinance_datetime(value) == expected
    else:
        assert dashboard._format_yfinance_datetime(value) == expected


def test_trendforce_text_and_date_normalization_support_current_formats():
    assert dashboard._clean_trendforce_text("  A &amp; B <b>HBM</b>\n news ") == "A & B HBM news"
    assert dashboard._extract_trendforce_date("发布于 2026年7月2日") == "2026-07-02"
    assert dashboard._extract_trendforce_date("2 July 2026") == "2026-07-02"
    assert dashboard._extract_trendforce_date("date unavailable") == ""


def test_trendforce_item_preserves_defaults_summary_fallback_and_source_metadata():
    result = dashboard._build_trendforce_item(
        " <b>Micron expands HBM production</b> ",
        "https://www.trendforce.com/presscenter/news/20260712-1.html",
    )

    assert result["title"] == "Micron expands HBM production"
    assert result["summary"] == result["title"]
    assert result["text"] == result["title"]
    assert result["publishedDate"] == ""
    assert result["published_date"] == ""
    assert result["category"] == "产业洞察"
    assert result["source"] == "TrendForce"
    assert result["site"] == "TrendForce"
    assert result["publisher"] == "TrendForce集邦咨询"
    assert result["ticker"] == "MU"
    assert result["sentiment"] == "中性"


@pytest.mark.parametrize(
    ("title", "url"),
    [("", "https://www.trendforce.com/presscenter/news/20260712-1.html"), ("Title", ""), (None, None)],
)
def test_trendforce_item_rejects_missing_title_or_url(title, url):
    assert dashboard._build_trendforce_item(title, url) is None


def test_trendforce_regex_parser_deduplicates_repeated_article_urls():
    url = "/presscenter/news/20260712-1.html"
    page_html = f"""
      <a href="{url}" title="Micron HBM production expands rapidly">first</a>
      <a href="{url}" title="Duplicate Micron HBM headline">second</a>
    """

    result = dashboard._trendforce_items_from_regex(page_html, "https://www.trendforce.com")

    assert len(result) == 1
    assert result[0]["url"] == "https://www.trendforce.com/presscenter/news/20260712-1.html"
    assert result[0]["source"] == "TrendForce"
