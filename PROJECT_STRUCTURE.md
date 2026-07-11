# Project Structure and Runtime Map

This document records the repository state verified on 2026-07-11. It describes observed imports and repository evidence; it does not authorize removal of older files.

## Runtime entry points

### Streamlit dashboard

The repository-supported local entry is:

```bash
streamlit run dashboard.py
```

Evidence:

- `dashboard.py` defines `main()`, calls `st.set_page_config(...)`, and invokes `main()` under `if __name__ == "__main__"`.
- Local runtime logs contain a `python -m streamlit run dashboard.py` command.
- Recent dashboard and production-facing feature commits consistently modify `dashboard.py`.

The Streamlit Community Cloud **Main file path** is stored in the Cloud console, not in this repository. There is no committed `.streamlit/config.toml`, Procfile, container file, or other Streamlit deployment manifest that proves the console value. The best repository evidence points to `dashboard.py`; the console value is **待确认**.

### Other executable scripts

- `main.py` is a non-Streamlit report workflow: news and financial collection → charts → PDF report. README currently describes this historical workflow.
- `ai_research_project/app.py` is a small Yahoo price example that imports `data.yahoo_client` and prints an AAPL price. It is not imported by `dashboard.py`.
- Monitoring, backtest, signal, strategy, supply-chain, and analysis scripts can be invoked independently. Their current external schedulers/users, beyond the committed GitHub workflow below, are **待确认**.

## Dashboard import and data-flow map

`dashboard.py` is currently a monolithic composition layer and also contains some normalization, fallback, analytics, caching, and translation logic. Its observed root-module dependencies are:

```text
dashboard.py
├── config.py
│   └── environment variables / .env / Streamlit secrets
├── financials.py
│   ├── FMP (primary for several company/news workflows)
│   └── Yahoo Finance/yfinance (selected history and fallback workflows)
├── macro_data.py
│   ├── config.py + financials.py helpers
│   ├── FMP
│   └── Yahoo Finance/yfinance fallback
├── etf_news_monitor.py
│   └── HTTP/HTML source collection and normalized ETF-news/flow records
├── factor_watch.py
│   └── Yahoo Finance/yfinance market series and factor calculations
├── option_walls.py
│   └── pure option-wall calculations from normalized option-chain frames
├── ibkr_client.py
│   └── read-only IBKR connectivity and market/account data
├── ibkr_statement_parser.py
│   └── uploaded IBKR CSV statement normalization
└── what_if_analysis.py
    └── normalized positions/trades/prices and What-if calculations
```

The dashboard also directly uses requests, yfinance, CSV/local files, Streamlit cache/session state, and internal calculation/rendering functions. Therefore the target Provider → Service → Analytics → UI separation is not yet fully implemented. This is documented technical debt, not a reason to perform an unscoped `dashboard.py` rewrite.

## Data sources and fallback behavior

- **FMP**: company snapshot, financial, news, and macro workflows through `config.py`, `financials.py`, `macro_data.py`, and dashboard helpers.
- **Yahoo Finance/yfinance**: quotes, technical history, option chains, news, market proxies, factor series, and multiple FMP/market fallbacks.
- **IBKR**: read-only current price/account interactions for the What-if workflow through `ibkr_client.py`.
- **CSV/local files**: IBKR statement uploads, price fallback, watchlist, valuation history, analyst/backtest inputs, and generated strategy data.
- **OpenAI**: summaries, translations, and analysis where configured; rule-based or unavailable states are used by selected workflows when no client/result is available.

Fallback source priority is workflow-specific. Callers must preserve the selected source, timestamp, and fallback status; there is no single repository-wide provider registry yet.

## Module status

Status definitions:

- **Current production call**: on the observed `dashboard.py` runtime path or committed scheduled workflow.
- **Test call**: directly imported by a collected test.
- **Deprecated/retained**: repository evidence indicates a superseded example or older workflow, but the file is intentionally retained.
- **Unknown**: not on the observed dashboard/test/scheduled path; external or manual use cannot be ruled out.

### Root modules relevant to current paths

| Module | Status | Observed consumer |
| --- | --- | --- |
| `dashboard.py` | Current production call | Local Streamlit command; Cloud console value 待确认 |
| `config.py` | Current production call | Dashboard modules and other root scripts; the subtree config test does not cover this file |
| `financials.py` | Current production call | `dashboard.py`, `macro_data.py`, report/agent scripts; the subtree financial test does not cover this file |
| `macro_data.py` | Current production call | `dashboard.py`; the subtree macro test does not cover this file |
| `etf_news_monitor.py` | Current production call; test call | `dashboard.py`, `tests/test_etf_news_monitor.py` |
| `factor_watch.py` | Current production call; test call | `dashboard.py`, `tests/test_factor_watch.py` |
| `option_walls.py` | Current production call; test call | `dashboard.py`, `options_levels.py`, `tests/test_option_walls.py` |
| `ibkr_client.py` | Current production call; test call | `dashboard.py`, `tests/test_ibkr_client.py` |
| `ibkr_statement_parser.py` | Current production call; test call | `dashboard.py`, `what_if_analysis.py`, tests |
| `what_if_analysis.py` | Current production call; test call | `dashboard.py`, `tests/test_what_if_analysis.py` |
| `main.py`, `charts.py`, `news.py`, `pdf_generator.py` | Deprecated/retained report workflow | README historical command and `main.py` import chain; not Dashboard |
| `monitor.py`, `news_sentiment.py`, `signal_system.py` | Current scheduled call | `.github/workflows/monitor.yml` |
| Other root analysis/backtest/strategy scripts | Unknown | Manual or external use 待确认 |

### `ai_research_project/` modules and duplicates

The subtree is not a conventional installed Python package at its root (there is no committed `ai_research_project/__init__.py`). Several files use bare imports such as `import config`, so resolution depends on the working directory and `sys.path`.

| Subtree module | Root counterpart/function | Status and finding |
| --- | --- | --- |
| `app.py` | `dashboard.py` / `main.py` entry roles | Deprecated/retained example candidate; prints one Yahoo price and is not on Dashboard path |
| `config.py` | `config.py` | Independent legacy/parallel variant; covered by `ai_research_project/tests/test_config.py`; runtime owner beyond tests 待确认 |
| `financials.py` | `financials.py` | Independent legacy/parallel, smaller variant; covered by `ai_research_project/tests/test_financials.py`; runtime owner beyond tests 待确认 |
| `macro_data.py` | `macro_data.py` | Independent legacy/parallel, smaller variant; covered by `ai_research_project/tests/test_macro_data.py`; runtime owner beyond tests 待确认 |
| `backtest.py` | `backtest.py` | Divergent, larger subtree implementation; covered by `ai_research_project/tests/test_backtest.py`; production/manual owner 待确认 |
| `ai_analysis.py` | `ai_analysis.py` | Divergent implementations; subtree version is smaller; manual use 待确认 |
| `supply_chain_analyzer.py` | `supply_chain_analyzer.py` | Divergent implementations; subtree version is larger; manual use 待确认 |
| `data/yahoo_client.py` | Yahoo logic in several root modules | Called only by subtree `app.py` in the observed static graph |
| `options.py`, `data_layer.py`, analyst and DRAM/backtest scripts | Related root functionality, no exact one-to-one module | Unknown; not on observed Dashboard import path |
| `tests/` | Root `tests/` | Active collected tests for the subtree's backtest, config, financial, and macro implementations |

No duplicate or older implementation should be deleted until its invocation environment, data files, and downstream users are confirmed.

## Tests

Two test directories are collected:

- `tests/`: ETF news, factor watch, IBKR client/parser, option walls, and What-if tests.
- `ai_research_project/tests/`: backtest, config, financial, and macro tests.

Instrumented pytest collection confirmed that the child suite's `import backtest`, `import config`, `import financials`, and `import macro_data` resolve to files under `ai_research_project/`, including when pytest is launched from the repository root. These are independent legacy/parallel implementations with their own active regression coverage.

A reversible experiment moved the four tests into root `tests/`. The move changed their imports to root modules and produced 17 failure items because the root and subtree APIs are incompatible. The files were restored. They must not be moved directly unless a future approved deprecation or restructuring of `ai_research_project/` includes an explicit test migration.

Standard commands:

```bash
pytest -q tests
pytest -q ai_research_project/tests
pytest -q
```

## Deployment and automation

- **Local Streamlit**: `streamlit run dashboard.py`.
- **Streamlit Community Cloud**: installs `requirements.txt`; the Cloud Main file path and secrets are external settings and are **待确认** in the Cloud console.
- **GitHub Actions**: `.github/workflows/monitor.yml` runs weekday jobs for `monitor.py`, `news_sentiment.py`, and `signal_system.py` on Python 3.11. It installs an explicit package subset rather than `requirements.txt`.
- **Secrets**: `.env` and `.streamlit/secrets.toml` are ignored. `.env.example` contains placeholders only. Expected names include `OPENAI_API_KEY`, `FMP_API_KEY`, and email credentials for scheduled notification workflows.

## Known follow-up questions

- Confirm the Streamlit Cloud Main file path is exactly `dashboard.py`.
- Confirm whether `main.py` and `ai_research_project/app.py` are still used manually.
- Confirm owners/consumers of divergent subtree backtest, analyst, DRAM, and supply-chain scripts.
- Decide whether `ai_research_project/` remains a supported parallel application or becomes deprecated; retain its current tests until that decision and any migration are explicitly approved.
