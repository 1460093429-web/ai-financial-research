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


def test_dashboard_translation_key_sets_are_identical_for_all_supported_languages():
    assert set(dashboard.TRANSLATIONS) == {"English", "中文", "Español"}

    english_keys = set(dashboard.TRANSLATIONS["English"])
    assert CORE_UI_KEYS <= english_keys
    assert set(dashboard.TRANSLATIONS["中文"]) == english_keys
    assert set(dashboard.TRANSLATIONS["Español"]) == english_keys


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


def test_translation_language_key_preserves_supported_canonical_names():
    assert dashboard._translation_language_key("English") == "English"
    assert dashboard._translation_language_key("中文") == "中文"
    assert dashboard._translation_language_key("Español") == "Español"
