"""Characterize the pre-Phase-4.8 Value Investing path before replacement."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = PROJECT_ROOT / "dashboard.py"
FINANCIALS_PATH = PROJECT_ROOT / "financials.py"
TRANSLATIONS_PATH = PROJECT_ROOT / "translations" / "core.py"


def _function_source(path, name):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node), node


def test_current_value_entry_is_render_value_section_in_existing_navigation_order():
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert 'elif selected_section == t("value_investing"):\n        render_value_section()' in source
    section_line = next(line for line in source.splitlines() if "section_labels = [" in line)
    assert section_line.strip() == "section_labels = ["
    assert 't("technical_analysis"), t("options_gex"), t("value_investing")' in source


def test_repaired_value_renderer_reads_watchlist_and_shared_snapshot_service():
    source, node = _function_source(DASHBOARD_PATH, "render_value_section")
    calls = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert {
        "load_watchlist", "load_value_investing_snapshot",
        "build_value_investing_view_model", "render_value_investing_dashboard",
    }.issubset(calls)
    assert "get_company_snapshot" not in calls
    assert "render_metric_row" not in calls
    assert "_snapshot_from_yfinance_fallback" not in source
    loader_source, _ = _function_source(DASHBOARD_PATH, "get_company_snapshot")
    dashboard_source = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "@st.cache_data(ttl=21600)\ndef get_company_snapshot" in dashboard_source
    assert "_snapshot_from_yfinance_fallback" in loader_source


def test_repaired_value_renderer_delegates_raw_data_and_display_semantics():
    source, _ = _function_source(DASHBOARD_PATH, "render_value_section")
    assert "load_value_investing_snapshot" in source
    assert "build_value_investing_view_model" in source
    assert "render_value_investing_dashboard" in source
    for marker in ("grossProfitRatio", "capitalExpenditure", "freeCashFlow", "priceTo"):
        assert marker not in source
    assert "snapshots" not in source


def test_legacy_financial_path_mixes_fmp_and_fallback_fields_under_one_snapshot():
    source, _ = _function_source(FINANCIALS_PATH, "get_company_snapshot")
    assert "_overlay_fmp(snapshot, ticker, api_key)" in source
    assert "fallback = _fetch_yfinance_snapshot(ticker)" in source
    assert "if snapshot.get(field) is None" in source
    overlay, _ = _function_source(FINANCIALS_PATH, "_overlay_fmp")
    assert '"source": "FMP"' in overlay


def test_legacy_fcf_margin_and_valuation_fields_lack_verified_period_join():
    source, _ = _function_source(FINANCIALS_PATH, "_overlay_fmp")
    assert 'free_cash_flow = _number(metrics.get("freeCashFlowToFirm"))' in source
    assert '"free_cash_flow_margin": _ratio(free_cash_flow, revenue)' in source
    assert 'ratios.get("priceToEarningsRatio")' in source
    assert 'ratios.get("priceToBookRatio")' in source
    assert 'ratios.get("priceToSalesRatio")' in source
    assert "period=" not in source


def test_legacy_financial_data_coerces_missing_margin_to_zero():
    source, _ = _function_source(FINANCIALS_PATH, "get_financial_data")
    assert '"Margin": snapshot["net_margin"] or 0' in source


def test_existing_value_navigation_label_is_available_in_three_languages():
    source = TRANSLATIONS_PATH.read_text(encoding="utf-8")
    assert '"value_investing": "Value Investing"' in source
    assert '"value_investing": "价值投资"' in source
    assert '"value_investing": "Inversión en valor"' in source
