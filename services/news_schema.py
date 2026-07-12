"""Pure compatibility adapters for the proposed unified news schema."""

import math
from numbers import Real


NEWS_SCHEMA_KEYS = (
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
)


def _first_present(item, keys):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _provider_name(item, provider):
    current = item.get("provider") or provider
    if current:
        return str(current).strip().lower()
    source = str(item.get("source") or item.get("site") or "").strip().lower()
    if "yahoo" in source or "yfinance" in source:
        return "yahoo"
    if source == "fmp":
        return "fmp"
    if source == "trendforce":
        return "trendforce"
    return "unknown"


def _related_tickers(item, ticker):
    value = item.get("related_tickers")
    if value is None:
        value = item.get("related_ticker")
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    elif value is None:
        values = []
    else:
        values = [value]
    normalized = []
    for value in values:
        symbol = str(value or "").strip().upper()
        if symbol and symbol not in normalized:
            normalized.append(symbol)
    primary = str(ticker or "").strip().upper()
    if primary:
        if primary in normalized:
            normalized.remove(primary)
        normalized.insert(0, primary)
    return normalized


def _credibility(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def normalize_news_item(item: dict, provider: str | None = None) -> dict:
    """Return a new unified-schema dictionary without mutating the legacy item."""
    item = item if isinstance(item, dict) else {}
    ticker_value = item.get("ticker")
    ticker = str(ticker_value).strip().upper() if ticker_value not in (None, "") else None
    provider_name = _provider_name(item, provider)
    source_value = item.get("source") or item.get("site") or provider or "unavailable"
    source = str(source_value)
    inferred_fallback = source.strip().lower() == "yfinance fallback"
    explicit_fallback = item.get("is_fallback")
    is_fallback = bool(explicit_fallback) if explicit_fallback is not None else inferred_fallback
    fallback_from = item.get("fallback_from")
    if fallback_from is None and inferred_fallback:
        fallback_from = "fmp"
    published = _first_present(
        item,
        ("published_at", "published_date", "publishedDate", "date", "timestamp", "published", "updated"),
    )
    retrieved = item.get("retrieved_at")
    return {
        "title": item.get("title"),
        "summary": _first_present(item, ("summary", "text", "description")),
        "url": item.get("url") or item.get("link"),
        "source": source,
        "publisher": item.get("publisher"),
        "site": item.get("site"),
        "category": item.get("category"),
        "ticker": ticker,
        "related_tickers": _related_tickers(item, ticker),
        "published_at": None if published is None else str(published),
        "retrieved_at": None if retrieved is None else str(retrieved),
        "is_fallback": is_fallback,
        "fallback_from": None if fallback_from is None else str(fallback_from).strip().lower(),
        "provider": provider_name,
        "raw_provider": item.get("raw_provider"),
        "credibility": _credibility(item.get("credibility")),
        "sentiment": item.get("sentiment"),
    }


def normalize_news_items(items: list[dict], provider: str | None = None) -> list[dict]:
    """Normalize a list or tuple in order; unsupported containers return empty."""
    if not isinstance(items, (list, tuple)):
        return []
    return [normalize_news_item(item, provider=provider) for item in items]


def attach_normalized_news_item(item: dict, provider: str | None = None) -> dict:
    """Return a new legacy envelope with a freshly generated normalized view."""
    legacy = dict(item) if isinstance(item, dict) else {}
    legacy["_normalized"] = normalize_news_item(item, provider=provider)
    return legacy


def attach_normalized_news_items(items: list[dict], provider: str | None = None) -> list[dict]:
    """Attach normalized views in order; unsupported containers return empty."""
    if not isinstance(items, (list, tuple)):
        return []
    return [attach_normalized_news_item(item, provider=provider) for item in items]
