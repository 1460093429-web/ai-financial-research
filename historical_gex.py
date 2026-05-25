import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta

def black_scholes_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return 0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

def find_big_moves(ticker, period="1y", threshold=0.05):
    """Find days with big price moves."""
    data = yf.Ticker(ticker).history(period=period)
    data["Return"] = data["Close"].pct_change()
    data["Volume_Ratio"] = data["Volume"] / data["Volume"].rolling(20).mean()
    
    # Find big up moves
    big_moves = data[abs(data["Return"]) >= threshold].copy()
    
    print(f"\n=== {ticker} Big Moves (>{threshold*100:.0f}%) in past year ===")
    print(f"Current Price: ${data['Close'].iloc[-1]:.2f}")
    print(f"\nDate          | Price   | Return  | Volume  | Type")
    print("-" * 60)
    
    for date, row in big_moves.iterrows():
        move_type = "🔥 SQUEEZE" if row["Return"] > 0 and row["Volume_Ratio"] > 1.5 else \
                   "🔴 CRASH" if row["Return"] < 0 and row["Volume_Ratio"] > 1.5 else \
                   "📈 UP" if row["Return"] > 0 else "📉 DOWN"
        print(f"{date.strftime('%Y-%m-%d')} | ${row['Close']:7.2f} | {row['Return']*100:+6.1f}% | {row['Volume_Ratio']:.1f}x | {move_type}")
    
    return big_moves, data

def analyze_before_squeeze(ticker, squeeze_date, days_before=3):
    """
    Analyze what happened in the days before a big move.
    Since historical options data requires paid APIs,
    we use price action and volume as proxies.
    """
    data = yf.Ticker(ticker).history(period="1y")
    
    # Find the squeeze date in data
    dates = [d.strftime("%Y-%m-%d") for d in data.index]
    if squeeze_date not in dates:
        return
    
    idx = dates.index(squeeze_date)
    start_idx = max(0, idx - days_before)
    
    pre_squeeze = data.iloc[start_idx:idx+1]
    
    print(f"\n--- {days_before} days before {squeeze_date} ---")
    print(f"Date          | Close   | Return  | Volume Ratio | Signal")
    print("-" * 65)
    
    pre_squeeze["Return"] = pre_squeeze["Close"].pct_change()
    pre_squeeze["Vol_Ratio"] = pre_squeeze["Volume"] / data["Volume"].rolling(20).mean()
    
    for date, row in pre_squeeze.iterrows():
        signal = "⚠️ Low Vol + Up = Weak" if row["Vol_Ratio"] < 0.8 and row["Return"] > 0 else \
                "🟢 High Vol + Up = Strong" if row["Vol_Ratio"] > 1.5 and row["Return"] > 0 else \
                "🔴 High Vol + Down = Danger" if row["Vol_Ratio"] > 1.5 and row["Return"] < 0 else ""
        print(f"{date.strftime('%Y-%m-%d')} | ${row['Close']:7.2f} | {row['Return']*100:+5.1f}% | {row['Vol_Ratio']:.1f}x | {signal}")

def summarize_squeeze_pattern(ticker):
    """Summarize the pattern before Gamma Squeezes."""
    big_moves, data = find_big_moves(ticker, threshold=0.05)
    
    # Analyze top 3 biggest up moves
    top_squeezes = big_moves[big_moves["Return"] > 0].nlargest(3, "Return")
    
    print(f"\n=== {ticker} Pre-Squeeze Pattern Analysis ===")
    for date, row in top_squeezes.iterrows():
        analyze_before_squeeze(ticker, date.strftime("%Y-%m-%d"))

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        summarize_squeeze_pattern(ticker)
        print("\n" + "="*70)