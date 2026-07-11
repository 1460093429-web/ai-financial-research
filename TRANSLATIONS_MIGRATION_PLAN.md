# Dashboard Translation Migration Plan

Audit date: 2026-07-12. Phase 1.5 is analysis and test protection only. It does not move `TRANSLATIONS` or change `t()`, language state, layout, providers, fallbacks, caches, or financial behavior.

## Current size and composition

The base `TRANSLATIONS` dictionary occupies 132 physical lines in `dashboard.py`. It contains three canonical languages (`English`, `中文`, and `Español`) with 141 keys per language. The three base key sets are identical.

At Dashboard import time, two static resources are merged into that dictionary:

- `NEWS_UI_TRANSLATION_OVERRIDES`: 27 keys per language.
- `MACRO_TRANSLATION_OVERRIDES`: 33 keys per language.

Three keys overlap the base dictionary, so the resulting runtime dictionary has 198 unique keys per language. `translations/news.py` contains independent news labels, language mappings, versions, and keyword constants. `translations/multi_agent.py` contains the separate `MULTI_AGENT_TEXTS` resource and language normalization helper. Neither is merged wholesale into `TRANSLATIONS`.

## Runtime relationships

- `t(key)` reads `st.session_state.get("language", DEFAULT_LANGUAGE)`, where the default is `中文`.
- For an unsupported language, `t()` selects the English dictionary.
- For a key missing in the selected language, `t()` falls back to the English value.
- If the key is also absent from English, `t()` returns the key itself.
- `_translation_language_key()` maps the canonical override language names to keys already present in `TRANSLATIONS`; it runs before the news and macro overrides are merged.
- The sidebar selector uses `English`, `中文`, and `Español`, derives its initial index from session state, and stores the selection under the existing `language` key.

A future extraction must preserve object mutability and import order because `dashboard.py` currently updates `TRANSLATIONS` in place after importing the override dictionaries.

## Key risk classification

### Low-risk migration candidates

Application-shell and generic display labels have no financial or source semantics. Examples include `language`, `dashboard_title`, `dashboard_caption`, `technical_analysis`, `news_sentiment`, `multi_agent_research`, `macro`, `source`, `price`, `today`, `all`, `ticker`, `company`, `open_article`, `untitled_article`, `unknown_publisher`, `date_unavailable`, and `unknown_source`.

### Move only after more characterization

Technical, news, daily-report, earnings, and macro UI keys are static, but they are consumed across several render paths. Representative keys include `technical_caption`, `rsi_signal`, `volume_vs_20d`, `daily_report_caption`, `technical_snapshot`, `earnings_catalysts`, `market_news_caption`, `macro_caption`, and `dynamic_macro_calendar`. Before feature-level splitting, tests should pin their complete three-language values and override precedence.

### Temporarily avoid feature-level migration

Do not separately reorganize keys that overlap an override (`open_article`, `last_updated`, and `macro_risk_score`) until merge precedence is explicitly tested. Watchlist labels from `news_ui.py` should remain where they are because moving them would touch a protected workflow boundary even if the strings themselves are static.

### Keys bound to protected or high-risk modules

- Options/GEX: `options_gex`, `options_caption`, `put_call_ratio`, `max_pain`, `net_gex`, `call_wall`, `put_wall`, `gamma_squeeze_risk`, `gex_unavailable`, `positive_gex`, `negative_gex`, `options_unavailable`, `strike`, `open_interest`, `gamma_exposure_by_strike`, and `gex_chart_unavailable`.
- Valuation/financial metrics: `value_caption`, `valuation_unavailable`, `gross_margin`, `operating_margin`, `fcf_margin`, `current_ratio`, `quick_ratio`, `debt_equity`, growth keys, target-price keys, and analyst-rating keys.
- Provider/fallback semantics: `historical_price_source`, `fmp_news_fallback`, `market_news_unavailable`, `data_source`, `macro_caption`, and `treasury_source`.

Moving these strings unchanged does not alter calculations, but accidental omissions or wording changes could misstate financial meaning, provenance, or fallback status. They should not be selected for the first feature-level extraction.

## Phase 1.6 recommendation

Do not split individual keys out of the nested dictionary because that would introduce new assembly and precedence behavior. The smallest safe implementation is one atomic relocation of the unchanged base dictionary:

1. Add `translations/core.py` containing the complete base `TRANSLATIONS` object.
2. Import and re-export that object under the same name in `dashboard.py`.
3. Leave `_translation_language_key()`, both override loops, `DEFAULT_LANGUAGE`, `t()`, session state, and the language selector unchanged.
4. Extend `tests/test_dashboard_translations.py` to assert object identity with `translations.core.TRANSLATIONS`, exact pre-override fixture equivalence, runtime key parity, override precedence, and fallback behavior.

Phase 1.6 should modify only `dashboard.py`, `translations/core.py`, and the translation test file. The principal risks are transcription loss, changed Unicode text, import-order changes, and accidentally replacing the shared mutable dictionary with a copy.
