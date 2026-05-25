import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
from financials import get_financial_data
from ai_analysis import analyze_financials

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

tabs = st.tabs(["📊 Overview", "📈 Technical", "🎯 Options & GEX", "🤖 AI Analysis"])

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
    except Exception as e:
        st.warning("Technical data temporarily unavailable.")

with tabs[2]:
    st.subheader("Options & Gamma Exposure")
    ticker_opt = st.selectbox("Select Stock", WATCHLIST, key="opt")

    try:
        with st.spinner("Loading options data..."):
            opt = get_options_data(ticker_opt)

        col1, col2, col3 = st.columns(3)
        col1.metric("Current Price", f"${opt['current_price']:.2f}")
        col2.metric("Put/Call Ratio", f"{opt['pc_ratio']:.2f}",
                    "Bearish" if opt['pc_ratio'] > 1 else "Bullish")
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

    except Exception as e:
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
        except Exception as e:
            st.warning("AI analysis temporarily unavailable.")