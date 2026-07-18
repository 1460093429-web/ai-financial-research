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

The demo header explicitly states in all three languages that the fixture does
not represent current market conditions or the latest filings. It shows the
unchanged fixture observation-date range (`2025-01-31` through `2025-02-14`),
the fixed demo `evaluated_at`, the fixture module as the demo/test source, and
that no real data is fetched. Observable fixture records are re-evaluated only
on fresh demo copies against the fixed demo date, so expired values display as
stale with deterministic `staleness_days`; source dates and financial values
are never advanced or replaced.

## 19. Phase 4.6 minimal production data pipeline

Phase 4.6 adds the pure, observation-in/contract-out service in
`services/memory_cycle_production.py`. It is a production validation and
orchestration boundary, not a live fetcher. The module reuses the existing
Memory Cycle adapters and 15-field metric contract, accepts caller-injected raw
observations, and returns fresh metrics plus a sanitized result envelope. It
performs no network request, provider-client creation, environment or secret
lookup, file access, cache operation, session-state mutation, Streamlit
rendering, composite scoring, or cycle-phase inference.

No provider wrapper was added. The repository audit found no existing helper
that can directly produce an accepted raw observation:

- current-price helpers omit at least currency, reliable timezone-aware price
  time, retrieval time, field/document provenance, or complete fallback
  lineage;
- `financials.fetch_historical_prices` retains provider name and trading dates,
  but not one verified adjusted-price, currency, retrieval-time, and fallback
  contract across MU, SNDK, SMH, and SOXX;
- company snapshots can mix FMP and Yahoo fields under an aggregate source and
  do not retain per-field fiscal label/type, currency/unit, or provenance;
- Dashboard, card, and What-if helpers are page/cache-specific and are not
  imported by this service.

These helpers may become dependency sources only after a future normalization
boundary supplies verified metadata. Incomplete output is rejected; the
service never fills gaps from a ticker, the current time, provider list order,
or an undocumented convention.

### 19.1 Locked market semantic and raw observation contract

All four Phase 4.6 market metrics use the uniform `latest_price` semantic. It
was selected instead of a 20-session return because the current history paths
cannot prove one adjustment, currency, valid-session-count, and provenance
contract across all four symbols.

| Ticker | Metric ID | Source type | Frequency | Maximum confidence |
| --- | --- | --- | --- | --- |
| MU | `mu_market_price_proxy` | `proxy` | `daily` | `medium` |
| SNDK | `sndk_market_price_proxy` | `proxy` | `daily` | `medium` |
| SMH | `smh_market_price_proxy` | `proxy` | `daily` | `medium` |
| SOXX | `soxx_market_price_proxy` | `proxy` | `daily` | `medium` |

An accepted market observation provides:

```text
ticker, positive finite numeric value, metric_kind=latest_price,
unit=USD, currency=USD, as_of, retrieved_at, source, source_field,
source_document or provenance, is_fallback, fallback_from
```

Supported source fields are explicit price fields (`regularMarketPrice`,
`postMarketPrice`, `preMarketPrice`, `price`, `last`, `lastPrice`,
`last_price`, or `close`), not unrelated fields such as market capitalization.
Booleans, numeric strings, zero, negative values, NaN, and infinity are
rejected. Declared market sources are restricted to normalized aliases for
IBKR/Interactive Brokers, Yahoo/Yahoo Finance/yfinance, and FMP/Financial
Modeling Prep. Evidence must syntactically identify a quote, market-data or
price snapshot, historical price/close, or OHLCV record; a financial statement
cannot be relabelled as quote evidence. Explicit evidence for another supported
ticker is rejected. These are syntactic boundary checks, not authentication:
caller-owned acquisition remains responsible for proving that a declared
provider and source document are genuine and authorized.

`as_of` is the security price time and must be an aware `datetime` or offset ISO
timestamp. `retrieved_at` is a separate aware timestamp and must satisfy
`as_of <= retrieved_at <= evaluated_at`. The service does not substitute
retrieval or page-access time for price time. Output notes preserve currency,
source field, source document/provenance, and fallback lineage because the
existing contract has no separate top-level fields for those items. Every
market record remains explicitly a proxy/estimate; it is not DRAM, NAND, HBM,
inventory, supply, demand, or a cycle conclusion.

### 19.2 Company financial raw contract and normalization

Only these six company-reported observations are supported:

```text
MU:   revenue, gross_margin, operating_margin
SNDK: revenue, gross_margin, operating_margin
```

Every accepted observation supplies:

```text
ticker, field, finite numeric value, unit, currency when monetary,
fiscal_period, period_type, as_of, retrieved_at, source, source_field,
source_document or declared provenance, is_fallback, fallback_from
```

`fiscal_period` is an explicit single-period label such as `FY2026 Q3`,
`Q1 2026`, `FY2026`, or `2026`. `period_type` is separately restricted to
`quarterly` or `annual`: a quarterly label must contain exactly one year and
one Q1-Q4 token, while an annual label must identify exactly one year and no
quarter. Mixed periods, estimate suffixes, `latest`, `recent`, `current`, `TTM`, `unknown`,
`estimate`, `consensus`, `forecast`, `projected`, and `guidance` are rejected.
`as_of` is the statement period end and may be a date-only value;
`retrieved_at` and caller-required `evaluated_at` are aware timestamps.

Declared financial evidence must syntactically identify a company report or
statement, such as an income statement, Form 10-Q/10-K, annual/quarterly
report, earnings release, or SEC/company filing. Declared Daily Brief, news,
fixture, demo, analyst article, consensus/model estimate, and synthetic/mock
inputs are rejected. An explicit 10-Q/quarterly/Q1-Q4 declaration cannot back
an annual observation, and an explicit 10-K/annual declaration cannot back a
quarterly observation. The accepted source identifier must be one exact,
named FMP, Yahoo, SEC/EDGAR, Micron, or Sandisk alias; generic “Primary API” or
composite names containing an approved provider token are not accepted. An
explicit MU/SNDK issuer identity must agree across source, document,
provenance, reference, and fallback metadata. The service does not authenticate
those declarations; caller-owned acquisition must establish source
authenticity and authorization. An optional safe `source_reference` is
preserved only as an HTTPS URL without query/fragment/userinfo or as a
conservative identifier. Credentials, secret-looking tokens, local paths,
control characters, traceback/response-body text, and JSON/XML-like payloads
are rejected from all metadata that could otherwise be echoed.

Revenue is normalized exactly once to `USD millions` with one shared MU/SNDK
mapping:

| Explicit input unit | Conversion to `USD millions` |
| --- | --- |
| `USD` | divide by 1,000,000 |
| `USD thousands` | divide by 1,000 |
| `USD millions` | unchanged |
| `USD billions` | multiply by 1,000 |

Revenue currently requires `currency=USD`; no FX conversion occurs. Unknown
units, currency/unit conflicts, and a non-finite result after explicit scaling
become missing with an input-validation code before the adapter is called.
The accepted Revenue `source_field` is exactly `revenue`; aliases are not
inferred. Zero and negative finite revenue values remain values under the
existing contract rather than being silently rewritten.

Margins are uniformly output as `percent` and their input `currency` must be
absent or null. Conversion is controlled only by the explicit source-field
mapping below:

| Field | Ratio source fields | Percent source field |
| --- | --- | --- |
| Gross margin | `grossProfitRatio`, `grossProfitMargin` | `grossMarginPercent` |
| Operating margin | `operatingIncomeRatio`, `operatingProfitMargin` | `operatingMarginPercent` |

A ratio is multiplied by 100 once; a percent is unchanged. The service never
uses a “less than one” heuristic. A field/unit mismatch is ambiguous and
becomes missing; an unlisted margin source field becomes unavailable. Finite
zero, negative, and extreme margins are not clamped. Fiscal label, period type,
original unit, currency, field/document provenance, optional reference, and
fallback lineage are preserved in existing contract fields or `notes`.

### 19.3 Service interface and canonical result

The public pure functions are:

```python
build_market_proxy_metrics(observations, *, evaluated_at)
build_company_financial_metrics(observations, *, evaluated_at)
build_memory_cycle_production_metrics(
    *, market_observations, financial_observations, evaluated_at
)
```

`evaluated_at` is mandatory and aware. No function reads a hidden clock. Inputs
are copied without sorting or mutation, and each call returns new lists,
dictionaries, metric records, and error records.

The stable canonical order is:

1. MU market-price proxy
2. SNDK market-price proxy
3. SMH market-price proxy
4. SOXX market-price proxy
5. MU Revenue
6. MU Gross Margin
7. MU Operating Margin
8. SNDK Revenue
9. SNDK Gross Margin
10. SNDK Operating Margin

The full result contains `metrics`, `status`, `expected_metric_count=10`,
`successful_metric_count`, `stale_metric_count`, `missing_metric_count`,
`unavailable_metric_count`, and `errors`. Successful count includes both `ok`
and `stale` records with values; stale is also counted separately. Missing and
unavailable remain distinct.

- `ok`: every expected slot has an `ok` or `stale` value;
- `partial`: non-empty caller input has recoverable missing, unavailable,
  invalid, or absent slots; this also covers an invalid-only call with zero
  successful slots so one bad observation never becomes a system error;
- `empty`: both observation collections are empty; ten missing placeholders are
  returned with no invented values;
- `error`: an unexpected internal failure prevents safe orchestration.

Input order does not affect metric order. Errors are sorted by family, ticker,
field, and code and contain exactly those four keys. Stable codes cover
unsupported ticker/field/kind/source, missing or invalid values, unit/currency/
period/time/provenance failures, ambiguous margin units, invalid references,
incomplete fallback metadata, duplicates, `fetch_failed`, `adapter_failed`,
identity/cadence conflicts, and overall `internal_error`. An injected
failed-observation envelope may use
`error` or `fetch_error`; its value is never copied to output. Exception text,
traceback, response bodies, headers, local paths, URL credentials, keys, and
tokens are never returned.

Invalid or missing values do not erase other verified metadata. When the
remaining timestamp order, source, unit/currency, and fallback lineage are
valid, the missing contract record retains them while keeping `value=null`.

### 19.4 Fallback, stale, and cache boundary

The service accepts an already-selected fallback observation only when it is
otherwise complete, both source identifiers are approved, their canonical
provider identities are different, `is_fallback=true`, and `fallback_from` is
named. Aliases for the same provider cannot manufacture fallback lineage. A
primary observation cannot carry any non-missing `fallback_from`, and a
rejected source cannot retain a fallback badge. Fallback does not change
`as_of` or `retrieved_at`, reset staleness, or raise confidence; accepted
fallbacks use low confidence. No live provider priority or fallback fetch is
implemented, and news/static fixtures are never company-financial fallbacks.

Existing contract thresholds remain authoritative: market proxies use the
audited `daily` rule and the three generic financial IDs retain their audited
`event_driven` rule. A stale value is kept and counted as successful; it is not
rewritten as current or discarded.

Phase 4.6 implements no cache and reuses no Dashboard cache. Future ownership
belongs to a dedicated provider/service boundary: market TTL may be 15–60
minutes with ticker and semantic in the key; financial TTL may be 6–24 hours
with ticker, field, fiscal period, currency, and unit isolated. Cache-hit or
cached-at time must never replace price time, filing period end, or original
retrieval time.

### 19.5 Remaining unavailable data and next gate

Exact DRAM/NAND/HBM and SSD prices or ASPs; inventory and inventory days;
channel/module inventory; bit supply/demand growth; shipments; wafer,
packaging, TSV, CoWoS, and utilization capacity; segment data; guidance;
estimates; news inference; composite scoring; and cycle phase remain
unavailable. Equity/ETF proxies do not populate those fields.

This pipeline is not imported by `dashboard.py`, is not passed through the
view model/component, creates no page, route, sidebar item, refresh control, or
session state, and has not been validated with a real network request. Phase
4.7, documented below, adds a separately testable metadata boundary, but it
does not validate credentials or a live provider schema. Formal integration
still requires an authorized acquisition binding, controlled smoke evidence,
cache/refresh ownership, and page-isolation and multilingual integration gates.
A separate preview harness may instead exercise the pure service without
production navigation, but must show missing/unavailable states and never use
static fixtures as production data.

## 20. Phase 4.7 provider metadata completion

Phase 4.7 adds `providers/memory_cycle_data.py` and
`services/memory_cycle_live.py`. They form a pure dependency-injection
boundary between caller-owned Yahoo/FMP acquisition and the Phase 4.6 service:

```text
caller-injected Yahoo/FMP raw callable
  -> Phase 4.7 provider-specific parsing and metadata validation
  -> metadata-complete raw observations plus sanitized provider errors
  -> Phase 4.7 live orchestration
  -> Phase 4.6 validation/adapters
  -> ten canonical metric slots
```

The repository audit rejected direct use of the existing high-level helpers.
Dashboard quote and What-if helpers lose currency or use naive/local quote
times; historical-price helpers do not provide one verified quote-time,
currency, and fallback contract; company/card snapshots mix sources and lose
field-level fiscal metadata. The current IBKR helper exposes a network-arrival
time rather than a reliably matched exchange price time. Importing root
`financials.py` would also import `config.py`, load environment/secrets, and
create data/cache directories. Phase 4.7 therefore imports none of those
modules. The only existing low-level raw boundary identified as potentially
bindable is the private FMP JSON helper, passed through a caller-owned closure;
there is no existing named Yahoo helper that already returns price, currency,
and aware market time together. A future composition must supply that raw
Yahoo `info` callable. Neither source is wired by Phase 4.7, which owns no
credentials or network client.

### 20.1 Market raw mapping and fallback

`fetch_market_observations(tickers, *, yahoo_quote_fetcher, retrieved_at,
fmp_quote_fetcher=None)` supports MU, SNDK, SMH, and SOXX in canonical order.
The exact accepted mappings are:

| Provider path | Value | Currency | Market time | Source metadata |
| --- | --- | --- | --- | --- |
| Yahoo primary | `regularMarketPrice` | `currency` | `regularMarketTime` | `Yahoo Finance` / `regularMarketPrice` / `quote` |
| FMP fallback | `price` | `currency` | `timestamp` | `FMP` / `price` / `quote` |

Numeric provider epochs are converted explicitly to aware UTC timestamps.
Aware ISO timestamps are normalized to UTC. Missing, invalid, or naive market
times are rejected; `retrieved_at` is mandatory, caller-injected, aware, and
never substituted for the market time. Currency comes only from the raw quote,
must be a safe three-letter uppercase ISO-style code, and is copied to both raw
`currency` and monetary `unit`; it is not guessed from the ticker. Phase 4.6
still requires USD for an accepted canonical market metric, so another safe
preserved currency becomes a visible validation failure rather than an
implicit conversion. Arbitrary currency text is rejected before it can be
echoed.

Yahoo is the only primary. FMP is called only after the Yahoo callable raises,
returns no matching row, or lacks required metadata. Primary success never
calls FMP. A successful fallback records `source=FMP`, `is_fallback=true`,
`fallback_from=Yahoo Finance`, the FMP market time, and the batch retrieval
time. It does not reset staleness or increase confidence. Current IBKR, CSV,
history, post/pre-market, options, card, and derived-score paths are excluded.

### 20.2 Financial raw mapping and SNDK boundary

`fetch_financial_observations(tickers, *,
fmp_income_statement_fetcher, retrieved_at,
fmp_identity_fetcher=None)` supports MU and SNDK. It accepts only raw FMP
income-statement rows with an exact statement `symbol`, `date`, provider year
metadata (`fiscalYear` when supplied, otherwise `calendarYear`), one of
`Q1`–`Q4` or `FY`, and `reportedCurrency`. It chooses the latest verifiable
period end rather than trusting response order. Two valid rows at the same
latest date are ambiguous and are rejected instead of selecting a quarterly
or annual interpretation by list order. A fallback `calendarYear` must match
the period-end calendar year; an explicit valid `fiscalYear` may differ and is
preserved without applying a Micron-specific rule. Reported currency must use
the same safe three-letter uppercase form as market currency.

| Canonical field | Raw field | Raw unit/currency | Phase 4.6 output |
| --- | --- | --- | --- |
| Revenue | `revenue` | full units in `reportedCurrency` | USD millions only when explicit USD passes Phase 4.6 |
| Gross Margin | `grossProfitRatio` | ratio; no observation currency | percent, converted once by Phase 4.6 |
| Operating Margin | `operatingIncomeRatio` | ratio; no observation currency | percent, converted once by Phase 4.6 |

No margin is synthesized from gross profit, operating income, or revenue, and
no alternative margin field is relabelled as a direct ratio. A missing or
invalid one of the three fields removes only that sibling observation. Shared
statement metadata failure removes all three fields for that ticker. The raw
`date` is the statement period end and becomes `as_of`; injected
`retrieved_at` remains separate.

Quarterly labels are the neutral provider label `<year> Q<n>` and annual labels
are `<year>`. They do not claim that `calendarYear` is Micron's formal fiscal
year, and no Micron fiscal-calendar rule is applied. Explicit `fiscalYear`, if
present and valid, has priority. TTM, unknown, latest, recent, unsupported
periods, missing year metadata, and same-date period ambiguity remain missing.

SNDK has an additional issuer boundary. Before statement acquisition, an
injected FMP profile response must contain exact `symbol=SNDK`, a complete
SanDisk company-name match, and exactly one distinct conservative ten-digit
CIK; duplicate rows with that same CIK are harmless, while conflicting CIKs
are ambiguous. Accepted statement rows must also use exact `SNDK`, match that
CIK, and have a period end on or after the repository-audited `2025-01-01`
cutoff. No WDC mapping, legacy WDC splice, or pre-cutoff history is accepted. A
missing, ambiguous, or mismatched profile or statement identifier becomes
`identity_unverified` or
`statement_identity_mismatch`; a pre-cutoff period becomes
`legacy_statement`. These are syntactic cross-response checks, not proof that
the live FMP history is complete, comparable, authorized, or tied to the
current listed entity; that still requires a controlled live smoke and source
review.

### 20.3 Provider result and live orchestration

Both provider functions return fresh objects with exactly `observations`,
`errors`, and `status`. Provider errors contain only `family`, `ticker`,
`field`, and `code`; exception strings, tracebacks, URLs/query parameters,
headers, response bodies, credentials, and local paths are never copied.
Ticker and field failures are isolated. An empty requested scope is `empty`;
a non-empty scope with no accepted observation is `error`; mixed success is
`partial`; complete accepted observations are `ok`.

`build_live_memory_cycle_result` receives both raw fetch callables plus
mandatory aware `retrieved_at` and `evaluated_at`, optional FMP market and SNDK
identity callables, and optional market/financial scopes. It invokes the two
provider wrappers, passes fresh observation dictionaries to
`build_memory_cycle_production_metrics`, merges/deduplicates/sorts both error
layers, and preserves all Phase 4.6 metrics and quality counts. A valid FMP
fallback can still produce `ok` because its low-confidence fallback lineage is
explicit. A provider outage for a non-empty scope is `partial`, not the
`empty` state reserved for an explicitly empty request. Unexpected production
failure returns only a sanitized `internal_error` envelope.
As in Phase 4.6, this catastrophic error envelope has no metric records;
the fixed ten slots apply to `ok`, `partial`, and `empty` results.

### 20.4 Cache, tests, smoke, and Phase 4.8 preconditions

Phase 4.7 implements no cache, refresh nonce, persistence, environment lookup,
secret lookup, Streamlit/session access, hidden current-time call, file I/O,
OpenAI, IBKR, news inference, score, or cycle-phase logic. Automated tests use
only injected fakes and make no real provider request. No manual network smoke
was run in this phase, so Yahoo/FMP entitlement, rate limits, live field
availability, SNDK issuer history, and production latency remain unverified.

No Dashboard Section, route, sidebar item, component call, view-model call,
production preview, or static-fixture fallback was added. A Phase 4.8
production preview or acquisition/cache phase must first:

1. supply an authorized caller-owned raw Yahoo adapter and, if suitable, bind
   the private FMP JSON helper without importing UI code;
2. perform a controlled, non-persistent schema/identity smoke without printing
   credentials or raw responses;
3. define Memory Cycle-owned market and financial cache keys, TTLs, and refresh
   isolation while preserving original `as_of` and `retrieved_at`;
4. retain the ten-slot partial-failure and sanitized-error behavior; and
5. remain outside formal Dashboard navigation until page isolation,
   multilingual text, responsive layout, and global loading-order gates pass.

## 21. Phase 4.8 shared FMP financial truth layer

Phase 4.8 adds a caller-owned, side-effect-free FMP boundary in
`providers/fmp_financial_data.py`. The caller supplies the JSON callable and
aware retrieval time; the provider does not read credentials, environment,
Streamlit state, files, or a clock. Raw profile, quote, quarterly/annual income,
balance-sheet, and cash-flow families remain separate and retain exact symbol,
CIK when supplied, provider period metadata, currency, and source fields.
Errors expose only stable family/ticker/endpoint/code fields.

`services/fmp_financial_normalization.py` rejects cross-symbol and CIK
conflicts, unsupported provider TTM/LTM rows, missing period/currency metadata,
invalid numeric values, and pre-2025 SNDK statement history. It never maps
SNDK to WDC. Monetary values normalize once to full reported-currency units.
Reported margins convert ratio to percent once; otherwise same-row margins may
be derived. CapEx is the magnitude of a reported non-positive cash outflow and
FCF is accepted only when it agrees with OCF minus that magnitude. TTM income
and cash flow are built only from four unique, continuous, same-ticker,
same-currency quarters. Balance-sheet fields remain point-in-time.

`services/fmp_financial_snapshot.py` consumes only normalized observations and
an injected evaluation time. It keeps current quote, TTM, annual, quarterly,
and latest-balance periods explicit. Revenue growth, inventory growth, net
debt, FCF margin, average-balance ROE/ROA, actual-tax-rate ROIC, and P/E, P/S,
P/B, and EV/EBITDA are derived only when their required periods, currencies,
and positive denominators are verifiable. Missing inputs remain unavailable;
real zero values are not replaced. The cash definition is the first complete
FMP cash-plus-short-term-investments field, without adding overlapping fields.

The minimal `services/memory_cycle_fmp_binding.py` acquires FMP quotes for MU,
SNDK, SMH, and SOXX plus FMP quarterly income statements/profile identity for
MU and SNDK. A dedicated primary FMP market wrapper records `source=FMP`,
`source_type=proxy`, `is_fallback=false`, the provider timestamp, currency, and
quote document. It then reuses the Phase 4.7 financial wrapper and live
orchestrator, preserving the fixed ten-slot Phase 4.6 result. Missing metadata
remains missing and one acquisition failure remains partial. No Yahoo call,
DRAM/NAND/HBM data, cache, score, cycle phase, UI, route, or Dashboard
integration is part of this binding.
