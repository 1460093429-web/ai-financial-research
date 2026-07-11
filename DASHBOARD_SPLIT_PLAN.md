# `dashboard.py` Responsibility Audit and Split Plan

Audit date: 2026-07-11. This is a planning document only. No functions, imports, cache decorators, financial calculations, GEX, Option Wall, or IBKR behavior were changed.

## Current size and coupling indicators

- 7,265 physical lines.
- 271 top-level functions.
- 31 functions decorated with Streamlit caching.
- 80 functions directly call `st.*`; only 40 are named `render*`/`_render*`, so UI coupling extends beyond visibly named render functions.
- 6 functions directly call `requests.*` and 12 directly call `yf.*`.
- One file owns global provider/cache configuration, local JSON/CSV paths, translation dictionaries, pure calculations, fallback orchestration, AI prompts, charts, page rendering, session state, and top-level routing.

Counts are static indicators, not semantic coverage measurements. A function may span multiple layers today; classification below records its dominant responsibility and the desired destination.

## Responsibility map by source region

| Approximate lines | Feature/responsibility | Current layer(s) | Recommended ownership |
| --- | --- | --- | --- |
| 1–73 | imports, cache paths, provider URLs, watchlist/valuation constants | Configuration / Provider setup | `config` plus feature constants; preserve yfinance cache initialization order |
| 74–116 | performance counters and sidebar diagnostics | Service state + Component | `services/performance_service.py`, `components/debug_panel.py` |
| 119–186 | ticker normalization, watchlist JSON I/O, company metadata | Service | `services/watchlist_service.py`; static metadata may remain in a feature constants module |
| 188–551 | general, news, and macro translation dictionaries/overrides | Translation | `translations/dashboard.py`, later feature translation files |
| 552–587 | translation lookup and number formatting | UI utility | `translations/__init__.py`, `utils/formatting.py` |
| 590–606 | RSI and Black–Scholes gamma | Analytics | `analytics/technical.py`, `analytics/options.py`; gamma is protected and should move only after characterization tests |
| 609–802 | Yahoo quote and FMP-first card data/fallback | Provider + Service + cache | provider adapters plus `services/company_snapshot_service.py` |
| 805–820 | cached technical history | Provider / Service | `services/technical_service.py`; reuse existing `financials.py` where contracts align |
| 823–1103 | expirations, option chain normalization, gamma points, missing reasons and options aggregation | Provider + Service + Analytics | `providers/yahoo_options.py`, `services/options_service.py`, `analytics/options.py`; do not alter GEX or Option Wall semantics |
| 1106–1301 | option prompt, rule fallback, OpenAI summary | Service | `services/options_summary_service.py` |
| 1304–1585 | snapshot/technical/options charts and section rendering | Components / UI | `components/market_cards.py`, `pages/technical.py`, `pages/options.py` |
| 1588–1634 | value comparison section | UI | `pages/value.py` |
| 1637–2337 | US market history, Yahoo/CNN providers, score analytics and fallback orchestration | Provider + Analytics + Service | `providers/market_sentiment.py`, `analytics/market_score.py`, `services/market_valuation_service.py` |
| 2340–2813 | US market formatting, charts, summaries and page | Components / UI | `components/market_valuation.py`, `pages/market_valuation.py` |
| 2816–3194 | FMP/Yahoo/TrendForce news fetching, normalization and rule sentiment | Provider + Service + Analytics | `providers/news.py`, `services/news_service.py`, `analytics/news_scoring.py` |
| 3197–3320 | news translation labels, language aliases, keywords and versions | Translation / Configuration | `translations/news.py`, `services/news_constants.py` |
| 3321–4205 | article extraction, AI/rule summaries, translation/session workflow, news cards and source tabs | Provider + Service + Components / UI | `services/news_ai_service.py`, `components/news.py`, `pages/news.py` |
| 4208–4368 | ETF flow cache/format/rendering and news page routing | Service + Components / UI | existing `etf_news_monitor.py` plus `components/etf_news.py`; keep root service contract stable |
| 4371–4620 | RSS sentiment, technical/options summaries, daily report prompt/rendering | Service + UI | `services/daily_report_service.py`, `pages/daily_report.py` |
| 4621–4707 | multi-agent translations | Translation | `translations/multi_agent.py` |
| 4708–5580 | multi-agent input collection, prompts, validation, rule fallback and rendering | Service + Analytics-like rules + UI | `services/multi_agent_service.py`, `components/multi_agent.py`, `pages/multi_agent.py` |
| 5583–6095 | overview cards and macro fetch/normalize/chart/page | Provider + Service + Components / UI | `providers/fred.py`, existing `macro_data.py`, `services/macro_service.py`, `pages/macro.py` |
| 6106–6320 | MU/analyst/investment-bank translation and baseline constants | Translation / Models | `translations/mu_valuation.py`, `models/mu_valuation.py` |
| 6321–6481 | MU valuation, surprise, target, DCF and sensitivity functions | Analytics | `analytics/mu_valuation.py`; requires extensive regression tests before movement |
| 6484–6805 | MU inputs, overlays, analyst tracker and valuation rendering | Components / UI | `components/mu_valuation.py`, `pages/mu_valuation.py` |
| 6808–6837 | watchlist sidebar | Component | `components/watchlist.py` |
| 6840–6922 | cached IBKR CSV parser and Yahoo/FMP What-if price providers | Provider + Service/cache | keep existing IBKR parser/client contracts; later `services/what_if_price_service.py` |
| 6925–7188 | IBKR What-if page | UI orchestration | `pages/ibkr_what_if.py`; defer until its existing calculation/provider tests are expanded |
| 7191–7265 | page configuration, language/watchlist setup and section router | Application shell | reduced `dashboard.py` entrypoint plus a page registry only after all feature moves |

## Layer classification

### UI and pages

Top-level layout and feature sections belong in page modules: technical, options, value, US market valuation, news, daily report, multi-agent, macro, MU valuation, and IBKR What-if. `main()` should eventually contain only page configuration, global sidebar setup, snapshot orchestration, routing, and diagnostics.

### Components

Reusable Streamlit units include the debug panel, watchlist manager, snapshot/metric cards, option/GEX charts, market-score cards/charts, news cards, multi-agent result panels, macro tables/charts, and MU analyst/overlay panels. Components may format validated view models but should not fetch providers or calculate financial results.

### Providers

Direct external access currently embedded in the file includes Yahoo/yfinance quotes/history/options/news, FMP quote/card calls, CNN Fear & Greed HTTP, TrendForce HTML, article HTML, FRED HTTP, and What-if Yahoo/FMP quotes. Providers should return raw or minimally parsed payloads with source/error metadata and explicit timeouts.

### Services

Services should own source priority, schema normalization, fallback selection, cache-facing parameters, prompt orchestration, and view-model assembly. Major candidates are company snapshots, options data/summary, market valuation, news, daily report, multi-agent, macro, and What-if price resolution.

### Analytics

Pure or mostly pure logic includes RSI, Black–Scholes gamma, gamma-point aggregation, US market score components, rule sentiment/credibility, multi-agent rule validation/rating, MU earnings surprises, forecast revisions, target-price/DCF calculations, and sensitivity tables. These functions require direct regression coverage before any move. Existing `option_walls.py` remains the canonical Option Wall calculation and must not be folded back into the Dashboard.

## Recommended target layout

The target is approximately **27 focused modules plus a reduced `dashboard.py`**, created only as each phase earns sufficient tests. This is a planning estimate, not a requirement to create empty scaffolding.

```text
dashboard.py
translations/
  dashboard.py
  news.py
  multi_agent.py
  mu_valuation.py
providers/
  yahoo_market.py
  yahoo_options.py
  news.py
  market_sentiment.py
  fred.py
services/
  performance_service.py
  watchlist_service.py
  company_snapshot_service.py
  technical_service.py
  options_service.py
  options_summary_service.py
  market_valuation_service.py
  news_service.py
  news_ai_service.py
  multi_agent_service.py
  macro_service.py
analytics/
  technical.py
  options.py
  market_score.py
  news_scoring.py
  mu_valuation.py
components/
  debug_panel.py
  market_cards.py
  watchlist.py
pages/
  feature modules introduced one at a time
```

Some provider/service responsibilities already exist in `financials.py`, `macro_data.py`, `etf_news_monitor.py`, `factor_watch.py`, `option_walls.py`, `ibkr_client.py`, `ibkr_statement_parser.py`, and `what_if_analysis.py`. Before creating any target module, compare and reuse those contracts to avoid a second duplicate implementation. The estimate will decrease if an existing module is the correct owner.

## Incremental implementation sequence

### Stage 0: characterization and import safety

Add tests for translation fallback, formatting, watchlist validation using a temporary path, selected pure market-score functions, and MU valuation pure functions. Add a lightweight Dashboard import/compile test that does not start external requests. Record current cache decorators, TTLs, and keys.

Risk: low. The main danger is importing Streamlit code with side effects. Rollback is test-file removal only.

### Stage 1: constants and translations

Move one complete translation family at a time, starting with multi-agent or MU dictionaries because their boundaries are explicit. Re-export temporarily from `dashboard.py` if tests or callers rely on names.

Risk: low to medium. Missing keys or circular imports can break one language. Validate English, Chinese, Spanish and English fallback after every family.

### Stage 2: leaf pure utilities

Move formatting and already-characterized pure functions without changing signatures or formulas. Start with non-financial formatting. Move financial analytics only in separate commits with before/after golden tests.

Risk: medium. Hidden global constants and pandas dtype behavior can change. GEX, Option Wall, and IBKR are excluded from this stage.

### Stage 3: watchlist and diagnostics

Extract watchlist file operations behind an injected/path parameter while preserving `WATCHLIST_FILE`, then extract the sidebar component. Extract performance state and panel separately.

Risk: medium. Wrong default paths or rerun/session behavior could overwrite `watchlist.json`. All tests must use temporary files; never exercise writes against the repository watchlist.

### Stage 4: one low-coupling feature slice

Choose a feature already backed by a root module, preferably ETF news or Factor Watch. Move only Dashboard adapters/rendering around the existing service contract. Keep cache keys and public imports stable.

Risk: medium. Streamlit reruns and cached arguments can change even when output looks identical. Verify API failure and manual refresh behavior.

### Stage 5: news and market valuation

Separate provider calls first, normalization/fallback second, and UI last. Maintain source/timestamp/fallback fields and cache version arguments. Do not combine this with translation migration.

Risk: medium to high. These areas have many caches, AI fallbacks, HTML schemas, and language-dependent session keys. Each source requires fixture-based tests.

### Stage 6: macro and multi-agent

Reuse `macro_data.py` rather than duplicating it; extract only the missing FRED/service/UI responsibilities. For multi-agent, separate deterministic input/validation/fallback from OpenAI calls and rendering.

Risk: high. Source mixing and incomplete-data validation can silently change conclusions. Use fixed payload/view-model fixtures and ensure unavailable values remain unavailable.

### Stage 7: protected financial areas

Only after dedicated normal/empty/missing/string/NaN/negative/extreme/duplicate/date/unit tests, consider moving options/GEX code, MU valuation analytics, or IBKR page orchestration. Perform moves without formula edits, then optimize only in later changes.

Risk: highest. Cache contamination, units, option expiry selection, sign conventions, margin/P&L and target-price behavior can change. GEX, Option Wall, and IBKR must each be isolated into their own approved change; `option_walls.py` should remain unchanged.

### Stage 8: shrink the entrypoint

After feature modules are proven, replace the long conditional router with an explicit page registry while preserving labels, session keys, default language, layout, and page order.

Risk: medium. Import order and eager module initialization can affect Streamlit caches and secrets. Roll back the registry without reverting the already-tested feature modules.

## File impact by future stage

- Stages 0–2: new focused tests and translation/utility/analytics modules; temporary re-exports in `dashboard.py`.
- Stages 3–4: `services/`, `components/`, one feature page, and small import-only changes in `dashboard.py`.
- Stages 5–6: provider/service/page modules for news, market valuation, macro, and multi-agent; fixture tests.
- Stage 7: protected analytics/page modules only with explicit approval and dedicated financial regression tests.
- Stage 8: `dashboard.py` router and page registry.

No stage requires deleting `ai_research_project/`. Duplicate root/subtree ownership must be resolved separately from Dashboard extraction.

## Required validation for every future extraction

1. Capture the focused tests and import graph before moving code.
2. Move code without changing behavior or formulas; preserve temporary imports/re-exports where necessary.
3. Run focused tests, then `pytest -q tests`, `pytest -q ai_research_project/tests`, and `pytest -q`.
4. Verify Streamlit startup, the affected page, all three languages, empty/error/fallback states, and refresh/cache behavior.
5. Review `git diff --check`, cache decorators/TTLs/keys, provider metadata, and protected files.
6. Keep each commit/PR limited to one feature or one layer so it can be reverted independently.
