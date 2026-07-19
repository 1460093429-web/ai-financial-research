"""Render a localized Value Investing view model without financial calculations."""

from copy import deepcopy
import math
from numbers import Real
from typing import Any

import streamlit as st

from translations.value_investing import value_investing_text


def build_value_investing_component_rows(view_model: Any) -> dict[str, Any]:
    """Copy a Value Investing view model into safe component rows."""

    if not isinstance(view_model, dict):
        return {
            "title": None,
            "ticker": None,
            "company_name": None,
            "periods": {},
            "data_quality": {},
            "sections": [],
            "status": "error",
            "text": {},
        }
    rows = deepcopy(view_model)
    rows["sections"] = []
    raw_sections = view_model.get("sections")
    if isinstance(raw_sections, (list, tuple)):
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                continue
            section = deepcopy(raw_section)
            metrics = raw_section.get("metrics")
            section["metrics"] = (
                [deepcopy(metric) for metric in metrics if isinstance(metric, dict)]
                if isinstance(metrics, (list, tuple)) else []
            )
            rows["sections"].append(section)
    rows["periods"] = deepcopy(view_model.get("periods")) if isinstance(view_model.get("periods"), dict) else {}
    rows["data_quality"] = deepcopy(view_model.get("data_quality")) if isinstance(view_model.get("data_quality"), dict) else {}
    rows["text"] = deepcopy(view_model.get("text")) if isinstance(view_model.get("text"), dict) else {}
    rows["status"] = view_model.get("status") if view_model.get("status") in {"ok", "partial", "error"} else "error"
    return rows


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _display_value(metric: dict[str, Any], text: dict[str, Any]) -> str:
    status = metric.get("status")
    if status in {"missing", "unavailable"}:
        return text["statuses"][status]
    value = _number(metric.get("normalized_value"))
    if value is None:
        return text["statuses"]["missing"]
    unit = metric.get("normalized_unit")
    if unit == "percent":
        return f"{value:,.2f}%"
    if unit == "ratio":
        return f"{value * 100:,.2f}%"
    if unit == "multiple":
        return f"{value:,.2f}x"
    if isinstance(unit, str) and unit:
        return f"{value:,.2f} {unit}"
    return f"{value:,.2f}"


def _render_metric(metric: dict[str, Any], text: dict[str, Any]) -> None:
    label = metric.get("label") or text["statuses"]["unavailable"]
    status = metric.get("status")
    if status not in {"ok", "stale", "missing", "unavailable"}:
        status = "unavailable"
    with st.container(border=True):
        st.metric(label=label, value=_display_value(metric, text))
        st.caption(
            f"{text['period']}: {metric.get('period_label') or text['statuses']['unavailable']}"
            f" | {text['data_date']}: {metric.get('period_end') or text['statuses']['unavailable']}"
        )
        st.caption(
            f"{text['source']}: {metric.get('source') or 'FMP'}"
            f" | {text['unit']}: {metric.get('normalized_unit') or text['statuses']['unavailable']}"
        )
        st.caption(
            f"{text['evidence_label']}: {metric.get('evidence_label') or text['evidence']['reported']}"
        )
        if status == "stale" and isinstance(metric.get("staleness_days"), int) and not isinstance(metric.get("staleness_days"), bool):
            st.warning(f"{text['days_stale']}: {metric['staleness_days']}")
        elif status in {"missing", "unavailable"}:
            st.info(text["statuses"][status])


def render_value_investing_dashboard(
    view_model: Any, *, language: Any = "English"
) -> None:
    """Render identity, quality, periods, and reliable metric sections."""

    rows = build_value_investing_component_rows(view_model)
    text = rows.get("text") or value_investing_text(language)
    st.subheader(rows.get("title") or text["title"])
    st.caption(
        f"{rows.get('ticker') or text['statuses']['unavailable']}"
        f" | {rows.get('company_name') or text['statuses']['unavailable']}"
    )

    quality = rows.get("data_quality", {})
    periods = rows.get("periods", {})
    st.subheader(text["quality"])
    st.caption(
        f"{text['source']}: {quality.get('source') or 'FMP'}"
        f" | {text['currency']}: {quality.get('currency') or text['statuses']['unavailable']}"
    )
    st.caption(
        f"{text['coverage']}: {quality.get('successful_metric_count', 0)}"
        f" / {quality.get('total_metric_count', 0)}"
    )
    st.caption(
        f"{text['retrieved_at']}: {quality.get('retrieved_at') or text['statuses']['unavailable']}"
    )
    st.caption(
        f"{text['ttm_ended']}: {periods.get('ttm_end') or text['statuses']['unavailable']}"
        f" | {text['balance_ended']}: {periods.get('balance_end') or text['statuses']['unavailable']}"
        f" | {text['annual_ended']}: {periods.get('annual_end') or text['statuses']['unavailable']}"
    )
    if rows.get("status") in {"partial", "error"} or quality.get("errors"):
        st.warning(text["incomplete"])

    for section in rows.get("sections", []):
        st.subheader(section.get("title") or text["statuses"]["unavailable"])
        for metric in section.get("metrics", []):
            _render_metric(metric, text)
