# Phase 2 Component and Service Plan

Phase 2.0 adds characterization tests only. It does not move Dashboard functions or change UI, provider, fallback, cache, session state, file I/O, or financial behavior.

## First component candidates

### `render_snapshot_card`

This function renders one self-contained stock-card HTML fragment. Its dependencies are limited to the supplied container, the existing translation lookup, and formatting helpers. Tests must preserve its signature, single Markdown call, `unsafe_allow_html=True`, HTML class names, field order, positive/negative colors, missing-value output, and English/Chinese/Spanish labels.

Risk: HTML is user-visible, translations depend on session language, and callers expect the existing snapshot schema. The component must not fetch its own data after extraction.

### `render_metric_row`

This function converts a sequence of metric tuples into Streamlit columns and ordered `metric()` calls. Tests must preserve column count, tuple order, optional delta handling, explicit falsey deltas such as zero, and its `None` return.

Risk: small layout changes are visible. The extraction must continue using the caller-provided metric ordering and must not add formatting or defaults.

These components are better first targets than a page because they do not own provider selection, caching, fallback, or financial calculations.

## First service candidates

### Yahoo news normalization

Candidate helpers are `_format_yfinance_datetime`, `_extract_yfinance_url`, and `_normalize_yfinance_news_item`. They normalize already-retrieved mappings and do not need yfinance or HTTP access themselves.

Tests cover nested-versus-flat field priority, missing title rejection, missing optional fields, canonical/click/flat URL selection, publisher selection, summary fallback, timestamps and string dates, ticker normalization, duplicate related tickers, and the fixed `Yahoo/yfinance` source label.

Risk: upstream Yahoo schemas vary, timestamp zero currently counts as unavailable, and related-ticker ordering is observable. Extraction must not absorb `get_cached_yahoo_news`, its cache decorator, or `yf.Ticker` calls.

### TrendForce normalization

Candidate helpers are `_match_trendforce_ticker`, `_clean_trendforce_text`, `_extract_trendforce_date`, `_is_trendforce_article_url`, `_extract_trendforce_category`, `_build_trendforce_item`, and—only after parser tests—HTML/regex item parsing.

Tests cover HTML/entity cleanup, Chinese and English dates, invalid dates, required title/URL, summary fallback, source/publisher/category defaults, ticker matching, and duplicate URL removal.

Risk: parsing rules encode current upstream markup and classification behavior. Extraction must not include requests, feed parsing, cache decorators, retry/fallback orchestration, or provider priority.

## Why components and normalization precede providers or analytics

The selected functions operate on supplied values and have deterministic outputs or Streamlit calls that can be recorded. Provider extraction would affect timeouts, errors, source metadata, caches, and fallback priority. Analytics extraction would touch GEX, market scores, macro derivations, or valuation formulas and requires financial regression coverage first.

## Phase 2.1 recommendation

Move only `render_snapshot_card` and `render_metric_row` into `components/market_cards.py`. Preserve their names in `dashboard.py` via direct imports, keep signatures unchanged, and pass no new state. Run the characterization tests plus a Streamlit startup smoke test.

Do not combine the component move with news normalization. A later Phase 2.2 can move the three Yahoo normalization helpers into a focused service module after confirming import boundaries.

## Protected areas

Continue to protect Watchlist reads/writes, session state, all Streamlit cache decorators and keys, Yahoo/FMP/OpenAI/TrendForce requests, provider/fallback ordering, GEX and Option Wall, IBKR and What-if, market and MU valuation, macro calculations, financial formulas, and the Dashboard page router/layout.
