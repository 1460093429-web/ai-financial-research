# Test Structure Audit and Migration Plan

Audit date: 2026-07-11. This document describes the current test targets and proposes a low-risk migration. It does not change imports, test discovery, or business logic.

## How test imports currently resolve

Tests are launched from the repository root. `tests/conftest.py` explicitly inserts the repository root into `sys.path`; the repository root is also available while collecting `ai_research_project/tests/`. The child test files use bare imports such as `import financials` rather than package-qualified imports.

Observed module resolution in the current environment:

```text
backtest     -> <repository>/backtest.py
config       -> <repository>/config.py
financials   -> <repository>/financials.py
macro_data   -> <repository>/macro_data.py
```

Therefore `ai_research_project/tests/` currently tests root modules when invoked from the repository root. It does not reliably test the same-named files beside it. A different working directory or import mode could change this behavior.

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

These imports match the test directory's current root-module role. No wrong target was found in this set.

### `ai_research_project/tests/`

| Test file | Actual module from repository root | Covered behavior | Co-located module not covered |
| --- | --- | --- | --- |
| `test_backtest.py` | root `backtest.py` | signal CSV typing, future price/result update, invalid close degradation and logging | `ai_research_project/backtest.py` |
| `test_config.py` | root `config.py` | local `.env` load, Streamlit secrets fallback, missing-key behavior | `ai_research_project/config.py` |
| `test_financials.py` | root `financials.py` | FMP-first data, yfinance fallback, retry/auth statuses, API-key redaction | `ai_research_project/financials.py` |
| `test_macro_data.py` | root `macro_data.py` | dynamic date window, failed FMP/`N/A`, Yahoo macro fallback, missing-field risk score | `ai_research_project/macro_data.py` |

All four child test files are structurally misleading: their location suggests that they cover co-located subtree modules, but their actual targets are root modules. Whether they were intended to test root or subtree implementations cannot be proven from the repository, so intent remains **待确认**. Relative to the natural directory expectation, all four currently cover the wrong implementation; relative to current root production coverage, their assertions remain useful.

## Risks in changing imports immediately

- `ai_research_project/` has no root `__init__.py`, and its modules use bare sibling imports. Making imports package-qualified without preparation may fail or silently mix root and subtree dependencies.
- Root and subtree implementations are divergent, not interchangeable copies. Redirecting an existing test can expose different APIs or behavior and must not be treated as a mechanical rename.
- Moving tests changes ownership/history and can create duplicate test module names during an intermediate state.
- Backtest and financial tests exercise data correctness and fallback. A target switch could appear to be a regression even though it is revealing previously untested code.

## Recommended gradual repair

### Step 1: lock current root coverage

Move the four child tests, without changing assertions, into uniquely named root test files:

```text
tests/test_root_backtest.py
tests/test_root_config.py
tests/test_root_financials.py
tests/test_root_macro_data.py
```

Use explicit root-oriented naming in comments or test metadata. Before and after the move, verify collection IDs and pass counts. This step preserves current behavior and makes ownership honest. Do not keep duplicate copies after the move once equivalence is verified.

### Step 2: make the subtree importable in isolation

In a separate change, decide whether `ai_research_project/` is a supported package or a retained legacy application. If supported, add package boundaries and convert its internal bare imports to explicit relative/package imports one module at a time. If retained legacy only, document its supported launch directory instead of pretending it is an installed package.

This step must not modify root Dashboard imports.

### Step 3: add subtree smoke/contract tests

Only after Step 2, add explicitly named tests such as:

```text
ai_research_project/tests/test_legacy_config.py
ai_research_project/tests/test_legacy_financials.py
```

Import package-qualified modules and begin with import/config/no-network smoke tests. Do not redirect root regression tests wholesale; first compare public functions, provider behavior, units, and fallback semantics.

### Step 4: decide long-term ownership

For each duplicate pair, choose and document one outcome:

- root module is canonical and subtree version is retained legacy;
- subtree module is canonical and root callers migrate in a separately tested phase; or
- both are supported with distinct names and contracts.

Deletion is not part of this plan. Any later removal requires confirmed consumers, data migration, and explicit approval.

## Proposed first implementation change

The lowest-risk next code change is Step 1 only: move the four tests to root `tests/` with unique filenames and prove that collection IDs, assertion counts, and imported `__file__` targets remain unchanged. Do not add `sys.path` manipulation to individual tests and do not redirect them to subtree implementations in the same change.

Validation for that future change:

```bash
pytest --collect-only -q
pytest -q tests
pytest -q ai_research_project/tests
pytest -q
```

Expected semantic result: the same root modules remain covered; the child suite becomes empty or contains only future explicit subtree tests. Exact pass-count reporting should distinguish pytest test functions, unittest subtests, and warnings.
