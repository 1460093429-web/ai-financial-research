# Phase 2 News Provider Coverage Audit

Audit date: 2026-07-13. Phase 2.8 adds tests and documentation only; it does not move providers, cached wrappers, or fallback logic.

## Current provider and cache boundaries

There is no `get_cached_fmp_news` function. FMP company and general news are retrieved by `financials.fetch_company_news` and `financials.fetch_general_news`. Dashboard caching is owned by `get_cached_company_news`, `get_cached_watchlist_news`, and `get_cached_market_news`.

Yahoo's direct Dashboard path is `get_cached_yahoo_news`, which owns both the yfinance request and normalization call under one `st.cache_data(ttl=1800)` wrapper. `get_cached_watchlist_yahoo_news` aggregates per-ticker cached results.

TrendForce request/fallback orchestration is in `providers/trendforce.py`, while Dashboard retains the callback wrapper and `get_cached_trendforce_news` with `st.cache_data(ttl=1800)` and the cacheable-call debug counter.

## Current metadata and fallback consistency

- FMP company/general items use `source="FMP"`, `publisher` from publisher-or-site, and provider-supplied date strings.
- `financials.fetch_company_news` silently falls back to yfinance on missing keys, unusable FMP responses, request errors, or other exceptions. Those items use `source="yfinance fallback"`.
- Direct Dashboard Yahoo items use `source="Yahoo/yfinance"`, a comma-separated `related_tickers` field, and normalized numeric timestamps.
- TrendForce items use `source` and `site` equal to `TrendForce`, a fixed Chinese publisher label, duplicated ticker relationship fields, and both `publishedDate` and `published_date`.

The aggregation layer therefore does not expose one uniform provenance schema. Source labels distinguish FMP, direct Yahoo, Yahoo fallback, and TrendForce, but timestamp fields, related-ticker fields, fallback markers, and publisher availability vary. No path currently supplies a universal retrieval timestamp or boolean `is_fallback` field.

## Protected current behavior

Tests characterize Yahoo normal/empty/error/property fallback, ticker uppercasing, limits, source metadata, cache reuse, and current empty/`None` ticker behavior. FMP tests cover missing API key, valid/empty/error/non-200/schema-incomplete responses, yfinance fallback, limits, metadata, and Dashboard wrapper caching/counters. TrendForce cached-wrapper tests cover provider delegation, empty-result caching, exception propagation, cache clearing, and cacheable-call counting.

## Migration assessment

Do not move cached wrappers yet. Streamlit cache ownership and Dashboard debug counters remain application concerns. The smallest next provider candidate is the direct Yahoo request logic inside `get_cached_yahoo_news`, but it should first be split conceptually into an uncached provider function plus the unchanged Dashboard cache wrapper. Any migration must preserve the unusual `get_news(count=limit)` → no-argument TypeError retry → `stock.news` fallback sequence and current invalid ticker behavior.

FMP company news should not be moved independently from `financials.py`: it already lives outside Dashboard and combines FMP access with yfinance fallback. A future change should focus on explicit metadata contracts rather than relocating the same function.

## Protected areas

Continue to protect cache decorators and TTLs, debug counters, provider priority, API key access, request timeouts, source labels, fallback semantics, OpenAI workflows, Watchlist, session state, GEX and Option Wall, IBKR and What-if, valuation, and all financial calculations.
