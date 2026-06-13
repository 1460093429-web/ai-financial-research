from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yfinance as yf


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SIGNALS_FILE = BASE_DIR / "signals.csv"
HORIZON_TRADING_DAYS = 3
NEUTRAL_RETURN_THRESHOLD = 0.01

DATE_COLUMNS = [
    "date",
    "future_date",
]

TEXT_COLUMNS = [
    "ticker",
    "signal",
    "result",
]

NUMERIC_COLUMNS = [
    "confidence",
    "price",
    "horizon_days",
    "future_price",
    "return_pct",
    "trend_alignment",
    "score",
]

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
    return pd.DataFrame(
        {
            **{column: pd.Series(dtype="object") for column in DATE_COLUMNS},
            **{column: pd.Series(dtype="string") for column in TEXT_COLUMNS},
            **{column: pd.Series(dtype="float64") for column in NUMERIC_COLUMNS},
        }
    )[SIGNAL_COLUMNS]


def _coerce_numeric(
    values: pd.Series,
    field: str,
    ticker: Any = None,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = values.notna() & numeric.isna()
    if invalid.any():
        if isinstance(ticker, pd.Series):
            invalid_rows = pd.DataFrame(
                {"ticker": ticker, "value": values}
            ).loc[invalid]
            for ticker_name, rows in invalid_rows.groupby("ticker", dropna=False):
                logger.warning(
                    "Numeric coercion dropped non-numeric value(s): ticker=%s field=%s values=%s",
                    ticker_name,
                    field,
                    rows["value"].astype(str).unique().tolist(),
                )
        else:
            logger.warning(
                "Numeric coercion dropped non-numeric value(s): ticker=%s field=%s values=%s",
                ticker or "unknown",
                field,
                values[invalid].astype(str).unique().tolist(),
            )
    return numeric


def _normalize_signal_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in SIGNAL_COLUMNS:
        if column not in df.columns:
            df[column] = None

    for column in DATE_COLUMNS:
        df[column] = df[column].astype("object")
    for column in TEXT_COLUMNS:
        df[column] = df[column].astype("string")
    for column in NUMERIC_COLUMNS:
        df[column] = _coerce_numeric(df[column], column, df["ticker"])
    return df[SIGNAL_COLUMNS]


def load_signals() -> pd.DataFrame:
    if not SIGNALS_FILE.exists():
        return _empty_signal_frame()

    return _normalize_signal_frame(pd.read_csv(SIGNALS_FILE))


def _normalize_history(history: Any, ticker: str) -> pd.DataFrame:
    if history is None:
        return pd.DataFrame(columns=["Close"])

    if isinstance(history, dict):
        history = history.get("historical", history)
    frame = pd.DataFrame(history).copy()
    if frame.empty:
        return pd.DataFrame(columns=["Close"])

    columns = {str(column).lower(): column for column in frame.columns}
    close_column = columns.get("close")
    if close_column is None:
        logger.warning("Historical data missing close field: ticker=%s", ticker)
        return pd.DataFrame(columns=["Close"])

    date_column = columns.get("date")
    if date_column is not None:
        history_dates = pd.to_datetime(frame[date_column], errors="coerce")
        invalid_dates = frame[date_column].notna() & history_dates.isna()
        if invalid_dates.any():
            logger.warning(
                "Date coercion dropped invalid value(s): ticker=%s field=%s values=%s",
                ticker,
                date_column,
                frame.loc[invalid_dates, date_column].astype(str).unique().tolist(),
            )
        frame.index = history_dates
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce")

    frame["Close"] = _coerce_numeric(frame[close_column], str(close_column), ticker)
    frame = frame[frame.index.notna()].sort_index()
    return frame[["Close"]]


def _latest_close(ticker: str) -> float:
    history = _normalize_history(yf.Ticker(ticker).history(period="5d"), ticker)
    if history.empty:
        raise ValueError(f"No price data found for {ticker}")
    return float(history["Close"].dropna().iloc[-1])


def _trend_alignment(ticker: str, signal: str) -> float:
    if signal == "NEUTRAL":
        return 0.5

    history = _normalize_history(yf.Ticker(ticker).history(period="3mo"), ticker)
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

    df = _normalize_signal_frame(df)
    df.to_csv(SIGNALS_FILE, index=False)
    return df


def _evaluate_signal(row: pd.Series) -> dict:
    signal_date = pd.to_datetime(row["date"]).date()
    ticker = str(row["ticker"])
    history = _normalize_history(
        yf.Ticker(ticker).history(
            start=signal_date.isoformat(),
            end=(datetime.now().date() + timedelta(days=1)).isoformat(),
        ),
        ticker,
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
            logger.exception("Signal evaluation failed: ticker=%s", row.get("ticker"))
            updates = {"result": "PENDING"}

        for key, value in updates.items():
            if key in NUMERIC_COLUMNS:
                value = _coerce_numeric(
                    pd.Series([value]),
                    key,
                    str(row.get("ticker") or ticker or ""),
                ).iloc[0]
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

    df = _normalize_signal_frame(df)
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
