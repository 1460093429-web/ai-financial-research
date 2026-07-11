import builtins
import inspect

import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()
BASE_URL = "https://www.trendforce.com"


def test_dashboard_reexports_trendforce_parser_helpers():
    from services import news_normalization

    assert dashboard._trendforce_items_from_soup is news_normalization._trendforce_items_from_soup
    assert dashboard._trendforce_items_from_regex is news_normalization._trendforce_items_from_regex


def test_trendforce_parser_signatures_are_characterized():
    assert str(inspect.signature(dashboard._trendforce_items_from_soup)) == (
        "(page_html, base_url, homepage=False)"
    )
    assert str(inspect.signature(dashboard._trendforce_items_from_regex)) == "(page_html, base_url)"


@pytest.fixture(autouse=True)
def forbid_external_state(monkeypatch):
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(dashboard.feedparser, "parse", lambda *args, **kwargs: pytest.fail("feedparser must not run"))
    monkeypatch.setattr(dashboard.yf, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(dashboard, "get_openai_client", lambda: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(
        dashboard,
        "get_cached_trendforce_news",
        lambda *args, **kwargs: pytest.fail("cached TrendForce wrapper must not run"),
    )
    monkeypatch.setattr(
        dashboard,
        "get_trendforce_news",
        lambda *args, **kwargs: pytest.fail("TrendForce provider must not run"),
    )
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def test_soup_parser_preserves_article_order_urls_date_category_and_nearby_summary():
    page_html = """
      <section>
        <article>
          <a href="/presscenter/news/20260712-1.html">Micron HBM capacity expands</a>
          <time>2026年7月12日</time><span>半导体</span>
          <p>Capacity is scheduled to increase next year.</p>
        </article>
        <article>
          <a href="https://www.trendforce.com/presscenter/news/20260711-2.html">NVIDIA AI server demand grows</a>
          <time>11 July 2026</time><span>Emerging Technologies</span>
          <p>Server shipments remain strong.</p>
        </article>
      </section>
    """

    result = dashboard._trendforce_items_from_soup(page_html, BASE_URL)

    assert [item["title"] for item in result] == [
        "Micron HBM capacity expands",
        "NVIDIA AI server demand grows",
    ]
    assert [item["url"] for item in result] == [
        "https://www.trendforce.com/presscenter/news/20260712-1.html",
        "https://www.trendforce.com/presscenter/news/20260711-2.html",
    ]
    assert [item["published_date"] for item in result] == ["2026-07-12", "2026-07-11"]
    assert [item["category"] for item in result] == ["半导体", "Emerging Technologies"]
    assert "Capacity is scheduled to increase next year." in result[0]["summary"]
    assert "Server shipments remain strong." in result[1]["summary"]


def test_soup_parser_deduplicates_urls_and_filters_external_and_short_titles():
    page_html = """
      <a href="/presscenter/news/20260712-1.html">Micron HBM capacity expands</a>
      <a href="/presscenter/news/20260712-1.html">Duplicate title for same article</a>
      <a href="https://outside.example/presscenter/news/20260712-2.html">External TrendForce-shaped article</a>
      <a href="/presscenter/news/20260712-3.html">Short</a>
      <a href="/not-an-article">Micron article with invalid URL</a>
    """

    result = dashboard._trendforce_items_from_soup(page_html, BASE_URL)

    assert [item["url"] for item in result] == [
        "https://www.trendforce.com/presscenter/news/20260712-1.html"
    ]


def test_soup_homepage_limits_results_to_industry_insight_root():
    page_html = """
      <a href="/presscenter/news/20260701-9.html">Outside section article headline</a>
      <section id="industry">
        <h2>产业洞察</h2>
        <a href="/presscenter/news/20260712-1.html">Micron HBM industry insight</a>
        <a href="/presscenter/news/20260712-2.html">NVIDIA AI industry insight</a>
        <a href="/presscenter/news/20260712-3.html">TSMC foundry industry insight</a>
      </section>
    """

    result = dashboard._trendforce_items_from_soup(page_html, BASE_URL, homepage=True)

    assert [item["url"] for item in result] == [
        "https://www.trendforce.com/presscenter/news/20260712-1.html",
        "https://www.trendforce.com/presscenter/news/20260712-2.html",
        "https://www.trendforce.com/presscenter/news/20260712-3.html",
    ]


def test_soup_parser_returns_none_when_beautifulsoup_import_is_unavailable(monkeypatch):
    real_import = builtins.__import__

    def fail_bs4_import(name, *args, **kwargs):
        if name == "bs4":
            raise ImportError("bs4 unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_bs4_import)

    assert dashboard._trendforce_items_from_soup("<a>article</a>", BASE_URL) is None


@pytest.mark.parametrize("page_html", ["", "<div><a href='broken'>Malformed"])
def test_soup_parser_current_empty_and_malformed_html_behavior(page_html):
    assert dashboard._trendforce_items_from_soup(page_html, BASE_URL) == []


def test_soup_parser_current_none_html_behavior_raises_type_error():
    with pytest.raises(TypeError, match="Incoming markup is of an invalid type"):
        dashboard._trendforce_items_from_soup(None, BASE_URL)


def test_regex_parser_preserves_order_urls_and_deduplicates():
    page_html = """
      <div>2026年7月12日 半导体</div>
      <a href="/presscenter/news/20260712-1.html" title="Micron HBM capacity expands">first</a>
      <a href="https://www.trendforce.com/presscenter/news/20260711-2.html" title="NVIDIA AI server demand grows">second</a>
      <a href="/presscenter/news/20260712-1.html" title="Duplicate article headline">duplicate</a>
    """

    result = dashboard._trendforce_items_from_regex(page_html, BASE_URL)

    assert [item["title"] for item in result] == [
        "Micron HBM capacity expands",
        "NVIDIA AI server demand grows",
    ]
    assert [item["url"] for item in result] == [
        "https://www.trendforce.com/presscenter/news/20260712-1.html",
        "https://www.trendforce.com/presscenter/news/20260711-2.html",
    ]
    assert result[0]["published_date"] == "2026-07-12"
    assert result[0]["category"] == "半导体"
    assert result[0]["summary"] == result[0]["title"]


def test_regex_parser_current_external_invalid_and_short_link_behavior():
    page_html = """
      <a href="https://outside.example/presscenter/news/20260712-1.html">External article headline</a>
      <a href="/presscenter/news/20260712-2.html">Short</a>
      <a href="/invalid">Micron HBM article with invalid URL</a>
    """

    result = dashboard._trendforce_items_from_regex(page_html, BASE_URL)

    assert [item["url"] for item in result] == [
        "https://outside.example/presscenter/news/20260712-1.html"
    ]


@pytest.mark.parametrize("page_html", ["", None, "<a href='unterminated>Malformed"])
def test_regex_parser_current_empty_and_malformed_html_behavior(page_html):
    assert dashboard._trendforce_items_from_regex(page_html, BASE_URL) == []


def test_soup_and_regex_parsers_preserve_common_output_contract():
    page_html = """
      <article>
        <a href="/presscenter/news/20260712-1.html">Micron HBM capacity expands</a>
        <time>2026-07-12</time><span>Semiconductors</span>
      </article>
    """

    soup_item = dashboard._trendforce_items_from_soup(page_html, BASE_URL)[0]
    regex_item = dashboard._trendforce_items_from_regex(page_html, BASE_URL)[0]

    assert set(soup_item) == set(regex_item)
    for field in (
        "title",
        "url",
        "source",
        "site",
        "publisher",
        "ticker",
        "related_ticker",
        "related_tickers",
        "sentiment",
        "credibility",
    ):
        assert soup_item[field] == regex_item[field]
