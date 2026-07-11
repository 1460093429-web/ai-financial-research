import numpy as np

from conftest import import_root_dashboard
from dashboard_support.formatting import card_number


dashboard = import_root_dashboard()


def test_dashboard_reexports_formatting_helpers_under_existing_names():
    assert dashboard.format_money(1_500_000, 1) == "$1.5M"
    assert dashboard.format_money(-1_500_000, 2) == "$-1.50M"
    assert dashboard.format_money(999.5, 1) == "$999.5"
    assert dashboard.format_ratio("1234.5") == "1,234.50"
    assert dashboard.format_percent("0.125") == "12.5%"


def test_formatting_helpers_preserve_missing_value_outputs():
    for value in (None, np.nan):
        assert dashboard.format_money(value) == "N/A"
        assert dashboard.format_ratio(value) == "N/A"
        assert dashboard.format_percent(value) == "N/A"


def test_card_number_preserves_numeric_coercion_and_rejects_invalid_values():
    assert card_number("1,000") is None
    assert card_number("1000") == 1000.0
    assert card_number(-25) == -25.0
    for value in (None, np.nan, np.inf, -np.inf, "bad", [1, 2]):
        assert card_number(value) is None
