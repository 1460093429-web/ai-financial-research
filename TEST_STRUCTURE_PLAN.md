# Test Structure Audit and Maintenance Plan

Audit date: 2026-07-11. Corrected after an instrumented pytest collection and a reversible test-move experiment. This document describes the current test targets; it does not change imports, test discovery, or business logic.

## How test imports actually resolve

The repository contains two distinct test groups with different import contexts:

- Root `tests/` imports root modules such as `option_walls.py` and `what_if_analysis.py`.
- `ai_research_project/tests/` uses bare imports such as `import financials`, but pytest adds the subtree to the collection import context. Instrumented collection confirmed that these imports resolve to the co-located `ai_research_project/` modules even when pytest is launched from the repository root.

Observed paths during `pytest --collect-only -q ai_research_project/tests`:

```text
backtest   -> <repository>/ai_research_project/backtest.py
config     -> <repository>/ai_research_project/config.py
financials -> <repository>/ai_research_project/financials.py
macro_data -> <repository>/ai_research_project/macro_data.py
```

The earlier conclusion that these four tests resolved to root modules was incorrect. A standalone Python import from the repository root does resolve the same bare names to root files, but that is not equivalent to pytest's collection context for this subtree.

## Current test-to-module coverage

### Root `tests/`

| Test file | Actual module(s) | Covered behavior |
| --- | --- | --- |
| `tests/test_etf_news_monitor.py` | root `etf_news_monitor.py` | ETF.com metadata/table parsing, flow signals, summaries, manual text parsing, blocked/network/empty fallback and source preservation |
| `tests/test_factor_watch.py` | root `factor_watch.py` | factor metrics/dataframe aliases, multilingual summaries and explanations, ETF holdings fallback |
| `tests/test_ibkr_client.py` | root `ibkr_client.py` | event-loop initialization, diagnostics, IBKR snapshot price priority |
| `tests/test_ibkr_statement_parser.py` | root `ibkr_statement_parser.py` | variable-width and multilingual IBKR statement sections, missing-section warnings, BOM/spacing/case normalization |
| `tests/test_option_walls.py` | root `option_walls.py` | selected-expiry Put/Call Wall, field aliases, open-interest tie-breaking |
| `tests/test_what_if_analysis.py` | root `what_if_analysis.py`; root `ibkr_statement_parser.py` | trade contribution/P&L, commissions, aggregation, CSV parsing/date filters, side normalization, position reconstruction, live-source priority and CSV fallback |

### `ai_research_project/tests/`

| Test file | Actual module | Covered behavior |
| --- | --- | --- |
| `test_backtest.py` | `ai_research_project/backtest.py` | signal CSV typing, future price/result update, invalid close degradation and logging |
| `test_config.py` | `ai_research_project/config.py` | local `.env` load, Streamlit secrets fallback, missing-key behavior |
| `test_financials.py` | `ai_research_project/financials.py` | FMP-first data, yfinance fallback, retry/auth statuses, API-key redaction |
| `test_macro_data.py` | `ai_research_project/macro_data.py` | dynamic date window, failed FMP/`N/A`, Yahoo macro fallback, missing-field risk score |

These four tests correctly cover the independent legacy/parallel implementation beside them. They do not currently provide regression coverage for the root `backtest.py`, `config.py`, `financials.py`, or `macro_data.py`.

## Reversible move experiment

The four files were temporarily moved to uniquely named root paths:

```text
tests/test_root_backtest.py
tests/test_root_config.py
tests/test_root_financials.py
tests/test_root_macro_data.py
```

Module-path assertions then confirmed that the moved files imported root modules. The test run reported **17 failure items**. The failures were caused by incompatible root/subtree APIs, including examples such as:

- root `backtest.py` has no `SIGNALS_FILE` contract used by the subtree tests;
- root `config.py` has no `load_local_env` or `_streamlit_secret` API used by those tests;
- root `financials.py` has no `get_tickers` API used by those tests;
- root `macro_data.py` has no `date_window`, `YFINANCE_FALLBACKS`, or `macro_risk_score` API used by those tests.

The experiment was fully rolled back. After restoration, the existing baseline returned to 50 passing root tests, 13 passing subtree tests with 9 passing subtests, and 63 passing tests overall.

## Correct conclusion

**Do not directly move these four tests to root `tests/`.** A move changes their imported implementation and therefore changes their test target and semantics. They should remain under `ai_research_project/tests/` unless a future, explicitly approved decision deprecates or restructures `ai_research_project/`.

Root-module coverage must be created as new tests designed against the root modules' actual public contracts. Existing subtree tests must not be repurposed as root tests merely by moving or renaming them.

## Maintenance plan

1. Keep the four existing tests and their current paths unchanged.
2. Treat `ai_research_project/` as an independently tested legacy/parallel implementation until ownership is decided.
3. If root coverage is needed, add separately named root tests after auditing each root module's actual API and production consumers.
4. If `ai_research_project/` is later retained as a supported package, consider explicit package imports to make test resolution less dependent on pytest import context.
5. If it is later deprecated, first confirm external/manual consumers, data files, and deployment paths; preserve its tests until removal is separately approved.

Standard validation remains:

```bash
pytest -q tests
pytest -q ai_research_project/tests
pytest -q
```
