import yfinance as yf
from datetime import datetime   # ✅ 必须加

def get_tickers():
    return {
        "NVIDIA": "NVDA",
        "Micron": "MU",
        "AMD": "AMD",
        "Intel": "INTC",
        "TSMC": "TSM",
        "Sandisk": "SNDK"
    }

def get_financial_data():
    data = {}

    for name, ticker in get_tickers().items():
        stock = yf.Ticker(ticker)
        info = stock.info

        revenue = info.get("totalRevenue", 0)
        net_income = info.get("netIncomeToCommon", 0)

        margin = net_income / revenue if revenue else 0

        data[name] = {
            "Ticker": ticker,
            "Revenue": revenue,
            "NetIncome": net_income,
            "Margin": margin,
            "data_source": "yfinance",   # ✅ 必须在 dict 里面
            "timestamp": datetime.now().isoformat()  # ✅ 时间戳
        }

    return data
