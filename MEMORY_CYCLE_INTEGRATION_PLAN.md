# Memory Cycle Dashboard Integration Plan

## 1. Scope and decision record

This document characterizes the current repository before any production
Dashboard integration. It does not authorize a route, Section label, provider,
cache, session key, score, or cycle-phase implementation.

The Phase 4.5 decision was `WAIT_FOR_MINIMUM_PRODUCTION_DATA_PIPELINE`.
Phase 4.6 now provides the pure validation/orchestration portion, but not live
acquisition, provider metadata completion, cache/refresh, or page isolation.
**Current decision: `WAIT_FOR_PROVIDER_METADATA_COMPLETION`.** Keep the static
Demo independent. Do not add a Static Preview to the production Dashboard now.

The decision is based on data credibility, user experience, misleading-current-
data risk, implementation cost, real-source availability, and the current lack
of a page-level exception boundary in `dashboard.py`.

## 2. Current Memory Cycle architecture

The implemented, non-production path is:

```text
reviewed static fixtures
  -> Phase 4.1 metric adapters and metric contract
  -> Phase 4.2 pure view model
  -> Phase 4.3 presentation-only Streamlit component
  -> Phase 4.4 independent static Demo
```

- `fixtures/memory_cycle_mvp.py` contains 21 synthetic, reviewed records with
  fixed observation and evaluation timestamps.
- `services/memory_cycle_view_model.py` groups metrics into seven ordered
  sections and retains provenance, status, confidence, warnings, and data-
  quality counts. It performs no I/O and emits no score or cycle phase.
- `components/memory_cycle.py` prepares component rows and renders the quality
  summary, sections, cards, evidence limitations, and empty state. It does not
  own providers or caches.
- `demos/memory_cycle_demo.py` is the only runnable page. It visibly identifies
  static data, preserves fixture dates, evaluates stale demo copies against a
  fixed timestamp, and remains outside the production Dashboard.

## 3. Current Dashboard characterization

### 3.1 Navigation and default Section

`dashboard.py` currently renders a horizontal body-level `st.radio` with key
`main_section_selector`; it is not a sidebar router. The ordered labels are:

1. Technical Analysis / 技术分析 / Análisis técnico
2. Options & GEX / 期权与 GEX / Opciones y GEX
3. Value Investing / 价值投资 / Inversión en valor
4. US Market Valuation
5. Factor Watch 因子监控
6. News & Sentiment / 新闻与情绪 / Noticias y sentimiento
7. Multi-Agent Research / 多智能体研究 / Análisis multiagente
8. Macro / 宏观 / Macro
9. IBKR What-if
10. Micron valuation (`mt("tab")`)

The radio has no explicit `index`, so a fresh session defaults to its first
item, Technical Analysis. Streamlit may retain a prior selection under
`main_section_selector`; Memory Cycle must not change that default or reuse the
key. There is no query-parameter or URL-routing state in the current file.

The sidebar owns the global language selector, Watchlist manager, and
performance debug panel. Memory Cycle is absent from both the body Section
radio and the sidebar.

### 3.2 Page loading order and Watchlist relationship

The current `main()` order is:

1. page configuration, debug reset, and global CSS;
2. sidebar language and Watchlist manager;
3. Dashboard title and caption;
4. `load_watchlist()` plus cached snapshot construction for every symbol;
5. overview-card rendering;
6. Section radio selection;
7. selected Section renderer;
8. timing capture and performance debug panel.

Consequently, merely selecting a future Memory Cycle Section would not prevent
the existing Dashboard shell from reading the Watchlist and attempting cached
Yahoo/FMP-backed overview-card work before the Section branch. Memory Cycle
must not write the Watchlist or derive its own state from Watchlist selection.
This loading order is a material reason not to claim that an embedded Static
Preview makes no external request at page entry.

### 3.3 Current exception and cache boundaries

Individual card loads and several existing workflows catch local exceptions,
but the selected Section dispatch itself has no page-level `try/except`. An
uncaught Section renderer error aborts that Streamlit rerun before timing and
debug rendering finish. A future Memory Cycle branch therefore requires its
own narrow, sanitized exception boundary.

Dashboard caches are function-owned and use workflow-specific TTLs. Global
overview quote snapshots currently use a 300-second cache and card financials
use a six-hour cache. News, macro, options, IBKR, and other workflows own other
caches and refresh keys. A future Memory Cycle page must not clear or reuse any
of those caches.

## 4. Recommended independent navigation entry

**Recommended insertion point: `AFTER_FACTOR_WATCH_BEFORE_NEWS`.** If and only
if the production gate is later satisfied, add Memory Cycle as an independent
Section immediately after Factor Watch and before News & Sentiment.

| Language | Proposed navigation name |
| --- | --- |
| 中文 | 存储周期监控 |
| English | Memory Cycle Monitor |
| Español | Monitor del ciclo de memoria |

Why this position:

- It follows market/factor context with a semiconductor-industry synthesis.
- It precedes news evidence without becoming a News subpage or implying that
  qualitative news signals are direct memory prices.
- It stays separate from the Micron valuation model, which is a single-company
  valuation workflow rather than an industry-cycle monitor.
- It stays separate from Value Investing, whose scope and calculation model are
  different.
- It avoids embedding Memory Cycle in Factor Watch, which would risk presenting
  equity/ETF proxies as memory fundamentals.

Option 2, near the Micron valuation tab, risks conflating an industry-wide
monitor with one company's valuation assumptions. Option 3, near or inside the
News module, risks making all cycle evidence look news-derived. Option 1 has
the clearest cognitive sequence, but an eleventh horizontal radio item creates
a real wrapping and discoverability risk—especially for the Spanish label.
That navigation risk needs visual validation before implementation.

## 5. Option A — Static Preview

### Proposed behavior

- Add the independent navigation label above.
- Render only the reviewed fixtures through the existing view model and
  component.
- Preserve the prominent Demo / Static Test Data warning, fixed fixture date
  range, fixed evaluation time, stale state, and test source.
- Make no Memory Cycle provider, cache, OpenAI, or IBKR call.
- Emit no composite score and no definitive cycle phase.

### Assessment

| Dimension | Assessment |
| --- | --- |
| User value | Demonstrates information architecture and evidence labeling, but supplies no current research observation. |
| Misleading risk | High inside a live-looking Dashboard, even with warnings; static financial dates sit next to current overview cards. |
| Implementation complexity | Low for rendering, medium for safe routing, language integration, error isolation, and navigation QA. |
| Suitable now? | No. The independent Demo already provides the valid preview use case without production-context ambiguity. |

An embedded Static Preview could be mistaken for current data because the
Dashboard shell displays market cards before the selected Section. It also
cannot truthfully promise that entering the page triggers no external API while
the existing shell retains that loading order. Static fixtures must never be
relabeled, cached, or refreshed as production data.

## 6. Option B — Production Data

### Target data flow

```text
authorized provider responses
  -> provider-specific normalization
  -> verified raw observations
  -> Phase 4.6 production validation
  -> Memory Cycle adapters
  -> metric contract records
  -> Phase 4.6 partial-result orchestration
  -> pure view model
  -> existing UI component
```

The page and component must receive already adapted metric contracts. They must
not fetch, normalize, calculate provider priority, or cache data.

### Required ownership

- **Providers:** external requests and raw responses only. Every provider has a
  timeout and explicit handling for rate limits, empty responses, invalid
  schemas, and network failure.
- **Service:** validates types and units, selects source priority, orchestrates
  fallback, retains provenance, and returns safe partial results.
- **Adapters/contract:** produce one normalized record per metric with source,
  source type, observation time, retrieval time, frequency, unit/currency,
  fallback, estimate, stale, missing, unavailable, confidence, and notes.
- **View model:** groups records and builds deterministic quality summaries and
  warnings only; no provider calls and no cycle conclusion.
- **Component/page:** renders passed data and page states only.

### Current missing production conditions

- No authorized direct DRAM/NAND spot or contract price series.
- No standardized HBM, enterprise/client SSD, wafer, or component price series.
- No normalized cross-company inventory, inventory-days, bit-supply, capacity,
  utilization, CapEx, segment revenue, shipment, or ASP history.
- Samsung, SK hynix, and Kioxia identity, currency, fiscal-calendar, and source
  mappings are not production-tested.
- News signals need durable citation retention, extraction-method metadata, and
  confidence review; Daily Brief is an aggregator, not a fact source.
- Phase 4.6 now owns pure observation validation, canonical ten-slot ordering,
  per-observation partial failure, quality counts, and a sanitized backend
  result envelope. It does not own live source priority, provider
  normalization, refresh isolation, cache, or a page-level error boundary.

Production data would provide materially greater user value, but it has high
implementation and validation cost. Static fixture values cannot fill these
gaps because they are synthetic test observations, not delayed production data.

## 7. Option comparison and current recommendation

| Question | Static Preview | Production Data |
| --- | --- | --- |
| Current observations | No | Yes, only after authorized sources exist |
| Misleading risk | High in production shell | Lower when metadata and timestamps are complete |
| Provider/cache work | None for Memory Cycle itself | Substantial and required |
| Error/fallback complexity | Low-to-medium | High |
| Immediate implementation cost | Lower | Higher |
| Current readiness | Demo-ready, not production-ready | Not ready |

**Recommendation:** `WAIT_FOR_PROVIDER_METADATA_COMPLETION` before adding a
formal Dashboard Section. The Phase 4.6 pure service boundary is necessary but
does not make the audited provider helpers production-ready. Continue using the
independent Demo for design and QA; this is not approval to begin production
integration in this phase.

## 8. Page-level error isolation contract

A future page integration must satisfy all of the following:

1. Wrap only the Memory Cycle page assembly/render call in a narrow exception
   boundary; a failure must not change or disable other Sections.
2. Convert fixture, service, view-model, or component failure into a localized,
   generic page error and retain navigation.
3. Never render a traceback, exception representation, local file path, secret,
   API key, authorization header, account identifier, or raw request/response.
4. Keep detailed diagnostics sanitized and out of the user-facing page.
5. Use the existing empty state when the service returns no metrics.
6. Do not request an external API, OpenAI, or IBKR merely on import.
7. Do not read, add, remove, or rewrite Watchlist entries.
8. Do not initialize or mutate unrelated session keys.
9. Do not clear global or other-page caches.
10. A page refresh may target Memory Cycle-owned cache keys only and must not
    trigger unrelated providers.
11. After a page failure, the user must still be able to choose another Section
    on the next Streamlit rerun.

The exception boundary belongs in the future Dashboard composition branch, not
inside the pure view model. It should distinguish safe no-data/fallback states
from unexpected programming errors without exposing internals.

## 9. Session-state boundary

No Memory Cycle session key is added in Phase 4.5. Future keys must use the
`memory_cycle_` namespace and must never share News, Factor Watch, IBKR,
What-if, Watchlist, or valuation keys.

| Possible key | Owner and rule |
| --- | --- |
| `memory_cycle_language` | Prefer reading the existing global language; use only if an explicit page-local override is later approved. |
| `memory_cycle_scenario` | Static Demo/Preview only; absent from Production Data mode. |
| `memory_cycle_refresh_nonce` | Production service refresh only; incremented by an explicit user action and scoped into Memory Cycle cache keys. |
| `memory_cycle_last_error` | Sanitized page status only; never store traceback, raw response, secret, or request payload. |
| `memory_cycle_last_generated_at` | Assembly/retrieval metadata only; never substitute for metric observation time. |

Rules:

- Keep `main_section_selector` and its default unchanged.
- Do not initialize production state at module import.
- Static Preview does not need a real-data refresh nonce.
- Production refresh is explicit, page-scoped, and must not call unrelated
  providers or clear unrelated state.
- State that depends on ticker, provider, date range, currency, unit, language,
  or refresh nonce must include those dimensions in its key or payload.

## 10. Cache ownership

Cache design belongs to provider/service functions, never to the component.
Phase 4.6 intentionally implements no cache and imports no existing Dashboard
cache. The rules below remain future requirements, not claims about the current
pure service.

### Company financials

- Use a quarterly/event-driven observation model with a conservative service
  cache, potentially hours to one day, not a fabricated daily observation.
- Preserve the fiscal period and company-reported observation date separately
  from provider retrieval time and cache-hit time.
- A cache refresh must not advance the filing date or turn old quarterly data
  into current data.

### Market proxies

- Use daily or hourly service caches appropriate to the authorized price source.
- Preserve exchange close/quote time, retrieval time, currency, and fallback.
- Label every proxy as market performance; never infer memory fundamentals or a
  cycle phase from equity/ETF movement.

### News signals

- Use a several-hour service cache only when citations and article publication
  times are retained.
- Preserve publisher, URL/citation, publication time, retrieval time, method,
  and confidence.
- Daily Brief may aggregate cited items but must not be relabeled as the fact
  source or a direct price sequence.

### Page layer

- Own no provider request and no duplicate cache decorator.
- Accept normalized contract records or a safe service result.
- Never call a global `st.cache_data.clear()` or another workflow's `.clear()`.

## 11. Refresh strategy

Phase 4.6 adds no refresh control, nonce, session key, or cache-clearing path.
The following strategy remains deferred until a provider/cache owner is
separately approved.

- Initial Production Data entry may load only Memory Cycle service inputs after
  the future Dashboard shell/loading-order issue is explicitly resolved.
- An explicit Refresh control increments `memory_cycle_refresh_nonce` and
  targets only Memory Cycle service cache keys.
- Company financials, daily/hourly proxies, and several-hour news signals use
  separate refresh cadences; one refresh timestamp must not overwrite their
  distinct observation times.
- Preserve each metric's original `as_of` and `retrieved_at`. Display page
  assembly time separately and never call it a market-data date.
- A provider failure returns partial normalized results plus status metadata; it
  does not erase prior valid provenance or crash unrelated Sections.

## 12. Fallback, stale, missing, and unavailable strategy

- **Fallback:** retain the fallback provider's source, observation time,
  retrieval time, unit/currency, and `is_fallback=true`; never relabel it as the
  primary provider.
- **Stale:** keep the value and exact `staleness_days`, display the stale badge,
  and do not describe it as current.
- **Missing:** show the localized missing state when an expected observation is
  absent or invalid; never coerce `None` to zero.
- **Unavailable:** show no numeric value when the audited capability/source does
  not exist.
- Empty, partial, fallback, and error results are distinct. Do not cache an
  empty/error response as a successful live result.

## 13. Visual and interaction risks requiring manual review

No CSS or component layout change is approved in this phase. Before formal
integration, manually inspect:

1. desktop wide layout;
2. narrow layout;
3. whether seven top quality metrics are too crowded;
4. whether 21 metric cards create excessive information density;
5. long Chinese notes;
6. long Spanish titles and badges;
7. Company Financials card-height consistency;
8. whether Unavailable Data should default to collapsed;
9. whether Notes remain appropriately collapsed;
10. whether all seven sections should remain expanded;
11. warning density in the stale-heavy state;
12. visibility of Proxy and News signal limitations;
13. dark-mode readability and contrast;
14. whether mobile requires a single-column layout;
15. wrapping and discoverability of an eleventh horizontal Section radio item.

## 14. Formal integration gates

Do not modify Dashboard navigation until every applicable gate is satisfied:

- [ ] authorized minimum production sources and permitted use are documented;
- [ ] provider timeouts, schemas, empty responses, rate limits, and failures are tested;
- [ ] normalization preserves observation time, retrieval time, currency, unit, source, and fallback;
- [ ] missing, stale, unavailable, proxy, news-signal, estimate, and fallback states have regression coverage;
- [ ] company, proxy, and news cache ownership and TTLs are explicit;
- [ ] explicit refresh affects only Memory Cycle-owned cache keys;
- [ ] page-level sanitized error isolation is tested;
- [ ] no import-time provider, OpenAI, IBKR, Watchlist, session, or cache mutation occurs;
- [ ] all three navigation labels and layouts are visually checked;
- [ ] desktop, narrow, mobile, and dark-mode states are reviewed;
- [ ] global Dashboard loading order and unwanted overview-card requests are resolved or explicitly accepted;
- [ ] default Technical Analysis Section remains unchanged;
- [ ] static fixtures remain identified as tests and are never a production fallback;
- [ ] no composite Memory Cycle score or definitive cycle phase is introduced.

## 15. Phase 4.6 implemented backend boundary

Phase 4.6 implements the minimum pure backend in
`services/memory_cycle_production.py` without adding a formal Dashboard entry.
The actual flow is:

```text
caller-owned acquisition and verified normalization
  -> injected raw observations
  -> Phase 4.6 validation and unit/period checks
  -> existing Memory Cycle adapters and 15-field contract
  -> stable service envelope; ten canonical slots for non-catastrophic results
```

The market scope is one uniform `latest_price` proxy for MU, SNDK, SMH, and
SOXX. Accepted observations require explicit USD currency, positive numeric
price, aware price and retrieval timestamps, a supported price field, source,
source document/provenance, and complete fallback metadata. These checks
validate declared metadata shape; caller-owned acquisition must authenticate
and authorize the actual source. This does not make any
existing quote helper production-ready: the audited helpers omit some of that
metadata. A 20-session return remains deferred because current history paths do
not prove one adjustment, currency, valid-session, and provenance contract.

The financial scope is exactly Revenue, Gross Margin, and Operating Margin for
MU and SNDK. Revenue is normalized once to USD millions from explicit USD,
thousands, millions, or billions. Margin ratio-to-percent conversion occurs
only for an allowlisted ratio source field; explicit percent fields are not
rescaled. Fiscal label, annual/quarterly type, period end, retrieval time,
field/document provenance, and fallback lineage are supplied, not inferred.
News, fixtures, demos, analyst/model estimates, and unverified source fields
cannot become company-reported metrics. Phase 4.6 accepts only named source
aliases, rejects conflicting ticker/issuer and explicit annual/quarterly
evidence, and requires fallback source and `fallback_from` to resolve to
different approved providers. It does not treat generic “Primary/Secondary
financial API” labels as verified provider identities.

For `ok`, `partial`, and `empty`, the full service returns ten metrics in
canonical order plus expected/successful/stale/missing/unavailable counts and
allowlisted error objects. A catastrophic `error` instead returns a sanitized
empty-metrics envelope. One bad ticker or field does not remove valid siblings.
Adapter exceptions and invalid adapter return types remain isolated to one
slot. User-visible missing notes are neutral; structured codes carry the
validation reason without echoing unsafe metadata. `evaluated_at` is mandatory;
inputs are not mutated and no hidden clock is read.

No provider wrapper, live source priority, cache, network smoke test, refresh,
session state, view-model/component execution, page, route, navigation, or
Dashboard change is part of Phase 4.6. Direct DRAM/NAND/HBM data, inventory,
capacity, ASP, bit growth, composite score, and cycle phase remain unavailable.
The independent static Demo is unchanged and is never a production fallback.

## 16. Phase 4.7 gate and recommendation

The Phase 4.6 service is necessary but not sufficient for formal integration.
Every applicable gate in section 14 remains binding. Phase 4.7 should choose
one separately approved direction:

1. **Provider Metadata Completion (recommended):** verify aware quote time,
   currency, and provenance for all four market tickers; verify field-level
   fiscal label/type, period end, unit/currency, and source document for both
   companies; then test provider failures, source priority, fallback selection,
   cache keys/TTLs, and refresh isolation with injected fakes.
2. **Production Preview Harness:** independently exercise the pure Phase 4.6
   service without production routing and visibly distinguish usable, stale,
   missing, unavailable, fallback, and error results. It must not use static
   fixtures as production data or imply that live acquisition exists.

Provider Metadata Completion is recommended first because no audited current
fetcher emits either complete accepted raw contract. Neither direction
implicitly approves a Dashboard Section. Formal navigation remains blocked
until provider metadata, cache/refresh, page error isolation, three languages,
responsive layouts, loading order, and every other integration gate are met.
