"""Uncached Yahoo Finance news retrieval."""

import yfinance as yf

from services.news_normalization import _normalize_yfinance_news_item


def fetch_yahoo_news(ticker, limit=10):
    ticker = ticker.upper()
    stock = yf.Ticker(ticker)
    raw_news = []
    try:
        raw_news = stock.get_news(count=limit) or []
    except TypeError:
        raw_news = stock.get_news() or []
    except Exception:
        raw_news = stock.news or []
    if not raw_news:
        try:
            raw_news = stock.news or []
        except Exception:
            raw_news = []
    normalized = []
    for item in raw_news:
        normalized_item = _normalize_yfinance_news_item(item, ticker)
        if normalized_item:
            normalized.append(normalized_item)
        if len(normalized) >= limit:
            break
    return normalized
