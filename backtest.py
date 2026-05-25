import yfinance as yf
import pandas as pd

def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def backtest(ticker, period="1y", initial_capital=10000):
    data = yf.Ticker(ticker).history(period=period)
    
    data["MA5"] = data["Close"].rolling(window=5).mean()
    data["MA20"] = data["Close"].rolling(window=20).mean()
    data["RSI"] = calculate_rsi(data)
    
    capital = initial_capital
    shares = 0
    trades = []
    
    for i in range(1, len(data)):
        price = data["Close"].iloc[i]
        rsi = data["RSI"].iloc[i]
        ma5 = data["MA5"].iloc[i]
        ma20 = data["MA20"].iloc[i]
        date = data.index[i].strftime("%Y-%m-%d")
        
        if ma5 > ma20 and data["MA5"].iloc[i-1] <= data["MA20"].iloc[i-1]:
            if rsi < 70 and capital > 0:
                shares = capital / price
                capital = 0
                trades.append({"date": date, "action": "BUY", "price": price, "rsi": rsi})
        
        elif (ma5 < ma20 and data["MA5"].iloc[i-1] >= data["MA20"].iloc[i-1]) or rsi > 75:
            if shares > 0:
                capital = shares * price
                shares = 0
                trades.append({"date": date, "action": "SELL", "price": price, "rsi": rsi})
    
    final_value = capital + shares * data["Close"].iloc[-1]
    profit = final_value - initial_capital
    return_pct = (profit / initial_capital) * 100
    
    print(f"\n=== {ticker} Backtest Results ===")
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Final Value:     ${final_value:,.2f}")
    print(f"Profit/Loss:     ${profit:,.2f}")
    print(f"Return:          {return_pct:.1f}%")
    print(f"Total Trades:    {len(trades)}")
    print(f"\nTrade History:")
    for t in trades:
        print(f"  {t['action']} {t['date']} | ${t['price']:.2f} | RSI: {t['rsi']:.1f}")
    
    return final_value, return_pct

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        backtest(ticker, period="1y", initial_capital=10000)