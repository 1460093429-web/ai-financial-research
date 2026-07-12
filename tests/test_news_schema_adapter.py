import builtins
from copy import deepcopy

import pytest

from services.news_schema import NEWS_SCHEMA_KEYS, normalize_news_item, normalize_news_items


EXPECTED_KEYS = set(NEWS_SCHEMA_KEYS)


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import requests
    import yfinance
    import openai

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def test_yahoo_item_converts_to_unified_schema():
    item = {
        "title": "Yahoo title",
        "text": "Yahoo summary",
        "url": "https://finance.yahoo.com/item",
        "source": "Yahoo/yfinance",
        "publisher": "Yahoo Publisher",
        "ticker": "NVDA",
        "related_tickers": "NVDA, MU, NVDA",
        "published_date": "2026-07-13T01:00:00Z",
    }

    result = normalize_news_item(item)

    assert set(result) == EXPECTED_KEYS
    assert result == {
        "title": "Yahoo title",
        "summary": "Yahoo summary",
        "url": "https://finance.yahoo.com/item",
        "source": "Yahoo/yfinance",
        "publisher": "Yahoo Publisher",
        "site": None,
        "category": None,
        "ticker": "NVDA",
        "related_tickers": ["NVDA", "MU"],
        "published_at": "2026-07-13T01:00:00Z",
        "retrieved_at": None,
        "is_fallback": False,
        "fallback_from": None,
        "provider": "yahoo",
        "raw_provider": None,
        "credibility": None,
        "sentiment": None,
    }


def test_trendforce_item_converts_without_fabricating_credibility_score():
    item = {
        "title": "TrendForce title",
        "summary": "TrendForce summary",
        "url": "https://trendforce.example/item",
        "source": "TrendForce",
        "site": "TrendForce",
        "publisher": "TrendForce集邦咨询",
        "category": "Semiconductors",
        "ticker": "MU",
        "related_ticker": "MU",
        "publishedDate": "2026-07-13",
        "credibility": "TrendForce",
        "sentiment": "中性",
    }

    result = normalize_news_item(item)

    assert set(result) == EXPECTED_KEYS
    assert result["provider"] == "trendforce"
    assert result["related_tickers"] == ["MU"]
    assert result["published_at"] == "2026-07-13"
    assert result["credibility"] is None
    assert result["sentiment"] == "中性"
    assert result["is_fallback"] is False


def test_fmp_item_converts_with_primary_ticker_as_related_ticker():
    item = {
        "title": "FMP title",
        "text": "FMP text",
        "url": "https://fmp.example/item",
        "source": "FMP",
        "publisher": "FMP Publisher",
        "ticker": "nvda",
        "published_date": "2026-07-13",
    }

    result = normalize_news_item(item)

    assert result["provider"] == "fmp"
    assert result["source"] == "FMP"
    assert result["ticker"] == "NVDA"
    assert result["related_tickers"] == ["NVDA"]
    assert result["summary"] == "FMP text"


def test_yfinance_fallback_item_gets_explicit_fallback_metadata():
    result = normalize_news_item({
        "title": "Fallback title",
        "source": "yfinance fallback",
        "ticker": "MU",
    })

    assert result["provider"] == "yahoo"
    assert result["source"] == "yfinance fallback"
    assert result["is_fallback"] is True
    assert result["fallback_from"] == "fmp"


def test_missing_fields_and_non_dict_input_return_complete_empty_schema():
    missing = normalize_news_item({}, provider="Yahoo")
    non_dict = normalize_news_item(None)

    assert set(missing) == EXPECTED_KEYS
    assert missing["source"] == "Yahoo"
    assert missing["provider"] == "yahoo"
    assert missing["related_tickers"] == []
    assert missing["is_fallback"] is False
    assert missing["fallback_from"] is None
    assert missing["retrieved_at"] is None
    assert set(non_dict) == EXPECTED_KEYS
    assert non_dict["source"] == "unavailable"
    assert non_dict["provider"] == "unknown"
    assert non_dict["related_tickers"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("published_at", "canonical"),
        ("published_date", "snake"),
        ("publishedDate", "camel"),
        ("date", "date"),
        ("timestamp", 1_700_000_000),
        ("published", "published"),
        ("updated", "updated"),
    ],
)
def test_published_at_supports_legacy_fields(field, value):
    result = normalize_news_item({field: value})

    assert result["published_at"] == str(value)


def test_publication_field_precedence_is_stable():
    result = normalize_news_item({
        "published_at": "canonical",
        "published_date": "snake",
        "publishedDate": "camel",
        "date": "date",
        "timestamp": "timestamp",
        "published": "published",
        "updated": "updated",
    })

    assert result["published_at"] == "canonical"


def test_adapter_returns_new_dict_and_does_not_mutate_nested_input():
    item = {
        "title": "Original",
        "related_tickers": ["NVDA", "MU"],
        "nested": {"unchanged": True},
    }
    before = deepcopy(item)

    result = normalize_news_item(item)

    assert item == before
    assert result is not item
    assert result["related_tickers"] is not item["related_tickers"]


def test_normalize_news_items_preserves_order_and_non_dict_positions():
    items = [{"title": "first"}, None, {"title": "third"}]

    result = normalize_news_items(items, provider="FMP")

    assert [item["title"] for item in result] == ["first", None, "third"]
    assert all(item["provider"] == "fmp" for item in result)


@pytest.mark.parametrize("items", [None, {}, "items", 1])
def test_normalize_news_items_unsupported_container_returns_empty(items):
    assert normalize_news_items(items) == []


def test_explicit_fields_are_preserved_without_overriding_source():
    result = normalize_news_item(
        {
            "source": "Legacy Source",
            "provider": "CustomProvider",
            "retrieved_at": "2026-07-13T03:00:00Z",
            "is_fallback": True,
            "fallback_from": "FMP",
            "raw_provider": "Raw Provider",
            "credibility": 87,
        },
        provider="Yahoo",
    )

    assert result["source"] == "Legacy Source"
    assert result["provider"] == "customprovider"
    assert result["retrieved_at"] == "2026-07-13T03:00:00Z"
    assert result["is_fallback"] is True
    assert result["fallback_from"] == "fmp"
    assert result["raw_provider"] == "Raw Provider"
    assert result["credibility"] == 87.0
