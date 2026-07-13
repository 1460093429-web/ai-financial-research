import builtins
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from services.news_daily_brief import (
    build_daily_brief_prompt,
    daily_brief_fingerprint,
    deduplicate_daily_brief_news,
    filter_technology_semiconductor_news,
    generate_daily_brief,
    normalize_daily_brief_candidates,
    rank_daily_brief_news,
    select_daily_brief_news,
    validate_daily_brief_text,
)
from services.news_schema import attach_normalized_news_item


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def legacy_item(title, *, source="FMP", url=None, ticker="NVDA", date="2026-07-13T01:00:00Z", text=None):
    return {
        "title": title,
        "text": text or f"{title} discusses semiconductor demand and data center capex.",
        "url": url,
        "source": source,
        "publisher": f"{source} Publisher",
        "ticker": ticker,
        "related_tickers": ticker,
        "published_date": date,
    }


@pytest.mark.parametrize("source", ["Yahoo/yfinance", "TrendForce", "FMP"])
def test_legacy_provider_items_normalize_to_candidates(source):
    candidate = normalize_daily_brief_candidates([legacy_item("AI chip demand", source=source)])[0]

    assert candidate["title"] == "AI chip demand"
    assert candidate["source"] == source
    assert candidate["published_at"] == "2026-07-13T01:00:00Z"
    assert candidate["related_tickers"] == ["NVDA"]


def test_unified_envelope_view_is_read_without_mutating_input():
    envelope = attach_normalized_news_item(
        legacy_item("HBM capacity", source="Yahoo/yfinance"), provider="yahoo"
    )
    envelope["_normalized"]["summary"] = "Normalized HBM summary"
    before = deepcopy(envelope)

    candidate = normalize_daily_brief_candidates([envelope])[0]

    assert candidate["summary"] == "Normalized HBM summary"
    assert envelope == before


def test_technology_filter_keeps_relevant_and_removes_unrelated_news():
    items = [
        legacy_item("GPU and advanced packaging expansion"),
        legacy_item("Local sports result", text="A team won a routine match.", ticker="SPORT"),
    ]

    assert [item["title"] for item in filter_technology_semiconductor_news(items)] == [
        "GPU and advanced packaging expansion"
    ]


def test_deduplication_uses_url_then_title_fallback_in_input_order():
    items = [
        legacy_item("First chip story", url="https://example.com/same"),
        legacy_item("Second chip story", url="https://example.com/same"),
        legacy_item("Repeated HBM Update", url=None),
        legacy_item("Repeated HBM update!", url=None),
    ]

    assert [item["title"] for item in deduplicate_daily_brief_news(items)] == [
        "First chip story", "Repeated HBM Update"
    ]


def test_ranking_is_predictable_and_invalid_time_does_not_crash():
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    items = [
        legacy_item("Old semiconductor note", date="invalid"),
        legacy_item("Fresh GPU order demand and capex", date="2026-07-13T11:00:00Z"),
    ]

    ranked = rank_daily_brief_news(items, now=now)

    assert [item["title"] for item in ranked] == [
        "Fresh GPU order demand and capex", "Old semiconductor note"
    ]


def test_selection_is_bounded_and_keeps_source_diversity():
    items = [
        legacy_item("GPU order one", source="FMP", url="https://a/1"),
        legacy_item("GPU order two", source="FMP", url="https://a/2"),
        legacy_item("HBM capacity", source="TrendForce", url="https://b/1", ticker="MU"),
        legacy_item("Cloud AI capex", source="Yahoo/yfinance", url="https://c/1"),
    ]

    selected = select_daily_brief_news(items, max_items=3, now="2026-07-13T12:00:00Z")

    assert len(selected) == 3
    assert {item["source"] for item in selected} == {"FMP", "TrendForce", "Yahoo/yfinance"}


def test_fallback_item_is_identified_in_candidate():
    item = legacy_item("AI chip fallback", source="yfinance fallback")

    candidate = normalize_daily_brief_candidates([item])[0]

    assert candidate["is_fallback"] is True
    assert candidate["fallback_from"] == "fmp"


def test_prompt_requires_one_combined_summary_and_language_limits():
    prompt = build_daily_brief_prompt([legacy_item("AI chip demand")], language="中文")

    assert "exactly one combined" in prompt
    assert "Do not create market, provider, company, or ticker sections" in prompt
    assert "180–260" in prompt
    assert "最多约 320" in prompt
    assert "buy, or sell advice" in prompt


def test_prompt_only_contains_required_candidate_fields():
    item = {**legacy_item("AI chip demand"), "raw_html": "<html>not allowed</html>"}

    prompt = build_daily_brief_prompt([item], language="English")

    assert "raw_html" not in prompt
    assert "not allowed" not in prompt


def test_validation_handles_empty_text_and_rejects_ticker_sections():
    assert validate_daily_brief_text(None) == ""
    assert validate_daily_brief_text("  ") == ""
    with pytest.raises(ValueError, match="combined industry summary"):
        validate_daily_brief_text("NVDA: separate summary")


def test_chinese_validation_caps_excessive_output():
    result = validate_daily_brief_text("科" * 400, language="zh")

    assert len(result) <= 321
    assert result.endswith("。")


def test_empty_and_missing_key_results_do_not_call_openai():
    forbidden = lambda: pytest.fail("OpenAI must not run")

    assert generate_daily_brief([], client_factory=forbidden)["status"] == "empty"
    result = generate_daily_brief([legacy_item("AI chip demand")], client_factory=None)
    assert result["status"] == "missing_key"


class FakeCompletions:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def fake_client(completions):
    return type("Client", (), {
        "chat": type("Chat", (), {"completions": completions})()
    })()


def test_generation_returns_structured_result_with_one_openai_call():
    completions = FakeCompletions("AI chip demand and memory capacity remain the main drivers, while export controls are the principal risk.")
    items = [legacy_item("GPU demand", source="Yahoo/yfinance")]

    result = generate_daily_brief(
        items,
        language="English",
        client_factory=lambda: fake_client(completions),
        now="2026-07-13T12:00:00Z",
    )

    assert result["status"] == "ok"
    assert result["articles_used"] == 1
    assert result["sources_used"] == ["Yahoo/yfinance"]
    assert result["generated_at"] == "2026-07-13T12:00:00+00:00"
    assert len(completions.calls) == 1
    assert completions.calls[0]["model"] == "gpt-4o-mini"


def test_missing_key_and_openai_errors_are_safe_and_do_not_leak_secret():
    item = legacy_item("AI chip demand")
    missing = generate_daily_brief(
        [item], client_factory=lambda: (_ for _ in ()).throw(ValueError("secret-key-value"))
    )
    completions = FakeCompletions(error=RuntimeError("secret-key-value"))
    failed = generate_daily_brief([item], client_factory=lambda: fake_client(completions))

    assert missing["status"] == "missing_key"
    assert missing["error"] is None
    assert failed["status"] == "error"
    assert "secret-key-value" not in failed["error"]
    assert failed["candidate_titles"] == ["AI chip demand"]


def test_fingerprint_is_stable_and_changes_with_material_news_content():
    item = legacy_item("AI chip demand")

    assert daily_brief_fingerprint([item]) == daily_brief_fingerprint([deepcopy(item)])
    changed = {**item, "text": "Changed semiconductor demand summary"}
    assert daily_brief_fingerprint([item]) != daily_brief_fingerprint([changed])
