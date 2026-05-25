import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
import os
import requests
import feedparser

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ask_agent(role, context, question):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": f"You are a {role}. Be concise and professional. Max 150 words."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
        ]
    )
    return response.choices[0].message.content

def agent_technical(ticker):
    data = yf.Ticker(ticker).history(period="3mo")
    price = data["Close"].iloc[-1]
    rsi = calculate_rsi(data).iloc[-1]
    ma5 = data["Close"].rolling(5).mean().iloc[-1]
    ma20 = data["Close"].rolling(20).mean().iloc[-1]
    vol_ratio = data["Volume"].iloc[-1] / data["Volume"].rolling(20).mean().iloc[-1]
    change = data["Close"].pct_change().iloc[-1] * 100

    context = f"""
{ticker} Technical Data:
- Price: ${price:.2f} ({change:+.1f}% today)
- RSI: {rsi:.1f}
- MA5: ${ma5:.2f} | MA20: ${ma20:.2f}
- Trend: {'Bullish' if ma5 > ma20 else 'Bearish'}
- Volume Ratio: {vol_ratio:.1f}x average
"""
    return ask_agent(
        "expert technical analyst",
        context,
        f"Analyze {ticker}'s technical setup. Is it bullish or bearish? Key levels to watch?"
    )

def agent_fundamental(ticker):
    from config import FMP_API_KEY

    try:
        url = f"https://financialmodelingprep.com/stable/income-statement?symbol={ticker}&limit=2&apikey={FMP_API_KEY}"
        data = requests.get(url).json()
    except:
        return "Fundamental data unavailable."

    if not data:
        return "Fundamental data unavailable."

    latest = data[0]
    prev = data[1] if len(data) > 1 else data[0]

    revenue = latest.get("revenue", 0)
    net_income = latest.get("netIncome", 0)
    margin = net_income / revenue * 100 if revenue > 0 else 0
    rev_growth = (latest.get("revenue", 0) - prev.get("revenue", 0)) / prev.get("revenue", 1) * 100

    context = f"""
{ticker} Fundamental Data:
- Revenue: ${revenue/1e9:.1f}B
- Net Income: ${net_income/1e9:.1f}B
- Net Margin: {margin:.1f}%
- Revenue Growth YoY: {rev_growth:.1f}%
"""
    return ask_agent(
        "expert fundamental analyst",
        context,
        f"Analyze {ticker}'s financial health. Is the business strong? Any concerns?"
    )

def agent_options(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.history(period="1d")["Close"].iloc[-1]
        exp = stock.options[0]
        chain = stock.option_chain(exp)
        calls = chain.calls
        puts = chain.puts

        pc_ratio = puts["openInterest"].sum() / calls["openInterest"].sum()
        atm_calls = calls[abs(calls["strike"] - price) < price * 0.05]
        iv = atm_calls["impliedVolatility"].mean() * 100 if len(atm_calls) > 0 else 0

        strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        pain = {}
        for strike in strikes:
            call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
            put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
            pain[strike] = call_loss + put_loss
        max_pain = min(pain, key=pain.get)

        context = f"""
{ticker} Options Data:
- Current Price: ${price:.2f}
- Put/Call Ratio: {pc_ratio:.2f}
- ATM IV: {iv:.1f}%
- Max Pain: ${max_pain:.0f}
- Expiry: {exp}
"""
        return ask_agent(
            "expert options market analyst",
            context,
            f"Analyze {ticker}'s options market. What is the market positioning? Bullish or bearish?"
        )
    except:
        return "Options data temporarily unavailable."

def agent_news(ticker):
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        headlines = [e.title for e in feed.entries[:6]]
        context = f"""
{ticker} Latest Headlines:
{chr(10).join(f'- {h}' for h in headlines)}
"""
        return ask_agent(
            "expert financial news analyst",
            context,
            f"Analyze the news sentiment for {ticker}. What are the key themes? Positive or negative?"
        )
    except:
        return "News data unavailable."

def agent_risk_manager(ticker, technical, fundamental, options, news):
    context = f"""
{ticker} Research Summary:

TECHNICAL ANALYSIS:
{technical}

FUNDAMENTAL ANALYSIS:
{fundamental}

OPTIONS ANALYSIS:
{options}

NEWS SENTIMENT:
{news}
"""
    return ask_agent(
        "senior risk manager and portfolio strategist",
        context,
        f"""Based on all the above analysis for {ticker}, provide:
1. Overall Rating: STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL
2. Key Risk: Main risk to watch
3. Key Opportunity: Main opportunity
4. Suggested Action: What should an investor do?
Be direct and actionable."""
    )

def run_multi_agent(ticker):
    print(f"\n{'='*60}")
    print(f"Multi-Agent Analysis: {ticker}")
    print(f"{'='*60}")

    print(f"\n🔍 Agent 1: Technical Analysis...")
    technical = agent_technical(ticker)
    print(technical)

    print(f"\n📊 Agent 2: Fundamental Analysis...")
    fundamental = agent_fundamental(ticker)
    print(fundamental)

    print(f"\n🎯 Agent 3: Options Analysis...")
    options = agent_options(ticker)
    print(options)

    print(f"\n📰 Agent 4: News Sentiment...")
    news = agent_news(ticker)
    print(news)

    print(f"\n⚖️  Agent 5: Risk Manager (Final Verdict)...")
    verdict = agent_risk_manager(ticker, technical, fundamental, options, news)
    print(verdict)

    return {
        "technical": technical,
        "fundamental": fundamental,
        "options": options,
        "news": news,
        "verdict": verdict
    }

if __name__ == "__main__":
    for company, ticker in WATCHLIST.items():
        run_multi_agent(ticker)
        print("\n" + "="*60 + "\n")