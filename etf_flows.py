from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd


SEMICONDUCTOR_ETFS = ["SMH", "SOXX", "SOXQ", "XSD", "PSI", "USD", "SOXL", "SOXS"]

DATE_COLUMNS = ("date", "flow_date", "as_of_date", "processed_date", "trade_date")
TICKER_COLUMNS = ("ticker", "symbol", "fund", "etf", "etf_ticker")
FLOW_COLUMNS = (
    "flow",
    "daily_flow",
    "net_flow",
    "net_flows",
    "fund_flow",
    "fund_flows",
    "flow_usd",
    "net_flow_usd",
    "creation_redemption",
)
AUM_COLUMNS = ("aum", "assets", "assets_under_management", "net_assets", "total_assets")


class ETFFlowDataError(ValueError):
    """Raised when an ETF flow CSV cannot be normalized into date/ticker/flow."""


def parse_flow_value(value, unit=None):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return np.nan
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()").replace(",", "").replace("$", "").replace("USD", "").strip()
        match = re.match(r"^([+-]?\d*\.?\d+)\s*([KMBT])?$", text, re.IGNORECASE)
        if not match:
            return np.nan
        number = float(match.group(1))
        suffix = (match.group(2) or "").upper()
        if suffix == "K":
            number *= 1_000
        elif suffix == "M":
            number *= 1_000_000
        elif suffix == "B":
            number *= 1_000_000_000
        elif suffix == "T":
            number *= 1_000_000_000_000
        if negative:
            number *= -1

    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit in {"thousand", "thousand usd", "k", "kusd"}:
        number *= 1_000
    elif normalized_unit in {"million", "million usd", "m", "musd"}:
        number *= 1_000_000
    elif normalized_unit in {"billion", "billion usd", "b", "busd"}:
        number *= 1_000_000_000
    return number


def _norm_col(column):
    return re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")


def _first_matching_column(columns: Iterable[str], candidates: Iterable[str]):
    normalized = {_norm_col(column): column for column in columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def normalize_etf_flow_columns(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "ticker", "flow"])

    date_col = _first_matching_column(df.columns, DATE_COLUMNS)
    ticker_col = _first_matching_column(df.columns, TICKER_COLUMNS)
    flow_col = _first_matching_column(df.columns, FLOW_COLUMNS)
    missing = []
    if not date_col:
        missing.append("date/processed_date")
    if not ticker_col:
        missing.append("ticker/symbol")
    if not flow_col:
        missing.append("flow/net_flow")
    if missing:
        preview = df.head(20).to_string(index=False)
        raise ETFFlowDataError(f"Missing required ETF flow columns: {', '.join(missing)}\nCSV preview:\n{preview}")

    normalized = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce").dt.date,
            "ticker": df[ticker_col].astype(str).str.upper().str.strip(),
            "flow": df[flow_col],
        }
    )
    unit_col = _first_matching_column(df.columns, ("unit", "flow_unit", "currency_unit"))
    if unit_col:
        normalized["flow"] = [parse_flow_value(value, unit) for value, unit in zip(normalized["flow"], df[unit_col])]
    else:
        normalized["flow"] = normalized["flow"].apply(parse_flow_value)

    for source_col in df.columns:
        normalized_name = _norm_col(source_col)
        if normalized_name in {"date", "ticker", "flow"}:
            continue
        if normalized_name in AUM_COLUMNS:
            normalized["aum"] = df[source_col].apply(parse_flow_value)
        elif normalized_name not in normalized.columns:
            normalized[normalized_name] = df[source_col].values
    return normalized.dropna(subset=["date", "ticker"]).reset_index(drop=True)


def parse_etf_flow_csv(file_or_buffer, unit=None):
    try:
        df = pd.read_csv(file_or_buffer)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=["date", "ticker", "flow"])
    normalized = normalize_etf_flow_columns(df)
    if unit and not normalized.empty:
        normalized["flow"] = normalized["flow"].apply(lambda value: parse_flow_value(value, unit))
    return normalized


def aggregate_flows(df, frequency="W"):
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "ticker", "flow"])
    frame = normalize_etf_flow_columns(df) if not {"date", "ticker", "flow"}.issubset(df.columns) else df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frequency = {"M": "ME", "Q": "QE", "Y": "YE"}.get(str(frequency).upper(), frequency)
    grouped = (
        frame.groupby([pd.Grouper(key="date", freq=frequency), "ticker"], dropna=False)["flow"]
        .sum()
        .reset_index()
    )
    grouped["date"] = grouped["date"].dt.date
    return grouped


def calculate_ytd_flow(df, as_of_date=None):
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "ytd_flow"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    as_of = pd.to_datetime(as_of_date or max(frame["date"])).date()
    start = date(as_of.year, 1, 1)
    ytd = frame[(frame["date"] >= start) & (frame["date"] <= as_of)]
    return ytd.groupby("ticker", as_index=False)["flow"].sum().rename(columns={"flow": "ytd_flow"})


def calculate_rolling_flow(df, window=4):
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "ticker", f"rolling_{window}_flow"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["ticker", "date"])
    column = f"rolling_{window}_flow"
    frame[column] = frame.groupby("ticker")["flow"].transform(lambda series: series.rolling(window, min_periods=1).sum())
    frame["date"] = frame["date"].dt.date
    return frame[["date", "ticker", column]]


def calculate_flow_aum_pct(flow_df, aum_df):
    if flow_df is None or flow_df.empty:
        return pd.DataFrame(columns=["date", "ticker", "flow", "aum", "flow_aum_pct"])
    flows = flow_df.copy()
    if aum_df is None or aum_df.empty:
        flows["aum"] = np.nan
    else:
        aum = aum_df.copy()
        if "ticker" not in aum.columns:
            raise ETFFlowDataError("AUM data must include ticker")
        aum_col = _first_matching_column(aum.columns, AUM_COLUMNS) or "aum"
        aum = aum[["ticker", aum_col]].rename(columns={aum_col: "aum"})
        aum["ticker"] = aum["ticker"].astype(str).str.upper()
        flows = flows.merge(aum, on="ticker", how="left")
    flows["flow_aum_pct"] = np.where(flows["aum"].astype(float) != 0, flows["flow"].astype(float) / flows["aum"].astype(float) * 100, np.nan)
    return flows


def calculate_flow_percentile(df, current_date=None):
    if df is None or df.empty:
        return np.nan
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    aggregate = frame.groupby("date")["flow"].sum().sort_index()
    current = pd.to_datetime(current_date).date() if current_date else aggregate.index.max()
    if current not in aggregate.index or len(aggregate) == 0:
        return np.nan
    return float((aggregate <= aggregate.loc[current]).mean() * 100)


def detect_record_inflow(df):
    if df is None or df.empty:
        return {"is_record_inflow": False, "is_near_record_inflow": False, "flow_percentile": np.nan}
    frame = df.copy()
    aggregate = frame.groupby("date")["flow"].sum()
    latest_date = max(aggregate.index)
    latest_flow = aggregate.loc[latest_date]
    percentile_95 = aggregate.quantile(0.95)
    return {
        "is_record_inflow": bool(latest_flow >= aggregate.max()),
        "is_near_record_inflow": bool(latest_flow >= percentile_95),
        "flow_percentile": calculate_flow_percentile(frame, latest_date),
    }


def filter_latest_available_flows(df, lookback_days=10):
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "ticker", "flow"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    latest = max(frame["date"])
    earliest = latest - timedelta(days=lookback_days)
    return frame[(frame["date"] >= earliest) & (frame["date"] <= latest)].copy()


def get_latest_available_flow_date(df):
    if df is None or df.empty or "date" not in df.columns:
        return None
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    return dates.max().date() if not dates.empty else None


def summarize_latest_flows(df, aum_df=None):
    if df is None or df.empty:
        return {
            "latest_available_date": None,
            "latest_aggregate_flow": 0.0,
            "top_inflow_etf": None,
            "top_outflow_etf": None,
            "flow_percentile": np.nan,
            "is_record_inflow": False,
            "is_near_record_inflow": False,
            "tickers_loaded": [],
            "tickers_missing": list(SEMICONDUCTOR_ETFS),
        }
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    latest_date = max(frame["date"])
    latest = frame[frame["date"] == latest_date].groupby("ticker", as_index=False)["flow"].sum()
    top_inflow = latest.sort_values("flow", ascending=False).iloc[0]
    top_outflow = latest.sort_values("flow", ascending=True).iloc[0]
    record = detect_record_inflow(frame)
    loaded = sorted(latest["ticker"].unique().tolist())
    missing = [ticker for ticker in SEMICONDUCTOR_ETFS if ticker not in loaded]
    ytd_total = float(calculate_ytd_flow(frame, latest_date)["ytd_flow"].sum())
    weekly_total = float(aggregate_flows(frame, "W")["flow"].tail(len(loaded) or 1).sum())
    monthly_total = float(aggregate_flows(frame, "M")["flow"].tail(len(loaded) or 1).sum())
    result = {
        "latest_available_date": latest_date,
        "latest_aggregate_flow": float(latest["flow"].sum()),
        "latest_week_aggregate_flow": weekly_total,
        "latest_month_aggregate_flow": monthly_total,
        "ytd_aggregate_flow": ytd_total,
        "top_inflow_etf": f"{top_inflow['ticker']} ({top_inflow['flow']:,.0f})",
        "top_outflow_etf": f"{top_outflow['ticker']} ({top_outflow['flow']:,.0f})",
        "tickers_loaded": loaded,
        "tickers_missing": missing,
        **record,
    }
    if aum_df is not None and not aum_df.empty:
        aum_col = _first_matching_column(aum_df.columns, AUM_COLUMNS) or "aum"
        result["aggregate_aum"] = float(pd.to_numeric(aum_df[aum_col], errors="coerce").sum())
    return result


def merge_flow_with_fmp_info(flow_df, fmp_info_df):
    if flow_df is None or flow_df.empty:
        return pd.DataFrame()
    if fmp_info_df is None or fmp_info_df.empty:
        return flow_df.copy()
    info = fmp_info_df.copy()
    info["ticker"] = info["ticker"].astype(str).str.upper()
    return flow_df.copy().merge(info, on="ticker", how="left")
