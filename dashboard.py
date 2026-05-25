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
from config import OPENAI_API_KEY
from supply_chain_analyzer import (
    COMPANIES,
    DATA_SOURCE_DISCLAIMER,
    add_news_sentiment,
    analyze_with_openai,
    compute_metrics,
    format_fx_rate,
    format_large_number,
)

YFINANCE_CACHE_DIR = r"C:\Temp\yfinance_cache"
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
yf.cache.set_cache_location(YFINANCE_CACHE_DIR)

ai_client = OpenAI(api_key=OPENAI_API_KEY)

EARNINGS_DATES = {
    "NVDA": "2026-08-26",
    "MU": "2026-07-01",
    "SNDK": "2026-08-13",
}

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
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

def extract_moat_scores(analysis, company_names):
    scores = {}
    for company_name in company_names:
        escaped_name = re.escape(company_name)
        pattern = rf"{escaped_name}.*?Moat Score:\*\*\s*(\d+(?:\.\d+)?)\s*/\s*10"
        match = re.search(pattern, analysis, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            pattern = rf"{escaped_name}.*?Moat Score:?\s*(\d+(?:\.\d+)?)\s*/\s*10"
            match = re.search(pattern, analysis, flags=re.IGNORECASE | re.DOTALL)
        if match:
            scores[company_name] = float(match.group(1))
    return scores

@st.cache_data(ttl=3600)
def run_value_investing_analysis():
    company_metrics = []
    for company in COMPANIES:
        try:
            company_metrics.append(compute_metrics(company))
        except Exception as exc:
            company_metrics.append({
                "name": company.name,
                "segment": company.segment,
                "requested_symbol": company.symbol,
                "symbol_used": company.symbol,
                "aliases": company.aliases,
                "error": str(exc),
            })
    add_news_sentiment(company_metrics)
    analysis = analyze_with_openai(company_metrics)
    return {
        "company_metrics": company_metrics,
        "analysis": analysis,
        "ai_analysis": analysis,
    }

def unpack_value_investing_result(result):
    if isinstance(result, tuple) and len(result) == 2:
        return result

    if isinstance(result, dict):
        company_metrics = result.get("company_metrics") or result.get("metrics") or []
        analysis = result.get("ai_analysis") or result.get("analysis") or ""
        return company_metrics, analysis

    raise ValueError("Unexpected value investing analysis result format.")

@st.cache_data(ttl=3600)
def get_options_data(ticker):
    stock = yf.Ticker(ticker)
    current_price = stock.history(period="1d")["Close"].iloc[-1]
    expirations = stock.options
    exp_date = expirations[0]
    chain = stock.option_chain(exp_date)
    calls = chain.calls
    puts = chain.puts
    total_call_oi = calls["openInterest"].sum()
    total_put_oi = puts["openInterest"].sum()
    pc_ratio = total_put_oi / total_call_oi
    calls_above = calls[calls["strike"] > current_price]
    puts_below = puts[puts["strike"] < current_price]
    call_wall = calls_above.loc[calls_above["openInterest"].idxmax(), "strike"] if len(calls_above) > 0 else None
    put_wall = puts_below.loc[puts_below["openInterest"].idxmax(), "strike"] if len(puts_below) > 0 else None
    strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
    pain = {}
    for strike in strikes:
        call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
        put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
        pain[strike] = call_loss + put_loss
    max_pain = min(pain, key=pain.get)
    total_gex = {}
    for exp in expirations[:2]:
        chain2 = stock.option_chain(exp)
        exp_dt = datetime.strptime(exp, "%Y-%m-%d")
        T = max((exp_dt - datetime.now()).days / 365, 0.001)
        for _, row in chain2.calls.iterrows():
            K, sigma, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
            if sigma > 0 and oi > 0:
                g = black_scholes_gamma(current_price, K, T, 0.05, sigma)
                total_gex[K] = total_gex.get(K, 0) + g * oi * 100 * current_price
        for _, row in chain2.puts.iterrows():
            K, sigma, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
            if sigma > 0 and oi > 0:
                g = black_scholes_gamma(current_price, K, T, 0.05, sigma)
                total_gex[K] = total_gex.get(K, 0) - g * oi * 100 * current_price
    net_gex = sum(total_gex.values())
    calls_near_gex = sum(v for k, v in total_gex.items() if v > 0 and current_price < k < current_price * 1.1)
    return {
        "current_price": current_price,
        "exp_date": exp_date,
        "pc_ratio": pc_ratio,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "max_pain": max_pain,
        "net_gex": net_gex,
        "calls_near_gex": calls_near_gex,
    }

st.set_page_config(page_title="AI Financial Research", layout="wide")
st.title("AI Financial Research System")

WATCHLIST = ["NVDA", "MU", "SNDK"]

tabs = st.tabs(["📊 Overview", "📈 Technical", "🎯 Options & GEX", "🤖 AI Analysis", "Value Investing", "📰 Daily Report", "🧠 Multi-Agent"])

with tabs[0]:
    st.subheader("Market Overview")
    cols = st.columns(len(WATCHLIST))
    for i, ticker in enumerate(WATCHLIST):
        try:
            data = yf.Ticker(ticker).history(period="2d")
            price = data["Close"].iloc[-1]
            prev = data["Close"].iloc[-2]
            change = (price - prev) / prev * 100
            cols[i].metric(ticker, f"${price:.2f}", f"{change:+.2f}%")
        except:
            cols[i].metric(ticker, "N/A", "Error")

with tabs[1]:
    st.subheader("Technical Analysis")
    ticker = st.selectbox("Select Stock", WATCHLIST)
    period = st.selectbox("Period", ["3mo", "6mo", "1y", "2y"])
    try:
        data = yf.Ticker(ticker).history(period=period)
        data["MA5"] = data["Close"].rolling(5).mean()
        data["MA20"] = data["Close"].rolling(20).mean()
        data["RSI"] = calculate_rsi(data)
        st.line_chart(data[["Close", "MA5", "MA20"]])
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", f"${data['Close'].iloc[-1]:.2f}")
        col2.metric("RSI", f"{data['RSI'].iloc[-1]:.1f}")
        rsi_val = data['RSI'].iloc[-1]
        if rsi_val > 70:
            col3.metric("RSI Signal", "⚠️ Overbought")
        elif rsi_val < 30:
            col3.metric("RSI Signal", "⚠️ Oversold")
        else:
            col3.metric("RSI Signal", "✅ Normal")
        st.subheader("Volume Analysis")
        data["Vol_MA20"] = data["Volume"].rolling(20).mean()
        data["Vol_Ratio"] = data["Volume"] / data["Vol_MA20"]
        st.bar_chart(data["Volume"].tail(30))
        st.metric("Volume Ratio (vs 20d avg)", f"{data['Vol_Ratio'].iloc[-1]:.2f}x")
        # Options Chain Chart
        st.subheader("Options Chain Visualization")
        with st.spinner("Loading options chain..."):
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots

                stock_opt = yf.Ticker(ticker)
                current_price_opt = stock_opt.history(period="1d")["Close"].iloc[-1]
                exp_date_opt = stock_opt.options[0]
                chain_opt = stock_opt.option_chain(exp_date_opt)
                calls_opt = chain_opt.calls
                puts_opt = chain_opt.puts

                price_range = 0.2
                calls_f = calls_opt[
                    (calls_opt["strike"] >= current_price_opt * (1 - price_range)) &
                    (calls_opt["strike"] <= current_price_opt * (1 + price_range))
                ]
                puts_f = puts_opt[
                    (puts_opt["strike"] >= current_price_opt * (1 - price_range)) &
                    (puts_opt["strike"] <= current_price_opt * (1 + price_range))
                ]

                fig = make_subplots(
                    rows=1, cols=2,
                    subplot_titles=["Open Interest by Strike", "IV Skew"]
                )

                fig.add_trace(go.Bar(
                    x=calls_f["strike"], y=calls_f["openInterest"],
                    name="Call OI", marker_color="green", opacity=0.7
                ), row=1, col=1)

                fig.add_trace(go.Bar(
                    x=puts_f["strike"], y=puts_f["openInterest"],
                    name="Put OI", marker_color="red", opacity=0.7
                ), row=1, col=1)

                fig.add_trace(go.Scatter(
                    x=calls_f["strike"], y=calls_f["impliedVolatility"] * 100,
                    name="Call IV", line=dict(color="lightgreen", width=2)
                ), row=1, col=2)

                fig.add_trace(go.Scatter(
                    x=puts_f["strike"], y=puts_f["impliedVolatility"] * 100,
                    name="Put IV", line=dict(color="salmon", width=2)
                ), row=1, col=2)

                fig.add_vline(x=current_price_opt, line_dash="dash",
                             line_color="yellow",
                             annotation_text=f"${current_price_opt:.2f}")

                fig.update_layout(
                    template="plotly_dark",
                    height=400,
                    barmode="overlay",
                    title=f"{ticker} Options Chain - Expiry: {exp_date_opt}"
                )

                st.plotly_chart(fig, use_container_width=True)

                col1, col2, col3 = st.columns(3)
                total_call_oi = calls_opt["openInterest"].sum()
                total_put_oi = puts_opt["openInterest"].sum()
                col1.metric("Total Call OI", f"{total_call_oi:,}")
                col2.metric("Total Put OI", f"{total_put_oi:,}")
                col3.metric("P/C Ratio", f"{total_put_oi/total_call_oi:.2f}")

            except Exception as e:
                st.warning("Options chain temporarily unavailable.")
    except:
        st.warning("Technical data temporarily unavailable.")

with tabs[2]:
    st.subheader("Options & Gamma Exposure")
    ticker_opt = st.selectbox("Select Stock", WATCHLIST, key="opt")
    try:
        with st.spinner("Loading options data..."):
            opt = get_options_data(ticker_opt)
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", f"${opt['current_price']:.2f}")
        col2.metric("Put/Call Ratio", f"{opt['pc_ratio']:.2f}", "Bearish" if opt['pc_ratio'] > 1 else "Bullish")
        col3.metric("Max Pain", f"${opt['max_pain']:.0f}")
        col4, col5, col6 = st.columns(3)
        col4.metric("Call Wall (Resistance)", f"${opt['call_wall']:.0f}" if opt['call_wall'] else "N/A")
        col5.metric("Put Wall (Support)", f"${opt['put_wall']:.0f}" if opt['put_wall'] else "N/A")
        col6.metric("Net GEX", f"${opt['net_gex']:,.0f}")
        st.subheader("Gamma Squeeze Risk")
        if opt['calls_near_gex'] > 1000000:
            st.error("🔥 HIGH - Strong Gamma Squeeze Potential!")
        elif opt['calls_near_gex'] > 500000:
            st.warning("⚠️ MEDIUM - Some Squeeze Potential")
        else:
            st.success("✅ LOW - Limited Squeeze Potential")
        if opt['net_gex'] < 0:
            st.info("→ Negative GEX: Market maker will BUY into rallies (amplifies moves)")
        else:
            st.info("→ Positive GEX: Market maker will SELL into rallies (dampens moves)")
    except:
        st.warning("Options data temporarily unavailable. Please try again later.")

with tabs[3]:
    st.subheader("AI Financial Analysis")
    if st.button("Run AI Analysis"):
        try:
            with st.spinner("Fetching financial data..."):
                fin_data = get_financial_data()
            st.success("Data loaded!")
            for company, info in fin_data.items():
                col1, col2, col3 = st.columns(3)
                col1.metric(f"{company} Revenue", f"${info['Revenue']/1e9:.1f}B")
                col2.metric(f"{company} Net Income", f"${info['NetIncome']/1e9:.1f}B")
                col3.metric(f"{company} Net Margin", f"{info['Margin']*100:.1f}%")
            with st.spinner("AI analyzing..."):
                analysis = analyze_financials(fin_data)
            st.write(analysis)
        except:
            st.warning("AI analysis temporarily unavailable.")

with tabs[4]:
    st.subheader("Value Investing Supply Chain Analysis")

    if st.button("Run Analysis", key="value_investing_run"):
        try:
            with st.spinner("Loading supply chain metrics and AI value analysis..."):
                result = run_value_investing_analysis()
                company_metrics, analysis = unpack_value_investing_result(result)

            valid_metrics = [item for item in company_metrics if not item.get("error")]
            moat_scores = extract_moat_scores(analysis or "", [item["name"] for item in valid_metrics])

            if moat_scores:
                moat_df = pd.DataFrame(
                    [{"Company": name, "Moat Score": score} for name, score in moat_scores.items()]
                )
                fig = px.bar(
                    moat_df,
                    x="Company",
                    y="Moat Score",
                    color="Moat Score",
                    color_continuous_scale="RdYlGn",
                    range_y=[0, 10],
                    title="AI-Inferred Moat Scores",
                )
                fig.update_layout(template="plotly_dark", height=420)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Moat scores could not be parsed from the AI analysis text.")

            table_rows = []
            for item in company_metrics:
                if item.get("error"):
                    table_rows.append({
                        "Company": item["name"],
                        "Segment": item["segment"],
                        "Symbol": item["symbol_used"],
                        "Fiscal Date": "N/A",
                        "Revenue Growth YoY": "N/A",
                        "Free Cash Flow": "N/A",
                        "Debt/Equity": "N/A",
                        "Error": item["error"],
                    })
                    continue

                fcf = item.get("free_cash_flow")
                fcf_text = "N/A" if fcf is None else f"USD {fcf / 1e9:,.2f}B"
                source_currency = item.get("free_cash_flow_source_currency")
                if source_currency and source_currency != item.get("free_cash_flow_currency"):
                    fx_rate = format_fx_rate(item.get("free_cash_flow_fx_rate_to_usd"))
                    fcf_text += f" ({source_currency} source, FX {fx_rate})"

                table_rows.append({
                    "Company": item["name"],
                    "Segment": item["segment"],
                    "Symbol": item["symbol_used"],
                    "Fiscal Date": item.get("fiscal_date") or "N/A",
                    "Revenue Growth YoY": "N/A" if item.get("revenue_growth_yoy_pct") is None else f"{item['revenue_growth_yoy_pct']:.2f}%",
                    "Free Cash Flow": fcf_text,
                    "Debt/Equity": "N/A" if item.get("debt_to_equity") is None else f"{item['debt_to_equity']:.2f}",
                    "Error": "",
                })

            st.subheader("Key Metrics")
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            quarterly_rows = []
            analyst_rows = []
            sentiment_rows = []
            for item in company_metrics:
                if item.get("error"):
                    continue

                for quarter in item.get("quarterly_financials_trend", []):
                    quarterly_rows.append({
                        "Company": item["name"],
                        "Symbol": item["symbol_used"],
                        "Quarter": quarter.get("date") or "N/A",
                        "Revenue": format_large_number(quarter.get("revenue"), item.get("financial_currency") or ""),
                        "Gross Margin": "N/A" if quarter.get("gross_margin_pct") is None else f"{quarter['gross_margin_pct']:.2f}%",
                    })

                targets = item.get("analyst_targets") or {}
                analyst_rows.append({
                    "Company": item["name"],
                    "Symbol": item["symbol_used"],
                    "Current Price": "N/A" if targets.get("current_price") is None else f"{targets['current_price']:,.2f}",
                    "Target Price": "N/A" if targets.get("target_price") is None else f"{targets['target_price']:,.2f}",
                    "Upside": "N/A" if targets.get("upside_pct") is None else f"{targets['upside_pct']:.2f}%",
                    "Recommendation": targets.get("recommendation") or "N/A",
                    "Recommendation Mean": "N/A" if targets.get("recommendation_mean") is None else f"{targets['recommendation_mean']:.2f}",
                })

                headlines = item.get("news_headlines") or []
                sentiment_rows.append({
                    "Company": item["name"],
                    "Symbol": item["symbol_used"],
                    "Sentiment Summary": item.get("news_sentiment_summary") or "N/A",
                    "Recent Headlines": "\n".join(headline.get("title", "") for headline in headlines[:3]) or "N/A",
                })

            st.subheader("Quarterly Financials")
            if quarterly_rows:
                st.dataframe(pd.DataFrame(quarterly_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Quarterly financials were not available from yfinance.")

            st.subheader("Analyst Targets")
            st.dataframe(pd.DataFrame(analyst_rows), use_container_width=True, hide_index=True)

            st.subheader("News Sentiment")
            st.dataframe(pd.DataFrame(sentiment_rows), use_container_width=True, hide_index=True)

            st.caption(DATA_SOURCE_DISCLAIMER)
            st.subheader("AI Analysis")
            st.markdown(analysis or "No analysis returned.")
        except Exception as e:
            st.warning(f"Value investing analysis temporarily unavailable: {e}")

with tabs[5]:
    st.subheader("Daily Research Report")
    if st.button("Generate Daily Report"):

        # Market Overview
        st.subheader("📊 Market Overview")
        cols = st.columns(3)
        for i, ticker in enumerate(WATCHLIST):
            try:
                data = yf.Ticker(ticker).history(period="2d")
                price = data["Close"].iloc[-1]
                change = (data["Close"].iloc[-1] - data["Close"].iloc[-2]) / data["Close"].iloc[-2] * 100
                cols[i].metric(ticker, f"${price:.2f}", f"{change:+.1f}%")
            except:
                cols[i].metric(ticker, "N/A", "")

        # Earnings Calendar
        st.subheader("📅 Earnings Calendar")
        for ticker, date in EARNINGS_DATES.items():
            days = (datetime.strptime(date, "%Y-%m-%d") - datetime.now()).days
            if days < 7:
                st.error(f"⚠️ {ticker}: Earnings in {days} days - {date}")
            elif days < 30:
                st.warning(f"📅 {ticker}: Earnings in {days} days - {date}")
            else:
                st.info(f"{ticker}: Earnings in {days} days - {date}")

        # News Sentiment
        st.subheader("📰 News Sentiment")
        with st.spinner("Analyzing news..."):
            for ticker in WATCHLIST:
                try:
                    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
                    headlines = [e.title for e in feed.entries[:5]]
                    if headlines:
                        prompt = f"Analyze sentiment of these {ticker} headlines: {headlines}. Reply with JSON only: {{\"sentiment\": \"BULLISH/BEARISH/NEUTRAL\", \"score\": 0, \"summary\": \"one line\"}}"
                        response = ai_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            response_format={"type": "json_object"}
                        )
                        result = json.loads(response.choices[0].message.content)
                        score = result.get("score", 0)
                        emoji = "🟢" if score >= 3 else "🔴" if score <= -3 else "🟡"
                        st.write(f"{emoji} **{ticker}**: {result.get('sentiment')} ({score}/10) — {result.get('summary')}")
                except Exception as e:
                    st.write(f"⚪ {ticker}: News unavailable")

        # AI Summary
        st.subheader("🤖 AI Summary")
        with st.spinner("AI generating summary..."):
            try:
                response = ai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "Give a brief 3-point investment summary for NVDA, MU, SNDK based on current AI memory chip market trends. Be concise and professional."}]
                )
                st.write(response.choices[0].message.content)
            except:
                st.warning("AI summary unavailable.")

        st.success("✅ Report generated!")

with tabs[6]:
    st.subheader("Multi-Agent AI Research Team")
    st.caption("5 specialized AI agents analyze each stock simultaneously")

    ticker_ma = st.selectbox("Select Stock", WATCHLIST, key="ma")

    if st.button("Run Multi-Agent Analysis"):
        from multi_agent import agent_technical, agent_fundamental, agent_options, agent_news, agent_risk_manager

        with st.spinner("Agent 1: Technical Analysis..."):
            technical = agent_technical(ticker_ma)

        with st.spinner("Agent 2: Fundamental Analysis..."):
            fundamental = agent_fundamental(ticker_ma)

        with st.spinner("Agent 3: Options Analysis..."):
            options_analysis = agent_options(ticker_ma)

        with st.spinner("Agent 4: News Sentiment..."):
            news_analysis = agent_news(ticker_ma)

        with st.spinner("Agent 5: Risk Manager synthesizing..."):
            verdict = agent_risk_manager(ticker_ma, technical, fundamental, options_analysis, news_analysis)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🔍 Technical Analysis")
            st.write(technical)
            st.subheader("🎯 Options Analysis")
            st.write(options_analysis)

        with col2:
            st.subheader("📊 Fundamental Analysis")
            st.write(fundamental)
            st.subheader("📰 News Sentiment")
            st.write(news_analysis)

        st.divider()
        st.subheader("⚖️ Final Verdict")
        st.info(verdict)
