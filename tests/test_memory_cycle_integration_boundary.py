"""Characterization tests that keep Phase 4.5 outside production routing."""

import ast
import hashlib
from pathlib import Path

import pytest

from fixtures.memory_cycle_mvp import FIXTURE_EVALUATED_AT, MEMORY_CYCLE_MVP_FIXTURES
from services.memory_cycle_view_model import build_memory_cycle_view_model


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = PROJECT_ROOT / "dashboard.py"
PLAN_PATH = PROJECT_ROOT / "MEMORY_CYCLE_INTEGRATION_PLAN.md"

BASELINE_HASHES = {
    "components/memory_cycle.py": "a29117590a9845357173d3350764c81e56bf62c329d9f548f0357041c8324c54",
    "demos/memory_cycle_demo.py": "dfec0ad11ee48b31f7eeae9f647a975806f5ed21f114fb1778448e9adfdb0398",
    "fixtures/memory_cycle_mvp.py": "2b0e452ad8fdea4cb4295e0304b222251dded54dd486ae496d754d83f70c64d8",
    "services/memory_cycle_view_model.py": "496d6470e00b04d8f07458924398ea81fea0ca9fd17cb83df4390076f64771f4",
    "services/memory_cycle_adapters.py": "a82b5012337a8663c18b3a98675ae5e2f076a2dba17ee93482855f85845197da",
    "services/memory_cycle_contract.py": "8d44f71c3292ce76bf9e401cff7881d3465992d10e7a783772b9f4fd1b7b9e0f",
}


def _source(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _imports(relative_path):
    tree = ast.parse(_source(relative_path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _main_function_tree():
    tree = ast.parse(_source("dashboard.py"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")


def _section_labels_assignment():
    main = _main_function_tree()
    for node in ast.walk(main):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "section_labels"
            for target in node.targets
        ):
            return node.value
    raise AssertionError("section_labels assignment not found")


def _all_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).casefold()
            yield from _all_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _all_keys(nested)


def test_dashboard_does_not_import_memory_cycle_component_fixture_view_model_or_demo():
    imports = _imports("dashboard.py")

    assert "components.memory_cycle" not in imports
    assert "fixtures.memory_cycle_mvp" not in imports
    assert "services.memory_cycle_view_model" not in imports
    assert "demos.memory_cycle_demo" not in imports


def test_dashboard_section_and_sidebar_do_not_contain_memory_cycle():
    source = _source("dashboard.py")
    section_list = _section_labels_assignment()

    assert isinstance(section_list, ast.List)
    assert all("memory" not in ast.unparse(item).casefold() for item in section_list.elts)
    assert "Memory Cycle Monitor" not in source
    assert "存储周期监控" not in source
    assert "Monitor del ciclo de memoria" not in source


def test_dashboard_default_section_remains_technical_analysis_without_query_routing():
    section_list = _section_labels_assignment()
    first = section_list.elts[0]
    assert isinstance(first, ast.Call)
    assert isinstance(first.func, ast.Name) and first.func.id == "t"
    assert first.args[0].value == "technical_analysis"

    main = _main_function_tree()
    radio = next(
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "radio"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "Section"
    )
    keywords = {keyword.arg: keyword.value for keyword in radio.keywords}
    assert "index" not in keywords
    assert isinstance(keywords["key"], ast.Constant)
    assert keywords["key"].value == "main_section_selector"
    assert "query_params" not in _source("dashboard.py")
    assert "experimental_get_query_params" not in _source("dashboard.py")


def test_dashboard_has_no_memory_cycle_dispatch_or_view_model_execution():
    source = _source("dashboard.py")

    assert "build_memory_cycle_view_model" not in source
    assert "render_memory_cycle_dashboard" not in source
    assert "build_demo_scenario" not in source


def test_static_demo_remains_an_independent_runnable_page():
    dashboard_source = _source("dashboard.py")
    demo_source = _source("demos/memory_cycle_demo.py")

    assert "demos.memory_cycle_demo" not in dashboard_source
    assert "fixtures.memory_cycle_mvp" in demo_source
    assert "build_memory_cycle_view_model" in demo_source
    assert "render_memory_cycle_dashboard" in demo_source
    assert 'if __name__ == "__main__"' in demo_source


@pytest.mark.parametrize(
    "relative_path",
    [
        "components/memory_cycle.py",
        "fixtures/memory_cycle_mvp.py",
        "services/memory_cycle_view_model.py",
        "demos/memory_cycle_demo.py",
    ],
)
def test_current_memory_cycle_layers_import_no_external_client_or_cache(relative_path):
    imports = _imports(relative_path)
    forbidden = {
        "requests",
        "yfinance",
        "openai",
        "ib_insync",
        "providers",
        "financials",
        "config",
        "os",
    }

    assert forbidden.isdisjoint(imports)
    source = _source(relative_path)
    assert "st.cache_data" not in source
    assert "st.cache_resource" not in source
    assert "st.secrets" not in source
    assert "session_state" not in source
    assert "getenv(" not in source


def test_fixture_uses_fixed_injected_time_and_no_real_time_or_file_io():
    source = _source("fixtures/memory_cycle_mvp.py")
    tree = ast.parse(source)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert FIXTURE_EVALUATED_AT == "2025-02-15T12:00:00Z"
    assert {"open", "getenv", "now", "today", "utcnow"}.isdisjoint(called_names)
    assert "secrets" not in source
    assert "environ" not in source


def test_view_model_and_component_rows_emit_no_score_or_cycle_phase():
    from components.memory_cycle import build_memory_cycle_component_rows

    view = build_memory_cycle_view_model(
        MEMORY_CYCLE_MVP_FIXTURES,
        evaluated_at=FIXTURE_EVALUATED_AT,
        language="en",
    )
    rows = build_memory_cycle_component_rows(view)

    for result in (view, rows):
        keys = set(_all_keys(result))
        assert "score" not in keys
        assert "cycle_phase" not in keys
        assert "phase" not in keys


def test_document_locks_three_navigation_names_and_recommended_position():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "存储周期监控" in plan
    assert "Memory Cycle Monitor" in plan
    assert "Monitor del ciclo de memoria" in plan
    assert "AFTER_FACTOR_WATCH_BEFORE_NEWS" in plan


def test_document_compares_static_preview_and_production_data_and_records_decision():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "## 5. Option A — Static Preview" in plan
    assert "## 6. Option B — Production Data" in plan
    assert "WAIT_FOR_MINIMUM_PRODUCTION_DATA_PIPELINE" in plan
    assert "Static fixtures must never be" in plan


def test_document_records_page_error_and_session_state_isolation():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "## 8. Page-level error isolation contract" in plan
    assert "Never render a traceback" in plan
    assert "must still be able to choose another Section" in plan
    assert "## 9. Session-state boundary" in plan
    for key in (
        "memory_cycle_language",
        "memory_cycle_scenario",
        "memory_cycle_refresh_nonce",
        "memory_cycle_last_error",
        "memory_cycle_last_generated_at",
    ):
        assert key in plan
    assert "No Memory Cycle session key is added in Phase 4.5" in plan


def test_document_records_cache_time_refresh_and_quality_boundaries():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "## 10. Cache ownership" in plan
    assert "observation time" in plan
    assert "retrieval time" in plan
    assert "## 11. Refresh strategy" in plan
    assert "explicit Refresh control" in plan
    assert "## 12. Fallback, stale, missing, and unavailable strategy" in plan
    for term in ("Fallback", "Stale", "Missing", "Unavailable"):
        assert f"**{term}:**" in plan


def test_document_records_all_required_visual_risks_and_formal_gates():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "## 13. Visual and interaction risks requiring manual review" in plan
    risks = (
        "desktop wide layout",
        "narrow layout",
        "seven top quality metrics",
        "21 metric cards",
        "long Chinese notes",
        "long Spanish titles and badges",
        "Company Financials card-height",
        "Unavailable Data",
        "Notes remain appropriately collapsed",
        "all seven sections",
        "stale-heavy state",
        "Proxy and News signal",
        "dark-mode",
        "mobile requires a single-column layout",
    )
    for risk in risks:
        assert risk in plan
    assert "## 14. Formal integration gates" in plan


def test_phase_45_memory_cycle_implementation_files_remain_unchanged():
    for relative_path, expected_hash in BASELINE_HASHES.items():
        digest = hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest()
        assert digest == expected_hash, relative_path


def test_plan_forbids_production_side_effects_and_keeps_watchlist_independent():
    plan = _source("MEMORY_CYCLE_INTEGRATION_PLAN.md")

    assert "Do not add a Static Preview to the production Dashboard now" in plan
    assert "Do not read, add, remove, or rewrite Watchlist entries" in plan
    assert "Do not request an external API, OpenAI, or IBKR merely on import" in plan
    assert "Do not clear global or other-page caches" in plan
