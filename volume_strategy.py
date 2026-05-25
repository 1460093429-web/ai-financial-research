import yfinance as yf
import pandas as pd

def volume_strategy(ticker, period="1y"):
    data = yf.Ticker(ticker).history(period=period)
    
    # Volume moving average
    data["Vol_MA20"] = data["Volume"].rolling(window=20).mean()
    data["Vol_Ratio"] = data["Volume"] / data["Vol_MA20"]
    
    # Price change
    data["Price_Change"] = data["Close"].pct_change()
    
    strong_buy = data[
        (data["Vol_Ratio"] > 1.5) &
        (data["Price_Change"] > 0.02)
    ]
    
    strong_sell = data[
        (data["Vol_Ratio"] > 1.5) &
        (data["Price_Change"] < -0.02)
    ]
    
    weak_up = data[
        (data["Vol_Ratio"] < 0.7) &
        (data["Price_Change"] > 0.01)
    ]
    
    print(f"\n=== {ticker} Volume Strategy ===")
    print(f"Current Volume Ratio: {data['Vol_Ratio'].iloc[-1]:.2f}x average")
    print(f"Current Price Change: {data['Price_Change'].iloc[-1]*100:.2f}%")
    
    print(f"\n🟢 Strong Buy Signals (High Volume + Price Up) [{len(strong_buy)}]:")
    for date, row in strong_buy.tail(5).iterrows():
        print(f"  {date.strftime('%Y-%m-%d')} | ${row['Close']:.2f} | Vol: {row['Vol_Ratio']:.1f}x | Change: {row['Price_Change']*100:.1f}%")
    
    print(f"\n🔴 Strong Sell Signals (High Volume + Price Down) [{len(strong_sell)}]:")
    for date, row in strong_sell.tail(5).iterrows():
        print(f"  {date.strftime('%Y-%m-%d')} | ${row['Close']:.2f} | Vol: {row['Vol_Ratio']:.1f}x | Change: {row['Price_Change']*100:.1f}%")
    
    print(f"\n⚠️  Weak Signals (Low Volume + Price Up) [{len(weak_up)}]:")
    for date, row in weak_up.tail(3).iterrows():
        print(f"  {date.strftime('%Y-%m-%d')} | ${row['Close']:.2f} | Vol: {row['Vol_Ratio']:.1f}x | Change: {row['Price_Change']*100:.1f}%")
    
    return data

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        volume_strategy(ticker)