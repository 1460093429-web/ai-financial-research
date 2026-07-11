from conftest import import_root_dashboard
from dashboard_support import company


dashboard = import_root_dashboard()


def test_dashboard_reexports_company_metadata_and_helpers():
    assert dashboard.COMPANY_NAMES is company.COMPANY_NAMES
    assert dashboard.SUPPLY_CHAIN_ROLES is company.SUPPLY_CHAIN_ROLES
    assert dashboard.normalize_ticker is company.normalize_ticker
    assert dashboard.company_name is company.company_name
    assert dashboard.supply_chain_role is company.supply_chain_role


def test_normalize_ticker_preserves_existing_whitespace_and_case_behavior():
    assert company.normalize_ticker(" nv da\t") == "NVDA"
    assert company.normalize_ticker("brk.b") == "BRK.B"
    assert company.normalize_ticker(None) == ""


def test_company_name_prefers_snapshot_and_preserves_unknown_ticker():
    assert company.company_name("NVDA") == "NVIDIA"
    assert company.company_name("NVDA", {"name": "NVIDIA Corporation"}) == "NVIDIA Corporation"
    assert company.company_name("UNKNOWN") == "UNKNOWN"


def test_supply_chain_role_preserves_known_and_unknown_outputs():
    assert company.supply_chain_role("MU") == "HBM and memory"
    assert company.supply_chain_role("UNKNOWN") == "Dynamic watchlist stock"
