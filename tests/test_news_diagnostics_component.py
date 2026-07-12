import builtins
from copy import deepcopy

import pytest

from components import news_diagnostics
from components.news_diagnostics import (
    build_news_schema_diagnostics_rows,
    render_news_schema_diagnostics,
)
from services.news_schema import attach_normalized_news_item


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import requests
    import yfinance
    import openai

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


@pytest.mark.parametrize(
    ("legacy", "expected_provider", "expected_fallback", "expected_related"),
    [
        (
            {
                "title": "Yahoo", "text": "Yahoo text", "source": "Yahoo/yfinance",
                "publisher": "Yahoo Publisher", "ticker": "NVDA", "related_tickers": "NVDA, MU",
                "published_date": "2026-07-13T01:00:00Z",
            },
            "yahoo",
            False,
            "NVDA, MU",
        ),
        (
            {
                "title": "TrendForce", "summary": "Trend summary", "source": "TrendForce",
                "site": "TrendForce", "publisher": "TrendForce集邦咨询", "ticker": "MU",
                "related_tickers": "MU", "publishedDate": "2026-07-13",
            },
            "trendforce",
            False,
            "MU",
        ),
        (
            {"title": "FMP", "text": "FMP text", "source": "FMP", "ticker": "NVDA"},
            "fmp",
            False,
            "NVDA",
        ),
        (
            {"title": "Fallback", "text": "Fallback text", "source": "yfinance fallback", "ticker": "MU"},
            "yahoo",
            True,
            "MU",
        ),
    ],
)
def test_diagnostics_rows_support_current_provider_envelopes(
    legacy, expected_provider, expected_fallback, expected_related
):
    envelope = attach_normalized_news_item(legacy)

    row = build_news_schema_diagnostics_rows([envelope])[0]

    assert row["Title"] == legacy["title"]
    assert row["Schema Status"] == "available"
    assert row["Legacy Source"] == legacy["source"]
    assert row["Normalized Provider"] == expected_provider
    assert row["Normalized Source"] == legacy["source"]
    assert row["Is Fallback"] is expected_fallback
    assert row["Related Tickers"] == expected_related
    assert row["Summary Matches"] is True
    assert row["Related Tickers Match"] is True


def test_diagnostics_does_not_mutate_envelope_or_nested_schema():
    envelope = attach_normalized_news_item({
        "title": "Yahoo", "text": "text", "source": "Yahoo/yfinance", "ticker": "NVDA"
    })
    before = deepcopy(envelope)

    build_news_schema_diagnostics_rows([envelope])

    assert envelope == before


def test_missing_normalized_schema_is_safe_and_explicit():
    row = build_news_schema_diagnostics_rows([{
        "title": "Legacy only", "text": "legacy", "source": "FMP", "ticker": "NVDA"
    }])[0]

    assert row["Schema Status"] == "missing"
    assert row["Normalized Provider"] == "missing"
    assert row["Normalized Source"] == "missing"
    assert row["Published At"] == "missing"
    assert row["Is Fallback"] == "missing"
    assert row["Summary Matches"] is False
    assert row["Publication Matches"] is False
    assert row["Related Tickers Match"] is False


def test_partial_normalized_schema_is_safe_and_reports_differences():
    envelope = {
        "title": "Partial",
        "summary": "legacy summary",
        "published_date": "2026-07-13",
        "related_tickers": "NVDA, MU",
        "_normalized": {
            "provider": "yahoo",
            "summary": "different summary",
            "published_at": "2026-07-12",
            "related_tickers": ["NVDA"],
        },
    }

    row = build_news_schema_diagnostics_rows([envelope])[0]

    assert row["Schema Status"] == "available"
    assert row["Normalized Source"] is None
    assert row["Summary Matches"] is False
    assert row["Publication Matches"] is False
    assert row["Related Tickers"] == "NVDA"
    assert row["Related Tickers Match"] is False


@pytest.mark.parametrize(
    ("legacy_field", "legacy_value", "normalized_value", "expected"),
    [
        ("published_date", "2026-07-13", "2026-07-13", True),
        ("publishedDate", "2026-07-13", "2026-07-12", False),
        ("date", "2026-07-13", "2026-07-13", True),
        ("timestamp", 1_700_000_000, "1700000000", True),
    ],
)
def test_publication_difference_detection(legacy_field, legacy_value, normalized_value, expected):
    row = build_news_schema_diagnostics_rows([{
        legacy_field: legacy_value,
        "_normalized": {"published_at": normalized_value},
    }])[0]

    assert row["Legacy Published"] == str(legacy_value)
    assert row["Published At"] == normalized_value
    assert row["Publication Matches"] is expected


def test_summary_text_difference_detection_uses_legacy_priority():
    rows = build_news_schema_diagnostics_rows([
        {"summary": "summary", "text": "text", "_normalized": {"summary": "summary"}},
        {"text": "text", "_normalized": {"summary": "different"}},
        {"description": "description", "_normalized": {"summary": "description"}},
    ])

    assert [row["Legacy Summary"] for row in rows] == ["summary", "text", "description"]
    assert [row["Summary Matches"] for row in rows] == [True, False, True]


def test_input_order_and_non_dict_positions_are_preserved_safely():
    rows = build_news_schema_diagnostics_rows([
        {"title": "first"},
        None,
        "invalid",
        {"title": "fourth", "_normalized": {}},
    ])

    assert [row["Title"] for row in rows] == ["first", None, None, "fourth"]
    assert [row["Schema Status"] for row in rows] == ["missing", "missing", "missing", "available"]


@pytest.mark.parametrize("envelopes", [None, {}, "items", 1, set()])
def test_non_sequence_input_returns_empty_rows(envelopes):
    assert build_news_schema_diagnostics_rows(envelopes) == []


def test_render_only_sends_rows_to_streamlit_dataframe(monkeypatch):
    calls = []
    envelopes = [attach_normalized_news_item({
        "title": "Diagnostic", "text": "text", "source": "FMP", "ticker": "NVDA"
    })]
    monkeypatch.setattr(
        news_diagnostics.st,
        "dataframe",
        lambda data, **kwargs: calls.append((data, kwargs)),
    )

    result = render_news_schema_diagnostics(envelopes)

    assert result is None
    assert len(calls) == 1
    assert calls[0][0] == build_news_schema_diagnostics_rows(envelopes)
    assert calls[0][1] == {"use_container_width": True, "hide_index": True}
