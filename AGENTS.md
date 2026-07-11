# AI Financial Research Engineering Guide

These instructions apply to the entire repository. Preserve existing behavior unless a task explicitly authorizes a change. Read `README.md`, `PROJECT_STRUCTURE.md`, dependency files, deployment configuration, the relevant modules, and their tests before editing.

## Data accuracy and provenance

- Never fabricate financial data. Missing, invalid, stale, or unavailable values must remain visibly unavailable (`N/A`, an empty result, or an explicit error/fallback state).
- Preserve the data source, observation/price time, retrieval/update time, currency, units, and fallback status wherever the source provides them.
- Do not present cached or historical data as real-time data.
- Normalize provider fields and types before calculations. Handle `None`, `NaN`, empty frames/dictionaries, missing fields, string numbers, duplicate rows, mixed date formats, time zones, currencies, and units.
- Keep complex financial calculations out of Streamlit rendering code. Prefer deterministic pure functions.

## Financial calculation tests

Add or update regression tests whenever changing returns, P&L, margin, option payoff, GEX, Put Wall, Call Wall, Max Pain, valuation, EPS, margins, target prices, ETF flows, factor returns, price reconstruction, portfolio equity, or FX conversion.

Tests should cover, as applicable: normal input, empty input, missing fields, numeric strings, `NaN`, negative and extreme values, duplicate data, differing date formats, and differing currencies or units. Do not weaken or skip tests merely to make a build pass.

## Architecture and data flow

The current production-oriented Streamlit path is rooted at `dashboard.py`; some layering is incomplete. Improve it incrementally without a wholesale rewrite:

1. **Provider**: external requests and raw responses only.
2. **Service**: validation, normalization, source priority, fallback orchestration, and metadata.
3. **Analytics**: pure financial calculations.
4. **UI**: Streamlit composition and display states; no direct complex calculations.

Prefer `providers/`, `services/`, `analytics/`, `models/`, `components/`, and `translations/` for new or extracted code when a scoped change justifies them. Avoid circular imports, duplicate requests, and duplicate cache layers. Do not delete root or `ai_research_project/` implementations until their runtime and test consumers have been proven and a migration is explicitly approved.

## Providers and fallback

- Existing sources include FMP, Yahoo Finance/yfinance, IBKR, and CSV/local files. Provider priority must be explicit for each workflow.
- Use request timeouts and handle network failures, rate limits, empty responses, schema changes, and invalid field types.
- A fallback must retain its own source, timestamp, and `is_fallback`/status metadata. Never silently relabel Yahoo, IBKR, CSV, or cached data as another source.
- API failure must not crash unrelated Streamlit sections. Do not cache an empty/error response as a successful live result.

## Multilingual UI

All new user-visible UI text must support English, Simplified Chinese, and Spanish through the existing translation mechanism or a shared translation module. English is the fallback for a missing translation. Verify language switching and layouts with longer Chinese and Spanish text. Do not introduce new hard-coded single-language UI labels.

## Cache and session state

- Review `st.cache_data`, `st.cache_resource`, TTLs, cache keys, and manual refresh behavior for every data-flow change.
- Cache keys must isolate ticker, provider, date range, expiry, currency/unit, language when output depends on it, and any refresh/version nonce.
- Initialize `st.session_state` safely and prevent state leakage across tickers, pages, dates, expiries, data sources, and languages.
- A refresh control must clear or bypass the relevant cache; do not store changing financial data in unscoped globals.

## Secrets and logging

- Read secrets only from environment variables, local ignored `.env`, or Streamlit `st.secrets`. Keep `.env.example` placeholder-only.
- Never commit API keys, credentials, private user data, `.streamlit/secrets.toml`, caches, virtual environments, runtime logs, or generated local artifacts.
- Logs may include provider/status diagnostics but must not expose keys, authorization headers, account identifiers, or statement contents containing private data.

## Streamlit and Streamlit Cloud

- The repository-supported Streamlit entry is `dashboard.py`; the exact Streamlit Cloud **Main file path** remains an external console setting and must be verified there before changing entry files.
- Keep Linux, Python, and headless Streamlit compatibility. Dependency files must be UTF-8 and parseable by pip.
- Pages must render useful loading, success, no-data, fallback, and error states. A single provider or component failure must not take down the entire app.
- Preserve existing layout and interaction patterns unless the task requires a UI change. When practical, validate the local app, all three languages, narrow layouts, API failure states, and refresh behavior.

## Testing and change review

Run focused tests first and then the repository suites:

```bash
pytest -q tests
pytest -q ai_research_project/tests
pytest -q
```

Classify failures caused by code, missing dependencies, environment variables, network access, or external services. Do not hide failures or change business behavior solely to accommodate the environment.

Before handoff:

- Review `git status`, `git diff`, and `git diff --check`.
- Preserve pre-existing user changes, especially `watchlist.json`, unless the task explicitly includes them.
- Confirm no unrelated files, secrets, caches, logs, virtual environments, or generated artifacts were added.
- Report modified files, public-interface/dependency/deployment effects, test results, remaining risks, and any environment/configuration migration.
