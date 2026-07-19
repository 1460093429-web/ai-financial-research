# Value Investing Financial Data Audit

## Scope and entry point

The production Streamlit entry remains `dashboard.py`. The existing Value
Investing navigation label and order are unchanged. Before Phase 4.8,
`dashboard.py::render_value_section` called the cached local
`get_company_snapshot`, which called `financials.get_company_snapshot` and
then silently fell back to a dashboard yfinance snapshot. The large Micron
valuation model is a separate final tab and is outside this repair.

Phase 4.8 changes only the Value Investing renderer to this path:

```text
caller-owned financials._fmp_get + existing FMP credential lookup
  -> services.value_investing.load_value_investing_snapshot
  -> shared FMP provider
  -> shared identity/period/unit normalization
  -> shared deterministic financial snapshot
  -> localized Value Investing view model
  -> components.value_investing
```

The page does not use Yahoo, news, static data, Memory Cycle fixtures, or the
legacy mixed snapshot. It does not add a cache. The legacy helpers remain
unchanged because other repository consumers still use them; this repair
isolates them from the Value Investing entry rather than performing an
unapproved repository-wide migration.

## Confirmed pre-repair errors and disposition

| File/function | Field or behavior | Confirmed old logic | Why it was unsafe or misleading | Phase 4.8 disposition | Regression coverage |
| --- | --- | --- | --- | --- | --- |
| `dashboard.py::get_company_snapshot` | source priority | Cached `financials.get_company_snapshot`, then dashboard yfinance fallback | The Value page could change provider and semantics without a field-level status | Value renderer now calls only the shared FMP service; no page cache or Yahoo fallback | Characterization and service source-boundary tests |
| `financials.get_company_snapshot` | all financial fields | FMP overlay followed by filling every `None` from yfinance | One object could contain two providers while `source` still said FMP | Legacy helper remains for other consumers but is no longer reachable from the Value renderer | Dashboard wiring characterization test |
| `financials._overlay_fmp` | income statement | Requested `limit=1` with no explicit quarterly/annual separation | A single row could be annual or quarterly; it could not support verified TTM | Shared provider fetches quarterly and annual separately; TTM is four continuous quarters only | Provider, normalization, snapshot, and service tests |
| `financials._fetch_yfinance_snapshot` | period selection | Tried annual statements before quarterly statements and used the first column | Period semantics depended on provider ordering and were not shown to the user | Removed from Value path | Characterization test |
| `financials._overlay_fmp` | `free_cash_flow_margin` | Divided `key-metrics.freeCashFlowToFirm` by one income-statement revenue row | The numerator and denominator did not prove the same period or even the same statement basis | TTM FCF is verified against TTM OCF minus CapEx magnitude, then divided by TTM revenue | Snapshot and Value service formula tests |
| `financials._overlay_fmp` | P/E, P/S, P/B, EV/EBITDA | Copied ratios/key-metrics endpoint values with no period/currency join | Current numerators and financial denominators were not auditable | P/E uses current price / TTM diluted EPS; P/S current market cap / TTM revenue; P/B current market cap / latest equity; EV/EBITDA current EV / TTM EBITDA | Snapshot and Value service formula/invalid-denominator tests |
| `financials._overlay_fmp` | ROE and ROA | Copied key-metrics endpoint values | Beginning/ending denominator periods were not visible or verified | TTM net income divided by average beginning/ending equity or assets | Snapshot and Value service tests |
| old Value page | ROIC | Not presented with a verifiable definition | A proxy or copied opaque value would be misleading | NOPAT / average invested capital, using only an actual valid TTM tax rate; otherwise unavailable | Snapshot and Value service invalid-tax tests |
| old Value page | balance sheet | Cash, debt, inventory, equity, and assets were absent | Point-in-time fields and net-debt semantics could not be audited | Latest valid quarterly balance only; cash uses one complete cash-plus-short-term-investments field; total debt is not re-added; net debt is debt minus cash | Normalization and snapshot tests |
| `financials.get_financial_data` | missing margin | Used `snapshot["net_margin"] or 0` | Missing margin became a false 0% | Value view model/component preserves missing and unavailable; real numeric zero remains visible | Characterization and component tests |
| old Value page | dates and quality | Displayed provider name but not statement period, period end, currency, retrieval time, derived status, or staleness | Users could not distinguish current quotes, TTM flows, annual flows, and balance-sheet points | Data Quality plus per-metric period, data date, source, unit, reported/derived/proxy, and stale days | Service and component tests |
| old Value page | SNDK | FMP supplied profile/quote, while financial values could come from yfinance; pre-split history had special-case risk | SNDK could be mixed with incomplete or legacy issuer history | Exact SNDK symbol/name/CIK required; no WDC mapping and no pre-2025 statement accepted | Normalization, binding, and Value service identity tests |

## Formula and metadata policy

- Revenue, gross profit, operating income, net income, EBITDA, diluted EPS,
  OCF, CapEx, and FCF are TTM flows only when four continuous quarters pass
  ticker, currency, statement-type, date, and uniqueness checks.
- Annual revenue remains a separate annual observation and is never labelled
  TTM. Inventory, cash, debt, equity, and assets are the latest balance-sheet
  point and are never summed.
- Reported margin ratios are converted from ratio to percent once. A missing
  margin may be derived only from the same normalized statement.
- CapEx is the magnitude of a non-positive reported cash outflow. Positive
  reported CapEx is a sign conflict. Provider FCF must agree with OCF minus
  the CapEx magnitude; otherwise FCF is unavailable.
- TTM diluted EPS is distinct from basic EPS and current shares outstanding.
  Shares outstanding are never summed. P/E is unavailable for non-positive
  TTM diluted EPS.
- ROE and ROA require positive comparable beginning and ending balances. ROIC
  uses `debt + equity - cash` for beginning and ending invested capital and no
  assumed tax rate.
- Missing currency is not defaulted to USD. Current quote and financial
  currencies must agree before a valuation multiple is produced.
- Statement period end, quote time, retrieval time, and caller-injected
  evaluation time remain separate. Missing and unavailable values are never
  zero-filled. Stale values retain their period end and display whole days.

## Cache and failure boundary

The repaired Value path adds no `st.cache_data`, service cache, file cache, or
session-state storage. The existing caller-owned FMP request helper performs
one request per explicit endpoint and includes the endpoint, symbol, and
period in each call. It does not cache an empty/error response as success.
Future caching should be service-owned, with quote and statement TTLs separated
and an explicit refresh nonce; it is not authorized by this phase.

Every ticker is isolated. Acquisition or normalization failure returns a
sanitized FMP error snapshot and a localized incomplete/unavailable page. No
exception message, traceback, credential, URL query, local path, or complete
raw response is rendered or persisted.

## Deferred items

- No Memory Cycle Dashboard route or production preview is added.
- No DRAM, NAND, or HBM industry price data is acquired.
- No analyst targets, analyst ratings, forecasts, current/quick ratios, or
  debt-to-equity card is shown because the shared snapshot does not yet prove
  their period and source semantics.
- Live FMP availability and plan entitlement must be reported by the controlled
  non-persistent smoke. Missing live SNDK statements remain unavailable.
