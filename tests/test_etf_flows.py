from io import StringIO

import pandas as pd
import pytest

from etf_flow_providers import fetch_fmp_etf_flow_if_available, fetch_massive_etf_flows
from etf_flows import (
    ETFFlowDataError,
    aggregate_flows,
    calculate_flow_aum_pct,
    calculate_rolling_flow,
    calculate_ytd_flow,
    filter_latest_available_flows,
    get_latest_available_flow_date,
    normalize_etf_flow_columns,
    parse_etf_flow_csv,
    parse_flow_value,
    summarize_latest_flows,
)


def test_parse_flow_value_units():
    assert parse_flow_value("$4.7B") == 4_700_000_000
    assert parse_flow_value("4700M") == 4_700_000_000
    assert parse_flow_value("-250M") == -250_000_000


def test_csv_column_auto_detection():
    csv = StringIO("processed_date,symbol,net_flows\n2026-06-15,SMH,$10M\n")
    df = parse_etf_flow_csv(csv)
    assert list(df[["date", "ticker", "flow"]].iloc[0]) == [pd.Timestamp("2026-06-15").date(), "SMH", 10_000_000]


def test_daily_to_weekly_aggregation():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-15", "2026-06-16", "2026-06-22"]),
            "ticker": ["SMH", "SMH", "SMH"],
            "flow": [1, 2, 3],
        }
    )
    weekly = aggregate_flows(df, "W")
    assert weekly["flow"].tolist() == [3, 3]


def test_monthly_aggregation():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-30", "2026-06-01", "2026-06-02"]),
            "ticker": ["SMH", "SMH", "SMH"],
            "flow": [1, 2, 3],
        }
    )
    monthly = aggregate_flows(df, "M")
    assert monthly["flow"].tolist() == [1, 5]


def test_ytd_flow_calculation():
    df = pd.DataFrame({"date": pd.to_datetime(["2025-12-31", "2026-01-02", "2026-06-01"]), "ticker": ["SMH"] * 3, "flow": [9, 1, 2]})
    ytd = calculate_ytd_flow(df, "2026-06-20")
    assert ytd.loc[0, "ytd_flow"] == 3


def test_rolling_4_week_flow():
    df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5, freq="W"), "ticker": ["SMH"] * 5, "flow": [1, 2, 3, 4, 5]})
    rolling = calculate_rolling_flow(df, 4)
    assert rolling[f"rolling_4_flow"].iloc[-1] == 14


def test_flow_aum_pct():
    flow = pd.DataFrame({"date": ["2026-06-15"], "ticker": ["SMH"], "flow": [10]})
    aum = pd.DataFrame({"ticker": ["SMH"], "aum": [100]})
    result = calculate_flow_aum_pct(flow, aum)
    assert result.loc[0, "flow_aum_pct"] == 10


def test_multi_etf_aggregate_flow():
    df = pd.DataFrame({"date": ["2026-06-15", "2026-06-15"], "ticker": ["SMH", "SOXX"], "flow": [10, -3]})
    summary = summarize_latest_flows(df)
    assert summary["latest_aggregate_flow"] == 7


def test_latest_available_date_selection():
    df = pd.DataFrame({"date": ["2026-06-13", "2026-06-17"], "ticker": ["SMH", "SMH"], "flow": [1, 2]})
    assert get_latest_available_flow_date(df) == pd.Timestamp("2026-06-17").date()


def test_weekend_or_holiday_falls_back_to_recent_available_date():
    df = pd.DataFrame({"date": ["2026-06-18"], "ticker": ["SMH"], "flow": [1]})
    latest = filter_latest_available_flows(df, lookback_days=10)
    assert latest["date"].iloc[0] == pd.Timestamp("2026-06-18").date()


def test_api_provider_empty_does_not_crash(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test")

    class Response:
        ok = True

        def json(self):
            return {"results": []}

    monkeypatch.setattr("etf_flow_providers.requests.get", lambda *args, **kwargs: Response())
    result = fetch_massive_etf_flows(["SMH"], "2026-06-01", "2026-06-10")
    assert result["flows"].empty
    assert "no ETF flow rows" in result["provider_status"]


def test_fmp_flow_endpoint_missing_falls_back(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.setattr("etf_flow_providers._fmp_get", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("404")))
    result = fetch_fmp_etf_flow_if_available(["SMH"], "2026-06-01", "2026-06-10")
    assert result["flows"].empty
    assert result["provider_status"] == "FMP ETF flow endpoint not available. Using fallback."


def test_massive_provider_mock_data_parsing(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test")

    class Response:
        ok = True

        def json(self):
            return {"results": [{"processed_date": "2026-06-10", "ticker": "SMH", "net_flow": "5M"}]}

    monkeypatch.setattr("etf_flow_providers.requests.get", lambda *args, **kwargs: Response())
    result = fetch_massive_etf_flows(["SMH"], "2026-06-01", "2026-06-10")
    assert result["latest_available_date"] == pd.Timestamp("2026-06-10").date()
    assert result["flows"]["flow"].iloc[0] == 5_000_000


def test_missing_fields_give_clear_error():
    with pytest.raises(ETFFlowDataError, match="Missing required ETF flow columns"):
        normalize_etf_flow_columns(pd.DataFrame({"date": ["2026-06-10"], "flow": [1]}))


def test_empty_csv_does_not_crash():
    df = parse_etf_flow_csv(StringIO(""))
    assert df.empty
