import pandas as pd

from option_walls import compute_option_walls


def test_compute_option_walls_uses_selected_expiry_highest_open_interest():
    options = pd.DataFrame([
        {"expiry": "2026-06-26", "optionType": "put", "strike": 150, "openInterest": 1057},
        {"expiry": "2026-06-26", "optionType": "put", "strike": 90, "openInterest": 800},
        {"expiry": "2026-06-26", "optionType": "call", "strike": 190, "openInterest": 1200},
        {"expiry": "2026-06-26", "optionType": "call", "strike": 170, "openInterest": 300},
        {"expiry": "2026-07-17", "optionType": "put", "strike": 90, "openInterest": 5000},
        {"expiry": "2026-07-17", "optionType": "call", "strike": 200, "openInterest": 5000},
    ])

    result = compute_option_walls(options, "2026-06-26", spot_price=167.5)

    assert result["put_wall"]["strike"] == 150
    assert result["put_wall"]["open_interest"] == 1057
    assert result["call_wall"]["strike"] == 190
    assert result["call_wall"]["open_interest"] == 1200


def test_compute_option_walls_supports_field_aliases_and_tiebreaks_by_spot():
    options = pd.DataFrame([
        {"expiration": "2026-06-26", "side": "P", "strike": "145", "oi": "100"},
        {"expiration": "2026-06-26", "side": "P", "strike": "155", "oi": "100"},
        {"expiration": "2026-06-26", "side": "C", "strike": "180", "oi": "200"},
        {"expiration": "2026-06-26", "side": "C", "strike": "190", "oi": "200"},
    ])

    result = compute_option_walls(options, "2026-06-26", spot_price=160)

    assert result["put_wall"]["strike"] == 155
    assert result["call_wall"]["strike"] == 180


def test_compute_option_walls_tiebreaks_by_lowest_strike_without_spot():
    options = pd.DataFrame([
        {"exp_date": "2026-06-26", "type": "put", "strike": 150, "open_interest": 100},
        {"exp_date": "2026-06-26", "type": "put", "strike": 140, "open_interest": 100},
        {"exp_date": "2026-06-26", "type": "call", "strike": 200, "open_interest": None},
    ])

    result = compute_option_walls(options, "2026-06-26")

    assert result["put_wall"]["strike"] == 140
    assert result["call_wall"]["strike"] == 200
    assert result["call_wall"]["open_interest"] == 0


def test_compute_option_walls_empty_or_missing_required_fields_returns_explicit_empty_walls():
    expected = {
        "put_wall": {"strike": None, "open_interest": 0.0},
        "call_wall": {"strike": None, "open_interest": 0.0},
    }

    assert compute_option_walls(None, "2026-06-26") == expected
    assert compute_option_walls(pd.DataFrame(), "2026-06-26") == expected
    assert compute_option_walls(pd.DataFrame({"strike": [100]}), "2026-06-26") == expected


def test_compute_option_walls_filters_expiry_and_invalid_rows_without_aggregating_duplicates():
    options = pd.DataFrame([
        {"expirationDate": "2026-06-26", "option_type": "P", "strike": "150", "open_interest": "250"},
        {"expirationDate": "2026-06-26", "option_type": "put", "strike": "150", "open_interest": "250"},
        {"expirationDate": "2026-06-26", "option_type": "put", "strike": "bad", "open_interest": "9999"},
        {"expirationDate": "2026-06-26", "option_type": "call", "strike": "180", "open_interest": None},
        {"expirationDate": "2026-07-17", "option_type": "call", "strike": "200", "open_interest": "9000"},
    ])

    result = compute_option_walls(options, "2026-06-26", spot_price="160")

    assert result == {
        "put_wall": {"strike": 150.0, "open_interest": 250.0},
        "call_wall": {"strike": 180.0, "open_interest": 0.0},
    }
