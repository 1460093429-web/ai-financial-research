from conftest import import_root_dashboard


dashboard = import_root_dashboard()


CORE_UI_KEYS = {
    "language",
    "dashboard_title",
    "dashboard_caption",
    "technical_analysis",
    "options_gex",
    "value_investing",
    "news_sentiment",
    "multi_agent_research",
    "macro",
    "source",
    "price",
    "last_updated",
    "watchlist_manager",
    "watchlist_input",
    "watchlist_add",
    "watchlist_remove",
    "option_expiry",
    "option_open_interest_missing",
    "option_gamma_missing",
    "option_call_put_empty",
    "option_price_available_chain_unavailable",
}

SUPPORTED_LANGUAGES = ("English", "中文", "Español")
RUNTIME_TRANSLATION_KEY_COUNT = 198


def test_dashboard_translation_key_sets_are_identical_for_all_supported_languages():
    assert set(dashboard.TRANSLATIONS) == {"English", "中文", "Español"}

    english_keys = set(dashboard.TRANSLATIONS["English"])
    assert CORE_UI_KEYS <= english_keys
    assert set(dashboard.TRANSLATIONS["中文"]) == english_keys
    assert set(dashboard.TRANSLATIONS["Español"]) == english_keys


def test_dashboard_runtime_translation_size_is_characterized():
    for language in SUPPORTED_LANGUAGES:
        assert len(dashboard.TRANSLATIONS[language]) == RUNTIME_TRANSLATION_KEY_COUNT


def test_dashboard_translation_values_for_core_keys_are_non_empty_strings():
    for language in ("English", "中文", "Español"):
        for key in CORE_UI_KEYS:
            value = dashboard.TRANSLATIONS[language][key]
            assert isinstance(value, str)
            assert value.strip()


def test_translation_lookup_uses_selected_language_and_english_fallback(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "Español"})
    assert dashboard.t("dashboard_title") == dashboard.TRANSLATIONS["Español"]["dashboard_title"]

    monkeypatch.setattr(dashboard.st, "session_state", {"language": "unsupported-language"})
    assert dashboard.t("dashboard_title") == dashboard.TRANSLATIONS["English"]["dashboard_title"]
    assert dashboard.t("missing_characterization_key") == "missing_characterization_key"


def test_translation_lookup_uses_default_language_when_session_language_is_missing(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {})

    assert dashboard.DEFAULT_LANGUAGE == "中文"
    assert dashboard.t("dashboard_title") == dashboard.TRANSLATIONS["中文"]["dashboard_title"]


def test_translation_lookup_falls_back_when_selected_language_lacks_key(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {"language": "中文"})
    english_value = dashboard.TRANSLATIONS["English"]["dashboard_caption"]
    monkeypatch.delitem(dashboard.TRANSLATIONS["中文"], "dashboard_caption")

    assert dashboard.t("dashboard_caption") == english_value


def test_translation_lookup_returns_key_when_all_languages_lack_it(monkeypatch):
    monkeypatch.setattr(dashboard.st, "session_state", {})

    assert dashboard.t("translation_key_absent_everywhere") == "translation_key_absent_everywhere"


def test_translation_language_key_preserves_supported_canonical_names():
    assert dashboard._translation_language_key("English") == "English"
    assert dashboard._translation_language_key("中文") == "中文"
    assert dashboard._translation_language_key("Español") == "Español"


def test_static_translation_overrides_are_reexported_and_merged_by_identity():
    from translations.macro import MACRO_TRANSLATION_OVERRIDES
    from translations.news_ui import NEWS_UI_TRANSLATION_OVERRIDES

    assert dashboard.MACRO_TRANSLATION_OVERRIDES is MACRO_TRANSLATION_OVERRIDES
    assert dashboard.NEWS_UI_TRANSLATION_OVERRIDES is NEWS_UI_TRANSLATION_OVERRIDES
    for language in SUPPORTED_LANGUAGES:
        for key, value in NEWS_UI_TRANSLATION_OVERRIDES[language].items():
            assert dashboard.TRANSLATIONS[language][key] == value
        for key, value in MACRO_TRANSLATION_OVERRIDES[language].items():
            assert dashboard.TRANSLATIONS[language][key] == value


def test_multi_agent_translation_keys_and_dashboard_reexport_are_stable():
    from translations.multi_agent import MULTI_AGENT_TEXTS, multi_agent_language

    assert dashboard.MULTI_AGENT_TEXTS is MULTI_AGENT_TEXTS
    english_keys = set(MULTI_AGENT_TEXTS["English"])
    assert set(MULTI_AGENT_TEXTS) == {"English", "中文", "Español"}
    assert set(MULTI_AGENT_TEXTS["中文"]) == english_keys
    assert set(MULTI_AGENT_TEXTS["Español"]) == english_keys
    assert dashboard.multi_agent_text("caption", language="English") == MULTI_AGENT_TEXTS["English"]["caption"]
    assert dashboard.multi_agent_text("caption", language="中文") == MULTI_AGENT_TEXTS["中文"]["caption"]
    assert dashboard.multi_agent_text("caption", language="Español") == MULTI_AGENT_TEXTS["Español"]["caption"]
    assert dashboard._multi_agent_language is multi_agent_language


def test_multi_agent_language_aliases_and_fallback_are_unchanged():
    assert dashboard._multi_agent_language("zh") == "中文"
    assert dashboard._multi_agent_language("Chinese") == "中文"
    assert dashboard._multi_agent_language("es") == "Español"
    assert dashboard._multi_agent_language("Spanish") == "Español"
    assert dashboard._multi_agent_language("Español") == "Español"
    assert dashboard._multi_agent_language("unsupported") == "English"
    assert dashboard._multi_agent_language(None) == "English"


def test_news_static_resources_are_reexported_without_behavior_changes():
    from translations import news

    resource_names = (
        "NEWS_SUMMARY_LABELS",
        "NEWS_TRANSLATION_LABELS",
        "NEWS_TRANSLATION_UI",
        "NEWS_DETAILED_SUMMARY_LABELS",
        "NEWS_DETAILED_SUMMARY_UI",
        "NEWS_DETAILED_SUMMARY_UNAVAILABLE",
        "NEWS_SCORE_LABELS",
        "NEWS_SUMMARY_LANGUAGE_NAMES",
        "NEWS_SUMMARY_LANGUAGE_ALIASES",
        "NEWS_SUMMARY_FIELD_LABELS",
        "NEWS_SUMMARY_UI",
        "NEWS_DRIVER_KEYWORDS",
        "POSITIVE_NEWS_KEYWORDS",
        "NEGATIVE_NEWS_KEYWORDS",
        "MARKET_NEWS_KEYWORDS",
    )
    for name in resource_names:
        assert getattr(dashboard, name) is getattr(news, name)

    assert set(news.NEWS_SUMMARY_LABELS) == {"English", "中文", "Español"}
    assert set(news.NEWS_SUMMARY_FIELD_LABELS["English"]) == set(news.NEWS_SUMMARY_FIELD_LABELS["中文"])
    assert set(news.NEWS_SUMMARY_FIELD_LABELS["English"]) == set(news.NEWS_SUMMARY_FIELD_LABELS["Español"])
    assert dashboard._news_summary_language("zh") == "中文"
    assert dashboard._news_summary_language("Spanish") == "Español"
    assert dashboard._news_summary_language("unsupported") == "English"


def test_news_versions_and_driver_keywords_are_unchanged():
    from translations import news

    assert news.AI_SUMMARY_VERSION == "v3"
    assert news.AI_TRANSLATION_VERSION == "v1"
    assert news.AI_SENTIMENT_VERSION == "v1"
    assert news.AI_DETAILED_SUMMARY_VERSION == "v2"
    assert dict(news.NEWS_DRIVER_KEYWORDS)["earnings"] == (
        "earnings",
        "revenue",
        "profit",
        "eps",
        "guidance",
        "margin",
    )
    assert news.POSITIVE_NEWS_KEYWORDS == (
        "beat", "raise", "growth", "demand", "upgrade", "strong", "record",
        "expansion", "partnership",
    )
    assert news.NEGATIVE_NEWS_KEYWORDS == (
        "miss", "cut", "downgrade", "weak", "lawsuit", "decline", "guidance cut",
        "export restriction", "inventory", "margin pressure",
    )
    assert news.MARKET_NEWS_KEYWORDS == (
        "semiconductor", "ai", "memory", "dram", "nand", "data center", "nvidia", "micron",
    )
