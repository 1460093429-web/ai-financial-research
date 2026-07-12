import builtins
from copy import deepcopy

import pytest

from services import news_schema
from services.news_schema import (
    NEWS_SCHEMA_KEYS,
    attach_normalized_news_item,
    attach_normalized_news_items,
)


EXPECTED_SCHEMA_KEYS = set(NEWS_SCHEMA_KEYS)


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import requests
    import yfinance
    import openai

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


@pytest.mark.parametrize(
    ("legacy", "provider", "expected_provider", "expected_fallback"),
    [
        (
            {
                "title": "Yahoo title", "text": "Yahoo text", "source": "Yahoo/yfinance",
                "ticker": "NVDA", "related_tickers": "NVDA, MU", "custom": "yahoo-legacy",
            },
            None,
            "yahoo",
            False,
        ),
        (
            {
                "title": "TrendForce title", "summary": "Trend summary", "source": "TrendForce",
                "site": "TrendForce", "ticker": "MU", "related_ticker": "MU", "category": "Semiconductors",
            },
            None,
            "trendforce",
            False,
        ),
        (
            {"title": "FMP title", "text": "FMP text", "source": "FMP", "ticker": "NVDA"},
            None,
            "fmp",
            False,
        ),
        (
            {"title": "Fallback title", "text": "Fallback", "source": "yfinance fallback", "ticker": "MU"},
            None,
            "yahoo",
            True,
        ),
    ],
)
def test_legacy_provider_items_are_preserved_with_unified_parallel_view(
    legacy, provider, expected_provider, expected_fallback
):
    before = deepcopy(legacy)

    result = attach_normalized_news_item(legacy, provider=provider)

    assert legacy == before
    assert result is not legacy
    assert {key: value for key, value in result.items() if key != "_normalized"} == legacy
    assert set(result["_normalized"]) == EXPECTED_SCHEMA_KEYS
    assert result["_normalized"]["provider"] == expected_provider
    assert result["_normalized"]["is_fallback"] is expected_fallback
    assert result["_normalized"]["retrieved_at"] is None


def test_provider_parameter_is_forwarded_to_normalize_news_item(monkeypatch):
    calls = []
    normalized = {key: None for key in NEWS_SCHEMA_KEYS}

    def fake_normalize(item, provider=None):
        calls.append((item, provider))
        return normalized

    monkeypatch.setattr(news_schema, "normalize_news_item", fake_normalize)
    legacy = {"title": "No source"}

    result = news_schema.attach_normalized_news_item(legacy, provider="Yahoo")

    assert calls == [(legacy, "Yahoo")]
    assert result == {"title": "No source", "_normalized": normalized}


def test_existing_normalized_field_is_overwritten_without_mutating_input():
    stale = {"provider": "stale", "unexpected": True}
    legacy = {"title": "Title", "source": "FMP", "_normalized": stale}
    before = deepcopy(legacy)

    result = attach_normalized_news_item(legacy)

    assert legacy == before
    assert result["_normalized"] is not stale
    assert set(result["_normalized"]) == EXPECTED_SCHEMA_KEYS
    assert result["_normalized"]["provider"] == "fmp"
    assert "unexpected" not in result["_normalized"]


def test_non_dict_single_item_returns_normalized_only_envelope():
    for value in (None, "news", 1, ["item"]):
        result = attach_normalized_news_item(value, provider="Yahoo")

        assert set(result) == {"_normalized"}
        assert set(result["_normalized"]) == EXPECTED_SCHEMA_KEYS
        assert result["_normalized"]["provider"] == "yahoo"
        assert result["_normalized"]["source"] == "Yahoo"


def test_batch_envelope_preserves_order_and_does_not_mutate_input_list():
    items = [
        {"title": "first", "source": "FMP"},
        {"title": "second", "source": "FMP"},
        {"title": "third", "source": "FMP"},
    ]
    before = deepcopy(items)

    result = attach_normalized_news_items(items)

    assert items == before
    assert result is not items
    assert [item["title"] for item in result] == ["first", "second", "third"]
    assert [item["_normalized"]["title"] for item in result] == ["first", "second", "third"]
    assert all(result[index] is not items[index] for index in range(len(items)))


def test_batch_envelope_preserves_non_dict_positions():
    result = attach_normalized_news_items([{"title": "first"}, None, {"title": "third"}], provider="FMP")

    assert [item.get("title") for item in result] == ["first", None, "third"]
    assert all(item["_normalized"]["provider"] == "fmp" for item in result)


@pytest.mark.parametrize("items", [None, {}, "items", 1, set()])
def test_batch_envelope_unsupported_container_returns_empty(items):
    assert attach_normalized_news_items(items) == []
