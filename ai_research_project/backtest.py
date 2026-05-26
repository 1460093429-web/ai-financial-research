from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


BASE_DIR = Path(__file__).resolve().parent
SIGNALS_FILE = BASE_DIR / "signals.csv"
HORIZON_TRADING_DAYS = 3
NEUTRAL_RETURN_THRESHOLD = 0.01

SIGNAL_COLUMNS = [
    "date",
    "ticker",
    "signal",
    "confidence",
    "price",
    "horizon_days",
    "future_date",
    "future_price",
    "return_pct",
    "result",
    "trend_alignment",
    "score",
]


def _empty_signal_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SIGNAL_COLUMNS)


def load_signals() -> pd.DataFrame:
    if not SIGNALS_FILE.exists():
        return _empty_signal_frame()

    df = pd.read_csv(SIGNALS_FILE)
    for column in SIGNAL_COLUMNS:
        if column not in df.columns:
            df[column] = None
    return df[SIGNAL_COLUMNS]


def _latest_close(ticker: str) -> float:
    history = yf.Ticker(ticker).history(period="5d")
    if history.empty:
        raise ValueError(f"No price data found for {ticker}")
    return float(history["Close"].dropna().iloc[-1])


def _trend_alignment(ticker: str, signal: str) -> float:
    if signal == "NEUTRAL":
        return 0.5

    history = yf.Ticker(ticker).history(period="3mo")
    closes = history["Close"].dropna()
    if len(closes) < 20:
        return 0.0

    latest_close = float(closes.iloc[-1])
    ma20 = float(closes.rolling(20).mean().iloc[-1])

    if signal == "BULLISH":
        return 1.0 if latest_close >= ma20 else 0.0
    if signal == "BEARISH":
        return 1.0 if latest_close <= ma20 else 0.0
    return 0.0


def _score(confidence: float, trend_alignment: float, accuracy: Optional[float]) -> float:
    accuracy_component = 0.5 if accuracy is None else accuracy
    return round(
        (accuracy_component * 0.50)
        + (float(confidence) * 0.30)
        + (float(trend_alignment) * 0.20),
        4,
    )


def _historical_accuracy(df: pd.DataFrame, ticker: str) -> Optional[float]:
    completed = df[
        (df["ticker"] == ticker)
        & (df["result"].isin(["WIN", "LOSS"]))
    ]
    if completed.empty:
        return None
    return float((completed["result"] == "WIN").mean())


def save_signal(ticker: str, signal: str, confidence: float) -> pd.DataFrame:
    df = load_signals()
    signal_date = date.today().isoformat()
    price = _latest_close(ticker)
    trend_alignment = _trend_alignment(ticker, signal)
    accuracy = _historical_accuracy(df, ticker)
    score = _score(confidence, trend_alignment, accuracy)

    same_signal_day = (
        (df["date"].astype(str) == signal_date)
        & (df["ticker"].astype(str) == ticker)
    )

    row = {
        "date": signal_date,
        "ticker": ticker,
        "signal": signal,
        "confidence": float(confidence),
        "price": price,
        "horizon_days": HORIZON_TRADING_DAYS,
        "future_date": None,
        "future_price": None,
        "return_pct": None,
        "result": "PENDING",
        "trend_alignment": trend_alignment,
        "score": score,
    }

    if same_signal_day.any():
        row_index = df.index[same_signal_day][0]
        for key, value in row.items():
            df.at[row_index, key] = value
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    df.to_csv(SIGNALS_FILE, index=False)
    return df


def _evaluate_signal(row: pd.Series) -> dict:
    signal_date = pd.to_datetime(row["date"]).date()
    history = yf.Ticker(row["ticker"]).history(
        start=signal_date.isoformat(),
        end=(datetime.now().date() + timedelta(days=1)).isoformat(),
    )

    closes = history["Close"].dropna()
    if closes.empty:
        return {"result": "PENDING"}

    future_closes = closes[closes.index.date > signal_date]
    if len(future_closes) < HORIZON_TRADING_DAYS:
        return {"result": "PENDING"}

    future_date = future_closes.index[HORIZON_TRADING_DAYS - 1].date().isoformat()
    future_price = float(future_closes.iloc[HORIZON_TRADING_DAYS - 1])
    entry_price = float(row["price"])
    return_pct = (future_price - entry_price) / entry_price

    if row["signal"] == "BULLISH":
        success = return_pct > 0
    elif row["signal"] == "BEARISH":
        success = return_pct < 0
    else:
        success = abs(return_pct) <= NEUTRAL_RETURN_THRESHOLD

    return {
        "future_date": future_date,
        "future_price": future_price,
        "return_pct": return_pct,
        "result": "WIN" if success else "LOSS",
    }


def backtest_signals(ticker: Optional[str] = None) -> Optional[dict]:
    df = load_signals()
    if df.empty:
        return None

    scope = df if ticker is None else df[df["ticker"] == ticker]
    if scope.empty:
        return None

    for index, row in scope.iterrows():
        if row.get("result") in ("WIN", "LOSS"):
            continue

        try:
            updates = _evaluate_signal(row)
        except Exception:
            updates = {"result": "PENDING"}

        for key, value in updates.items():
            df.at[index, key] = value

    ticker_mask = (
        df["ticker"] == ticker
        if ticker is not None
        else pd.Series(True, index=df.index)
    )
    completed = df[
        ticker_mask & (df["result"].isin(["WIN", "LOSS"]))
    ]
    pending = df[
        ticker_mask & (df["result"] == "PENDING")
    ]

    for ticker_name in df["ticker"].dropna().unique():
        accuracy = _historical_accuracy(df, ticker_name)
        if accuracy is None:
            continue
        rows = df["ticker"] == ticker_name
        df.loc[rows, "score"] = df.loc[rows].apply(
            lambda item: _score(
                item["confidence"],
                item["trend_alignment"],
                accuracy,
            ),
            axis=1,
        )

    df.to_csv(SIGNALS_FILE, index=False)

    win_rate = (
        float((completed["result"] == "WIN").mean())
        if not completed.empty
        else 0.0
    )

    return {
        "win_rate": win_rate,
        "total_signals": int(len(completed)),
        "pending_signals": int(len(pending)),
        "signals": df if ticker is None else df[df["ticker"] == ticker],
    }
