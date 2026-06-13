import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt


WEIGHTS = {
    "DRAM": 0.30,
    "MU": 0.30,
    "MUU": 0.20,
    "SNXX": 0.15,
    "LITE": 0.05,
}


def download_prices(tickers, start_date):
    all_prices = {}

    for ticker in tickers:
        data = yf.download(
            ticker,
            start=start_date,
            auto_adjust=True,
            progress=False
        )

        if data.empty:
            print(f"{ticker} 下载失败，跳过。")
            continue

        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"].iloc[:, 0]
        else:
            close = data["Close"]

        all_prices[ticker] = close.rename(ticker)

    if not all_prices:
        raise ValueError("没有成功下载任何股票数据。")

    prices = pd.concat(all_prices.values(), axis=1).dropna()
    return prices


def run_full_buy_hold(prices, weights, initial_capital=10000):
    """
    策略 A：
    100% 资金一次性按权重买入。
    """
    first_prices = prices.iloc[0]

    shares = {}
    cash = 0

    for ticker, weight in weights.items():
        if ticker not in prices.columns:
            continue

        amount = initial_capital * weight
        shares[ticker] = amount / first_prices[ticker]

    records = []

    for date, row in prices.iterrows():
        portfolio_value = cash

        for ticker, share_count in shares.items():
            portfolio_value += share_count * row[ticker]

        records.append({
            "Date": date,
            "Portfolio Value": portfolio_value,
            "Cash": cash,
        })

    result = pd.DataFrame(records).set_index("Date")
    result["Return %"] = (result["Portfolio Value"] / initial_capital - 1) * 100
    result["Peak"] = result["Portfolio Value"].cummax()
    result["Drawdown %"] = (result["Portfolio Value"] / result["Peak"] - 1) * 100

    return result, shares


def run_cash_add_strategy(
    prices,
    weights,
    initial_capital=10000,
    initial_invest_pct=0.70,
    cash_add_pct=0.30,
    pullback_trigger=0.05,
    add_tickers=("DRAM", "MU"),
):
    """
    策略 B：
    1. 初始只投入 70% 资金。
    2. 初始资金按 DRAM/MU/MUU/SNXX/LITE 同比例分配。
    3. 剩余 30% 保留现金。
    4. 只有 DRAM 和 MU 触发加仓。
    5. 当 DRAM 或 MU 从最近一次买入价回撤 5%，使用当前剩余现金的 30% 加仓该股票。
    """

    first_prices = prices.iloc[0]

    cash = initial_capital * (1 - initial_invest_pct)
    shares = {}
    last_buy_price = {}
    trades = []

    # 初始买入
    for ticker, weight in weights.items():
        if ticker not in prices.columns:
            continue

        amount = initial_capital * initial_invest_pct * weight
        shares[ticker] = amount / first_prices[ticker]
        last_buy_price[ticker] = first_prices[ticker]

        trades.append({
            "Date": prices.index[0],
            "Ticker": ticker,
            "Action": "Initial Buy",
            "Price": first_prices[ticker],
            "Amount": amount,
            "Shares": shares[ticker],
            "Cash After": cash,
        })

    records = []

    for date, row in prices.iterrows():
        portfolio_value = cash

        for ticker, share_count in shares.items():
            portfolio_value += share_count * row[ticker]

        records.append({
            "Date": date,
            "Portfolio Value": portfolio_value,
            "Cash": cash,
        })

        # 只对 DRAM 和 MU 做回撤加仓
        for ticker in add_tickers:
            if ticker not in prices.columns:
                continue

            if ticker not in shares:
                continue

            price = row[ticker]
            drawdown_from_last_buy = price / last_buy_price[ticker] - 1

            if drawdown_from_last_buy <= -pullback_trigger and cash > 10:
                add_amount = cash * cash_add_pct
                add_shares = add_amount / price

                cash -= add_amount
                shares[ticker] += add_shares
                last_buy_price[ticker] = price

                trades.append({
                    "Date": date,
                    "Ticker": ticker,
                    "Action": "Pullback Add Buy",
                    "Price": price,
                    "Amount": add_amount,
                    "Shares": add_shares,
                    "Cash After": cash,
                })

    result = pd.DataFrame(records).set_index("Date")
    trades_df = pd.DataFrame(trades)

    result["Return %"] = (result["Portfolio Value"] / initial_capital - 1) * 100
    result["Peak"] = result["Portfolio Value"].cummax()
    result["Drawdown %"] = (result["Portfolio Value"] / result["Peak"] - 1) * 100

    return result, shares, trades_df


def summarize_strategy(name, result, initial_capital=10000):
    final_value = result["Portfolio Value"].iloc[-1]
    total_return = final_value / initial_capital - 1
    max_drawdown = result["Drawdown %"].min()
    final_cash = result["Cash"].iloc[-1]

    return {
        "Strategy": name,
        "Final Value": final_value,
        "Return %": total_return * 100,
        "Max Drawdown %": max_drawdown,
        "Final Cash": final_cash,
    }


def plot_comparison(strategy_a, strategy_b):
    plt.figure(figsize=(14, 7))
    plt.plot(strategy_a.index, strategy_a["Return %"], label="Strategy A: 100% Buy & Hold")
    plt.plot(strategy_b.index, strategy_b["Return %"], label="Strategy B: 70% Initial + Pullback Add")
    plt.title("Portfolio Strategy Return % Comparison")
    plt.xlabel("Date")
    plt.ylabel("Return %")
    plt.legend()
    plt.grid(True)

    plt.figure(figsize=(14, 7))
    plt.plot(strategy_a.index, strategy_a["Drawdown %"], label="Strategy A Drawdown")
    plt.plot(strategy_b.index, strategy_b["Drawdown %"], label="Strategy B Drawdown")
    plt.title("Portfolio Drawdown % Comparison")
    plt.xlabel("Date")
    plt.ylabel("Drawdown %")
    plt.legend()
    plt.grid(True)

    plt.show()


if __name__ == "__main__":
    initial_capital = 10000

    tickers_input = input("请输入 ticker，默认 DRAM,MU,MUU,SNXX,LITE：").strip().upper()

    if tickers_input == "":
        tickers = ["DRAM", "MU", "MUU", "SNXX", "LITE"]
    else:
        tickers = [x.strip().upper() for x in tickers_input.split(",")]

    start_date = input("请输入开始日期，默认 2026-04-01：").strip()

    if start_date == "":
        start_date = "2026-04-01"

    prices = download_prices(tickers, start_date)

    # 根据成功下载的数据调整权重
    available_weights = {
        ticker: weight
        for ticker, weight in WEIGHTS.items()
        if ticker in prices.columns
    }

    total_weight = sum(available_weights.values())

    if total_weight == 0:
        raise ValueError("没有任何 ticker 权重可用。")

    available_weights = {
        ticker: weight / total_weight
        for ticker, weight in available_weights.items()
    }

    print("\n========== 使用的权重 ==========")
    for ticker, weight in available_weights.items():
        print(f"{ticker}: {weight:.2%}")

    strategy_a, shares_a = run_full_buy_hold(
        prices=prices,
        weights=available_weights,
        initial_capital=initial_capital,
    )

    strategy_b, shares_b, trades_b = run_cash_add_strategy(
        prices=prices,
        weights=available_weights,
        initial_capital=initial_capital,
        initial_invest_pct=0.70,
        cash_add_pct=0.30,
        pullback_trigger=0.05,
        add_tickers=("DRAM", "MU"),
    )

    summary = pd.DataFrame([
        summarize_strategy("A: 100% Buy & Hold", strategy_a, initial_capital),
        summarize_strategy("B: 70% Initial + DRAM/MU Pullback Add", strategy_b, initial_capital),
    ])

    print("\n========== 策略对比总结 ==========")
    display_summary = summary.copy()
    display_summary["Final Value"] = display_summary["Final Value"].map(lambda x: f"${x:,.2f}")
    display_summary["Return %"] = display_summary["Return %"].map(lambda x: f"{x:.2f}%")
    display_summary["Max Drawdown %"] = display_summary["Max Drawdown %"].map(lambda x: f"{x:.2f}%")
    display_summary["Final Cash"] = display_summary["Final Cash"].map(lambda x: f"${x:,.2f}")

    print(display_summary.to_string(index=False))

    print("\n========== 策略 B 交易记录 ==========")
    print(trades_b.to_string(index=False))

    # 保存结果
    strategy_a.to_csv("strategy_A_full_buy_hold.csv")
    strategy_b.to_csv("strategy_B_cash_add.csv")
    trades_b.to_csv("strategy_B_trades.csv", index=False)
    summary.to_csv("portfolio_strategy_summary.csv", index=False)

    print("\n已保存文件：")
    print("strategy_A_full_buy_hold.csv")
    print("strategy_B_cash_add.csv")
    print("strategy_B_trades.csv")
    print("portfolio_strategy_summary.csv")

    plot_comparison(strategy_a, strategy_b)