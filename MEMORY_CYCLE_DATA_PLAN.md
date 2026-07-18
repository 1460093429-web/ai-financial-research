# Memory Cycle Dashboard Data Plan

## 1. Module objective and boundary

The future Memory Cycle Dashboard should explain memory-industry conditions from
traceable observations without implying that the repository owns a live DRAM,
NAND, or HBM pricing feed. Every displayed metric must retain its observation
time, retrieval time, source, fallback state, estimate/proxy status, confidence,
and availability status.

Phase 4.0 is an audit and contract phase only. It does **not** add a page, route,
provider, scraper, cache, score, or production data flow. It does not convert
news prose or valuation assumptions into observed prices.

## 2. Availability classes

| Class | Meaning | Permitted presentation |
|---|---|---|
| A — Direct structured data | An existing structured interface returns the raw observation with a verifiable observation time. | Display the value with source and time. A market price remains A only as a market price; using it to infer the memory cycle makes the derived metric D. |
| B — Company-reported data | The economic fact originates in a filing, earnings release, call, or management guidance. FMP/yfinance may transport it, but do not change its provenance to direct market data. | Display only after company identity, fiscal period, unit/currency, and source are verified. |
| C — News-derived signal | Dated, cited reporting supports a qualitative direction or event. | Display an evidence-backed label such as `improving`, `stable`, or `weakening`; never synthesize an exact price or quantity. |
| D — Proxy | A different observable is used as an indirect signal. | Mark as a proxy through `is_estimate=true` or explicit notes, and name the relationship and limitations. |
| E — Unavailable | The repository cannot currently obtain or verify the metric. | Keep `value=null` and `status=unavailable`; show `N/A`/“Unavailable”, never zero. |

Class describes evidence availability. The contract's `source_type` describes
the intended evidence type (`direct`, `company_reported`, `news_signal`, or
`proxy`), while `status=unavailable` records that no usable observation exists.
For example, `dram_spot_price` is intended to be direct data but is currently E
and unavailable. A fact that may exist in a future filing adapter is still E
today if the current project cannot retrieve and verify it; its intended
`source_type` can remain `company_reported`.

## 3. Current repository source audit

| Current entry | Valid use | Class by use | Observation / retrieval support | Important limits |
|---|---|---|---|---|
| Yahoo / yfinance | Security prices; company statements; Yahoo news | A for raw security prices, B for statements, C for news, D when a price becomes a cycle proxy | Market/statement/news observations are sometimes available; retrieval time is generally not retained by current news output | No memory-product pricing. `get_news` and `stock.news` fallback are not separately marked in legacy output. |
| FMP | Quotes/OHLCV; macro; company statements; company/general news | A for raw market/macro observations, B for statements, C for news, D for derived cycle use | Observation dates are available on several endpoints; current wrappers do not consistently preserve per-field retrieval time | No memory-product pricing. A mixed FMP/Yahoo financial snapshot has only snapshot-level provenance. |
| Root `financials.py` | Generic MU/SNDK financial snapshot and company news | B for financials, C for news; price fields can be A | `fiscal_date` and `last_updated` are a useful foundation | Production structured company coverage is MU and SNDK only. Period may be annual, and field-level source/fallback is incomplete. Missing values from convenience APIs must not be allowed to become zero in a Memory adapter. |
| TrendForce public HTML/RSS | Public news and direction signals | C | Article publication date may be present; current output lacks a uniform retrieval time | This is not the licensed TrendForce price database. It cannot support exact DRAM/NAND/HBM prices. |
| Technology & Semiconductor Daily Brief | Citation-backed news transformation | C | Citation publication dates and brief generation time exist | The underlying cited articles remain the facts. `generated_at` is retrieval/generation context, not the observation time. AI synthesis is not an independently verified numeric data series; confidence should be no higher than medium. |
| `macro_data.py` / `factor_watch.py` / ETF monitoring | Macro series, security/ETF prices, relative strength and flows | A for the underlying series; D for Memory Cycle inference | Historical series commonly carry an observation date; retrieval time is not uniform | Broad context only. Static holdings fallback and general macro observations are not memory-industry fundamentals. |
| Watchlist | Ticker universe/configuration | E as a data source | None | It selects symbols; it is not an observation source. |
| IBKR | Account, position, and security snapshots | A/D/E conditionally | A raw security snapshot is A only when both price and `price_time` are present; using it for cycle inference is D, and a missing price/time is E | No memory fundamentals. `SMART/USD` assumptions do not provide safe cross-market coverage for Samsung, SK hynix, or Kioxia. |
| Local CSV and statement fallback | User/account price fallback or broad-market history | D/E | Metadata is incomplete and file-specific | What-if missing-price-to-zero semantics must never leak into this contract. `DRAM_portfolio.csv`, `DRAM_trades.csv`, and security ticker `DRAM` are not DRAM product prices. |
| MU valuation assumptions | Editable scenario inputs | D only when explicitly presented as a user scenario; otherwise E | No verified observation/retrieval time | UBS/Nomura/Goldman-style labels, HBM TAM, price, share, CapEx, and revenue assumptions are model inputs, not company-reported or observed facts. |
| Legacy supply-chain analyzer | Experimental yfinance financial trend code | B-capable in concept, currently E for production | Partial fiscal dates; no complete retrieval/provenance contract | Not connected to the supported Dashboard path and lacks characterization tests. Do not use its SK hynix fallback as production coverage. |
| Environment/secrets configuration | Existing FMP/OpenAI/etc. configuration | E for memory pricing | Not applicable | No approved/licensed memory-pricing key, SDK, or ingestion job is configured. Real secrets were not inspected. |

No current source may be described as “real-time” or “latest” merely because a
cache or function ran recently.

Current cache/update behavior is an implementation boundary, not an observation
frequency or a provider freshness promise:

| Existing path | Current cache/update behavior | Memory Cycle implication |
|---|---:|---|
| Dashboard yfinance quote/card/technical snapshots | 300 seconds | Retain the quote/close observation time; cache age is not market-data age. |
| Dashboard company snapshot and card financials | 21,600 seconds | The underlying fiscal period remains annual/quarterly/event-driven and must be verified. |
| Yahoo/FMP/TrendForce news wrappers | 1,800 seconds | Article publication time is `as_of`; wrapper execution/cache time is not. |
| Daily Brief and ETF-flow digest wrappers | 21,600 seconds | Preserve underlying article dates and original retrieval/generation metadata. |
| Macro market/rates, calendar, and indicators | 900 / 3,600 / 86,400 seconds | Each underlying series keeps its own observation date; broad context remains a proxy when used for memory. |
| Factor Watch price downloads | No Streamlit data cache in the audited path | Provider observation dates are still required before reuse. |
| ETF top holdings | Process-local `lru_cache`; static fallback has no verified update time | Static fallback must not be labelled current holdings. |

## 4. Metric inventory and classification

### 4.1 Prices

| Metric | Class | Intended source type / frequency | Current evidence and rule |
|---|---:|---|---|
| DRAM spot price | E | direct / daily | No authorized structured source; unavailable. |
| DRAM contract price | E | direct / monthly | No authorized structured source; unavailable. |
| NAND spot price | E | direct / daily | No authorized structured source; unavailable. |
| NAND contract price | E | direct / monthly | No authorized structured source; unavailable. |
| HBM price | E | direct / monthly | No standardized or licensed series; unavailable. |
| Enterprise SSD price | E | direct / monthly | No verified series; unavailable. |
| Client SSD price | E | direct / monthly | No verified series; unavailable. |
| Wafer/component price | E | direct / monthly | No verified series; unavailable. |
| DRAM spot-price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| DRAM spot-price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| DRAM contract-price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| DRAM contract-price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| NAND spot-price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| NAND spot-price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| NAND contract-price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| NAND contract-price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| HBM price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| HBM price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Enterprise SSD price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Enterprise SSD price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Client SSD price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Client SSD price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Wafer/component price MoM | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| Wafer/component price YoY | E | direct / monthly | Cannot be calculated without a verified underlying series. |
| DRAM price direction | C | news_signal / event-driven | TrendForce public news and cited Daily Brief evidence; qualitative direction only. |
| NAND price direction | C | news_signal / event-driven | TrendForce public news and cited Daily Brief evidence; qualitative direction only. |
| HBM price direction | C | news_signal / event-driven | TrendForce public news and cited Daily Brief evidence; qualitative direction only. |
| Enterprise SSD price direction | C | news_signal / event-driven | Qualitative cited direction only; not a structured product-price series. |
| Client SSD price direction | C | news_signal / event-driven | Qualitative cited direction only; not a structured product-price series. |
| Wafer/component price direction | C | news_signal / event-driven | Qualitative cited direction only; not a structured product-price series. |

### 4.2 Supply

| Metric | Class | Intended source type / frequency | Current evidence and rule |
|---|---:|---|---|
| DRAM bit supply growth | E | company_reported / quarterly | Future filing/guidance metric; no normalized current series. A separately named direction signal can be C. |
| NAND bit supply growth | E | company_reported / quarterly | Future filing/guidance metric; no normalized current series. A separately named direction signal can be C. |
| DRAM supply direction | C | news_signal / event-driven | Qualitative cited direction only. |
| NAND supply direction | C | news_signal / event-driven | Qualitative cited direction only. |
| Wafer starts/capacity | E | company_reported / quarterly | Not extracted by production modules. |
| Capacity utilization | E | company_reported / quarterly | No verified current field. |
| HBM capacity | E | company_reported / quarterly | Exact values need a future cited company adapter; current news may only produce a separately named C direction signal. |
| Advanced packaging, TSV, CoWoS capacity direction | C | news_signal / event-driven | News can show expansion/tightness direction, not a precise capacity series. |
| Manufacturer expansion plans | C | news_signal / event-driven | Dated cited expansion events. |
| Production cuts/supply discipline | C | news_signal / event-driven | Dated cited cut or discipline events. |
| Node-transition effective capacity | C | news_signal / event-driven | Directional evidence only; no precise effective-capacity calculation. |

### 4.3 Demand

| Metric | Class | Intended source type / frequency | Current evidence and rule |
|---|---:|---|---|
| AI server/accelerator demand | C | news_signal / event-driven | Cited direction only. |
| HBM demand | C | news_signal / event-driven | Cited direction only. |
| Data-center server demand | C | news_signal / event-driven | Cited direction only; no verified unit series. |
| Enterprise SSD demand | C | news_signal / event-driven | Cited direction only. |
| PC/smartphone demand | E | company_reported / monthly | No shipment/demand series and no approved proxy. Cited news may provide a separately named C direction signal. |
| Company-reported cloud-provider CapEx | E | company_reported / quarterly | No normalized company-reported series. |
| Cloud-provider CapEx news | C | news_signal / event-driven | Dated, cited CapEx events only. |
| Cloud CapEx → memory demand | D | proxy / event-driven | The inference is a proxy and must not be presented as memory demand itself. |
| GPU/ASIC/AI-server shipments | E | company_reported / quarterly | No verified structured shipment series. |
| Customer inventory restocking | C | news_signal / event-driven | Qualitative cited restocking signal only. |

### 4.4 Inventory

| Metric | Class | Intended source type / frequency | Current evidence and rule |
|---|---:|---|---|
| Manufacturer inventory | E | company_reported / quarterly | Future filing field; not extracted by the current production financials path. |
| Inventory days | E | company_reported / quarterly (derived) | Needs verified inventory and matching COGS periods; not currently calculated. Its later use as inventory-health evidence becomes D. |
| Channel inventory | C | news_signal / event-driven | Qualitative cited signal only. |
| Customer inventory | C | news_signal / event-driven | Qualitative cited signal only. |
| Inventory QoQ | E | company_reported / quarterly (derived) | No normalized inventory history. |
| Inventory YoY | E | company_reported / quarterly (derived) | No normalized inventory history. |
| Inventory digestion stage | E | proxy / quarterly | Future derived label; unavailable until verified inputs exist. |

### 4.5 Company financials

| Metric | Class | Current coverage / frequency | Rule |
|---|---:|---|---|
| Revenue | B | Generic MU/SNDK snapshot; current frequency is event-driven/unknown until annual versus quarterly period verification | Preserve company, fiscal period, currency/unit, transport source, and per-field fallback. |
| Gross margin | B | Generic MU/SNDK snapshot; current frequency is event-driven/unknown until period verification | Do not relabel margin improvement as a product price. |
| Operating margin | B | Generic MU/SNDK snapshot; current frequency is event-driven/unknown until period verification | Same provenance constraints as revenue. |
| Inventory | E | Not extracted in current production path | Unavailable until a verified filing adapter exists. |
| CapEx | E | Not exposed as a verified production field | Manual valuation inputs are not observations. |
| Free cash flow | E | Current production exposes limited FCF margin, not a verified absolute cross-company series | Do not infer absolute FCF from an ambiguous field. The limited FCF-margin field remains a separate B candidate requiring definition/period tests. |
| Management guidance | E | Filing/call evidence adapter is absent | Current automation can only expose a separately named C qualitative guidance direction. |
| DRAM revenue | E | No verified segment series | Never substitute model assumptions. |
| NAND revenue | E | No verified segment series | Never substitute model assumptions. |
| HBM revenue | E | No verified series | Never substitute model assumptions. |
| Bit shipment growth | E | No normalized series; individual cited disclosures could later be B | Keep unavailable until an evidence adapter and tests exist. |
| ASP change | E | No normalized series; individual cited disclosures could later be B | Keep unavailable until an evidence adapter and tests exist. |
| Production growth | E | No normalized series; individual cited disclosures could later be B | Keep unavailable until an evidence adapter and tests exist. |
| Supply-growth guidance | E | No normalized series; individual cited disclosures could later be B | Keep unavailable until an evidence adapter and tests exist. |

Company coverage today:

| Company | Current production structured coverage | Confidence and limitation |
|---|---|---|
| Micron (MU) | Partial generic financial snapshot | Medium only after fiscal period and field provenance are verified. |
| SanDisk (SNDK) | Partial generic financial snapshot | Low; must retain identity/date safeguards because of legacy-symbol risk. |
| SK hynix | No approved production mapping | Legacy untested analyzer only; KR/OTC identity, currency, fallback, and dates need tests. |
| Samsung Electronics | None | Ticker identity, currency, reporting periods, and source mapping are unverified. |
| Kioxia | None | Ticker identity, currency, reporting periods, and source mapping are unverified. |

### 4.6 Cycle signals (not scores)

| Future signal | Present class | Permitted first-stage output |
|---|---:|---|
| Pricing strength | E today; future C-derived | `improving / stable / weakening / unavailable`, with cited evidence. |
| Demand strength | E today; future C/D-derived | `strong / mixed / weak / unavailable`, with each source/proxy shown. |
| Supply discipline | E today; future B/C-derived | `disciplined / neutral / aggressive / unavailable`, with cited company/news evidence. |
| Inventory health | E today; future B/C/D-derived | `improving / elevated / deteriorating / unavailable`, only when inputs support it. |
| CapEx risk | E today; future B/C/D-derived | Explanatory label, not a precise risk score. |
| Margin direction | E today; future D | Current production has a single mixed-period snapshot, not a verified multi-period trend. |
| Cycle phase | E today | Do not calculate `Downcycle`, `Bottoming`, `Early recovery`, `Expansion`, `Tight supply`, or `Late cycle` until evidence coverage is sufficient. |

## 5. Metric data contract

The pure planning contract in `services/memory_cycle_contract.py` requires:

```python
{
    "metric_id": str,
    "label": str,
    "value": object | None,
    "unit": str | None,
    "as_of": str | None,
    "retrieved_at": str | None,
    "source": str,
    "source_type": "direct" | "company_reported" | "news_signal" | "proxy",
    "frequency": "daily" | "weekly" | "monthly" | "quarterly" | "event_driven",
    "is_fallback": bool,
    "is_estimate": bool,
    "staleness_days": int | None,
    "confidence": "high" | "medium" | "low",
    "status": "ok" | "stale" | "missing" | "unavailable",
    "notes": str | None,
}
```

This is not yet a production schema. Future adapters must build one record per
metric rather than wrap a mixed-source snapshot under one source label.

## 6. Observation, retrieval, source, and frequency rules

- `as_of` is the economic observation time: market close/quote time, fiscal
  period end, filing/guidance date, or article publication time.
- `retrieved_at` is when the adapter actually obtained that observation. A cache
  hit must not replace the original retrieval time.
- `evaluated_at` is an injected helper argument, not a stored field in the
  Phase 4.0 schema. Status evaluation uses `evaluated_at - as_of`; this lets a
  cached record continue to age without rewriting `retrieved_at`. It must be at
  or after `retrieved_at`, and tests must inject a fixed value rather than read
  the wall clock implicitly. A record built with `evaluated_at` must be validated
  with the same value; otherwise validation intentionally expects age at
  `retrieved_at`. Evaluation time only ages observable records; a legitimate
  E/unavailable record with no observation or retrieval time remains valid.
- Use timezone-aware ISO 8601 UTC when time-of-day is known. A date-only value is
  acceptable when the provider only supports a date; do not fabricate a time.
  Naive date-time strings are invalid rather than silently assumed to be UTC.
- A company statement transported by FMP/yfinance remains
  `source_type=company_reported`. The transport/provider belongs in source or
  notes without erasing the company-report origin.
- News signals must retain article date, publisher, URL/citation, and the
  direction-extraction method. Brief generation time is not the article date.
- Frequency records expected cadence, not cache TTL. A six-hour cache does not
  turn a quarterly observation into a daily metric.
- Registry `sources` identify upstream evidence lineage, not a claim that the
  source directly emits the derived metric. For example, a C news item may be
  cited by a D cloud-CapEx demand proxy, and a B margin observation may feed a D
  margin-direction proxy.

## 7. Fallback rules

1. Preserve the fallback provider's own source, observation time, unit/currency,
   and retrieved time. Never relabel Yahoo, IBKR, CSV, or cached data as FMP.
2. Set `is_fallback=true`; explain the primary source and reason in `notes` until
   a dedicated `fallback_from` field is approved for this contract.
3. Apply fallback per metric. A partially mixed FMP/Yahoo snapshot cannot inherit
   one source label for every field.
4. A fallback does not reset age or confidence. A fallback observation can be
   `ok`, `stale`, `missing`, or `unavailable` independently.
5. Empty response, provider failure, missing field, and unavailable capability
   are distinct states. Do not cache an empty/error result as a successful live
   observation in a future pipeline.
6. Local files require their own provenance and observation date. Existing
   account/What-if zero-contribution behavior is not a valid financial metric
   fallback.

## 8. Stale and status rules

Phase 4.0 defaults are conservative planning thresholds:

| Frequency | Stale when observation age is greater than |
|---|---:|
| daily | 3 days |
| weekly | 14 days |
| monthly | 45 days |
| quarterly | 135 days |
| event-driven | 30 days |

These are the fixed Phase 4 planning thresholds. Any provider-specific change,
calendar rule, or market-closure adjustment requires an explicit contract
revision and matching tests before production use.

Status precedence:

1. `unavailable`: the audited capability/source does not exist.
2. `missing`: an expected observation/value or a valid timestamp is absent, or
   retrieval appears earlier than observation.
3. `stale`: a valid observation exists but its age at the injected
   `evaluated_at` exceeds its threshold.
4. `ok`: value, source, observation time, retrieval time, and age all pass.

`is_fallback` and `is_estimate` are orthogonal flags; neither overrides status.
Do not use “real-time”, “live”, or “latest” as a label without explicit source
support and a verified timestamp.

## 9. Missing, proxy, estimate, and confidence display

- `None` stays `None`. UI should render `N/A`, `Missing`, or `Unavailable`
  according to status; it must never coerce missing revenue, margin, inventory,
  price, or days to zero.
- `unavailable` means the current project has no trustworthy capability;
  `missing` means a normally expected observation was absent or invalid.
- A proxy must set `is_estimate=true` or explain the proxy relationship in
  `notes`. Recommended production practice is to do both.
- A model/manual assumption must be labelled as a scenario, never as observed or
  company-reported data.
- A news signal value uses a canonical qualitative label such as `improving`,
  `stable`, or `weakening`, always with `unit=null`. The named article source,
  citation, and extraction method belong in source/notes. Phase 4 uses explicit
  `Citation:` and `Method:` note markers; product names such as HBM3E or DDR5
  also belong in notes rather than the canonical value. A number
  quoted in an article remains evidence text until a verified
  structured/company-reported adapter validates its unit, period, company, and
  citation.
- Suggested confidence ceiling: high for identity/time/unit-verified direct
  observations; medium for verified company-reported values and cited news;
  low for fallbacks, ambiguous mixed-source fields, manual inputs, and proxies
  with weak linkage. Confidence never repairs missing provenance.

## 10. Explicitly unavailable metrics

Until an approved source and tests exist, do not display concrete values for:

- DRAM/NAND spot or contract prices;
- HBM, enterprise SSD, client SSD, wafer, or component prices;
- price MoM/YoY derived from those absent series;
- exact bit supply, wafer starts, utilization, HBM/TSV/CoWoS capacity;
- exact GPU/ASIC/AI-server shipments or customer inventory/restocking amounts;
- normalized inventory days and inventory history;
- verified absolute cross-company CapEx/FCF history in the current production
  path;
- DRAM/NAND/HBM segment revenue and normalized ASP/bit-shipment guidance;
- production financial coverage for Samsung, SK hynix, and Kioxia;
- a composite Memory Cycle score or definitive cycle phase.

## 11. Recommended first MVP indicators

The smallest honest MVP should prefer a few well-labelled observations over a
wide but synthetic panel:

1. **Verified company-reported fields**: MU and SNDK revenue, gross margin, and
   operating margin only when company identity, fiscal period, unit, and
   per-field provenance are valid. The limited FCF-margin field waits for
   separate definition and period tests. Unsupported inventory, CapEx, and
   absolute FCF remain unavailable cards.
2. **Market proxies**: MU/SNDK share-price trend and SMH/SOXX trend, each clearly
   marked as a proxy and never labelled memory-product pricing. Cross-market SK
   hynix/Samsung/Kioxia prices wait for ticker, currency, calendar, and identity
   tests.
3. **Cited qualitative signals**: DRAM/NAND/HBM pricing direction, supply
   discipline/capacity events, AI/HBM/enterprise-SSD demand, cloud CapEx, and
   inventory/restocking signals from TrendForce public news and Daily Brief
   evidence.
4. **Transparent gaps**: show explicit unavailable status for exact prices,
   inventory days, segment revenue, and unsupported company coverage.
5. **Interpretation only**: explain each pricing/demand/supply/inventory signal;
   do not compute a numeric cycle score or definitive phase.

## 12. Deferred work

- Licensed/authorized memory product-price integration and legal/data licensing
  review.
- Filing/IR adapters for inventory, CapEx, FCF, guidance, segment revenue, ASP,
  bit shipment, and supply growth.
- Tested Samsung, SK hynix, and Kioxia identities, currencies, fiscal calendars,
  ticker fallbacks, and corporate actions.
- Field-level provenance adapters for mixed FMP/yfinance financial snapshots.
- Provider-error versus empty-result cache semantics and refresh/version keys.
- Evidence aggregation and explainable cycle labels, followed only much later by
  a calibrated score if coverage and historical validation justify it.
- Production UI, translations, routing, responsive layout, and Streamlit smoke
  tests.

## 13. Text-only page sketch (future, not implemented)

1. Header: “Memory Cycle Monitor”, selected observation date, retrieval date,
   coverage summary, and an explicit “No licensed price feed” notice.
2. Data-quality strip: counts of ok/stale/missing/unavailable metrics, fallback
   indicators, and source legend A–E.
3. Company cards: MU and SNDK verified quarterly fields with fiscal dates and
   source drill-down; unsupported companies remain visible as unavailable.
4. Proxy panel: company equities and semiconductor ETFs with a persistent
   “market proxy—not memory price” label.
5. Evidence panels: Pricing, Demand, Supply Discipline, Inventory, CapEx Risk,
   and Margin Direction. Each label links to dated citations and shows
   confidence/fallback status.
6. Unavailable panel: exact product prices and missing fundamental series, with
   the reason rather than a fabricated chart or zero.
7. Methodology footer: source classification, stale thresholds, fallback rules,
   and last retrieval details. No numeric cycle score in the first version.

## 14. Phase 4.1 injected metric adapters

Phase 4.1 implements a data-layer-only boundary in
`services/memory_cycle_adapters.py`. It accepts observations that a caller has
already obtained and returns the existing 15-field contract; it does not fetch,
cache, score, chart, or render anything.

### Company financial observations

- `adapt_company_financial_metric` currently accepts explicitly identified MU
  and SNDK observations.
- The caller must provide the metric ID, label, finite numeric value, unit,
  fiscal period (`annual` or `quarterly`), observation/retrieval/evaluation
  times, named source, source field, frequency, and either a source document or
  provenance description. Monetary values additionally require currency when
  the caller explicitly sets `currency_required=true`.
- Fiscal period, unit, currency, field identity, and source are never inferred
  from the ticker, metric name, or current date. Zero is retained; booleans,
  blank strings, NaN, infinity, absent metadata, and naive timestamps produce a
  `missing` record with `value=null`.
- The contract has no separate fiscal-period, currency, source-field, or
  provenance fields. These explicit inputs are therefore retained in `notes`
  rather than adding a second schema.
- Metrics classified E by the Phase 4.0 audit stay `unavailable` even if a
  caller supplies a value. Enabling inventory, inventory days, CapEx, or FCF
  requires a separate source-audit/contract change; the adapter cannot bypass
  the registry.

### Market proxies

- `adapt_market_proxy_metric` emits `source_type=proxy` and
  `is_estimate=true`, requires an explicit method, and states that the value is
  market performance rather than a direct memory price, inventory, supply,
  demand, company fundamental, or cycle-phase observation.
- Missing timestamps return `missing`. Requested high confidence is capped at
  medium; a rising equity or ETF value never creates a DRAM/NAND/HBM or cycle
  conclusion.

### Cited news signals

- `adapt_news_signal_metric` accepts only the contract's canonical qualitative
  vocabulary and always emits `unit=null`.
- A named independent source, citation, method, and explicit timestamps are
  required. Output notes contain both `Citation:` and `Method:` markers.
- Daily Brief is an aggregation boundary, not an independent fact source; it
  cannot be supplied as the source. Precise numbers, percentages, unknown
  labels, and uncited assertions become `missing`, never invented values.
- An explicit `unavailable` input produces the same unavailable contract used
  for audited source gaps.

### Unavailable, time, and batch behavior

- `build_unavailable_metric` always returns `value=null`,
  `source=unavailable`, `status=unavailable`, `confidence=low`, and
  `is_fallback=false`, using the audited source type/frequency where one exists.
- Observation, retrieval, and evaluation times remain separate. `evaluated_at`
  is mandatory for usable observations and no hidden current time is read.
  Date-only values are supported; timestamps containing a time must be
  timezone-aware. The Phase 4.0 stale thresholds are reused unchanged, and a
  fallback flag never resets observation age.
- `adapt_memory_cycle_metrics` accepts ordered list/tuple call specifications,
  preserves order, does not mutate inputs, and replaces an invalid element with
  an explicit unavailable placeholder. It performs no I/O.

The adapters are deliberately not connected to `dashboard.py`, providers,
Streamlit cache/session state, the sidebar, or any production data path.

## 15. Phase 4.2 recommended scope

Use static, reviewed fixtures to build a pure Memory Cycle MVP view model from
these records. The view model should group contract records, expose data-quality
counts and explanatory labels, and preserve all source/time/fallback metadata.
It should not fetch data, add a production page, compute a score, infer a cycle
phase, or turn unavailable metrics into synthetic observations. Three-language
UI integration remains a later, separately approved step after the static view
model is characterized.

## 16. Phase 4.2 static fixtures and MVP view model

Phase 4.2 adds reviewed synthetic records in `fixtures/memory_cycle_mvp.py` and
the pure presentation model in `services/memory_cycle_view_model.py`. The
fixtures cover MU/SNDK financials, MU/SNDK/SMH/SOXX market proxies, six cited
qualitative signals, and five explicit source gaps. They are built with the
Phase 4.1 adapters, use fixed injected timestamps, identify themselves as
test/demo data, and are not imported by the production Dashboard path.

The view model preserves source, observation time, unit, confidence, fallback,
estimate, staleness, notes, and evidence availability. It groups records into
company financials, pricing, demand, supply discipline, inventory health,
market proxies, and unavailable data while retaining input order inside each
group. Deterministic quality summaries and warnings are available in English,
Simplified Chinese, and Spanish. Missing or unavailable values remain visibly
non-numeric, zero remains a valid observation, qualitative news values remain
labels, and proxy/news warnings state their limitations.

This module performs no provider, network, OpenAI, IBKR, filesystem, secret,
cache, Streamlit, score, or cycle-phase operation. No Dashboard page, route, or
sidebar entry is added in this phase.

## 17. Phase 4.3 standalone MVP UI components

Phase 4.3 adds `components/memory_cycle.py`, a presentation-only Streamlit
component built from the Phase 4.2 view model. A pure preparation function
copies and safely shapes sections, metrics, the quality summary, warnings, and
the most recent observation date without changing order or deriving any new
financial signal. Separate dashboard, section, and metric renderers keep this
preparation independent from Streamlit calls.

The component displays the seven existing sections and a quality summary for
available, missing, stale, unavailable, proxy, and news-signal observations.
Each metric keeps its value/unit, status, confidence, observation date, source,
source type, badges, evidence state, staleness, and notes visible. Missing and
unavailable values are rendered as explicit states rather than zero; proxy,
news-signal, fallback, estimate, and stale limitations remain prominent.

English, Simplified Chinese, and Spanish component copy is local to this
standalone boundary, with English as the fallback for an unknown language. The
component uses no provider, network, OpenAI, IBKR, filesystem, secret, cache,
score, or cycle-phase operation. It is not imported by `dashboard.py`, and no
page, route, sidebar entry, or production data flow is added in this phase.

## 18. Phase 4.4 static demo harness

Phase 4.4 adds `demos/memory_cycle_demo.py`, an independently runnable
Streamlit harness for visual review of the Phase 4.2 static fixtures through
the Phase 4.3 component. It provides Simplified Chinese, English, and Spanish
selection plus stable full, empty, missing-heavy, stale-heavy,
unavailable-heavy, and proxy/news-signal-focused scenarios. Every scenario
returns fresh records, preserves the original fixture, and uses an explicit
fixed evaluation timestamp rather than the current clock.

Run the centered, responsive review page with:

```bash
streamlit run demos/memory_cycle_demo.py
```

The harness identifies itself as static demo data and states that no real
market data is fetched and no cycle score or phase is calculated. It delegates
all Memory Cycle presentation to `render_memory_cycle_dashboard`; it does not
copy metric or section rendering. The demo reads no provider, production
session state, secret, API key, environment variable, cache, or file and is not
imported by `dashboard.py`. No production page, route, or sidebar entry is
added.
