"""Static, non-production fixtures for manually inspecting news diagnostics."""

from components.news_diagnostics import render_news_schema_diagnostics_if_enabled


def _normalized_item(
    *,
    title,
    summary,
    url,
    source,
    publisher,
    site,
    category,
    ticker,
    related_tickers,
    published_at,
    provider,
    is_fallback=False,
    fallback_from=None,
):
    return {
        "title": title,
        "summary": summary,
        "url": url,
        "source": source,
        "publisher": publisher,
        "site": site,
        "category": category,
        "ticker": ticker,
        "related_tickers": list(related_tickers),
        "published_at": published_at,
        "retrieved_at": None,
        "is_fallback": is_fallback,
        "fallback_from": fallback_from,
        "provider": provider,
        "raw_provider": None,
        "credibility": None,
        "sentiment": None,
    }


def build_mock_news_diagnostics_envelopes() -> list[dict]:
    """Return fresh static envelopes without contacting any external system."""
    yahoo = {
        "title": "Mock Yahoo semiconductor update",
        "text": "Static Yahoo diagnostic summary.",
        "url": "https://example.invalid/mock-yahoo",
        "source": "Yahoo/yfinance",
        "publisher": "Mock Yahoo Publisher",
        "ticker": "NVDA",
        "related_tickers": "NVDA, MU",
        "published_date": "2026-01-01T09:00:00Z",
    }
    yahoo["_normalized"] = _normalized_item(
        title=yahoo["title"], summary=yahoo["text"], url=yahoo["url"],
        source=yahoo["source"], publisher=yahoo["publisher"], site=None,
        category=None, ticker="NVDA", related_tickers=["NVDA", "MU"],
        published_at=yahoo["published_date"], provider="yahoo",
    )

    trendforce = {
        "title": "Mock TrendForce memory update",
        "summary": "Static TrendForce diagnostic summary.",
        "url": "https://example.invalid/mock-trendforce",
        "source": "TrendForce",
        "site": "TrendForce",
        "publisher": "Mock TrendForce Publisher",
        "category": "Memory",
        "ticker": "MU",
        "related_tickers": "MU",
        "publishedDate": "2026-01-02",
    }
    trendforce["_normalized"] = _normalized_item(
        title=trendforce["title"], summary=trendforce["summary"], url=trendforce["url"],
        source=trendforce["source"], publisher=trendforce["publisher"],
        site=trendforce["site"], category=trendforce["category"], ticker="MU",
        related_tickers=["MU"], published_at=trendforce["publishedDate"],
        provider="trendforce",
    )

    fmp = {
        "title": "Mock FMP company update",
        "text": "Static FMP diagnostic summary.",
        "url": "https://example.invalid/mock-fmp",
        "source": "FMP",
        "site": "Mock FMP Publisher",
        "ticker": "AAPL",
        "publishedDate": "2026-01-03 10:00:00",
    }
    fmp["_normalized"] = _normalized_item(
        title=fmp["title"], summary=fmp["text"], url=fmp["url"], source=fmp["source"],
        publisher=None, site=fmp["site"], category=None, ticker="AAPL",
        related_tickers=["AAPL"], published_at=fmp["publishedDate"], provider="fmp",
    )

    fallback = {
        "title": "Mock yfinance fallback update",
        "text": "Static fallback diagnostic summary.",
        "url": "https://example.invalid/mock-fallback",
        "source": "yfinance fallback",
        "publisher": "Mock Fallback Publisher",
        "ticker": "MSFT",
        "published_date": "2026-01-04T11:00:00Z",
    }
    fallback["_normalized"] = _normalized_item(
        title=fallback["title"], summary=fallback["text"], url=fallback["url"],
        source=fallback["source"], publisher=fallback["publisher"], site=None,
        category=None, ticker="MSFT", related_tickers=["MSFT"],
        published_at=fallback["published_date"], provider="yahoo", is_fallback=True,
        fallback_from="fmp",
    )

    missing_schema = {
        "title": "Mock legacy item without normalized schema",
        "summary": "Static missing-schema diagnostic summary.",
        "source": "Mock Legacy",
        "date": "2026-01-05",
    }
    partial_schema = {
        "title": "Mock item with partial normalized schema",
        "text": "Static partial-schema legacy summary.",
        "source": "Mock Partial",
        "ticker": "DEMO",
        "timestamp": "2026-01-06T12:00:00Z",
        "_normalized": {
            "provider": "mock",
            "summary": "Deliberately different normalized summary.",
            "related_tickers": ["DEMO"],
        },
    }
    return [yahoo, trendforce, fmp, fallback, missing_schema, partial_schema]


def render_mock_news_diagnostics_demo(*, enabled=False, language="zh"):
    """Render static diagnostics only after explicit development opt-in."""
    if not enabled:
        return None
    envelopes = build_mock_news_diagnostics_envelopes()
    return render_news_schema_diagnostics_if_enabled(
        envelopes,
        enabled=True,
        language=language,
    )
