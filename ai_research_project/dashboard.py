# -*- coding: utf-8 -*-

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
import os
import re
import plotly.graph_objects as go
from options import get_options_data as fetch_options_data
import plotly.express as px

from backtest import backtest_signals, save_signal
from openai import OpenAI
from financials import get_financial_data
from ai_analysis import analyze_financials
from analyst_db import (
    ANALYST_COLUMNS,
    get_analyst_records,
    get_target_stats,
    load_analyst_db,
    save_analyst_db,
)
from analyst_distribution import (
    build_aggregate_proxy_records,
    parse_broker_targets,
    summarize_distribution,
)
from data_layer import (
    get_analyst_data,
    get_macro_data,
    get_market_data,
    get_options_flow_data,
    get_technical_data,
    normalize_ticker,
)
from supply_chain_analyzer import (
    COMPANIES,
    DATA_SOURCE_DISCLAIMER,
    add_news_sentiment,
    analyze_with_openai,
    compute_metrics,
)

st.set_page_config(
    page_title="AI Financial Research",
    layout="wide"
)

st.write("NEW VERSION")

# -----------------------------
# SAFE OPENAI CLIENT
# -----------------------------
try:
    ai_client = OpenAI()
except Exception:
    ai_client = None

WATCHLIST = ["NVDA", "MU", "AMD", "INTC", "TSM", "WDC", "SNDK"]

MACRO_MARKET_INDICATORS = [
    {
        "label": "10Y Treasury",
        "symbols": ["^TNX"],
        "format": "yield_index",
        "source": "Yahoo Finance: ^TNX",
    },
    {
        "label": "DXY",
        "symbols": ["DX-Y.NYB", "DX=F"],
        "format": "number",
        "source": "Yahoo Finance: DX-Y.NYB",
    },
    {
        "label": "VIX",
        "symbols": ["^VIX"],
        "format": "number",
        "source": "Yahoo Finance: ^VIX",
    },
    {
        "label": "USD/CNY",
        "symbols": ["CNY=X"],
        "format": "fx",
        "source": "Yahoo Finance: CNY=X",
    },
    {
        "label": "USD/JPY",
        "symbols": ["JPY=X"],
        "format": "fx",
        "source": "Yahoo Finance: JPY=X",
    },
    {
        "label": "EUR/USD",
        "symbols": ["EURUSD=X"],
        "format": "fx",
        "source": "Yahoo Finance: EURUSD=X",
    },
]

MACRO_FRED_INDICATORS = [
    {
        "label": "Fed Funds Rate",
        "series_id": "FEDFUNDS",
        "format": "percent",
        "source": "FRED: FEDFUNDS",
    },
    {
        "label": "CPI",
        "series_id": "CPIAUCSL",
        "format": "cpi_yoy",
        "source": "FRED: CPIAUCSL",
    },
]

# -----------------------------
# CACHE
# -----------------------------
try:
    YFINANCE_CACHE_DIR = r"C:\Temp\yfinance_cache"
    os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
except Exception:
    pass


# -----------------------------
# HELPERS
# -----------------------------
def calculate_rsi(data, window=14):

    delta = data["Close"].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def black_scholes_gamma(S, K, T, r, sigma):

    if T <= 0 or sigma <= 0:
        return 0

    d1 = (
        np.log(S / K)
        + (r + 0.5 * sigma**2) * T
    ) / (sigma * np.sqrt(T))

    return (
        norm.pdf(d1)
        / (S * sigma * np.sqrt(T))
    )


def extract_moat_scores(analysis, company_names):

    scores = {}

    for company_name in company_names:

        escaped_name = re.escape(company_name)

        pattern = (
            rf"{escaped_name}.*?Moat Score:\*\*\s*"
            rf"(\d+(?:\.\d+)?)\s*/\s*10"
        )

        match = re.search(
            pattern,
            analysis,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            scores[company_name] = float(match.group(1))

    return scores


def format_macro_value(value, value_format):

    if value is None or pd.isna(value):
        return "N/A"

    if value_format == "yield_index":
        return f"{value / 10:.2f}%"

    if value_format in ("percent", "cpi_yoy"):
        return f"{value:.2f}%"

    if value_format == "fx":
        return f"{value:.4f}"

    return f"{value:.2f}"


def format_macro_delta(delta, value_format):

    if delta is None or pd.isna(delta):
        return None

    if value_format == "yield_index":
        return f"{delta * 10:+.0f} bp"

    if value_format in ("percent", "cpi_yoy"):
        return f"{delta * 100:+.0f} bp"

    if value_format == "fx":
        return f"{delta:+.4f}"

    return f"{delta:+.2f}"


@st.cache_data(ttl=1800)
def fetch_macro_market_indicator(symbols, value_format):

    for symbol in symbols:

        try:
            data = yf.Ticker(symbol).history(period="5d")

            if data.empty or "Close" not in data:
                continue

            closes = data["Close"].dropna()

            if closes.empty:
                continue

            value = float(closes.iloc[-1])
            previous = (
                float(closes.iloc[-2])
                if len(closes) > 1
                else None
            )

            return {
                "value": value,
                "delta": (
                    value - previous
                    if previous is not None
                    else None
                ),
                "symbol": symbol,
            }

        except Exception:
            continue

    return {
        "value": None,
        "delta": None,
        "symbol": symbols[0],
    }


@st.cache_data(ttl=21600)
def fetch_fred_series(series_id):

    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}"
    )

    data = pd.read_csv(url)
    data[series_id] = pd.to_numeric(
        data[series_id],
        errors="coerce",
    )
    return data.dropna(subset=[series_id])


def fetch_macro_fred_indicator(series_id, value_format):

    try:
        data = fetch_fred_series(series_id)

        if data.empty:
            return {
                "value": None,
                "delta": None,
            }

        values = data[series_id]

        if value_format == "cpi_yoy":
            if len(values) < 13:
                return {
                    "value": None,
                    "delta": None,
                }

            latest_yoy = (
                values.iloc[-1] / values.iloc[-13] - 1
            ) * 100
            previous_yoy = (
                values.iloc[-2] / values.iloc[-14] - 1
            ) * 100

            return {
                "value": float(latest_yoy),
                "delta": float(latest_yoy - previous_yoy),
            }

        latest = float(values.iloc[-1])
        previous = (
            float(values.iloc[-2])
            if len(values) > 1
            else None
        )

        return {
            "value": latest,
            "delta": (
                latest - previous
                if previous is not None
                else None
            ),
        }

    except Exception:
        return {
            "value": None,
            "delta": None,
        }


def load_macro_panel():
    return get_macro_data(
        MACRO_MARKET_INDICATORS,
        MACRO_FRED_INDICATORS,
        fetch_macro_market_indicator,
        fetch_macro_fred_indicator,
    )


def render_macro_panel():

    st.subheader("Macro Panel")

    macro_items = load_macro_panel()
    cols = st.columns(4)

    for index, item in enumerate(macro_items):
        value_format = item["format"]
        cols[index % 4].metric(
            item["label"],
            format_macro_value(
                item.get("value"),
                value_format,
            ),
            format_macro_delta(
                item.get("delta"),
                value_format,
            ),
            help=item["source"],
        )


def safe_float(value):

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_latest_price(ticker):

    try:
        last_price = safe_float(
            yf.Ticker(ticker).fast_info.get("last_price")
        )
        if last_price is not None:
            return last_price
    except Exception:
        pass

    try:
        data = yf.Ticker(ticker).history(period="5d")
        if data is not None and not data.empty:
            return safe_float(data["Close"].dropna().iloc[-1])
    except Exception:
        pass

    return None


def compute_analyst_weight(analyst):

    return (
        analyst.get("historical_accuracy", 1.0)
        * analyst.get("credibility", 1.0)
        * analyst.get("recency_factor", 1.0)
    )


def weighted_target_price(analysts):

    total_weight = 0
    weighted_sum = 0

    for analyst in analysts:
        target = safe_float(analyst.get("target"))
        if target is None:
            continue

        weight = compute_analyst_weight(analyst)
        weighted_sum += target * weight
        total_weight += weight

    if total_weight == 0:
        return None

    return weighted_sum / total_weight


def analyst_sentiment(recommendation, upside_pct):

    recommendation = str(recommendation or "").lower()

    if recommendation in ("buy", "strong_buy"):
        return "Bullish"

    if recommendation in ("sell", "strong_sell", "underperform"):
        return "Bearish"

    if upside_pct is None:
        return "Neutral"

    if upside_pct >= 10:
        return "Bullish"

    if upside_pct <= -10:
        return "Bearish"

    return "Neutral"


@st.cache_data(ttl=3600)
def fetch_analyst_consensus(ticker):
    return get_analyst_data(ticker)


def render_system_essence():

    with st.expander("一、你想实现的系统本质", expanded=False):
        st.markdown(
            """
你想要的是：**不同券商目标价 -> 加权平均目标价**。

权重来自：历史预测准确率、券商权威性、覆盖频率和更新时效。

最终输出：Consensus Target Price、Weighted Target Price、Analyst Sentiment、Top Analysts influence。

系统层级会从 `price + options + macro` 升级为：
`Market Price + Options Flow + Macro Regime + Analyst Consensus`。

最关键的派生指标是：
`Target Gap = (Weighted Target - Current Price) / Current Price`，
也就是上涨或下跌空间。
"""
        )


def format_price(value):

    if value is None or pd.isna(value):
        return "N/A"

    return f"${value:,.2f}"


def format_percent(value):

    if value is None or pd.isna(value):
        return "N/A"

    return f"{value:+.2f}%"


def render_target_distribution_panel(display_df):

    st.subheader("Analyst Target Distribution")

    analyst_db = load_analyst_db()

    with st.expander("Analyst Database", expanded=False):
        st.caption(
            "Persistent local database: analyst_targets.csv. "
            "Edit rows here, then save to update the distribution engine."
        )

        editable_db = st.data_editor(
            analyst_db,
            num_rows="dynamic",
            use_container_width=True,
            key="analyst_db_editor",
            column_config={
                "ticker": st.column_config.TextColumn("Ticker"),
                "firm": st.column_config.TextColumn("Firm"),
                "target": st.column_config.NumberColumn(
                    "Target",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                ),
                "rating": st.column_config.TextColumn("Rating"),
                "date": st.column_config.TextColumn("Date"),
                "tier": st.column_config.SelectboxColumn(
                    "Tier",
                    options=["tier1", "tier2", "tier3"],
                ),
            },
        )

        save_col, count_col = st.columns([1, 3])
        if save_col.button("Save Analyst DB", key="save_analyst_db"):
            saved_db = save_analyst_db(
                pd.DataFrame(editable_db, columns=ANALYST_COLUMNS)
            )
            st.success(f"Saved {len(saved_db)} analyst target rows.")
            st.cache_data.clear()
            st.rerun()

        count_col.metric("Database Rows", len(analyst_db))

    st.caption(
        "Paste broker-level targets to preserve high-conviction bull/bear cases. "
        "Temporary input below is included in the chart but is not saved."
    )

    manual_text = st.text_area(
        "Broker-level target input",
        value="",
        height=120,
        placeholder=(
            "MU, UBS, 1625, Buy, 2026-05-26, tier1\n"
            "MU, Morgan Stanley, 1200, Buy, 2026-05-26, tier1\n"
            "MU, Goldman Sachs, 1100, Buy, 2026-05-26, tier1"
        ),
        key="broker_target_input",
    )

    manual_records = parse_broker_targets(manual_text)

    selected_ticker = normalize_ticker(st.selectbox(
        "Distribution ticker",
        list(display_df["Ticker"]),
        key="distribution_ticker",
    ))

    selected_row = display_df[
        display_df["Ticker"] == selected_ticker
    ].iloc[0]

    aggregate_records = build_aggregate_proxy_records(
        selected_ticker,
        selected_row.get("Consensus Target Price"),
        selected_row.get("Median Target Price"),
        selected_row.get("Low Target Price"),
        selected_row.get("High Target Price"),
    )

    ticker_manual_records = [
        record
        for record in manual_records
        if normalize_ticker(record.ticker) == selected_ticker
    ]
    ticker_db_records = get_analyst_records(selected_ticker)

    distribution = summarize_distribution(
        aggregate_records + ticker_db_records + ticker_manual_records,
        selected_row.get("Market Price"),
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "Bear Target",
        format_price(distribution["bear_target"]),
        "weighted p10",
    )
    metric_cols[1].metric(
        "Base Target",
        format_price(distribution["base_target"]),
        "weighted median",
    )
    metric_cols[2].metric(
        "Bull Target",
        format_price(distribution["bull_target"]),
        "weighted p90",
    )
    metric_cols[3].metric(
        "High Target",
        format_price(distribution["high_target"]),
        f"{distribution['outlier_count']} outliers",
    )

    rows = distribution["rows"]
    if not rows:
        st.info("No target distribution data available.")
        return

    dist_df = pd.DataFrame(rows)

    fig = px.histogram(
        dist_df,
        x="Target",
        nbins=min(max(len(dist_df), 4), 12),
        color="Source",
        title=f"{selected_ticker} Target Price Distribution",
    )
    fig.add_vline(
        x=distribution["base_target"],
        line_dash="dash",
        line_color="white",
        annotation_text="Base",
    )
    fig.add_vline(
        x=distribution["bull_target"],
        line_dash="dot",
        line_color="green",
        annotation_text="Bull",
    )
    fig.update_layout(
        height=360,
        template="plotly_dark",
        xaxis_title="Target Price",
        yaxis_title="Count",
    )
    st.plotly_chart(fig, use_container_width=True)

    formatted_dist_df = dist_df.copy()
    formatted_dist_df["Target"] = formatted_dist_df["Target"].map(format_price)
    formatted_dist_df["Upside %"] = formatted_dist_df["Upside %"].map(format_percent)
    formatted_dist_df["Weight"] = formatted_dist_df["Weight"].map(
        lambda value: f"{value:.2f}"
    )

    st.dataframe(
        formatted_dist_df[[
            "Ticker",
            "Firm",
            "Target",
            "Upside %",
            "Rating",
            "Date",
            "Tier",
            "Weight",
            "Source",
            "Scenario Tag",
        ]],
        use_container_width=True,
    )


def render_analyst_consensus_panel():

    st.subheader("Analyst Consensus")

    selected = st.multiselect(
        "Analyst universe",
        WATCHLIST,
        default=WATCHLIST[:4],
        key="analyst_universe",
    )

    if not selected:
        st.info("Select at least one stock.")
        return

    rows = [
        fetch_analyst_consensus(normalize_ticker(ticker))
        for ticker in selected
    ]

    display_df = pd.DataFrame(rows)

    lead = display_df.iloc[0]
    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "Consensus Target Price",
        (
            f"${lead['Consensus Target Price']:.2f}"
            if pd.notna(lead["Consensus Target Price"])
            else "N/A"
        ),
        lead["Ticker"],
    )
    metric_cols[1].metric(
        "Weighted Target Price",
        (
            f"${lead['Weighted Target Price']:.2f}"
            if pd.notna(lead["Weighted Target Price"])
            else "N/A"
        ),
        "accuracy x credibility x recency",
    )
    metric_cols[2].metric(
        "Upside/Downside %",
        (
            f"{lead['Upside/Downside %']:+.2f}%"
            if pd.notna(lead["Upside/Downside %"])
            else "N/A"
        ),
        lead["Analyst Sentiment"],
    )

    formatted_df = display_df.copy()
    for column in [
        "Market Price",
        "Consensus Target Price",
        "Weighted Target Price",
    ]:
        formatted_df[column] = formatted_df[column].map(
            lambda value: (
                f"${value:.2f}"
                if pd.notna(value)
                else "N/A"
            )
        )

    for column in ["Upside/Downside %", "Divergence %"]:
        formatted_df[column] = formatted_df[column].map(
            lambda value: (
                f"{value:+.2f}%"
                if pd.notna(value)
                else "N/A"
            )
        )

    formatted_df["Analyst Count"] = formatted_df[
        "Analyst Count"
    ].map(
        lambda value: (
            str(int(value))
            if pd.notna(value)
            else "N/A"
        )
    )

    st.dataframe(
        formatted_df[[
            "Ticker",
            "Market Price",
            "Consensus Target Price",
            "Weighted Target Price",
            "Upside/Downside %",
            "Analyst Sentiment",
            "Analyst Count",
            "Divergence %",
            "Top Analysts influence",
        ]],
        use_container_width=True,
    )

    db_rows = []
    for row in rows:
        stats = get_target_stats(
            row["Ticker"],
            row.get("Market Price"),
        )
        if not stats:
            continue
        db_rows.append({
            "Ticker": row["Ticker"],
            "DB Consensus": stats["consensus"],
            "DB Weighted": stats["weighted"],
            "DB Bear": stats["bear_target"],
            "DB Base": stats["base_target"],
            "DB Bull": stats["bull_target"],
            "DB High": stats["max_target"],
            "DB Analysts": stats["count"],
            "Outliers": stats["outlier_count"],
        })

    if db_rows:
        st.subheader("Analyst Database Summary")
        db_summary = pd.DataFrame(db_rows)
        formatted_db_summary = db_summary.copy()
        for column in [
            "DB Consensus",
            "DB Weighted",
            "DB Bear",
            "DB Base",
            "DB Bull",
            "DB High",
        ]:
            formatted_db_summary[column] = formatted_db_summary[column].map(
                format_price
            )
        st.dataframe(
            formatted_db_summary,
            use_container_width=True,
        )

    render_target_distribution_panel(display_df)

    st.caption(
        "Current free implementation uses yfinance aggregate analyst targets. "
        "Broker-level historical accuracy and top analyst influence can be "
        "added when FMP, Refinitiv, Bloomberg, or FactSet data is available."
    )


# -----------------------------
# VALUE INVESTING
# -----------------------------
@st.cache_data(ttl=3600)
def run_value_investing_analysis():

    company_metrics = []

    for company in COMPANIES:

        try:
            company_metrics.append(
                compute_metrics(company)
            )

        except Exception as exc:

            company_metrics.append({
                "name": company.name,
                "segment": company.segment,
                "requested_symbol": company.symbol,
                "symbol_used": company.symbol,
                "aliases": company.aliases,
                "error": str(exc),
            })

    try:
        add_news_sentiment(company_metrics)
    except Exception:
        pass

    try:
        analysis = analyze_with_openai(company_metrics)
    except Exception:
        analysis = "AI analysis unavailable."

    return {
        "company_metrics": company_metrics,
        "analysis": analysis,
        "ai_analysis": analysis,
    }


def unpack_value_investing_result(result):

    if isinstance(result, dict):

        company_metrics = (
            result.get("company_metrics")
            or result.get("metrics")
            or []
        )

        analysis = (
            result.get("ai_analysis")
            or result.get("analysis")
            or ""
        )

        return company_metrics, analysis

    return [], ""


@st.cache_data(ttl=3600)
def load_options_data(ticker):
    return get_options_flow_data(ticker)


def build_oi_summary_fig(opt, ticker):
    fig = px.bar(
        x=["Call OI", "Put OI"],
        y=[opt["call_oi"], opt["put_oi"]],
        title=f"{ticker} Open Interest Comparison",
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Contract Side",
        yaxis_title="Open Interest",
        height=360,
    )
    return fig


def build_options_flow_structure_fig(opt, ticker):
    calls = opt["calls"].copy()
    puts = opt["puts"].copy()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=calls["strike"],
        y=calls["openInterest"].fillna(0),
        name="Call OI",
    ))
    fig.add_trace(go.Bar(
        x=puts["strike"],
        y=puts["openInterest"].fillna(0),
        name="Put OI",
    ))
    fig.update_layout(
        template="plotly_dark",
        title=f"{ticker} Options Flow Structure (V2+V3)",
        barmode="overlay",
        xaxis_title="Strike",
        yaxis_title="Open Interest",
        height=420,
    )
    return fig


def build_iv_curve_fig(opt, ticker):
    calls = opt["calls"].copy()
    puts = opt["puts"].copy()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=calls["strike"],
        y=calls["impliedVolatility"],
        mode="lines",
        name="Call IV",
    ))
    fig.add_trace(go.Scatter(
        x=puts["strike"],
        y=puts["impliedVolatility"],
        mode="lines",
        name="Put IV",
    ))
    fig.update_layout(
        template="plotly_dark",
        title=f"{ticker} Implied Volatility Curve",
        xaxis_title="Strike",
        yaxis_title="Implied Volatility",
        height=420,
    )
    return fig


def render_options_section(ticker, opt):
    if opt is None:
        st.warning("No options data available")
        return

    st.subheader(f"{ticker} Options Overview")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Call OI", f"{int(opt['call_oi']):,}")
    col2.metric("Put OI", f"{int(opt['put_oi']):,}")
    col3.metric("Put/Call Ratio", f"{opt['pc_ratio']:.2f}")
    col4.metric("Expiry", opt["expiry"])

    st.subheader("AI Market Signal")

    signal = opt["signal"]
    conf = opt["confidence"]

    if signal == "BULLISH":
        st.success(f"BULLISH ({conf:.2f})")
    elif signal == "BEARISH":
        st.error(f"BEARISH ({conf:.2f})")
    else:
        st.warning(f"NEUTRAL ({conf:.2f})")

    signal_col, pain_col = st.columns(2)
    signal_col.metric("Bias Score", f"{opt['bias_score']:.2f}")
    pain_col.metric("Max Pain", f"{opt['max_pain']:.2f}")

    try:
        signal_history = save_signal(ticker, signal, conf)
        latest_signal = signal_history[
            signal_history["ticker"] == ticker
        ].tail(1)
        if not latest_signal.empty:
            st.metric(
                "Signal Score",
                f"{float(latest_signal.iloc[0]['score']):.2f}",
            )
    except Exception as exc:
        st.warning(f"Signal tracking unavailable: {exc}")

    backtest_result = backtest_signals(ticker)
    if backtest_result:
        st.subheader("Strategy Performance")
        perf_col1, perf_col2, perf_col3 = st.columns(3)
        perf_col1.metric("Win Rate", f"{backtest_result['win_rate']:.2%}")
        perf_col2.metric("Completed Signals", backtest_result["total_signals"])
        perf_col3.metric("Pending Signals", backtest_result["pending_signals"])

        signals_df = backtest_result["signals"].tail(20)
        st.dataframe(
            signals_df,
            use_container_width=True,
        )

    overview_tab, oi_tab, iv_tab, chain_tab = st.tabs([
        "Overview",
        "OI Chart",
        "IV Chart",
        "Chain",
    ])

    with overview_tab:
        st.plotly_chart(
            build_oi_summary_fig(opt, ticker),
            use_container_width=True,
        )

    with oi_tab:
        st.subheader("Smart Money Level")
        st.metric("Max Pain", f"{opt['max_pain']:.2f}")

        st.plotly_chart(
            build_options_flow_structure_fig(opt, ticker),
            use_container_width=True,
        )

    with iv_tab:
        st.plotly_chart(
            build_iv_curve_fig(opt, ticker),
            use_container_width=True,
        )

    with chain_tab:
        calls_col, puts_col = st.columns(2)
        calls_col.subheader("Call Chain")
        calls_col.dataframe(opt["calls"].head(20), use_container_width=True)
        puts_col.subheader("Put Chain")
        puts_col.dataframe(opt["puts"].head(20), use_container_width=True)


st.title("AI Financial Research System")

tabs = st.tabs([
    "📊 Overview",
    "📈 Technical",
    "🎯 Options & GEX",
    "🤖 AI Analysis",
    "Value Investing",
])

# -----------------------------
# OVERVIEW
# -----------------------------
with tabs[0]:

    render_system_essence()

    st.subheader("Market Overview")

    cols = st.columns(len(WATCHLIST))

    for i, ticker in enumerate(WATCHLIST):

        market = get_market_data(ticker)
        price = market.get("price")
        change = market.get("change_pct")

        cols[i].metric(
            market["ticker"],
            f"${price:.2f}" if price is not None else "No Data",
            f"{change:+.2f}%" if change is not None else market["status"],
        )

    st.divider()
    render_analyst_consensus_panel()

    st.divider()
    render_macro_panel()

# -----------------------------
# TECHNICAL
# -----------------------------
with tabs[1]:

    st.subheader("Technical Analysis")

    ticker = normalize_ticker(st.selectbox(
        "Select Stock",
        WATCHLIST
    ))

    technical = get_technical_data(ticker)
    data = technical["history"]

    if data.empty:

        st.warning("Technical data unavailable.")

    else:

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data["Close"],
                name="Close",
                line=dict(
                    color="white",
                    width=3
                )
            )
        )

        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data["MA5"],
                name="MA5",
                line=dict(
                    color="yellow",
                    width=2
                )
            )
        )

        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data["MA20"],
                name="MA20",
                line=dict(
                    color="cyan",
                    width=2
                )
            )
        )

        fig.update_layout(
            height=500,
            template="plotly_dark",
            title=f"{ticker} Technical Chart",
            xaxis_title="Date",
            yaxis_title="Price",
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.subheader("Volume")

        volume_fig = go.Figure()

        volume_fig.add_trace(
            go.Bar(
                x=data.index,
                y=data["Volume"],
                name="Volume"
            )
        )

        volume_fig.update_layout(
            height=250,
            template="plotly_dark",
            title="Trading Volume"
        )

        st.plotly_chart(
            volume_fig,
            use_container_width=True
        )

        col1, col2 = st.columns(2)

        col1.metric(
            "Current Price",
            (
                f"${technical['current_price']:.2f}"
                if technical["current_price"] is not None
                else "No Data"
            )
        )

        col2.metric(
            "RSI",
            (
                f"{technical['rsi']:.1f}"
                if technical["rsi"] is not None
                else "No Data"
            )
        )

# -----------------------------
# OPTIONS
# -----------------------------
with tabs[2]:

    st.subheader("Options & Market Flow")

    ticker_opt = normalize_ticker(st.selectbox(
        "Select Stock",
        WATCHLIST,
        key="opt"
    ))

    with st.spinner("Loading options data..."):

        opt = load_options_data(ticker_opt)

    render_options_section(ticker_opt, opt)
# -----------------------------
# AI ANALYSIS
# -----------------------------
with tabs[3]:

    st.subheader("AI Financial Analysis")

    if st.button("Run AI Analysis"):

        try:

            with st.spinner(
                "Loading data..."
            ):

                fin_data = get_financial_data()

            for company, info in fin_data.items():

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    f"{company} Revenue",
                    f"${info['Revenue']/1e9:.1f}B"
                )

                col2.metric(
                    f"{company} Net Income",
                    f"${info['NetIncome']/1e9:.1f}B"
                )

                col3.metric(
                    f"{company} Margin",
                    f"{info['Margin']*100:.1f}%"
                )

            if ai_client is not None:

                with st.spinner(
                    "AI analyzing..."
                ):

                    analysis = analyze_financials(
                        fin_data
                    )

                st.write(analysis)

            else:

                st.warning(
                    "OpenAI client unavailable."
                )

        except Exception as e:

            st.warning(
                f"AI analysis unavailable: {e}"
            )

# -----------------------------
# VALUE INVESTING
# -----------------------------
with tabs[4]:

    st.subheader(
        "Value Investing Supply Chain Analysis"
    )

    if st.button(
        "Run Analysis",
        key="value_investing_run"
    ):

        try:

            with st.spinner(
                "Loading supply chain analysis..."
            ):

                result = (
                    run_value_investing_analysis()
                )

                company_metrics, analysis = (
                    unpack_value_investing_result(
                        result
                    )
                )

            valid_metrics = [
                item
                for item in company_metrics
                if not item.get("error")
            ]

            moat_scores = extract_moat_scores(
                analysis or "",
                [
                    item["name"]
                    for item in valid_metrics
                ]
            )

            if moat_scores:

                moat_df = pd.DataFrame([
                    {
                        "Company": name,
                        "Moat Score": score,
                    }
                    for name, score
                    in moat_scores.items()
                ])

                fig = px.bar(
                    moat_df,
                    x="Company",
                    y="Moat Score",
                    color="Moat Score",
                    color_continuous_scale="RdYlGn",
                    range_y=[0, 10],
                    title="AI-Inferred Moat Scores",
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True
                )

            st.subheader("AI Analysis")

            st.markdown(
                analysis or "No analysis."
            )

        except Exception as e:

            st.warning(
                f"Value investing analysis unavailable: {e}"
            )
