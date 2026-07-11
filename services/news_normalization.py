"""Pure normalization helpers for already-retrieved Yahoo news items."""

from datetime import datetime


def _format_yfinance_datetime(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value).isoformat(timespec="seconds") + "Z"
    return str(value)


def _extract_yfinance_url(item, content):
    canonical_url = content.get("canonicalUrl") if isinstance(content, dict) else None
    click_url = content.get("clickThroughUrl") if isinstance(content, dict) else None
    if isinstance(canonical_url, dict) and canonical_url.get("url"):
        return canonical_url.get("url")
    if isinstance(click_url, dict) and click_url.get("url"):
        return click_url.get("url")
    return item.get("link") or item.get("url")


def _normalize_yfinance_news_item(item, ticker):
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    title = content.get("title") or item.get("title")
    if not title:
        return None
    related_tickers = content.get("finance") or item.get("relatedTickers") or item.get("tickers") or [ticker]
    if isinstance(related_tickers, dict):
        related_tickers = related_tickers.get("stockTickers") or related_tickers.get("tickers") or [ticker]
    if not isinstance(related_tickers, (list, tuple)):
        related_tickers = [ticker]
    related_tickers = [str(symbol).upper() for symbol in related_tickers if symbol]
    if ticker not in related_tickers:
        related_tickers.insert(0, ticker)
    return {
        "title": title,
        "text": content.get("summary") or item.get("summary") or "",
        "published_date": _format_yfinance_datetime(
            content.get("pubDate") or item.get("providerPublishTime") or item.get("published")
        ),
        "url": _extract_yfinance_url(item, content),
        "publisher": provider.get("displayName") or content.get("providerName") or item.get("publisher"),
        "source": "Yahoo/yfinance",
        "ticker": ticker,
        "related_tickers": ", ".join(dict.fromkeys(related_tickers)),
    }
