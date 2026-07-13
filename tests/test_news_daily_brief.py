import builtins
from copy import deepcopy
import json

import pytest

from services.news_daily_brief import (
    build_daily_brief_citations,
    build_daily_brief_prompt,
    daily_brief_fingerprint,
    deduplicate_daily_brief_news,
    filter_technology_semiconductor_news,
    generate_daily_brief,
    group_daily_brief_events,
    normalize_daily_brief_candidates,
    rank_daily_brief_news,
    sanitize_news_url,
    select_daily_brief_news,
    validate_daily_brief_response,
    validate_importance_reason,
)
from services.news_schema import attach_normalized_news_item


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import openai
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def legacy_item(
    title,
    *,
    text,
    source="FMP",
    url=None,
    ticker=None,
    related_tickers=None,
    date="2026-07-13T01:00:00Z",
):
    return {
        "title": title,
        "text": text,
        "url": url,
        "source": source,
        "publisher": f"{source} Publisher",
        "ticker": ticker,
        "related_tickers": related_tickers if related_tickers is not None else ticker,
        "published_date": date,
    }


def distinct_events(count=10):
    definitions = [
        ("TSMC foundry earnings guidance", "TSMC revenue and advanced foundry demand guidance rose.", "TSM"),
        ("Nvidia launches new GPU", "Nvidia launched a GPU for artificial intelligence data centers.", "NVDA"),
        ("Micron expands HBM supply", "Micron HBM supply and capacity expansion responds to demand.", "MU"),
        ("SanDisk sees NAND pricing shift", "SanDisk NAND pricing reflects tighter memory supply.", "SNDK"),
        ("Microsoft raises AI data center capex", "Microsoft increased AI data center capital expenditure.", "MSFT"),
        ("Meta expands AI accelerator investment", "Meta expanded ASIC accelerator investment and capacity.", "META"),
        ("ASML reports lithography orders", "ASML lithography equipment orders changed its guidance.", "ASML"),
        ("Applied Materials deposition demand", "Applied Materials sees semiconductor deposition equipment demand.", "AMAT"),
        ("AMD signs ASIC partnership", "AMD announced an ASIC partnership and product launch.", "AMD"),
        ("Intel expands foundry capacity", "Intel expanded foundry wafer capacity for new orders.", "INTC"),
        ("Broadcom AI chip revenue", "Broadcom AI chip revenue guidance reflects accelerator demand.", "AVGO"),
        ("Amazon increases cloud AI investment", "Amazon AWS increased cloud AI capex investment.", "AMZN"),
    ]
    sources = ["FMP", "Yahoo/yfinance", "TrendForce"]
    return [
        legacy_item(
            title,
            text=text,
            source=sources[index % len(sources)],
            url=f"https://example.com/event-{index}",
            ticker=ticker,
            date=f"2026-07-13T{index:02d}:00:00Z",
        )
        for index, (title, text, ticker) in enumerate(definitions[:count])
    ]


def structured_response(candidates, count):
    items = []
    for index, candidate in enumerate(candidates[:count]):
        ticker = (candidate.get("related_tickers") or [None])[0]
        items.append({
            "title": f"Event highlight {index + 1}: {candidate['title']}",
            "summary": (
                f"{candidate['summary']} This distinct event affects its specific technology value chain; "
                f"the main open question is whether the reported change can be executed as described."
            ),
            "importance_reason": (
                "This event matters because it can change technology demand, supply-chain capacity, "
                "and capital spending decisions."
            ),
            "kind": "company" if ticker else "event",
            "primary_ticker": ticker,
            "related_tickers": [ticker] if ticker else [],
            "source_article_indices": [index],
            "risk": "Execution remains the main risk.",
        })
    return json.dumps({"items": items})


@pytest.mark.parametrize("source", ["Yahoo/yfinance", "TrendForce", "FMP"])
def test_legacy_provider_items_normalize_with_verified_tickers(source):
    item = legacy_item(
        "Nvidia GPU demand",
        text="Nvidia data center GPU and semiconductor demand increased.",
        source=source,
        ticker="NVDA",
    )

    candidate = normalize_daily_brief_candidates([item])[0]

    assert candidate["source"] == source
    assert candidate["ticker"] == "NVDA"
    assert candidate["related_tickers"] == ["NVDA"]


def test_envelope_is_supported_without_mutating_input():
    raw = distinct_events(1)[0]
    envelope = attach_normalized_news_item(raw, provider="fmp")
    before = deepcopy(envelope)

    candidate = normalize_daily_brief_candidates([envelope])[0]

    assert candidate["title"] == raw["title"]
    assert envelope == before


def test_embedded_string_related_tickers_are_not_split_into_characters():
    raw = distinct_events(1)[0]
    envelope = attach_normalized_news_item(raw, provider="fmp")
    envelope["_normalized"]["related_tickers"] = "TSM, NVDA"
    envelope["_normalized"]["summary"] += " Nvidia demand supports TSMC."

    candidate = normalize_daily_brief_candidates([envelope])[0]

    assert candidate["related_tickers"] == ["TSM", "NVDA"]


def test_ticker_without_text_evidence_is_removed():
    item = legacy_item(
        "SpaceX launch schedule",
        text="SpaceX discussed a rocket launch schedule.",
        ticker="NVDA",
    )

    candidate = normalize_daily_brief_candidates([item])[0]

    assert candidate["ticker"] is None
    assert candidate["related_tickers"] == []


def test_technology_filter_removes_unrelated_spacex_prediction_and_sports():
    items = [
        distinct_events(1)[0],
        legacy_item(
            "Prediction: SpaceX Shares Can Reach $220 by End of 2026",
            text="A speculative share price prediction about SpaceX.",
            ticker="NVDA",
        ),
        legacy_item("Local sports result", text="A team won a match.", ticker="NVDA"),
    ]

    filtered = filter_technology_semiconductor_news(items)

    assert [item["title"] for item in filtered] == ["TSMC foundry earnings guidance"]


def test_speculative_space_news_with_injected_chip_ticker_is_filtered():
    item = legacy_item(
        "Goldman Sachs' Insane SpaceX AI Forecast Has One Clear Winner: Nvidia",
        text="A speculative SpaceX AI forecast names Nvidia as a possible stock winner.",
        source="Yahoo/yfinance",
        ticker="NVDA",
    )

    assert filter_technology_semiconductor_news([item]) == []


def test_stock_to_buy_comparison_without_factual_event_is_filtered():
    item = legacy_item(
        "Best AI Stock to Buy: Micron Stock vs. AMD Stock",
        text="A comparison calls Micron and AMD attractive AI semiconductor stocks.",
        source="Yahoo/yfinance",
        ticker="MU",
        related_tickers=["MU", "AMD"],
    )

    assert filter_technology_semiconductor_news([item]) == []


def test_url_and_title_fallback_deduplication_preserve_first_item():
    first = distinct_events(1)[0]
    duplicate_url = {**first, "title": "Different TSMC foundry title"}
    title_one = legacy_item("Repeated HBM supply", text="Micron HBM supply demand.", ticker="MU")
    title_two = {**title_one, "title": "Repeated HBM supply!"}

    result = deduplicate_daily_brief_news([first, duplicate_url, title_one, title_two])

    assert [item["title"] for item in result] == [first["title"], title_one["title"]]


def test_same_event_reporting_is_grouped_but_distinct_events_remain_separate():
    duplicate_report = legacy_item(
        "TSMC AI demand lifts foundry revenue",
        text="TSMC earnings and revenue guidance cite advanced foundry demand.",
        source="Yahoo/yfinance",
        url="https://example.com/tsmc-confirmation",
        ticker="TSM",
    )
    items = [distinct_events(2)[0], duplicate_report, distinct_events(2)[1]]

    groups = group_daily_brief_events(items, now="2026-07-13T12:00:00Z")

    assert len(groups) == 2
    assert sorted(group["article_count"] for group in groups) == [1, 2]
    merged = next(group for group in groups if group["article_count"] == 2)
    assert set(merged["sources"]) == {"FMP", "Yahoo/yfinance"}


def test_article_ranking_prioritizes_factual_events_over_price_predictions():
    factual = distinct_events(1)[0]
    prediction = legacy_item(
        "Prediction: Nvidia stock price could reach a new target",
        text="Nvidia semiconductor stock price prediction mentions AI chip demand.",
        ticker="NVDA",
    )

    ranked = rank_daily_brief_news([prediction, factual], now="2026-07-13T12:00:00Z")

    assert ranked[0]["title"] == factual["title"]


def test_invalid_date_does_not_break_ranking_or_grouping():
    items = distinct_events(3)
    items[0]["published_date"] = "not-a-date"

    ranked = rank_daily_brief_news(items, now="2026-07-13T12:00:00Z")
    groups = group_daily_brief_events(items, now="2026-07-13T12:00:00Z")

    assert len(ranked) == 3
    assert len(groups) == 3


def test_article_selection_limit_and_source_diversity_are_deterministic():
    selected = select_daily_brief_news(distinct_events(12), max_items=6, now="2026-07-13T12:00:00Z")

    assert len(selected) == 6
    assert len({item["source"] for item in selected[:3]}) == 3
    assert len(select_daily_brief_news(distinct_events(12), max_items=99)) <= 40


def test_event_candidate_limit_is_at_most_eighteen():
    many = distinct_events(12) + [
        legacy_item(
            f"Unique semiconductor equipment order {index}",
            text=f"Unique supplier {index} reported lithography equipment orders and capacity.",
            url=f"https://example.com/extra-{index}",
        )
        for index in range(12)
    ]

    assert len(group_daily_brief_events(many, max_events=18)) <= 18


def test_prompt_requests_multiple_dynamic_json_items_and_language_limits():
    prompt = build_daily_brief_prompt(distinct_events(10), language="中文")

    assert '"items"' in prompt
    assert "8–10 items" in prompt
    assert "160–240" in prompt
    assert "最多约 280" in prompt
    assert '"importance_reason"' in prompt
    assert "40–100" in prompt
    assert "1–4 supplied article indices" in prompt
    assert "Do not organize" in prompt
    assert "fixed Market, AI, Memory, NVDA, MU, AMD" in prompt
    assert "buy, or sell advice" in prompt


def test_prompt_excludes_full_html_and_truncates_article_summary():
    item = {**distinct_events(1)[0], "text": "Nvidia GPU demand " + "x" * 1000, "raw_html": "<html>secret</html>"}

    prompt = build_daily_brief_prompt([item], language="English")

    assert "raw_html" not in prompt
    assert "<html>secret</html>" not in prompt
    assert "x" * 701 not in prompt


def test_citations_rebuild_actual_candidate_fields_in_requested_index_order():
    candidates = distinct_events(3)
    candidates[0]["publisher"] = "Primary Publisher"
    candidates[0]["published_date"] = "2026-07-13T09:30:00Z"
    candidates[1]["source"] = "yfinance fallback"
    candidates[1]["publisher"] = "Fallback Publisher"
    candidates[1]["published_date"] = "2026-07-13T10:00:00Z"
    candidates[2]["url"] = None
    before = deepcopy(candidates)

    citations = build_daily_brief_citations(
        {"source_article_indices": [1, 0, 2]},
        candidates,
    )

    assert [citation["title"] for citation in citations] == [
        candidates[1]["title"], candidates[0]["title"], candidates[2]["title"],
    ]
    assert citations[0] == {
        "title": candidates[1]["title"],
        "url": candidates[1]["url"],
        "source": "yfinance fallback",
        "publisher": "Fallback Publisher",
        "published_at": "2026-07-13T10:00:00Z",
        "ticker": "NVDA",
        "related_tickers": ["NVDA"],
        "is_fallback": True,
    }
    assert citations[1]["publisher"] == "Primary Publisher"
    assert citations[1]["published_at"] == "2026-07-13T09:30:00Z"
    assert citations[2]["url"] is None
    assert candidates == before


def test_citations_filter_mixed_indices_duplicate_urls_and_enforce_maximum_four():
    candidates = distinct_events(6)
    candidates[1]["url"] = candidates[0]["url"]

    citations = build_daily_brief_citations(
        {"source_article_indices": [0, 0, 999, "1", True, 1, 2, 3, 4, 5]},
        candidates,
        max_citations=99,
    )

    assert len(citations) == 4
    assert [citation["title"] for citation in citations] == [
        candidates[0]["title"],
        candidates[2]["title"],
        candidates[3]["title"],
        candidates[4]["title"],
    ]
    assert len({citation["url"] for citation in citations if citation["url"]}) == 4


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/news?id=1", "https://example.com/news?id=1"),
        (" http://example.com/story ", "http://example.com/story"),
        ("HTTPS://example.com/story", "HTTPS://example.com/story"),
        (None, None),
        ("", None),
        ("//example.com/story", None),
        ("javascript:alert(1)", None),
        ("data:text/html,unsafe", None),
        ("file:///tmp/news", None),
        ("https:///missing-host", None),
        ("http://[::1", None),
        ("https://example.com/line\nbreak", None),
    ],
)
def test_sanitize_news_url_only_keeps_safe_http_and_https(url, expected):
    assert sanitize_news_url(url) == expected


def test_valid_json_rebuilds_citations_sources_and_count_and_ignores_model_forgery():
    candidates = select_daily_brief_news(distinct_events(3), now="2026-07-13T12:00:00Z")
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0]["sources"] = ["invented"]
    payload["items"][0]["article_count"] = 99
    payload["items"][0]["citations"] = [{
        "title": "Invented article",
        "url": "https://attacker.invalid/fake",
        "source": "invented",
    }]
    before_candidates = deepcopy(candidates)
    before_payload = deepcopy(payload)

    result = validate_daily_brief_response(json.dumps(payload), candidates, language="English")

    assert len(result) == 3
    assert result[0]["sources"] == [candidates[0]["source"]]
    assert result[0]["article_count"] == 1
    assert result[0]["source_article_indices"] == [0]
    assert result[0]["citations"] == [{
        "title": candidates[0]["title"],
        "url": candidates[0]["url"],
        "source": candidates[0]["source"],
        "publisher": candidates[0]["publisher"],
        "published_at": candidates[0]["published_at"],
        "ticker": candidates[0]["ticker"],
        "related_tickers": candidates[0]["related_tickers"],
        "is_fallback": False,
    }]
    assert result[0]["importance_reason"] == payload["items"][0]["importance_reason"]
    assert result[0]["kind"] in ("event", "company")
    assert candidates == before_candidates
    assert payload == before_payload


def test_importance_reason_is_optional_cleaned_and_filters_investment_advice():
    reason = "  This event may affect semiconductor supply, margins, and capital spending.  "

    assert validate_importance_reason(reason, language="English") == reason.strip()
    assert validate_importance_reason(None) is None
    assert validate_importance_reason(123) is None
    assert validate_importance_reason("  ") is None
    assert validate_importance_reason("该事件很重要，建议买入相关股票。") is None
    assert validate_importance_reason("This supports a price target and position size.", language="English") is None


def test_validator_allows_missing_importance_reason_without_fabricating_fallback():
    candidates = select_daily_brief_news(distinct_events(3))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0].pop("importance_reason")

    result = validate_daily_brief_response(json.dumps(payload), candidates, language="English")

    assert result[0]["importance_reason"] is None


@pytest.mark.parametrize("text", ["not json", "[]", '{"items": "wrong"}'])
def test_malformed_json_contract_is_rejected(text):
    with pytest.raises(ValueError):
        validate_daily_brief_response(text, select_daily_brief_news(distinct_events(3)))


def test_duplicate_response_items_are_rejected():
    candidates = select_daily_brief_news(distinct_events(3))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][1]["title"] = payload["items"][0]["title"]

    with pytest.raises(ValueError, match="duplicate"):
        validate_daily_brief_response(json.dumps(payload), candidates)


def test_near_duplicate_chinese_summaries_are_rejected():
    candidates = select_daily_brief_news(distinct_events(3))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0]["summary"] = "台积电先进制程需求持续增长，云厂商资本开支推动产能扩张，主要风险是订单兑现速度。"
    payload["items"][1]["summary"] = "台积电先进制程需求持续增长，云厂商资本开支推动产能扩张，主要风险是订单兑现节奏。"

    with pytest.raises(ValueError, match="duplicate"):
        validate_daily_brief_response(json.dumps(payload, ensure_ascii=False), candidates)


def test_more_than_ten_items_are_truncated():
    candidates = select_daily_brief_news(distinct_events(12))

    result = validate_daily_brief_response(structured_response(candidates, 12), candidates, language="English")

    assert len(result) == 10


def test_unsupported_ticker_is_rejected():
    candidates = select_daily_brief_news(distinct_events(3))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0]["primary_ticker"] = "FAKE"
    payload["items"][0]["related_tickers"] = ["FAKE"]
    with pytest.raises(ValueError, match="ticker absent"):
        validate_daily_brief_response(json.dumps(payload), candidates)


def test_validator_filters_invalid_duplicate_and_non_integer_article_indices():
    candidates = select_daily_brief_news(distinct_events(3))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0]["source_article_indices"] = [0, 999, "1", True, 0]

    result = validate_daily_brief_response(json.dumps(payload), candidates)

    assert result[0]["source_article_indices"] == [0]
    assert result[0]["article_count"] == 1
    assert [citation["title"] for citation in result[0]["citations"]] == [candidates[0]["title"]]


def test_validator_filters_in_range_indices_that_were_not_submitted_to_openai():
    candidates = select_daily_brief_news(distinct_events(4))
    payload = json.loads(structured_response(candidates, 3))
    payload["items"][0]["source_article_indices"] = [3, 0]

    result = validate_daily_brief_response(
        json.dumps(payload),
        candidates,
        allowed_indices={0, 1, 2},
    )

    assert result[0]["source_article_indices"] == [0]
    assert [citation["title"] for citation in result[0]["citations"]] == [candidates[0]["title"]]
    assert candidates[3]["title"] not in {
        citation["title"]
        for item in result
        for citation in item["citations"]
    }


def test_validator_drops_items_without_any_valid_source_index():
    candidates = select_daily_brief_news(distinct_events(4))
    payload = json.loads(structured_response(candidates, 4))
    payload["items"][0]["source_article_indices"] = [999, "0", True]

    result = validate_daily_brief_response(json.dumps(payload), candidates)

    assert len(result) == 3
    assert all(item["source_article_indices"] for item in result)
    assert candidates[0]["title"] not in {citation["title"] for item in result for citation in item["citations"]}


def test_fewer_than_three_events_and_empty_input_do_not_call_openai():
    forbidden = lambda: pytest.fail("OpenAI must not run")

    assert generate_daily_brief([], client_factory=forbidden)["status"] == "empty"
    assert generate_daily_brief(distinct_events(2), client_factory=forbidden)["status"] == "empty"


def test_missing_key_with_enough_events_does_not_call_openai():
    result = generate_daily_brief(distinct_events(3), client_factory=None)

    assert result["status"] == "missing_key"
    assert result["items"] == []


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


def test_generation_returns_eight_distinct_items_with_one_openai_call():
    raw = distinct_events(10)
    candidates = select_daily_brief_news(raw, now="2026-07-13T12:00:00Z")
    completions = FakeCompletions(structured_response(candidates, 8))

    result = generate_daily_brief(
        raw,
        language="English",
        client_factory=lambda: fake_client(completions),
        now="2026-07-13T12:00:00Z",
    )

    assert result["status"] == "ok"
    assert len(result["items"]) == 8
    assert len({item["title"] for item in result["items"]}) == 8
    assert all(item["summary"] and item["kind"] and isinstance(item["related_tickers"], list) for item in result["items"])
    assert all(item["importance_reason"] and item["citations"] for item in result["items"])
    assert all(item["article_count"] == len(item["citations"]) for item in result["items"])
    assert len(completions.calls) == 1
    assert completions.calls[0]["model"] == "gpt-4o-mini"


def test_generation_allows_five_high_quality_events_without_padding():
    raw = distinct_events(5)
    candidates = select_daily_brief_news(raw, now="2026-07-13T12:00:00Z")
    completions = FakeCompletions(structured_response(candidates, 5))

    result = generate_daily_brief(
        raw,
        client_factory=lambda: fake_client(completions),
        now="2026-07-13T12:00:00Z",
    )

    assert result["status"] == "ok"
    assert len(result["items"]) == 5


def test_openai_and_json_errors_are_safe_and_do_not_leak_secrets():
    raw = distinct_events(3)
    failed_client = FakeCompletions(error=RuntimeError("secret-key-value"))
    malformed = FakeCompletions("not json")

    request_error = generate_daily_brief(raw, client_factory=lambda: fake_client(failed_client))
    json_error = generate_daily_brief(raw, client_factory=lambda: fake_client(malformed))

    assert request_error["status"] == json_error["status"] == "error"
    assert "secret-key-value" not in request_error["error"]
    assert 3 <= len(request_error["candidate_titles"]) <= 5


def test_fingerprint_is_stable_and_changes_with_material_content():
    items = distinct_events(3)

    assert daily_brief_fingerprint(items) == daily_brief_fingerprint(deepcopy(items))
    changed = deepcopy(items)
    changed[0]["text"] += " Material change."
    assert daily_brief_fingerprint(items) != daily_brief_fingerprint(changed)
