# Unified News Metadata Schema

Design date: 2026-07-13. This document describes a future compatibility contract. It does not change Yahoo, TrendForce, FMP, Dashboard cache wrappers, fallback behavior, or current provider output.

## Current output inventory

### Direct Yahoo Dashboard path

`providers.yahoo_news.fetch_yahoo_news` delegates item normalization to `services.news_normalization._normalize_yfinance_news_item`. A normalized item has:

- `title`, `text`, `published_date`, `url`, `publisher`
- `source="Yahoo/yfinance"`
- `ticker`
- `related_tickers` as one comma-separated string, not a list

There is no `summary`, `site`, `category`, `provider`, `raw_provider`, `is_fallback`, `fallback_from`, `retrieved_at`, `credibility`, or `sentiment` field. Numeric dates are converted to a UTC-looking ISO string; provider date strings otherwise remain unchanged.

### TrendForce path

TrendForce normalized items have:

- `title`, `summary`, `text`, `url`
- both `publishedDate` and `published_date`
- `source="TrendForce"`, `site="TrendForce"`, fixed `publisher="TrendForce集邦咨询"`
- `category`, `ticker`, `related_ticker`, and `related_tickers` as strings
- `sentiment="中性"` and `credibility="TrendForce"`

There is no explicit provider identifier separate from source, no retrieval timestamp, and no fallback metadata. The RSS branch preserves repeated URLs; HTML parsers deduplicate by URL.

### FMP company and general news

`financials.fetch_company_news` and `fetch_general_news` return:

- `title`, `text`, `published_date`, `url`, `publisher`
- `source="FMP"`
- `ticker` (requested symbol for company news; `Market` for general news)

Company news catches FMP failures, missing API keys, and empty/unusable responses, then attempts yfinance. Those fallback items keep the same seven-key shape but use `source="yfinance fallback"`. There is no boolean fallback marker or `fallback_from` field. If both providers fail, the function returns an empty list.

Dashboard wrappers add caching and debug counters but do not enrich item metadata. `get_cached_watchlist_news` concatenates per-ticker FMP/fallback results in ticker order. `get_cached_market_news` returns FMP general results or an empty list; it has no Yahoo fallback.

## Recommended future schema

Every adapter-produced item should contain the same keys, even when nullable:

```python
{
    "title": str | None,
    "summary": str | None,
    "url": str | None,
    "source": str,
    "publisher": str | None,
    "site": str | None,
    "category": str | None,
    "ticker": str | None,
    "related_tickers": list[str],
    "published_at": str | None,
    "retrieved_at": str | None,
    "is_fallback": bool,
    "fallback_from": str | None,
    "provider": str,
    "raw_provider": str | None,
    "credibility": float | None,
    "sentiment": str | None,
}
```

The key set is required; nullable values are allowed. `source`, `provider`, `related_tickers`, and `is_fallback` must always be non-null. Missing values must remain unavailable and must never be invented.

## Field semantics

- `provider`: stable machine identifier such as `yahoo`, `fmp`, or `trendforce`.
- `source`: user-visible provenance label. Initially preserve current labels exactly.
- `raw_provider`: upstream provider/publisher label when supplied separately from the normalized provider.
- `summary`: current `summary`, then current `text`; do not generate or call AI in the adapter.
- `related_tickers`: ordered, deduplicated list. Preserve the primary ticker first when current behavior does so.
- `published_at`: upstream observation/publication time normalized only when parsing is unambiguous. Prefer ISO 8601 with timezone; retain `None` rather than guessing a timezone.
- `retrieved_at`: UTC time when the provider response was obtained. It must not be derived from publication time or cache-read time.
- `is_fallback`: true only when the selected item came from a secondary source in the workflow.
- `fallback_from`: machine provider identifier that failed or returned unusable data; otherwise `None`.
- `credibility`: numeric normalized score only. Current string labels such as TrendForce's `"TrendForce"` require a compatibility decision and must not be coerced into a fabricated score.
- `sentiment`: normalized label when already available; no AI call in metadata adaptation.

## Compatibility mapping

| Current path | provider | source | is_fallback | fallback_from |
| --- | --- | --- | --- | --- |
| Direct Yahoo | `yahoo` | `Yahoo/yfinance` | `False` | `None` |
| FMP success | `fmp` | `FMP` | `False` | `None` |
| FMP company → Yahoo | `yahoo` | `yfinance fallback` | `True` | `fmp` |
| TrendForce HTML/RSS | `trendforce` | `TrendForce` | `False` | `None` |

This mapping is a proposal for a future adapter and is not current runtime behavior.

## Adapter rollout plan

1. Add pure adapter functions alongside characterization fixtures; do not call them from production.
2. Test adapters against captured current Yahoo, TrendForce, FMP-success, and FMP-fallback items.
3. Preserve legacy fields temporarily through an explicit compatibility view if a consumer needs them.
4. Introduce adapters at one aggregation boundary, without changing provider requests or cache ownership.
5. Update UI consumers only after all three languages, missing states, provenance, and fallback labels are verified.

Do not migrate FMP merely to implement this schema. Its request and fallback workflow already belongs outside Dashboard. Provider relocation and metadata adaptation are separate concerns.

## Risks requiring explicit decisions

- Date-only and timezone-free provider strings cannot be safely converted to UTC without extra provenance.
- Current Yahoo and TrendForce `related_tickers` values are strings with different delimiters/meanings.
- TrendForce `credibility` is a provider label, not a numeric score.
- Current FMP fallback is encoded only in the source label.
- Cached responses have no original retrieval timestamp, so adapters cannot honestly reconstruct one.
- Adding retrieval time inside cached functions would affect cache values and must be designed separately.
