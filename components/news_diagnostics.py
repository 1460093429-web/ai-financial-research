"""Non-production diagnostics for legacy and normalized news envelopes."""

import streamlit as st


def _first_present(item, keys):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _ticker_text(value):
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    elif value is None:
        values = []
    else:
        values = [value]
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return ", ".join(result)


def build_news_schema_diagnostics_rows(envelopes) -> list[dict]:
    """Build ordered comparison rows without mutating supplied envelopes."""
    if not isinstance(envelopes, (list, tuple)):
        return []
    rows = []
    for envelope in envelopes:
        legacy = envelope if isinstance(envelope, dict) else {}
        normalized_value = legacy.get("_normalized")
        normalized = normalized_value if isinstance(normalized_value, dict) else {}
        has_schema = isinstance(normalized_value, dict)
        legacy_summary = _first_present(legacy, ("summary", "text", "description"))
        normalized_summary = normalized.get("summary")
        legacy_published = _first_present(
            legacy,
            ("published_date", "publishedDate", "date", "timestamp", "published", "updated"),
        )
        normalized_published = normalized.get("published_at")
        legacy_related = _first_present(legacy, ("related_tickers", "ticker"))
        normalized_related = normalized.get("related_tickers")
        legacy_related_text = _ticker_text(legacy_related)
        normalized_related_text = _ticker_text(normalized_related)
        rows.append({
            "Title": legacy.get("title"),
            "Schema Status": "available" if has_schema else "missing",
            "Legacy Source": legacy.get("source") or legacy.get("site"),
            "Normalized Provider": normalized.get("provider") if has_schema else "missing",
            "Normalized Source": normalized.get("source") if has_schema else "missing",
            "Publisher": legacy.get("publisher") or legacy.get("site"),
            "Published At": normalized_published if has_schema else "missing",
            "Is Fallback": normalized.get("is_fallback") if has_schema else "missing",
            "Fallback From": normalized.get("fallback_from") if has_schema else "missing",
            "Ticker": normalized.get("ticker") if has_schema else legacy.get("ticker"),
            "Related Tickers": normalized_related_text if has_schema else "missing",
            "Legacy Summary": legacy_summary,
            "Normalized Summary": normalized_summary if has_schema else "missing",
            "Summary Matches": has_schema and legacy_summary == normalized_summary,
            "Legacy Published": None if legacy_published is None else str(legacy_published),
            "Publication Matches": (
                has_schema
                and (None if legacy_published is None else str(legacy_published)) == normalized_published
            ),
            "Legacy Related Tickers": legacy_related_text,
            "Related Tickers Match": has_schema and legacy_related_text == normalized_related_text,
        })
    return rows


def render_news_schema_diagnostics(envelopes):
    """Render caller-supplied diagnostics without fetching or modifying news."""
    rows = build_news_schema_diagnostics_rows(envelopes)
    st.dataframe(rows, use_container_width=True, hide_index=True)
