import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

PORTFOLIO = {
    "total_capital": 100000,
    "max_risk_per_trade": 0.02,
    "stop_loss_pct": 0.15,
    "take_profit_pct": 0.20,
}

def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def risk_backtest(ticker, period="1y"):
    data = yf.Ticker(ticker).history(period=period)
    capital = PORTFOLIO["total_capital"]
    initial_capital = capital
    stop_loss_pct = PORTFOLIO["stop_loss_pct"]
    take_profit_pct = PORTFOLIO["take_profit_pct"]
    max_risk_per_trade = PORTFOLIO["max_risk_per_trade"]

    shares = 0
    entry_price = 0
    stop_loss_price = 0
    take_profit_price = 0
    trades = []
    equity_curve = []

    data["RSI"] = calculate_rsi(data)
    data["MA5"] = data["Close"].rolling(5).mean()
    data["MA20"] = data["Close"].rolling(20).mean()
    data["Vol_Ratio"] = data["Volume"] / data["Volume"].rolling(20).mean()

    for i in range(20, len(data)):
        price = data["Close"].iloc[i]
        date = data.index[i].strftime("%Y-%m-%d")
        rsi = data["RSI"].iloc[i]
        ma5 = data["MA5"].iloc[i]
        ma20 = data["MA20"].iloc[i]
        vol_ratio = data["Vol_Ratio"].iloc[i]

        current_value = capital + shares * price
        equity_curve.append(current_value)

        # Check stop loss and take profit
        if shares > 0:
            if price <= stop_loss_price:
                capital += shares * price
                trades.append({
                    "date": date,
                    "action": "STOP LOSS",
                    "price": price,
                    "entry": entry_price,
                    "pnl": (price - entry_price) / entry_price * 100,
                    "capital": capital
                })
                shares = 0

            elif price >= take_profit_price:
                capital += shares * price
                trades.append({
                    "date": date,
                    "action": "TAKE PROFIT",
                    "price": price,
                    "entry": entry_price,
                    "pnl": (price - entry_price) / entry_price * 100,
                    "capital": capital
                })
                shares = 0

        # Buy signal
        if shares == 0 and capital > 0:
            buy_signal = (
                ma5 > ma20 and
                rsi < 65 and
                vol_ratio > 0.8
            )

            if buy_signal:
                max_position = capital * 0.25
                risk_per_share = price * stop_loss_pct
                max_dollar_risk = capital * max_risk_per_trade
                shares_to_buy = max_dollar_risk / risk_per_share
                position_value = shares_to_buy * price

                if position_value > max_position:
                    shares_to_buy = max_position / price
                    position_value = max_position

                shares = shares_to_buy
                capital -= position_value
                entry_price = price
                stop_loss_price = price * (1 - stop_loss_pct)
                take_profit_price = price * (1 + take_profit_pct)

                trades.append({
                    "date": date,
                    "action": "BUY",
                    "price": price,
                    "entry": entry_price,
                    "pnl": 0,
                    "capital": capital
                })

    # Final value
    final_value = capital + shares * data["Close"].iloc[-1]
    profit = final_value - initial_capital
    return_pct = (profit / initial_capital) * 100

    # Buy & Hold
    bh_return = (data["Close"].iloc[-1] - data["Close"].iloc[20]) / data["Close"].iloc[20] * 100

    # Max drawdown
    equity = pd.Series(equity_curve)
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100
    max_dd = drawdown.min()

    # Win rate
    closed_trades = [t for t in trades if t["action"] in ["STOP LOSS", "TAKE PROFIT"]]
    wins = [t for t in closed_trades if t["pnl"] > 0]
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0

    print(f"\n=== {ticker} Risk-Managed Backtest ===")
    print(f"Stop Loss: {stop_loss_pct*100:.0f}% | Take Profit: {take_profit_pct*100:.0f}%")
    print(f"Initial Capital:  ${initial_capital:,.2f}")
    print(f"Final Value:      ${final_value:,.2f}")
    print(f"Return:           {return_pct:.1f}%")
    print(f"Buy & Hold:       {bh_return:.1f}%")
    print(f"Max Drawdown:     {max_dd:.1f}%")
    print(f"Total Trades:     {len(closed_trades)}")
    print(f"Win Rate:         {win_rate:.1f}%")

    print(f"\nTrade History:")
    for t in trades:
        if t["action"] == "BUY":
            print(f"  🟢 BUY         {t['date']} | ${t['price']:.2f}")
        elif t["action"] == "TAKE PROFIT":
            print(f"  ✅ TAKE PROFIT  {t['date']} | ${t['price']:.2f} | PnL: {t['pnl']:+.1f}%")
        elif t["action"] == "STOP LOSS":
            print(f"  🛑 STOP LOSS   {t['date']} | ${t['price']:.2f} | PnL: {t['pnl']:+.1f}%")

    return return_pct, bh_return, max_dd, win_rate

if __name__ == "__main__":
    print("Risk-Managed Backtest (Stop Loss 15%, Take Profit 20%)")
    print("=" * 60)

    results = []
    for company, ticker in WATCHLIST.items():
        ret, bh, dd, wr = risk_backtest(ticker, period="1y")
        results.append({
            "company": company,
            "return": ret,
            "buyhold": bh,
            "max_dd": dd,
            "win_rate": wr
        })

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Stock':<12} {'Return':>10} {'B&H':>10} {'MaxDD':>10} {'WinRate':>10}")
    print("-" * 55)
    for r in results:
        print(f"{r['company']:<12} {r['return']:>9.1f}% {r['buyhold']:>9.1f}% {r['max_dd']:>9.1f}% {r['win_rate']:>9.1f}%")
        