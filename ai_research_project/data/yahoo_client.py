import yfinance as yf


def get_current_price(symbol: str):

    ticker = yf.Ticker(symbol)

    history = ticker.history(period="5d")

    if history.empty:
        return None

    return history["Close"].dropna().iloc[-1]