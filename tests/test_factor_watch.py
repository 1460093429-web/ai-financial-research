# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from factor_watch import (
    FACTOR_COLUMNS,
    FACTOR_DEFINITIONS,
    build_factor_metrics,
    build_factor_watch_df,
    generate_factor_summary,
    get_etf_top_holdings,
    get_factor_explanation,
)


def test_build_factor_watch_df_empty_input_preserves_schema():
    for prices in (None, pd.DataFrame(), pd.DataFrame({"SPY": [np.nan]})):
        result = build_factor_watch_df(prices)

        assert result.empty
        assert list(result.columns) == FACTOR_COLUMNS


def test_build_factor_watch_df_coerces_numeric_strings_and_drops_invalid_ratio_values():
    prices = pd.DataFrame(
        {
            "VTV": ["100", "102", "bad", "108"],
            "VUG": ["50", "0", "52", "54"],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03"]),
    )

    result = build_factor_watch_df(prices)

    assert list(result["Ratio"]) == ["VTV / VUG"]
    assert result.iloc[0]["Current"] == 2.0
    assert result.iloc[0]["Signal"] == "Neutral"


def test_build_factor_watch_df_contains_required_columns_and_rows():
    dates = pd.date_range("2020-01-01", periods=400, freq="D")
    prices = pd.DataFrame(index=dates)
    base = np.exp(np.linspace(0, 0.25, len(dates)))
    prices["SPY"] = 100 * base
    prices["QQQ"] = 110 * base
    prices["RSP"] = 102 * np.exp(np.linspace(0, 0.18, len(dates)))
    prices["VTV"] = 95 * np.exp(np.linspace(0, 0.12, len(dates)))
    prices["VUG"] = 105 * np.exp(np.linspace(0, 0.20, len(dates)))
    prices["VLUE"] = 97 * np.exp(np.linspace(0, 0.10, len(dates)))
    prices["MTUM"] = 108 * np.exp(np.linspace(0, 0.22, len(dates)))
    prices["QUAL"] = 103 * np.exp(np.linspace(0, 0.16, len(dates)))
    prices["USMV"] = 99 * np.exp(np.linspace(0, 0.09, len(dates)))
    prices["IWM"] = 96 * np.exp(np.linspace(0, 0.15, len(dates)))
    prices["SMH"] = 112 * np.exp(np.linspace(0, 0.25, len(dates)))
    prices["SOXX"] = 110 * np.exp(np.linspace(0, 0.24, len(dates)))
    prices["XLP"] = 101 * np.exp(np.linspace(0, 0.11, len(dates)))
    prices["XLV"] = 100 * np.exp(np.linspace(0, 0.12, len(dates)))
    prices["XLU"] = 98 * np.exp(np.linspace(0, 0.08, len(dates)))

    df = build_factor_metrics(prices)
    alias_df = build_factor_watch_df(prices)

    assert not df.empty
    assert len(alias_df) == len(df)
    assert list(df.columns) == [
        "Factor",
        "Ratio",
        "Current",
        "Percentile_1Y",
        "Percentile_3Y",
        "Percentile_5Y",
        "ZScore_3Y",
        "Trend_20D",
        "Trend_60D",
        "Signal",
        "Numerator Top Holdings",
        "Denominator Top Holdings",
    ]
    assert len(df) == 11
    assert df["Numerator Top Holdings"].notna().all()
    assert df["Denominator Top Holdings"].notna().all()
    assert df.loc[df["Factor"] == "Momentum", "Signal"].iloc[0] in {
        "Cheap",
        "Strong",
        "Overheated",
        "Neutral",
        "Defensive strengthening",
        "Momentum crowded",
    }


def test_generate_factor_summary_mentions_key_topics():
    df = pd.DataFrame(
        {
            "Factor": ["Value vs Growth", "Momentum", "Defensive", "Equal Weight/Breadth", "Semiconductor"],
            "Ratio": ["VTV / VUG", "MTUM / SPY", "USMV / SPY", "RSP / SPY", "SMH / SPY"],
            "Current": [1.10, 1.05, 1.02, 0.98, 1.20],
            "Percentile_1Y": [80.0, 85.0, 70.0, 20.0, 90.0],
            "Percentile_3Y": [75.0, 78.0, 68.0, 25.0, 88.0],
            "Percentile_5Y": [73.0, 80.0, 65.0, 30.0, 85.0],
            "ZScore_3Y": [1.2, 1.1, 0.7, -0.8, 1.6],
            "Trend_20D": [0.03, 0.04, 0.01, -0.02, 0.05],
            "Trend_60D": [0.05, 0.06, 0.02, -0.03, 0.06],
            "Signal": ["Strong", "Momentum crowded", "Neutral", "Cheap", "Overheated"],
        }
    )
    summary = generate_factor_summary(df, lang="zh")

    assert "风险偏好" in summary
    assert "动量" in summary
    assert "价值" in summary
    assert "防御" in summary
    assert "半导体" in summary
    assert "市场宽度" in summary


def test_generate_factor_summary_supports_english_and_spanish():
    df = pd.DataFrame(
        {
            "Factor": ["Value vs Growth", "Momentum", "Low Vol / Defensive", "Equal Weight / Breadth", "Semiconductor strength"],
            "Ratio": ["VTV / VUG", "MTUM / SPY", "USMV / SPY", "RSP / SPY", "SMH / SPY"],
            "Current": [1.10, 1.05, 1.02, 0.98, 1.20],
            "Percentile_1Y": [80.0, 90.0, 70.0, 20.0, 92.0],
            "Percentile_3Y": [75.0, 88.0, 68.0, 25.0, 90.0],
            "Percentile_5Y": [73.0, 86.0, 65.0, 30.0, 89.0],
            "ZScore_3Y": [1.2, 1.1, 0.7, -0.8, 1.7],
            "Trend_20D": [0.03, 0.04, 0.01, -0.02, 0.05],
            "Trend_60D": [0.05, 0.06, 0.02, -0.03, 0.06],
            "Signal": ["Strong", "Momentum crowded", "Neutral", "Cheap", "Overheated"],
        }
    )

    english = generate_factor_summary(df, lang="en")
    spanish = generate_factor_summary(df, lang="es")

    assert "Risk-on" in english
    assert "Momentum" in english
    assert "Semiconductor" in english
    assert "high-beta" in english
    assert "Risk-on" in spanish
    assert "Momentum" in spanish
    assert "semiconductores" in spanish.lower()
    assert "high beta" in spanish


def test_every_factor_ratio_has_explanation_in_all_languages():
    ratios = [definition[1] for definition in FACTOR_DEFINITIONS]

    assert len(ratios) == 11
    for ratio in ratios:
        for lang in ("zh", "en", "es"):
            explanation = get_factor_explanation(ratio, lang=lang)
            assert explanation
            assert len(explanation) > 20


def test_get_etf_top_holdings_returns_fallback_holdings_for_core_etfs():
    for etf in ("SPY", "SMH"):
        holdings = get_etf_top_holdings(etf, top_n=5)

        assert 0 < len(holdings) <= 5
        for holding in holdings:
            assert {"Ticker", "Name", "Weight"}.issubset(holding)
            assert holding["Ticker"]
            assert holding["Name"]
            assert isinstance(holding["Weight"], float | int)


def test_get_etf_top_holdings_unknown_etf_does_not_raise():
    holdings = get_etf_top_holdings("UNKNOWN_ETF_FOR_TESTS", top_n=5)

    assert isinstance(holdings, list)
    assert len(holdings) == 0
