from copy import deepcopy

import pytest

from fixtures.memory_cycle_mvp import FIXTURE_EVALUATED_AT, MEMORY_CYCLE_MVP_FIXTURES
from services.memory_cycle_contract import build_metric_record
from services.memory_cycle_view_model import build_memory_cycle_view_model


def _all_metrics(view_model):
    return [metric for section in view_model["sections"] for metric in section["metrics"]]


def _metric(metric_id, **overrides):
    values = {
        "metric_id": metric_id,
        "label": metric_id,
        "value": 1.5,
        "unit": "%",
        "as_of": "2025-02-01",
        "retrieved_at": "2025-02-02T00:00:00Z",
        "source": "test/demo evidence",
        "source_type": "direct",
        "frequency": "daily",
        "is_fallback": False,
        "is_estimate": False,
        "confidence": "high",
        "status": "ok",
        "notes": "Reviewed test evidence.",
        "evaluated_at": "2025-02-02T00:00:00Z",
    }
    values.update(overrides)
    return build_metric_record(**values)


def test_all_sections_are_present_and_fixture_metrics_are_grouped():
    view = build_memory_cycle_view_model(MEMORY_CYCLE_MVP_FIXTURES, evaluated_at=FIXTURE_EVALUATED_AT, language="en")
    sections = {section["section_id"]: section for section in view["sections"]}

    assert list(sections) == [
        "company_financials",
        "pricing_signals",
        "demand_signals",
        "supply_discipline",
        "inventory_health",
        "market_proxies",
        "unavailable_data",
    ]
    assert len(sections["company_financials"]["metrics"]) == 6
    assert len(sections["pricing_signals"]["metrics"]) == 2
    assert len(sections["demand_signals"]["metrics"]) == 2
    assert len(sections["supply_discipline"]["metrics"]) == 1
    assert len(sections["inventory_health"]["metrics"]) == 1
    assert len(sections["market_proxies"]["metrics"]) == 4
    assert len(sections["unavailable_data"]["metrics"]) == 5


def test_input_order_is_stable_inside_sections_and_input_is_not_modified():
    metrics = [deepcopy(MEMORY_CYCLE_MVP_FIXTURES[index]) for index in (9, 6, 8, 7, 1, 0)]
    before = deepcopy(metrics)

    view = build_memory_cycle_view_model(metrics, evaluated_at=FIXTURE_EVALUATED_AT)
    sections = {section["section_id"]: section for section in view["sections"]}

    assert [metric["label"] for metric in sections["market_proxies"]["metrics"]] == [
        "SOXX Trend", "MU Price Trend", "SMH Trend", "SNDK Price Trend"
    ]
    assert [metric["label"] for metric in sections["company_financials"]["metrics"]] == ["MU Gross Margin", "MU Revenue"]
    assert metrics == before


def test_none_is_missing_not_zero_and_real_zero_is_preserved():
    missing = _metric("company_revenue", value=None, status="missing")
    zero = _metric("operating_margin", value=0.0, unit="%")
    view = build_memory_cycle_view_model([missing, zero], evaluated_at="2025-02-02", language="en")
    rendered = _all_metrics(view)

    assert rendered[0]["display_value"] == "Missing"
    assert rendered[0]["display_value"] != "0"
    assert rendered[1]["display_value"] == "0"


@pytest.mark.parametrize(
    ("language", "unavailable", "missing", "stale", "proxy", "news", "fallback", "estimate"),
    [
        ("en", "Unavailable", "Missing", "Stale", "Proxy", "News signal", "Fallback", "Estimate"),
        ("zh", "暂不可用", "数据缺失", "已过期", "代理指标", "新闻信号", "备用数据", "估算"),
        ("es", "No disponible", "Faltante", "Desactualizado", "Proxy", "Señal de noticias", "Fuente alternativa", "Estimación"),
    ],
)
def test_status_and_badge_labels_are_localized(language, unavailable, missing, stale, proxy, news, fallback, estimate):
    metrics = [
        _metric("dram_spot_price", value=None, status="unavailable", as_of=None, retrieved_at=None, source="unavailable", confidence="low", notes="No source."),
        _metric("company_revenue", value=None, status="missing", confidence="low"),
        _metric("company_revenue", status="stale", evaluated_at="2025-03-05T00:00:00Z"),
        _metric("memory_company_equity_trend", source_type="proxy", is_estimate=True, is_fallback=True),
        _metric("dram_price_direction", value="stable", unit=None, source_type="news_signal"),
    ]
    view = build_memory_cycle_view_model(metrics, evaluated_at="2025-02-02", language=language)
    rendered = {metric["status"] + metric["source_type"]: metric for metric in _all_metrics(view)}

    assert rendered["unavailabledirect"]["display_value"] == unavailable
    assert missing in rendered["missingdirect"]["badge"]
    assert stale in rendered["staledirect"]["badge"]
    assert proxy in rendered["okproxy"]["badge"]
    assert estimate in rendered["okproxy"]["badge"]
    assert fallback in rendered["okproxy"]["badge"]
    assert news in rendered["oknews_signal"]["badge"]


def test_quality_summary_and_section_counts_are_exact_for_static_fixtures():
    view = build_memory_cycle_view_model(MEMORY_CYCLE_MVP_FIXTURES, evaluated_at=FIXTURE_EVALUATED_AT)

    assert view["quality_summary"] == {
        "ok": 16,
        "missing": 0,
        "stale": 0,
        "unavailable": 5,
        "proxy": 4,
        "news_signal": 6,
        "fallback": 3,
        "estimate": 4,
        "high_confidence": 0,
        "medium_confidence": 16,
        "low_confidence": 5,
        "ok_count": 16,
        "missing_count": 0,
        "stale_count": 0,
        "unavailable_count": 5,
        "proxy_count": 4,
        "news_signal_count": 6,
        "fallback_count": 3,
        "estimate_count": 4,
        "high_confidence_count": 0,
        "medium_confidence_count": 16,
        "low_confidence_count": 5,
        "status_counts": {"ok": 16, "missing": 0, "stale": 0, "unavailable": 5},
        "confidence_counts": {"high": 0, "medium": 16, "low": 5},
    }
    assert view["available_metric_count"] == 16
    assert view["missing_metric_count"] == 0
    assert view["unavailable_metric_count"] == 5
    assert view["proxy_metric_count"] == 4
    assert view["news_signal_count"] == 6


def test_latest_as_of_safely_compares_date_only_and_timezone_timestamps():
    metrics = [
        _metric("company_revenue", as_of="2025-02-03"),
        _metric("gross_margin", as_of="2025-02-03T23:00:00-05:00"),
        _metric("operating_margin", as_of="not-a-date"),
    ]

    view = build_memory_cycle_view_model(metrics, evaluated_at="2025-02-04T12:00:00Z")

    assert view["latest_as_of"] == "2025-02-03T23:00:00-05:00"


def test_notes_and_evidence_availability_are_preserved_and_conservative():
    notes = "Citation: reviewed demo\nMethod: deterministic"
    available = _metric("dram_price_direction", value="improving", unit=None, source_type="news_signal", notes=notes)
    unavailable = _metric("hbm_price", value=None, status="unavailable", as_of=None, retrieved_at=None, source="unavailable", notes="No direct source.")

    rendered = _all_metrics(build_memory_cycle_view_model([available, unavailable], evaluated_at="2025-02-02"))

    assert rendered[0]["notes"] == notes
    assert rendered[0]["evidence_available"] is True
    assert rendered[1]["evidence_available"] is False


def test_warnings_are_deterministic_and_do_not_overstate_evidence():
    view = build_memory_cycle_view_model(MEMORY_CYCLE_MVP_FIXTURES, evaluated_at=FIXTURE_EVALUATED_AT, language="en")

    assert view["warnings"] == [
        "5 metrics are unavailable.",
        "Pricing information is based on news signals, not direct price series.",
        "Market performance metrics are proxies and do not represent memory fundamentals.",
    ]
    assert "score" not in view
    assert "cycle_phase" not in view


@pytest.mark.parametrize("metrics", [None, {}, "metrics", 1, set()])
def test_non_sequence_input_returns_an_empty_safe_view_model(metrics):
    view = build_memory_cycle_view_model(metrics, evaluated_at="2025-02-15", language="en")

    assert len(view["sections"]) == 7
    assert _all_metrics(view) == []
    assert view["available_metric_count"] == 0
    assert view["latest_as_of"] is None
    assert view["warnings"] == []


def test_unknown_language_uses_english_fallback():
    view = build_memory_cycle_view_model([], evaluated_at="2025-02-15", language="fr")

    assert view["language"] == "en"
    assert view["sections"][0]["title"] == "Company Financials"


def test_view_model_module_exposes_no_external_clients_or_dashboard_link():
    import services.memory_cycle_view_model as module

    forbidden = {"requests", "yfinance", "openai", "ib_insync", "streamlit", "dashboard"}
    assert forbidden.isdisjoint(module.__dict__)
