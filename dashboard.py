# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta
import json
import os

import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm
import streamlit as st
import yfinance as yf

from config import CACHE_DIR, get_openai_client
from financials import fetch_company_news, fetch_historical_prices, get_company_snapshot as get_fmp_company_snapshot
from macro_data import build_macro_snapshot, fetch_indicator, fetch_macro_calendar, fetch_market_series, fetch_treasury_rates


YFINANCE_CACHE_DIR = CACHE_DIR / "yfinance"
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
yf.cache.set_cache_location(YFINANCE_CACHE_DIR)

WATCHLIST = ["NVDA", "MU", "SNDK", "LITE", "RKLB"]
COMPANY_NAMES = {
    "NVDA": "NVIDIA",
    "MU": "Micron",
    "SNDK": "SanDisk",
    "LITE": "Lumentum",
    "RKLB": "Rocket Lab",
}
SUPPLY_CHAIN_ROLES = {
    "NVDA": "AI accelerators and compute platform",
    "MU": "HBM and memory",
    "SNDK": "Flash storage",
    "LITE": "Optical networking components",
    "RKLB": "Space systems and launch services",
}
EARNINGS_DATES = {
    "NVDA": "2026-08-26",
    "MU": "2026-07-01",
    "SNDK": "2026-08-13",
}


def format_money(value, decimals=1):
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= divisor:
            return f"${value / divisor:,.{decimals}f}{suffix}"
    return f"${value:,.{decimals}f}"


def format_ratio(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):,.2f}"


def format_percent(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value) * 100:,.1f}%"


def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def black_scholes_gamma(spot, strike, time_to_expiry, rate, volatility):
    if time_to_expiry <= 0 or volatility <= 0:
        return 0
    d1 = (
        np.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry
    ) / (volatility * np.sqrt(time_to_expiry))
    return norm.pdf(d1) / (spot * volatility * np.sqrt(time_to_expiry))


@st.cache_data(ttl=900)
def get_company_snapshot(ticker):
    return {**get_fmp_company_snapshot(ticker), "role": SUPPLY_CHAIN_ROLES[ticker]}


@st.cache_data(ttl=900)
def get_technical_data(ticker, period="6mo"):
    days = {"3mo": 100, "6mo": 190, "1y": 370, "2y": 740}.get(period, 190)
    data, source = fetch_historical_prices(ticker, date.today() - timedelta(days=days), date.today())
    if data.empty:
        raise ValueError("No technical data returned.")
    data = data.copy()
    data["MA5"] = data["Close"].rolling(5).mean()
    data["MA20"] = data["Close"].rolling(20).mean()
    data["RSI"] = calculate_rsi(data)
    data["Vol_MA20"] = data["Volume"].rolling(20).mean()
    data["Vol_Ratio"] = data["Volume"] / data["Vol_MA20"]
    data.attrs["source"] = source
    return data


@st.cache_data(ttl=900)
def get_options_data(ticker):
    stock = yf.Ticker(ticker)
    history = stock.history(period="1d")
    expirations = stock.options
    if history.empty or not expirations:
        raise ValueError("No options data returned.")
    current_price = float(history["Close"].iloc[-1])
    exp_date = expirations[0]
    chain = stock.option_chain(exp_date)
    calls = chain.calls.fillna(0)
    puts = chain.puts.fillna(0)
    total_call_oi = float(calls["openInterest"].sum())
    total_put_oi = float(puts["openInterest"].sum())
    calls_above = calls[calls["strike"] > current_price]
    puts_below = puts[puts["strike"] < current_price]
    call_wall = calls_above.loc[calls_above["openInterest"].idxmax(), "strike"] if not calls_above.empty else None
    put_wall = puts_below.loc[puts_below["openInterest"].idxmax(), "strike"] if not puts_below.empty else None
    strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
    pain = {}
    for strike in strikes:
        call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
        put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
        pain[strike] = call_loss + put_loss
    total_gex = {}
    for expiration in expirations[:2]:
        try:
            exp_chain = stock.option_chain(expiration)
            time_to_expiry = max((datetime.strptime(expiration, "%Y-%m-%d") - datetime.now()).days / 365, 0.001)
            for option_type, direction in ((exp_chain.calls, 1), (exp_chain.puts, -1)):
                for _, row in option_type.fillna(0).iterrows():
                    strike, volatility, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
                    if volatility > 0 and oi > 0:
                        gamma = black_scholes_gamma(current_price, strike, time_to_expiry, 0.05, volatility)
                        total_gex[strike] = total_gex.get(strike, 0) + direction * gamma * oi * 100 * current_price
        except Exception:
            continue
    return {
        "current_price": current_price,
        "exp_date": exp_date,
        "pc_ratio": None if total_call_oi == 0 else total_put_oi / total_call_oi,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "max_pain": min(pain, key=pain.get) if pain else None,
        "net_gex": sum(total_gex.values()) if total_gex else None,
        "calls_near_gex": sum(value for strike, value in total_gex.items() if value > 0 and current_price < strike < current_price * 1.1),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "calls": calls,
        "puts": puts,
        "gex_by_strike": total_gex,
    }


def render_snapshot_card(container, snapshot):
    change = snapshot["change_pct"] or 0
    delta_color = "#22c55e" if change >= 0 else "#ef4444"
    container.markdown(
        f"""
        <div class="stock-card">
          <div class="ticker">{snapshot["ticker"]}</div>
          <div class="company">{snapshot["name"]}</div>
          <div class="source">Source: {snapshot["source"]}</div>
          <div class="price">{format_money(snapshot["price"], 2)}</div>
          <div class="change" style="color:{delta_color}">{change:+.2f}% today</div>
          <div class="card-grid">
            <span>Market cap<b>{format_money(snapshot["market_cap"])}</b></span>
            <span>Revenue<b>{format_money(snapshot["revenue"])}</b></span>
            <span>Net margin<b>{"N/A" if snapshot["net_margin"] is None else f'{snapshot["net_margin"] * 100:.1f}%'}</b></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_row(metrics):
    columns = st.columns(len(metrics))
    for column, (label, value, *delta) in zip(columns, metrics):
        column.metric(label, value, delta[0] if delta else None)


def filter_options_near_price(options, current_price, price_range=0.2):
    filtered = options[
        (options["strike"] >= current_price * (1 - price_range))
        & (options["strike"] <= current_price * (1 + price_range))
    ]
    return filtered if not filtered.empty else options


def render_option_chain_chart(ticker, option_type, options, current_price, exp_date, color):
    filtered = filter_options_near_price(options, current_price)
    fig = go.Figure(go.Bar(
        x=filtered["strike"],
        y=filtered["openInterest"],
        marker_color=color,
        name=f"{option_type} open interest",
    ))
    fig.add_vline(x=current_price, line_dash="dash", line_color="yellow")
    fig.update_layout(
        template="plotly_dark",
        height=300,
        title=f"{ticker} {option_type} Options | Open Interest by Strike | Expiry {exp_date}",
        xaxis_title="Strike",
        yaxis_title="Open interest",
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_{option_type.lower()}_options")


def render_gex_chart(ticker, gex_by_strike, current_price):
    if not gex_by_strike:
        st.warning(f"{ticker} GEX chart unavailable: no usable gamma exposure data returned.")
        return
    strikes, values = zip(*sorted(gex_by_strike.items()))
    colors = ["#22c55e" if value >= 0 else "#ef4444" for value in values]
    fig = go.Figure(go.Bar(x=strikes, y=values, marker_color=colors, name="Net GEX"))
    fig.add_vline(x=current_price, line_dash="dash", line_color="yellow")
    fig.update_layout(
        template="plotly_dark",
        height=320,
        title=f"{ticker} Gamma Exposure by Strike",
        xaxis_title="Strike",
        yaxis_title="Net GEX",
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_gex")


def render_technical_section():
    st.caption("Six-month price trend, moving averages, RSI, and volume activity for the complete watchlist.")
    for ticker in WATCHLIST:
        with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]}", expanded=ticker == "NVDA"):
            try:
                data = get_technical_data(ticker)
                rsi = float(data["RSI"].iloc[-1])
                signal = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
                render_metric_row([
                    ("Price", format_money(data["Close"].iloc[-1], 2)),
                    ("RSI (14)", f"{rsi:.1f}"),
                    ("RSI signal", signal),
                    ("Volume vs 20D", f"{data['Vol_Ratio'].iloc[-1]:.2f}x"),
                ])
                st.line_chart(data[["Close", "MA5", "MA20"]], height=260)
                st.caption(f"Historical price source: {data.attrs.get('source', 'N/A')}")
            except Exception as exc:
                st.warning(f"{ticker} technical data unavailable: {exc}")


def render_options_section():
    st.caption("Gamma exposure and options positioning are calculated independently for every tracked stock.")
    for ticker in WATCHLIST:
        with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]} Gamma Exposure", expanded=ticker == "NVDA"):
            try:
                opt = get_options_data(ticker)
                render_metric_row([
                    ("Price", format_money(opt["current_price"], 2)),
                    ("Put/Call ratio", format_ratio(opt["pc_ratio"])),
                    ("Max pain", format_money(opt["max_pain"], 0)),
                    ("Net GEX", format_money(opt["net_gex"], 0)),
                    ("Call wall", format_money(opt["call_wall"], 0)),
                    ("Put wall", format_money(opt["put_wall"], 0)),
                ])
                squeeze = "High" if opt["calls_near_gex"] > 1_000_000 else "Medium" if opt["calls_near_gex"] > 500_000 else "Low"
                if opt["net_gex"] is None:
                    regime = "GEX regime unavailable."
                elif opt["net_gex"] >= 0:
                    regime = "Positive GEX: positioning may dampen moves."
                else:
                    regime = "Negative GEX: positioning may amplify moves."
                st.info(f"Gamma squeeze risk: {squeeze}. {regime} Nearest expiration: {opt['exp_date']}.")
                chart_columns = st.columns(2)
                with chart_columns[0]:
                    render_option_chain_chart(ticker, "Call", opt["calls"], opt["current_price"], opt["exp_date"], "#22c55e")
                with chart_columns[1]:
                    render_option_chain_chart(ticker, "Put", opt["puts"], opt["current_price"], opt["exp_date"], "#ef4444")
                render_gex_chart(ticker, opt["gex_by_strike"], opt["current_price"])
            except Exception as exc:
                st.warning(f"{ticker} options data unavailable: {exc}")


def render_value_section(snapshots):
    st.caption("FMP-first ratios, key metrics, and growth comparison for every tracked company.")
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker)
        with st.expander(f"{ticker} | {snapshot['name'] if snapshot else COMPANY_NAMES[ticker]}", expanded=ticker == "NVDA"):
            st.markdown(f"**{ticker} | {COMPANY_NAMES[ticker]}**")
            st.caption(SUPPLY_CHAIN_ROLES[ticker])
            if not snapshot:
                st.write("Valuation data unavailable")
                continue
            st.caption(f"Source: {snapshot['source']} | {snapshot.get('sector') or 'N/A'} | {snapshot.get('industry') or 'N/A'}")
            render_metric_row([
                ("P/E", format_ratio(snapshot["trailing_pe"])),
                ("P/B", format_ratio(snapshot["price_to_book"])),
                ("P/S", format_ratio(snapshot["price_to_sales"])),
                ("EV/EBITDA", format_ratio(snapshot["ev_to_ebitda"])),
                ("ROE", format_percent(snapshot["return_on_equity"])),
                ("ROA", format_percent(snapshot["return_on_assets"])),
            ])
            render_metric_row([
                ("Gross margin", format_percent(snapshot["gross_margin"])),
                ("Operating margin", format_percent(snapshot["operating_margin"])),
                ("Net margin", format_percent(snapshot["net_margin"])),
                ("FCF margin", format_percent(snapshot["free_cash_flow_margin"])),
                ("Current ratio", format_ratio(snapshot["current_ratio"])),
                ("Quick ratio", format_ratio(snapshot["quick_ratio"])),
                ("Debt / equity", format_ratio(snapshot["debt_to_equity"])),
            ])
            render_metric_row([
                ("Revenue YoY", format_percent(snapshot["revenue_growth_yoy"])),
                ("Gross profit growth", format_percent(snapshot["gross_profit_growth"])),
                ("Operating income growth", format_percent(snapshot["operating_income_growth"])),
                ("Net income growth", format_percent(snapshot["net_income_growth"])),
                ("EPS growth", format_percent(snapshot["eps_growth"])),
            ])
            render_metric_row([
                ("Current price", format_money(snapshot["price"], 2)),
                ("Consensus target", format_money(snapshot["analyst_target"], 2)),
                ("High target", format_money(snapshot["analyst_target_high"], 2)),
                ("Low target", format_money(snapshot["analyst_target_low"], 2)),
                ("Upside / downside", "N/A" if snapshot["analyst_upside_pct"] is None else f"{snapshot['analyst_upside_pct']:+.1f}%"),
                ("Analyst rating", snapshot.get("analyst_rating") or "N/A"),
            ])


@st.cache_data(ttl=3600)
def get_cached_company_news(ticker, limit=5):
    return fetch_company_news(ticker, limit)


def fetch_news_headlines(ticker, limit=5):
    fmp_news = get_cached_company_news(ticker, limit)
    if fmp_news:
        return [item["title"] for item in fmp_news if item.get("title")]
    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    return [entry.title for entry in feed.entries[:limit]]


def fetch_news_sentiment(ticker, client):
    headlines = fetch_news_headlines(ticker)
    if not headlines:
        return {"sentiment": "N/A", "score": 0, "summary": "No recent headlines returned."}
    prompt = (
        f"Analyze sentiment of these {ticker} headlines: {headlines}. Reply with JSON only: "
        '{"sentiment": "BULLISH/BEARISH/NEUTRAL", "score": 0, "summary": "one line"}'
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def get_technical_summary(ticker):
    data = get_technical_data(ticker)
    latest = data.iloc[-1]
    price = float(latest["Close"])
    ma5 = None if pd.isna(latest["MA5"]) else float(latest["MA5"])
    ma20 = None if pd.isna(latest["MA20"]) else float(latest["MA20"])
    if ma5 is None or ma20 is None:
        trend = "unavailable"
    elif price > ma20 and ma5 > ma20:
        trend = "bullish"
    elif price < ma20 and ma5 < ma20:
        trend = "bearish"
    else:
        trend = "neutral"
    return {
        "trend": trend,
        "rsi_14": None if pd.isna(latest["RSI"]) else round(float(latest["RSI"]), 2),
        "ma_5": ma5,
        "ma_20": ma20,
        "volume_vs_20d": None if pd.isna(latest["Vol_Ratio"]) else round(float(latest["Vol_Ratio"]), 2),
    }


def get_options_summary(ticker):
    opt = get_options_data(ticker)
    return {
        "nearest_expiration": opt["exp_date"],
        "put_call_ratio": opt["pc_ratio"],
        "max_pain": opt["max_pain"],
        "net_gex": opt["net_gex"],
        "call_wall": opt["call_wall"],
        "put_wall": opt["put_wall"],
    }


def build_ai_summary_payload(snapshots, macro_snapshot=None):
    stocks = []
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker) or {}
        stock_data = {
            "ticker": ticker,
            "company_name": COMPANY_NAMES[ticker],
            "supply_chain_role": SUPPLY_CHAIN_ROLES[ticker],
            "current_price": snapshot.get("price"),
            "daily_change_pct": snapshot.get("change_pct"),
            "revenue": snapshot.get("revenue"),
            "net_margin": snapshot.get("net_margin"),
            "trailing_pe": snapshot.get("trailing_pe"),
            "forward_pe": snapshot.get("forward_pe"),
            "price_to_book": snapshot.get("price_to_book"),
            "price_to_sales": snapshot.get("price_to_sales"),
            "ev_to_ebitda": snapshot.get("ev_to_ebitda"),
            "revenue_growth_yoy": snapshot.get("revenue_growth_yoy"),
            "gross_profit_growth": snapshot.get("gross_profit_growth"),
            "operating_income_growth": snapshot.get("operating_income_growth"),
            "net_income_growth": snapshot.get("net_income_growth"),
            "eps_growth": snapshot.get("eps_growth"),
            "analyst_consensus_target": snapshot.get("analyst_target"),
            "analyst_high_target": snapshot.get("analyst_target_high"),
            "analyst_low_target": snapshot.get("analyst_target_low"),
            "analyst_upside_downside_pct": snapshot.get("analyst_upside_pct"),
            "next_earnings_date": snapshot.get("next_earnings_date"),
            "estimated_eps": snapshot.get("estimated_eps"),
            "actual_eps": snapshot.get("actual_eps"),
            "eps_surprise": snapshot.get("eps_surprise"),
            "days_until_earnings": snapshot.get("days_until_earnings"),
            "analyst_rating": snapshot.get("analyst_rating"),
            "data_source": snapshot.get("source"),
        }
        try:
            news = get_cached_company_news(ticker, 5)
            stock_data["latest_news"] = news or [{"title": title, "source": "Yahoo RSS fallback"} for title in fetch_news_headlines(ticker)]
        except Exception as exc:
            stock_data["latest_news_headlines"] = []
            stock_data["news_error"] = str(exc)
        try:
            stock_data["technical"] = get_technical_summary(ticker)
        except Exception as exc:
            stock_data["technical"] = {"status": "unavailable", "error": str(exc)}
        try:
            stock_data["options_gex"] = get_options_summary(ticker)
        except Exception as exc:
            stock_data["options_gex"] = {"status": "unavailable", "error": str(exc)}
        stocks.append(stock_data)
    return {"report_date": datetime.now().strftime("%Y-%m-%d"), "macro": macro_snapshot or {}, "stocks": stocks}


def build_ai_summary_prompt(payload):
    return f"""
You are a professional US equity analyst. Write a concise daily watchlist summary dated {payload["report_date"]}.
Use only the supplied structured data. Do not invent missing values, do not use placeholder dates,
and never ask the user to provide data. State that a metric is unavailable when needed.

Structured watchlist data:
{json.dumps(payload, indent=2, default=str)}

Use this exact report structure:
1. Market Summary
2. Macro Backdrop
- Explain whether the US 10Y yield is rising, falling, or stable.
- Explain whether the yield curve is inverted or normal.
- Assess USD strength, inflation pressure, oil risk, and important 30-day events.
- State the Macro Risk Score from 0 to 10.
- State whether macro is favorable, neutral, or unfavorable for growth stocks, AI stocks, semiconductors, and high-duration stocks.
3. Stock-by-stock analysis
4. Bull Case
5. Bear Case
6. Catalysts
7. Risks
8. Options / GEX interpretation
9. Investment View
10. Portfolio Conclusion
- Compare all tracked stocks
- Identify strongest setup
- Identify highest risk name
- State whether the group is bullish, neutral, or bearish overall
- Explain how macro affects NVDA, MU, SNDK, LITE, and RKLB based on their supplied roles and metrics.
- Treat NVDA as an AI growth stock with rate-sensitive valuation; MU and SNDK as memory/storage-cycle names sensitive to global demand and USD; LITE as optical AI-infrastructure exposure sensitive to capex; and RKLB as a high-duration growth stock sensitive to rates and risk appetite.
"""


def render_daily_report(snapshots):
    st.caption("Build a complete daily research report for the watchlist in one pass.")
    if st.button("Generate Complete Daily Report", key="daily_report"):
        st.subheader(f"Daily Watchlist Report | {datetime.now():%Y-%m-%d}")
        render_overview_cards(snapshots)
        st.markdown("#### Technical Snapshot")
        rows = []
        for ticker in WATCHLIST:
            try:
                data = get_technical_data(ticker)
                rows.append({
                    "Ticker": ticker,
                    "Price": format_money(data["Close"].iloc[-1], 2),
                    "RSI (14)": f"{data['RSI'].iloc[-1]:.1f}",
                    "Volume vs 20D": f"{data['Vol_Ratio'].iloc[-1]:.2f}x",
                })
            except Exception:
                rows.append({"Ticker": ticker, "Price": "N/A", "RSI (14)": "N/A", "Volume vs 20D": "N/A"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("#### Options & GEX Snapshot")
        options_rows = []
        for ticker in WATCHLIST:
            try:
                opt = get_options_data(ticker)
                options_rows.append({
                    "Ticker": ticker,
                    "Put/Call Ratio": format_ratio(opt["pc_ratio"]),
                    "Max Pain": format_money(opt["max_pain"], 0),
                    "Net GEX": format_money(opt["net_gex"], 0),
                    "Call Wall": format_money(opt["call_wall"], 0),
                    "Put Wall": format_money(opt["put_wall"], 0),
                })
            except Exception:
                options_rows.append({
                    "Ticker": ticker,
                    "Put/Call Ratio": "N/A",
                    "Max Pain": "N/A",
                    "Net GEX": "N/A",
                    "Call Wall": "N/A",
                    "Put Wall": "N/A",
                })
        st.dataframe(pd.DataFrame(options_rows), use_container_width=True, hide_index=True)
        st.markdown("#### Value Investing Snapshot")
        valuation_rows = []
        for ticker in WATCHLIST:
            snapshot = snapshots.get(ticker)
            valuation_rows.append({
                "Ticker": ticker,
                "Company": COMPANY_NAMES[ticker],
                "Supply Chain Role": SUPPLY_CHAIN_ROLES[ticker],
                "Trailing P/E": "N/A" if not snapshot else format_ratio(snapshot["trailing_pe"]),
                "Forward P/E": "N/A" if not snapshot else format_ratio(snapshot["forward_pe"]),
                "Price / Book": "N/A" if not snapshot else format_ratio(snapshot["price_to_book"]),
                "Revenue YoY": "N/A" if not snapshot else format_percent(snapshot["revenue_growth_yoy"]),
                "Analyst Target": "N/A" if not snapshot else format_money(snapshot["analyst_target"], 2),
                "Upside / Downside": "N/A" if not snapshot else format_percent(snapshot["analyst_upside_pct"] / 100 if snapshot["analyst_upside_pct"] is not None else None),
            })
        st.dataframe(pd.DataFrame(valuation_rows), use_container_width=True, hide_index=True)
        st.markdown("#### Earnings Catalysts")
        catalyst_rows = []
        for ticker in WATCHLIST:
            snapshot = snapshots.get(ticker) or {}
            catalyst_rows.append({
                "Ticker": ticker,
                "Next Earnings Date": snapshot.get("next_earnings_date") or "N/A",
                "Estimated EPS": format_ratio(snapshot.get("estimated_eps")),
                "Actual EPS": format_ratio(snapshot.get("actual_eps")),
                "EPS Surprise": format_percent(snapshot.get("eps_surprise")),
                "Days Until Earnings": snapshot.get("days_until_earnings") if snapshot.get("days_until_earnings") is not None else "N/A",
            })
        st.dataframe(pd.DataFrame(catalyst_rows), use_container_width=True, hide_index=True)
        st.markdown("#### News Sentiment")
        try:
            client = get_openai_client()
            sentiment_rows = []
            for ticker in WATCHLIST:
                try:
                    sentiment_rows.append({"Ticker": ticker, **fetch_news_sentiment(ticker, client)})
                except Exception as exc:
                    sentiment_rows.append({"Ticker": ticker, "sentiment": "N/A", "score": 0, "summary": str(exc)})
            st.dataframe(pd.DataFrame(sentiment_rows), use_container_width=True, hide_index=True)
            summary_payload = build_ai_summary_payload(snapshots, summarize_macro_snapshot(build_macro_snapshot()))
            prompt = build_ai_summary_prompt(summary_payload)
            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
            st.markdown("#### AI Summary")
            st.write(response.choices[0].message.content)
        except Exception as exc:
            st.warning(f"AI report summary unavailable: {exc}")


def render_multi_agent_section():
    st.caption("Run the five-agent workflow for the whole watchlist. Each stock receives a separate verdict.")
    if st.button("Run All-Stock Multi-Agent Analysis", key="multi_agent"):
        from multi_agent import agent_fundamental, agent_news, agent_options, agent_risk_manager, agent_technical
        for ticker in WATCHLIST:
            with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]} Multi-Agent Research", expanded=ticker == "NVDA"):
                with st.spinner(f"Running research agents for {ticker}..."):
                    technical = agent_technical(ticker)
                    fundamental = agent_fundamental(ticker)
                    options = agent_options(ticker)
                    news = agent_news(ticker)
                    verdict = agent_risk_manager(ticker, technical, fundamental, options, news)
                st.markdown("##### Final Verdict")
                st.info(verdict)
                with st.expander("Agent Detail"):
                    st.markdown("**Technical Analysis**")
                    st.write(technical)
                    st.markdown("**Fundamental Analysis**")
                    st.write(fundamental)
                    st.markdown("**Options Analysis**")
                    st.write(options)
                    st.markdown("**News Sentiment**")
                    st.write(news)


def render_overview_cards(snapshots):
    columns = st.columns(len(WATCHLIST))
    for column, ticker in zip(columns, WATCHLIST):
        snapshot = snapshots.get(ticker)
        if snapshot:
            render_snapshot_card(column, snapshot)
        else:
            column.warning(f"{ticker} data unavailable")


def render_diagnostics(snapshots):
    rows = []
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker) or {}
        rows.append({
            "Ticker": ticker,
            "Company": snapshot.get("name") or COMPANY_NAMES[ticker],
            "Data Source": snapshot.get("source") or "unavailable",
            "Revenue": format_money(snapshot.get("revenue")),
            "Net Margin": format_percent(snapshot.get("net_margin")),
            "P/E": format_ratio(snapshot.get("trailing_pe")),
            "P/B": format_ratio(snapshot.get("price_to_book")),
            "Revenue Growth YoY": format_percent(snapshot.get("revenue_growth_yoy")),
            "Analyst Target": format_money(snapshot.get("analyst_target"), 2),
            "Next Earnings Date": snapshot.get("next_earnings_date") or "N/A",
            "Last Updated": snapshot.get("last_updated") or "N/A",
            "Diagnostic Note": snapshot.get("diagnostic_note") or "N/A",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def get_macro_trend(history):
    if history is None or history.empty or len(history) < 2:
        return "N/A"
    first = float(history["value"].iloc[0])
    last = float(history["value"].iloc[-1])
    if not first:
        return "N/A"
    change = (last - first) / abs(first)
    return "rising" if change > 0.01 else "falling" if change < -0.01 else "stable"


def summarize_macro_snapshot(macro):
    rates = macro["rates"]
    markets = macro["markets"]
    calendar = macro["calendar"]
    important_events = [item for item in calendar["events"] if item["Important"]][:20]
    return {
        "last_updated": macro["last_updated"],
        "macro_risk_score_0_to_10": macro["macro_risk_score"],
        "us_10y_yield": rates["year10"],
        "us_10y_trend": get_macro_trend(rates["history"].rename(columns={"year10": "value"})[["date", "value"]].dropna()) if "year10" in rates["history"] else "N/A",
        "us_10y_minus_2y_spread": rates["spread_10y_2y"],
        "yield_curve": "inverted" if rates["spread_10y_2y"] is not None and rates["spread_10y_2y"] < 0 else "normal" if rates["spread_10y_2y"] is not None else "N/A",
        "eur_usd": markets["EUR/USD"]["value"],
        "usd_cny": markets["USD/CNY"]["value"],
        "usd_jpy": markets["USD/JPY"]["value"],
        "dxy": markets["DXY"]["value"],
        "cpi_yoy_pct": macro["cpi_yoy"],
        "unemployment_rate_pct": macro["indicators"]["unemploymentRate"]["value"],
        "gdp_growth_yoy_pct": macro["gdp_growth_yoy"],
        "brent_crude": markets["Brent crude oil"]["value"],
        "wti_crude": markets["WTI crude oil"]["value"],
        "important_events_next_30_days": important_events,
    }


def render_macro_chart(title, history):
    if history is None or history.empty:
        st.caption(f"{title}: historical data unavailable")
        return
    chart = history[["date", "value"]].dropna().set_index("date")
    values = pd.to_numeric(chart["value"], errors="coerce").dropna()
    if values.empty:
        st.caption(f"{title}: historical data unavailable")
        return
    minimum = float(values.min())
    maximum = float(values.max())
    padding = (maximum - minimum) * 0.1 or max(abs(maximum) * 0.05, 0.01)
    figure = go.Figure(go.Scatter(x=chart.index, y=chart["value"], mode="lines"))
    figure.update_layout(
        height=220, margin={"l": 8, "r": 8, "t": 8, "b": 8},
        template="plotly_dark", showlegend=False,
        yaxis={"range": [minimum - padding, maximum + padding]},
    )
    st.plotly_chart(figure, use_container_width=True, key=f"macro_{title}")
    st.caption(title)


def render_macro_section():
    st.caption("Dynamic FMP-first macro dashboard for the next 30 days. Market-series fallbacks use yfinance.")
    if st.button("Refresh Macro Data", key="refresh_macro"):
        fetch_treasury_rates.clear()
        fetch_market_series.clear()
        fetch_indicator.clear()
        fetch_macro_calendar.clear()
        st.rerun()
    macro = build_macro_snapshot()
    rates = macro["rates"]
    markets = macro["markets"]
    indicators = macro["indicators"]
    st.caption(f"Last updated: {macro['last_updated']} | Calendar window: {macro['calendar']['start_date']} to {macro['calendar']['end_date']}")
    render_metric_row([
        ("Macro risk score", f"{macro['macro_risk_score']}/10"),
        ("US 2Y", "N/A" if rates["year2"] is None else f"{rates['year2']:.2f}%"),
        ("US 10Y", "N/A" if rates["year10"] is None else f"{rates['year10']:.2f}%"),
        ("US 30Y", "N/A" if rates["year30"] is None else f"{rates['year30']:.2f}%"),
        ("10Y - 2Y", "N/A" if rates["spread_10y_2y"] is None else f"{rates['spread_10y_2y']:+.2f}%"),
        ("10Y - 3M", "N/A" if rates["spread_10y_3m"] is None else f"{rates['spread_10y_3m']:+.2f}%"),
    ])
    st.caption(f"Treasury source: {rates['source']}")
    render_metric_row([(label, format_ratio(markets[label]["value"])) for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY")])
    st.caption(" | ".join(f"{label}: {markets[label]['source']}" for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY")))
    render_metric_row([
        ("CPI YoY", "N/A" if macro["cpi_yoy"] is None else f"{macro['cpi_yoy']:.2f}%"),
        ("Core CPI YoY", "N/A"),
        ("PCE / Core PCE", "N/A"),
        ("Unemployment", "N/A" if indicators["unemploymentRate"]["value"] is None else f"{indicators['unemploymentRate']['value']:.2f}%"),
        ("GDP growth YoY", "N/A" if macro["gdp_growth_yoy"] is None else f"{macro['gdp_growth_yoy']:.2f}%"),
    ])
    render_metric_row([(label, format_money(markets[label]["value"], 2)) for label in ("Brent crude oil", "WTI crude oil", "Gold", "Copper")])
    st.caption(" | ".join(f"{label}: {markets[label]['source']}" for label in ("Brent crude oil", "WTI crude oil", "Gold", "Copper")))
    chart_columns = st.columns(4)
    with chart_columns[0]:
        treasury_history = rates["history"]
        render_macro_chart("US 10Y Treasury yield", treasury_history.rename(columns={"year10": "value"})[["date", "value"]].dropna() if "year10" in treasury_history else pd.DataFrame())
    with chart_columns[1]:
        render_macro_chart("EUR/USD", markets["EUR/USD"]["history"])
    with chart_columns[2]:
        render_macro_chart("Brent crude oil", markets["Brent crude oil"]["history"])
    with chart_columns[3]:
        render_macro_chart("CPI index", indicators["CPI"]["history"])
    st.markdown("#### Dynamic 30-Day Macro Calendar")
    events = macro["calendar"]["events"]
    if events:
        show_all_events = st.checkbox("Show all macro calendar events", value=False, key="show_all_macro_events")
        visible_events = events if show_all_events else [item for item in events if item["Important"]]
        if visible_events:
            table = pd.DataFrame(visible_events).drop(columns=["Important"])
            table = table.fillna("N/A")
            for column in ("Actual", "Estimate", "Previous"):
                table[column] = table[column].map(lambda value: "N/A" if value == "N/A" else str(value))
            st.dataframe(table, use_container_width=True, hide_index=True)
        else:
            st.info("No highlighted macro events in the next 30 days.")
    else:
        st.info("Economic calendar unavailable.")
    return macro


st.set_page_config(page_title="Equity Research Terminal", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1800px;}
    .stock-card {background:#111827; border:1px solid #263244; border-radius:10px; padding:16px; min-height:220px;}
    .ticker {font-size:1.25rem; font-weight:700; letter-spacing:.08em; color:#e5e7eb;}
    .company {font-size:.8rem; color:#94a3b8; min-height:26px;}
    .source {font-size:.68rem; color:#64748b;}
    .price {font-size:1.65rem; font-weight:700; margin-top:12px; color:#f8fafc;}
    .change {font-size:.85rem; margin-bottom:14px;}
    .card-grid {display:grid; gap:8px; font-size:.72rem; color:#94a3b8;}
    .card-grid span {display:flex; justify-content:space-between; border-top:1px solid #253044; padding-top:6px;}
    .card-grid b {color:#e5e7eb;}
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Equity Research Terminal")
st.caption("Cross-company dashboard | AI infrastructure and growth watchlist")

snapshots = {}
for symbol in WATCHLIST:
    try:
        snapshots[symbol] = get_company_snapshot(symbol)
    except Exception:
        snapshots[symbol] = None

render_overview_cards(snapshots)
st.divider()

tabs = st.tabs([
    "Technical Analysis", "Options & GEX", "Value Investing",
    "Multi-Agent Research", "Data Diagnostics", "Macro",
])
with tabs[0]:
    render_technical_section()
with tabs[1]:
    render_options_section()
with tabs[2]:
    render_value_section(snapshots)
with tabs[3]:
    render_multi_agent_section()
with tabs[4]:
    render_diagnostics(snapshots)
with tabs[5]:
    render_macro_section()
