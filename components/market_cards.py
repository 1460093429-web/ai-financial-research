"""Snapshot and metric card components for the Streamlit dashboard."""

import streamlit as st

from dashboard_support.formatting import format_money
from translations.core import TRANSLATIONS


DEFAULT_LANGUAGE = "中文"


def _translate(key):
    language = st.session_state.get("language", DEFAULT_LANGUAGE)
    return TRANSLATIONS.get(language, TRANSLATIONS["English"]).get(
        key,
        TRANSLATIONS["English"].get(key, key),
    )


def render_snapshot_card(container, snapshot):
    change = snapshot["change_pct"] or 0
    delta_color = "#22c55e" if change >= 0 else "#ef4444"
    container.markdown(
        f"""
        <div class="stock-card">
          <div class="ticker">{snapshot["ticker"]}</div>
          <div class="company">{snapshot["name"]}</div>
          <div class="source">{_translate("source")}: {snapshot["source"]}</div>
          <div class="price">{format_money(snapshot["price"], 2)}</div>
          <div class="change" style="color:{delta_color}">{change:+.2f}% {_translate("today")}</div>
          <div class="card-grid">
            <span>{_translate("market_cap")}<b>{format_money(snapshot["market_cap"])}</b></span>
            <span>{_translate("revenue")}<b>{format_money(snapshot["revenue"])}</b></span>
            <span>{_translate("net_margin")}<b>{"N/A" if snapshot["net_margin"] is None else f'{snapshot["net_margin"] * 100:.1f}%'}</b></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_row(metrics):
    columns = st.columns(len(metrics))
    for column, (label, value, *delta) in zip(columns, metrics):
        column.metric(label, value, delta[0] if delta else None)
