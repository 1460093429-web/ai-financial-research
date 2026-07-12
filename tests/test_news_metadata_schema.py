import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()
import financials
from services.news_normalization import _build_trendforce_item, _normalize_yfinance_news_item


CURRENT_COMMON_KEYS = {
    "title",
    "text",
    "published_date",
    "url",
    "publisher",
    "source",
    "ticker",
}

FUTURE_NEWS_SCHEMA_KEYS = {
    "title",
    "summary",
    "url",
    "source",
    "publisher",
    "site",
    "category",
    "ticker",
    "related_tickers",
    "published_at",
    "retrieved_at",
    "is_fallback",
    "fallback_from",
    "provider",
    "raw_provider",
    "credibility",
    "sentiment",
}

FUTURE_NON_NULL_KEYS = {"source", "provider", "related_tickers", "is_fallback"}


def test_future_schema_design_has_stable_required_and_non_null_partitions():
    assert len(FUTURE_NEWS_SCHEMA_KEYS) == 17
    assert FUTURE_NON_NULL_KEYS < FUTURE_NEWS_SCHEMA_KEYS
    assert {"published_at", "retrieved_at", "is_fallback", "fallback_from"} <= FUTURE_NEWS_SCHEMA_KEYS


def test_current_yahoo_item_field_contract_and_missing_metadata():
    result = _normalize_yfinance_news_item(
        {
            "content": {
                "title": "Yahoo title",
                "summary": "Yahoo summary",
                "pubDate": "2026-07-13T01:00:00Z",
                "canonicalUrl": {"url": "https://finance.yahoo.com/item"},
                "provider": {"displayName": "Yahoo Publisher"},
                "finance": {"stockTickers": ["NVDA", "MU"]},
            }
        },
        "NVDA",
    )

    assert set(result) == CURRENT_COMMON_KEYS | {"related_tickers"}
    assert result["source"] == "Yahoo/yfinance"
    assert result["publisher"] == "Yahoo Publisher"
    assert result["published_date"] == "2026-07-13T01:00:00Z"
    assert result["ticker"] == "NVDA"
    assert result["related_tickers"] == "NVDA, MU"
    assert isinstance(result["related_tickers"], str)
    assert FUTURE_NEWS_SCHEMA_KEYS - set(result) == {
        "summary", "site", "category", "published_at", "retrieved_at", "is_fallback",
        "fallback_from", "provider", "raw_provider", "credibility", "sentiment",
    }


def test_current_trendforce_item_field_contract_and_metadata_types():
    result = _build_trendforce_item(
        "Micron HBM expansion",
        "https://www.trendforce.com/presscenter/news/20260713-1.html",
        "2026-07-13",
        "Semiconductors",
        "TrendForce summary",
    )

    assert set(result) == {
        "title", "publishedDate", "published_date", "category", "site", "source",
        "publisher", "ticker", "related_ticker", "related_tickers", "summary", "text",
        "url", "sentiment", "credibility",
    }
    assert result["source"] == result["site"] == "TrendForce"
    assert result["publisher"] == "TrendForce集邦咨询"
    assert result["publishedDate"] == result["published_date"] == "2026-07-13"
    assert result["related_ticker"] == result["related_tickers"] == result["ticker"] == "MU"
    assert isinstance(result["related_tickers"], str)
    assert result["credibility"] == "TrendForce"
    assert isinstance(result["credibility"], str)
    assert {"published_at", "retrieved_at", "is_fallback", "fallback_from", "provider", "raw_provider"}.isdisjoint(result)


def test_current_fmp_company_item_field_contract(monkeypatch):
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(
        financials,
        "_fmp_get",
        lambda *args, **kwargs: [{
            "title": "FMP title",
            "text": "FMP text",
            "publishedDate": "2026-07-13",
            "url": "https://fmp.example/item",
            "site": "FMP Site",
        }],
    )
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: pytest.fail("fallback must not run"))

    result = financials.fetch_company_news("nvda", 1)[0]

    assert set(result) == CURRENT_COMMON_KEYS
    assert result["source"] == "FMP"
    assert result["publisher"] == "FMP Site"
    assert result["published_date"] == "2026-07-13"
    assert result["ticker"] == "NVDA"
    assert {"site", "category", "related_tickers", "retrieved_at", "is_fallback", "fallback_from", "provider"}.isdisjoint(result)


def test_current_fmp_general_item_uses_market_ticker(monkeypatch):
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: [{"title": "Market title"}])

    result = financials.fetch_general_news(1)[0]

    assert set(result) == CURRENT_COMMON_KEYS
    assert result["source"] == "FMP"
    assert result["ticker"] == "Market"
    assert result["publisher"] is None


def test_current_fmp_yahoo_fallback_has_same_shape_but_only_source_marks_fallback(monkeypatch):
    class Stock:
        news = [{
            "content": {
                "title": "Fallback title",
                "summary": "Fallback summary",
                "pubDate": "2026-07-13T02:00:00Z",
                "canonicalUrl": {"url": "https://finance.yahoo.com/fallback"},
                "provider": {"displayName": "Fallback Publisher"},
            }
        }]

    monkeypatch.setattr(
        financials,
        "get_fmp_api_key",
        lambda: (_ for _ in ()).throw(ValueError("missing key")),
    )
    monkeypatch.setattr(financials.yf, "Ticker", lambda ticker: Stock())

    result = financials.fetch_company_news("MU", 1)[0]

    assert set(result) == CURRENT_COMMON_KEYS
    assert result["source"] == "yfinance fallback"
    assert result["ticker"] == "MU"
    assert "is_fallback" not in result
    assert "fallback_from" not in result
    assert "provider" not in result


def test_current_news_paths_do_not_expose_retrieval_time_or_uniform_publication_key(monkeypatch):
    yahoo = _normalize_yfinance_news_item({"title": "Yahoo"}, "NVDA")
    trendforce = _build_trendforce_item("TrendForce title", "https://example.com/item")
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: [{"title": "FMP"}])
    fmp = financials.fetch_company_news("NVDA", 1)[0]

    for current in (yahoo, trendforce, fmp):
        assert "retrieved_at" not in current
        assert "published_at" not in current
    assert "publishedDate" not in yahoo
    assert "publishedDate" in trendforce
    assert "publishedDate" not in fmp


def test_current_source_labels_are_distinct_and_not_machine_provider_fields(monkeypatch):
    yahoo = _normalize_yfinance_news_item({"title": "Yahoo"}, "NVDA")
    trendforce = _build_trendforce_item("TrendForce title", "https://example.com/item")
    monkeypatch.setattr(financials, "get_fmp_api_key", lambda: "test-key")
    monkeypatch.setattr(financials, "_fmp_get", lambda *args, **kwargs: [{"title": "FMP"}])
    fmp = financials.fetch_company_news("NVDA", 1)[0]

    assert {yahoo["source"], trendforce["source"], fmp["source"]} == {
        "Yahoo/yfinance", "TrendForce", "FMP"
    }
    assert all("provider" not in current for current in (yahoo, trendforce, fmp))
