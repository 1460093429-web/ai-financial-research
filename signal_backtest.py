import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

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

def simple_signal_score(data, i):
    """Calculate signal score using only price-based indicators."""
    if i < 20:
        return 50
    
    slice = data.iloc[:i+1]
    price = slice["Close"].iloc[-1]
    rsi = calculate_rsi(slice).iloc[-1]
    ma5 = slice["Close"].rolling(5).mean().iloc[-1]
    ma20 = slice["Close"].rolling(20).mean().iloc[-1]
    vol_ratio = slice["Volume"].iloc[-1] / slice["Volume"].rolling(20).mean().iloc[-1]
    price_change = slice["Close"].pct_change().iloc[-1]
    
    score = 0
    
    # RSI (0-30)
    if rsi < 30:
        score += 30
    elif rsi < 50:
        score += 22
    elif rsi < 70:
        score += 15
    else:
        score += 0
    
    # MA (0-30)
    if ma5 > ma20 and price > ma5:
        score += 30
    elif ma5 > ma20:
        score += 22
    elif ma5 < ma20 and price < ma5:
        score += 0
    else:
        score += 15
    
    # Volume (0-40)
    if vol_ratio > 1.5 and price_change > 0.02:
        score += 40
    elif vol_ratio > 1.5 and price_change < -0.02:
        score += 0
    elif vol_ratio < 0.7 and price_change > 0:
        score += 15
    else:
        score += 20
    
    return score

def signal_backtest(ticker, period="1y", initial_capital=10000):
    data = yf.Ticker(ticker).history(period=period)
    
    capital = initial_capital
    shares = 0
    trades = []
    scores = []
    
    for i in range(20, len(data)):
        price = data["Close"].iloc[i]
        date = data.index[i].strftime("%Y-%m-%d")
        score = simple_signal_score(data, i)
        scores.append(score)
        
        # Buy when score >= 70 and not holding
        if score >= 70 and capital > 0 and shares == 0:
            shares = capital / price
            capital = 0
            trades.append({
                "date": date,
                "action": "BUY",
                "price": price,
                "score": score,
                "value": shares * price
            })
        
        # Sell when score < 40 and holding
        elif score < 40 and shares > 0:
            capital = shares * price
            shares = 0
            trades.append({
                "date": date,
                "action": "SELL",
                "price": price,
                "score": score,
                "value": capital
            })
    
    # Final value
    final_value = capital + shares * data["Close"].iloc[-1]
    profit = final_value - initial_capital
    return_pct = (profit / initial_capital) * 100
    
    # Buy & Hold comparison
    buy_hold_return = (data["Close"].iloc[-1] - data["Close"].iloc[20]) / data["Close"].iloc[20] * 100
    
    print(f"\n=== {ticker} Signal System Backtest ===")
    print(f"Period: {period}")
    print(f"Initial Capital:  ${initial_capital:,.2f}")
    print(f"Final Value:      ${final_value:,.2f}")
    print(f"Profit/Loss:      ${profit:,.2f}")
    print(f"Signal Return:    {return_pct:.1f}%")
    print(f"Buy & Hold:       {buy_hold_return:.1f}%")
    print(f"Outperformance:   {return_pct - buy_hold_return:.1f}%")
    print(f"Total Trades:     {len(trades)}")
    
    print(f"\nTrade History:")
    for t in trades:
        emoji = "🟢" if t["action"] == "BUY" else "🔴"
        print(f"  {emoji} {t['action']} {t['date']} | ${t['price']:.2f} | Score: {t['score']} | Value: ${t['value']:,.2f}")
    
    return final_value, return_pct, buy_hold_return

if __name__ == "__main__":
    print("Signal System Backtest vs Buy & Hold")
    print("=" * 50)
    
    results = []
    for company, ticker in WATCHLIST.items():
        final, signal_ret, bh_ret = signal_backtest(ticker, period="1y", initial_capital=10000)
        results.append({
            "company": company,
            "signal_return": signal_ret,
            "buyhold_return": bh_ret,
            "outperformance": signal_ret - bh_ret
        })
    
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"{'Stock':<12} {'Signal':>10} {'Buy&Hold':>10} {'Alpha':>10}")
    print("-" * 45)
    for r in results:
        print(f"{r['company']:<12} {r['signal_return']:>9.1f}% {r['buyhold_return']:>9.1f}% {r['outperformance']:>+9.1f}%")