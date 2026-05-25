# -*- coding: utf-8 -*-

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import json
import feedparser
import os
import re
import plotly.express as px
from openai import OpenAI

from financials import get_financial_data
from ai_analysis import analyze_financials
from supply_chain_analyzer import (
    COMPANIES,
    DATA_SOURCE_DISCLAIMER,
    add_news_sentiment,
    analyze_with_openai,
    compute_metrics,
    format_fx_rate,
    format_large_number,
)

# -----------------------------
# SAFE OPENAI CLIENT
# -----------------------------
try:
    ai_client = OpenAI()
except Exception:
    ai_client = None

WATCHLIST = ["NVDA", "MU", "SNDK"]

# -----------------------------
# YFINANCE CACHE
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


# -----------------------------
# OPTIONS DATA
# -----------------------------
@st.cache_data(ttl=3600)
def get_options_data(ticker):

    try:

        stock = yf.Ticker(ticker)

        hist = stock.history(period="1d")

        if hist.empty:
            return None

        current_price = hist["Close"].iloc[-1]

        expirations = stock.options

        if not expirations:
            return None

        exp_date = expirations[0]

        chain = stock.option_chain(exp_date)

        calls = chain.calls
        puts = chain.puts

        total_call_oi = calls["openInterest"].sum()
        total_put_oi = puts["openInterest"].sum()

        pc_ratio = (
            total_put_oi / total_call_oi
            if total_call_oi > 0
            else 0
        )

        return {
            "current_price": current_price,
            "pc_ratio": pc_ratio,
            "call_wall": None,
            "put_wall": None,
            "max_pain": current_price,
            "net_gex": 0,
            "calls_near_gex": 0,
        }

    except Exception:
        return None


# -----------------------------
# PAGE
# -----------------------------
st.set_page_config(
    page_title="AI Financial Research",
    layout="wide"
)

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

    st.subheader("Market Overview")

    cols = st.columns(len(WATCHLIST))

    for i, ticker in enumerate(WATCHLIST):

        try:

            data = yf.Ticker(ticker).history(period="2d")

            if data.empty or len(data) < 2:

                cols[i].metric(
                    ticker,
                    "N/A",
                    "No Data"
                )

                continue

            price = data["Close"].iloc[-1]
            prev = data["Close"].iloc[-2]

            change = (
                (price - prev) / prev * 100
            )

            cols[i].metric(
                ticker,
                f"${price:.2f}",
                f"{change:+.2f}%"
            )

        except Exception:

            cols[i].metric(
                ticker,
                "N/A",
                "Rate Limited"
            )

# -----------------------------
# TECHNICAL
# -----------------------------
with tabs[1]:

    st.subheader("Technical Analysis")

    ticker = st.selectbox(
        "Select Stock",
        WATCHLIST
    )

    try:

        data = yf.Ticker(ticker).history(
            period="6mo"
        )

        if data.empty:

            st.warning(
                "Technical data unavailable."
            )

        else:

            data["MA20"] = (
                data["Close"]
                .rolling(20)
                .mean()
            )

            data["RSI"] = calculate_rsi(data)

            st.line_chart(
                data[["Close", "MA20"]]
            )

            col1, col2 = st.columns(2)

            col1.metric(
                "Current Price",
                f"${data['Close'].iloc[-1]:.2f}"
            )

            col2.metric(
                "RSI",
                f"{data['RSI'].iloc[-1]:.1f}"
            )

    except Exception:

        st.warning(
            "Technical analysis unavailable."
        )

# -----------------------------
# OPTIONS
# -----------------------------
with tabs[2]:

    st.subheader("Options & Gamma Exposure")

    ticker_opt = st.selectbox(
        "Select Stock",
        WATCHLIST,
        key="opt"
    )

    with st.spinner(
        "Loading options data..."
    ):

        opt = get_options_data(ticker_opt)

    if opt is None:

        st.warning(
            "Yahoo Finance rate limited."
        )

    else:

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Current Price",
            f"${opt['current_price']:.2f}"
        )

        col2.metric(
            "Put/Call Ratio",
            f"{opt['pc_ratio']:.2f}"
        )

        col3.metric(
            "Max Pain",
            f"${opt['max_pain']:.2f}"
        )

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

            table_rows = []

            for item in company_metrics:

                table_rows.append({
                    "Company": item.get("name"),
                    "Segment": item.get("segment"),
                    "Symbol": item.get(
                        "symbol_used",
                        item.get("requested_symbol"),
                    ),
                    "Error": item.get("error", ""),
                })

            st.dataframe(
                pd.DataFrame(table_rows),
                use_container_width=True,
            )

            st.caption(
                DATA_SOURCE_DISCLAIMER
            )

            st.subheader("AI Analysis")

            st.markdown(
                analysis or "No analysis."
            )

        except Exception as e:

            st.warning(
                f"Value investing analysis unavailable: {e}"
            )
