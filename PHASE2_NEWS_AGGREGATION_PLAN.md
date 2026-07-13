# Phase 2 News Aggregation Boundary Plan

Audit date: 2026-07-13. This phase adds characterization tests and documentation only. The unified adapter remains disconnected from providers, Dashboard caches, aggregation, and UI.

## Current news data flow

```text
Yahoo provider
  -> dashboard.get_cached_yahoo_news
  -> get_cached_watchlist_yahoo_news
  -> render_yahoo_news_section / render_standard_news_card

TrendForce provider
  -> dashboard.get_trendforce_news callback wrapper
  -> get_cached_trendforce_news
  -> render_trendforce_news_section / render_standard_news_card

financials.fetch_company_news (FMP -> yfinance fallback)
  -> get_cached_company_news
  -> get_cached_watchlist_news
  -> render_fmp_news_section / render_standard_news_card

financials.fetch_general_news
  -> get_cached_market_news
  -> render_fmp_news_section / render_standard_news_card

services.news_schema adapter
  -> not connected
```

Dashboard cached wrappers currently store and return legacy provider items. They add cache/debug behavior but do not add a unified schema, retrieval timestamp, provider identifier, or explicit fallback fields.

## Current legacy field dependencies

- Card title: `title`, otherwise translated untitled label.
- Body text: `summary` -> `text` -> `description`.
- Link: `url` only. A legacy `link` field is not read by the card.
- Display source: `source` -> `source_type` -> `site` -> translated unknown source.
- Display publisher: `publisher` -> `site` -> `source_name` -> translated unknown publisher.
- Display/sort date: `published_date` -> `publishedDate`. `date` and `timestamp` are not used by `_news_sort_key` or the standard card.
- Related ticker caption: `related_tickers` -> `ticker` -> translated Market. Singular `related_ticker` alone is ignored by the standard card.
- Filtering: FMP section reads `source`, `ticker`, and calculated `sentiment`; Yahoo grouping is keyed by requested ticker.
- Yahoo scoring and ticker digest read `title`, `publisher`, `published_date`, `text`, `ticker`, and `url`.
- TrendForce section supplies missing `source`/`sentiment`, filters missing titles, sorts by legacy date keys, and limits to 20.

Fields such as `symbols`, `date`, `timestamp`, and `link` may occur upstream but are not general aggregation aliases today. This is intentional characterization, not a recommendation.

## Cache and fallback boundaries

Cache keys are determined by current wrapper signatures: ticker and limit for company/direct Yahoo, ticker tuples and per-ticker limits for watchlist aggregation, and limit for market/TrendForce. Language is not a cache argument because cached items are not translated UI output.

The wrappers execute `track_cacheable_call` only on cache misses. Company and market wrappers catch provider exceptions and return an empty list. Per-ticker watchlist wrappers isolate failures. TrendForce cached wrapper currently propagates provider exceptions. FMP-to-yfinance fallback is encoded only as `source="yfinance fallback"`; the UI treats it as a filter/display label, not a boolean fallback state.

## Adapter integration risks

- Replacing `text` with `summary` would affect Yahoo scoring, ticker digests, AI inputs, and card body selection.
- Replacing `published_date`/`publishedDate` with `published_at` would make current sorting and captions show items as undated.
- Converting `related_tickers` to a list would make the current caption render Python list syntax unless the UI changes.
- Replacing user-visible source labels would alter filters, captions, and fallback visibility.
- Putting unified items in existing caches changes cached value contracts and may require cache invalidation/versioning.
- Current language behavior is applied after cache reads; adapting translated values inside cache would change cache keys.

## Recommended integration pattern

Do not replace or mutate legacy items. First add a parallel view at one non-provider boundary, for example:

```python
{
    **legacy_item,
    "_normalized": normalize_news_item(legacy_item, provider="yahoo"),
}
```

The legacy fields remain authoritative for existing pages. New diagnostics or a new component can read `_normalized`. Do not add the parallel field inside existing cached providers until cache-value compatibility and invalidation are explicitly approved. Prefer assembling it after cache retrieval in a pure, separately tested function.

## Phase 2.13 recommendation

Keep the adapter disconnected from production for one more step. Add a pure parallel-envelope helper and tests using captured Yahoo, TrendForce, FMP, and fallback fixtures, but do not call it from existing pages or cached wrappers. Only after equivalence tests confirm legacy rendering inputs should a new diagnostic component optionally consume the normalized view.

## Phase 2.14 diagnostics

`components/news_diagnostics.py` provides an inactive diagnostics surface with a pure row builder and a thin Streamlit renderer. It compares legacy source, publisher, summary/date/related-ticker fields with the `_normalized` view and exposes explicit match flags. Missing or partial schemas are displayed safely. The component accepts only caller-supplied envelopes and is not imported by Dashboard, providers, caches, aggregation, routing, or existing news pages.

## Phase 2.15 development gate

`dashboard_support/dev_mode.py` defines a caller-supplied, default-off diagnostics gate. An explicit `config["enable_news_diagnostics"]` value is authoritative; when that key is absent, only a passed `env["ENABLE_NEWS_DIAGNOSTICS"]` value of `1` or `true` enables diagnostics. The helper never reads the process environment, Streamlit secrets, or session state. The diagnostics component also exposes an opt-in wrapper that returns before processing envelopes or calling Streamlit when disabled. Neither helper is imported by Dashboard or connected to production routing.

## Phase 2.16 static mock demo

`components/news_diagnostics_demo.py` supplies fresh, static development fixtures for Yahoo, TrendForce, FMP, FMP-to-yfinance fallback, missing-schema, and partial-schema diagnostics. Its renderer is default-off and returns before constructing fixtures; explicit enablement delegates only to the existing gated diagnostics renderer. The module does not read environment configuration or call providers, caches, OpenAI, network services, or file I/O, and it remains disconnected from Dashboard, sidebar, routing, and production news pages.

## Phase 3.0 technology daily brief

The News & Sentiment source selector is followed by one on-demand Technology & Semiconductor Daily Brief card, before the selected legacy news list. Generation reuses the existing Watchlist and cached FMP, Yahoo, TrendForce, and market-news boundaries; it does not change provider or cache ownership. ETF.com remains available as an existing source tab but is not fetched separately for the brief because its cache key depends on controls local to that tab. A deterministic service normalizes, filters, deduplicates, ranks, and selects at most eight source-diverse candidates before calling the existing OpenAI client with `gpt-4o-mini`.

The AI result cache has a six-hour TTL and keys on candidate JSON, page language, current date, candidate fingerprint, and an explicit regeneration nonce. No news or AI work occurs until the user clicks Generate; regeneration increments the nonce. Existing cards, source selection, sorting, translation, detailed summaries, scoring, and legacy fields remain authoritative and unchanged.
