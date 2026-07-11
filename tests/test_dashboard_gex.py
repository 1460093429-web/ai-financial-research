import numpy as np
import pandas as pd
import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()
_build_gamma_points_for_side = dashboard._build_gamma_points_for_side
_normalize_option_chain_frame = dashboard._normalize_option_chain_frame
_option_missing_reasons = dashboard._option_missing_reasons
calculate_strongest_gamma_points = dashboard.calculate_strongest_gamma_points


def test_normalize_option_chain_frame_coerces_numeric_fields_and_fills_activity_gaps():
    raw = pd.DataFrame(
        {
            "strike": ["100", "bad"],
            "openInterest": ["25", None],
            "volume": [None, "7"],
            "impliedVolatility": ["0.20", "bad"],
            "gamma": ["0.01", None],
            "contractSymbol": ["CALL100", "CALLBAD"],
        }
    )

    result = _normalize_option_chain_frame(raw)

    assert result.loc[0, "strike"] == 100.0
    assert pd.isna(result.loc[1, "strike"])
    assert result["openInterest"].tolist() == [25.0, 0.0]
    assert result["volume"].tolist() == [0.0, 7.0]
    assert result.loc[0, "impliedVolatility"] == 0.20
    assert pd.isna(result.loc[1, "impliedVolatility"])
    assert result["contractSymbol"].tolist() == ["CALL100", "CALLBAD"]


def test_gamma_points_preserve_call_positive_and_put_negative_sign_convention():
    calls = pd.DataFrame(
        [{"strike": 100, "openInterest": 10, "volume": 3, "impliedVolatility": 0.20, "gamma": 0.01}]
    )
    puts = pd.DataFrame(
        [{"strike": 100, "openInterest": 5, "volume": 2, "impliedVolatility": 0.25, "gamma": 0.01}]
    )

    result = calculate_strongest_gamma_points(calls, puts, underlying_price=100, expiry="2030-01-18")
    detail = result["top_gamma_points"].sort_values("option_type").reset_index(drop=True)
    by_strike = result["gex_by_strike"].iloc[0]

    assert detail["option_type"].tolist() == ["call", "put"]
    assert detail.loc[0, "gex"] == pytest.approx(0.10)
    assert detail.loc[1, "gex"] == pytest.approx(-0.05)
    assert by_strike["call_gex"] == pytest.approx(0.10)
    assert by_strike["put_gex"] == pytest.approx(-0.05)
    assert by_strike["net_gex"] == pytest.approx(0.05)
    assert by_strike["total_oi"] == 15
    assert by_strike["total_volume"] == 5


def test_gamma_builder_skips_nan_negative_and_zero_financial_inputs():
    invalid = pd.DataFrame(
        [
            {"strike": np.nan, "openInterest": 10, "impliedVolatility": 0.2},
            {"strike": 100, "openInterest": -1, "impliedVolatility": 0.2},
            {"strike": 100, "openInterest": 10, "impliedVolatility": 0},
            {"strike": "bad", "openInterest": 10, "impliedVolatility": 0.2},
        ]
    )

    result = _build_gamma_points_for_side(invalid, "call", underlying_price=100, time_to_expiry=0.25)

    assert result.empty


def test_strongest_gamma_points_invalid_underlying_returns_stable_empty_payload():
    valid_chain = pd.DataFrame(
        [{"strike": 100, "openInterest": 10, "impliedVolatility": 0.2, "gamma": 0.01}]
    )

    for underlying in (None, np.nan, 0, -100):
        result = calculate_strongest_gamma_points(valid_chain, valid_chain, underlying, "bad-date")

        assert result["top_gamma_points"].empty
        assert result["gex_by_strike"].empty


def test_option_missing_reasons_characterizes_empty_chain_and_missing_gamma():
    calls = pd.DataFrame(columns=["strike", "openInterest", "impliedVolatility"])
    puts = pd.DataFrame(columns=["strike", "openInterest", "impliedVolatility"])

    reasons = _option_missing_reasons(
        calls,
        puts,
        {},
        current_price_available=True,
        chain_available=False,
    )

    assert reasons == [
        "option_price_available_chain_unavailable",
        "option_call_put_empty",
        "option_open_interest_missing",
        "option_gamma_missing",
    ]
