import yfinance as yf
import pandas as pd

def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def moving_average_rsi_strategy(ticker, period="1y"):
    # Fetch historical data
    data = yf.Ticker(ticker).history(period=period)
    
    # Calculate moving averages
    data["MA5"] = data["Close"].rolling(window=5).mean()
    data["MA20"] = data["Close"].rolling(window=20).mean()
    
    # Calculate RSI
    data["RSI"] = calculate_rsi(data)
    
    # Generate signals
    data["Signal"] = 0
    data.loc[data["MA5"] > data["MA20"], "Signal"] = 1   # Buy
    data.loc[data["MA5"] < data["MA20"], "Signal"] = -1  # Sell
    
    # Detect crossovers
    data["Position"] = data["Signal"].diff()
    
    buy_signals = data[
        (data["Position"] == 2) & 
        (data["RSI"] < 70)  # Not overbought
    ]
    sell_signals = data[
        (data["Position"] == -2) | 
        (data["RSI"] > 70)  # Overbought - sell
    ]
    
    # RSI oversold buy signals
    rsi_buy = data[
        (data["RSI"] < 30) &  # Oversold
        (data["RSI"].shift(1) >= 30)  # Just crossed below 30
    ]
    
    print(f"\n=== {ticker} MA + RSI Strategy ===")
    print(f"Period: {period}")
    print(f"Current Price: ${data['Close'].iloc[-1]:.2f}")
    print(f"Current RSI: {data['RSI'].iloc[-1]:.1f}", end=" ")
    
    rsi_now = data['RSI'].iloc[-1]
    if rsi_now > 70:
        print("⚠️  OVERBOUGHT")
    elif rsi_now < 30:
        print("⚠️  OVERSOLD")
    else:
        print("✅ Normal")
    
    print(f"\nMA Buy Signals ({len(buy_signals)}):")
    for date, row in buy_signals.iterrows():
        print(f"  BUY  {date.strftime('%Y-%m-%d')} | Price: ${row['Close']:.2f} | RSI: {row['RSI']:.1f}")
    
    print(f"\nRSI Oversold Buy Signals ({len(rsi_buy)}):")
    for date, row in rsi_buy.iterrows():
        print(f"  BUY  {date.strftime('%Y-%m-%d')} | Price: ${row['Close']:.2f} | RSI: {row['RSI']:.1f}")
    
    print(f"\nSell Signals ({len(sell_signals)}):")
    for date, row in sell_signals.iterrows():
        print(f"  SELL {date.strftime('%Y-%m-%d')} | Price: ${row['Close']:.2f} | RSI: {row['RSI']:.1f}")
    
    return data

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        moving_average_rsi_strategy(ticker)