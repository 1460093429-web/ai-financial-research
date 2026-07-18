"""Standalone Streamlit harness for static Memory Cycle fixture review."""

from copy import deepcopy
from datetime import date

import streamlit as st

from components.memory_cycle import render_memory_cycle_dashboard
from fixtures.memory_cycle_mvp import FIXTURE_EVALUATED_AT, MEMORY_CYCLE_MVP_FIXTURES
from services.memory_cycle_view_model import build_memory_cycle_view_model


LANGUAGE_OPTIONS = ("中文", "English", "Español")
SCENARIO_OPTIONS = (
    "Full fixture",
    "Empty data",
    "Missing-heavy",
    "Stale-heavy",
    "Unavailable-heavy",
    "Proxy/news-signal focused",
)
STALE_EVALUATED_AT = "2025-08-01T12:00:00Z"

_LANGUAGE_CODES = {"中文": "zh", "English": "en", "Español": "es"}
_DEMO_TEXT = {
    "zh": {
        "title": "存储周期静态演示",
        "notice": "Demo / Static Fixture：仅用于人工视觉检查，不是生产数据。",
        "scenario": "演示场景",
        "evaluated_at": "固定评估时间",
    },
    "en": {
        "title": "Memory Cycle Static Demo",
        "notice": "Demo / Static Fixture: for visual review only; this is not production data.",
        "scenario": "Demo scenario",
        "evaluated_at": "Fixed evaluation time",
    },
    "es": {
        "title": "Demo estática del ciclo de memoria",
        "notice": "Demo / Datos estáticos: solo para revisión visual; no son datos de producción.",
        "scenario": "Escenario de demostración",
        "evaluated_at": "Hora fija de evaluación",
    },
}


def _fixed_staleness_days(as_of):
    if not isinstance(as_of, str) or len(as_of) < 10:
        return None
    try:
        observation = date.fromisoformat(as_of[:10])
        reference = date.fromisoformat(STALE_EVALUATED_AT[:10])
    except ValueError:
        return None
    return (reference - observation).days


def normalize_demo_language(language):
    """Return a component language code, defaulting unknown values to English."""
    if language in _LANGUAGE_CODES:
        return _LANGUAGE_CODES[language]
    value = str(language or "").strip().casefold()
    return value if value in {"zh", "en", "es"} else "en"


def build_demo_scenario(scenario="Full fixture") -> dict:
    """Return a fresh deterministic fixture scenario and its evaluation time."""
    selected = scenario if scenario in SCENARIO_OPTIONS else SCENARIO_OPTIONS[0]
    metrics = [deepcopy(metric) for metric in MEMORY_CYCLE_MVP_FIXTURES]
    evaluated_at = FIXTURE_EVALUATED_AT

    if selected == "Empty data":
        metrics = []
    elif selected == "Missing-heavy":
        changed = 0
        for metric in metrics:
            if metric.get("status") == "ok" and changed < 12:
                metric["value"] = None
                metric["status"] = "missing"
                metric["staleness_days"] = None
                changed += 1
    elif selected == "Stale-heavy":
        evaluated_at = STALE_EVALUATED_AT
        for metric in metrics:
            if metric.get("status") == "ok":
                metric["status"] = "stale"
                metric["staleness_days"] = _fixed_staleness_days(metric.get("as_of"))
    elif selected == "Unavailable-heavy":
        metrics = [metric for metric in metrics if metric.get("status") == "unavailable"]
    elif selected == "Proxy/news-signal focused":
        metrics = [
            metric
            for metric in metrics
            if metric.get("source_type") in {"proxy", "news_signal"}
        ]

    return {
        "scenario": selected,
        "metrics": metrics,
        "evaluated_at": evaluated_at,
    }


def build_demo_view_model(scenario="Full fixture", *, language="zh") -> dict:
    """Build the existing Phase 4.2 view model for a static demo scenario."""
    demo = build_demo_scenario(scenario)
    return build_memory_cycle_view_model(
        demo["metrics"],
        evaluated_at=demo["evaluated_at"],
        language=normalize_demo_language(language),
    )


def render_memory_cycle_demo():
    """Render the standalone page without reading production state or data."""
    st.set_page_config(page_title="Memory Cycle Static Demo", layout="centered")
    language_choice = st.selectbox(
        "Language / 语言 / Idioma",
        LANGUAGE_OPTIONS,
        index=0,
    )
    language = normalize_demo_language(language_choice)
    text = _DEMO_TEXT[language]
    st.title(text["title"])
    st.warning(text["notice"])
    scenario = st.selectbox(text["scenario"], SCENARIO_OPTIONS, index=0)
    demo = build_demo_scenario(scenario)
    st.caption(f"{text['evaluated_at']}: {demo['evaluated_at']}")
    view_model = build_memory_cycle_view_model(
        demo["metrics"],
        evaluated_at=demo["evaluated_at"],
        language=language,
    )
    render_memory_cycle_dashboard(view_model, language=language)
    st.divider()
    st.caption("This is static demo data.")
    st.caption("No real market data is being fetched.")
    st.caption("No cycle score or phase is calculated.")


if __name__ == "__main__":
    render_memory_cycle_demo()
