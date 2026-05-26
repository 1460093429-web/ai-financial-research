from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf

from analyst_db import get_analyst_records
from analyst_distribution import build_aggregate_proxy_records, summarize_distribution
from options import get_options_data as fetch_options_data


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, "technical.db")


def normalize_ticker(ticker: Any) -> str:
    value = str(ticker or "").upper().strip()
    if "." in value:
        symbol, suffix = value.split(".", 1)
        if suffix in {"O", "N", "A", "K"}:
            return symbol
    return value


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def empty_analyst_data(ticker: Any = "") -> Dict[str, Any]:
    return {
        "Ticker": normalize_ticker(ticker),
        "Market Price": None,
        "Consensus Target Price": None,
        "Median Target Price": None,
        "Low Target Price": None,
        "High Target Price": None,
        "Weighted Target Price": None,
        "Upside/Downside %": None,
        "Analyst Sentiment": "Neutral",
        "Analyst Count": 0,
        "Divergence %": None,
        "Top Analysts influence": "No broker-level rows available",
        "Recommendation": None,
        "Recommendation Mean": None,
        "source": "fallback",
    }


def empty_options_data(ticker: Any = "") -> Dict[str, Any]:
    return {
        "ticker": normalize_ticker(ticker),
        "expiry": "N/A",
        "calls": pd.DataFrame(columns=["strike", "openInterest", "volume", "impliedVolatility"]),
        "puts": pd.DataFrame(columns=["strike", "openInterest", "volume", "impliedVolatility"]),
        "call_oi": 0,
        "put_oi": 0,
        "call_volume": 0,
        "put_volume": 0,
        "pc_ratio": 0.0,
        "max_pain": 0.0,
        "bias_score": 0.0,
        "signal": "NEUTRAL",
        "confidence": 0.0,
        "source": "fallback",
    }


def empty_market_data(ticker: Any = "") -> Dict[str, Any]:
    return {
        "ticker": normalize_ticker(ticker),
        "price": None,
        "previous": None,
        "change_pct": None,
        "status": "No Data",
    }


def empty_technical_data(ticker: Any = "") -> Dict[str, Any]:
    return {
        "ticker": normalize_ticker(ticker),
        "history": pd.DataFrame(columns=["Date", "Close", "Volume", "MA5", "MA20", "RSI"]),
        "current_price": None,
        "rsi": None,
        "status": "No Data",
    }


def default_macro_item(indicator: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **indicator,
        "value": None,
        "delta": None,
        "symbol": (indicator.get("symbols") or [indicator.get("series_id") or "N/A"])[0],
        "status": "No Data",
    }


def calculate_rsi(data: pd.DataFrame, window: int = 14) -> pd.Series:
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def init_technical_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS technical_history (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                close REAL,
                volume REAL,
                ma5 REAL,
                ma20 REAL,
                rsi REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date)
            )
            """
        )


def save_technical_history(ticker: str, history: pd.DataFrame) -> None:
    if history.empty:
        return
    init_technical_db()
    rows = []
    for index, row in history.iterrows():
        rows.append(
            (
                ticker,
                pd.Timestamp(index).date().isoformat(),
                safe_float(row.get("Close")),
                safe_float(row.get("Volume")),
                safe_float(row.get("MA5")),
                safe_float(row.get("MA20")),
                safe_float(row.get("RSI")),
            )
        )
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO technical_history
                (ticker, date, close, volume, ma5, ma20, rsi)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def load_cached_technical_history(ticker: str) -> pd.DataFrame:
    init_technical_db()
    with sqlite3.connect(DB_PATH) as conn:
        cached = pd.read_sql_query(
            """
            SELECT date AS Date, close AS Close, volume AS Volume,
                   ma5 AS MA5, ma20 AS MA20, rsi AS RSI
            FROM technical_history
            WHERE ticker = ?
            ORDER BY date
            """,
            conn,
            params=(ticker,),
        )
    if cached.empty:
        return cached
    cached["Date"] = pd.to_datetime(cached["Date"])
    return cached.set_index("Date")


def get_market_data(ticker: Any) -> Dict[str, Any]:
    normalized = normalize_ticker(ticker)
    try:
        data = yf.Ticker(normalized).history(period="5d")
        if data is None or data.empty or "Close" not in data:
            return empty_market_data(normalized)
        closes = data["Close"].dropna()
        if closes.empty:
            return empty_market_data(normalized)
        price = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else None
        return {
            "ticker": normalized,
            "price": price,
            "previous": previous,
            "change_pct": ((price - previous) / previous * 100) if previous else None,
            "status": "OK",
        }
    except Exception:
        return empty_market_data(normalized)


def get_latest_price(ticker: Any) -> Optional[float]:
    normalized = normalize_ticker(ticker)
    try:
        last_price = safe_float(yf.Ticker(normalized).fast_info.get("last_price"))
        if last_price is not None:
            return last_price
    except Exception:
        pass
    return get_market_data(normalized)["price"]


def analyst_sentiment(recommendation: Any, upside_pct: Optional[float]) -> str:
    recommendation_text = str(recommendation or "").lower()
    if recommendation_text in ("buy", "strong_buy"):
        return "Bullish"
    if recommendation_text in ("sell", "strong_sell", "underperform"):
        return "Bearish"
    if upside_pct is None:
        return "Neutral"
    if upside_pct >= 10:
        return "Bullish"
    if upside_pct <= -10:
        return "Bearish"
    return "Neutral"


def weighted_target_price(analysts: Iterable[Dict[str, Any]]) -> Optional[float]:
    total_weight = 0.0
    weighted_sum = 0.0
    for analyst in analysts:
        target = safe_float(analyst.get("target"))
        if target is None:
            continue
        weight = (
            analyst.get("historical_accuracy", 1.0)
            * analyst.get("credibility", 1.0)
            * analyst.get("recency_factor", 1.0)
        )
        weighted_sum += target * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight else None


def get_analyst_data(ticker: Any) -> Dict[str, Any]:
    normalized = normalize_ticker(ticker)
    result = empty_analyst_data(normalized)
    current_price = get_latest_price(normalized)
    result["Market Price"] = current_price

    try:
        stock = yf.Ticker(normalized)
        raw_targets = {}
        try:
            targets = stock.analyst_price_targets
            if isinstance(targets, dict):
                raw_targets = targets
            elif hasattr(targets, "to_dict"):
                raw_targets = targets.to_dict()
        except Exception:
            raw_targets = {}

        normalized_targets = {
            str(key).lower().replace(" ", "_"): value
            for key, value in raw_targets.items()
        }

        def target_value(*keys: str) -> Optional[float]:
            for key in keys:
                value = safe_float(normalized_targets.get(key.lower().replace(" ", "_")))
                if value is not None:
                    return value
            return None

        result["Consensus Target Price"] = target_value(
            "mean",
            "target_mean_price",
            "mean_target",
            "median",
            "target_median_price",
        )
        result["Median Target Price"] = target_value("median", "target_median_price")
        result["Low Target Price"] = target_value("low", "target_low_price")
        result["High Target Price"] = target_value("high", "target_high_price")

        try:
            info = stock.get_info()
        except Exception:
            info = getattr(stock, "info", {}) or {}
        if isinstance(info, dict):
            result["Recommendation"] = info.get("recommendationKey") or info.get("recommendation")
            result["Recommendation Mean"] = safe_float(info.get("recommendationMean"))
            result["Analyst Count"] = safe_float(info.get("numberOfAnalystOpinions")) or 0
    except Exception:
        pass

    db_records = get_analyst_records(normalized)
    aggregate_records = build_aggregate_proxy_records(
        normalized,
        result["Consensus Target Price"],
        result["Median Target Price"],
        result["Low Target Price"],
        result["High Target Price"],
    )
    distribution = summarize_distribution(aggregate_records + db_records, current_price)

    if result["Consensus Target Price"] is None:
        result["Consensus Target Price"] = distribution["mean_target"]
    result["Weighted Target Price"] = distribution["weighted_mean_target"]
    if result["Weighted Target Price"] is None:
        result["Weighted Target Price"] = result["Consensus Target Price"]

    if result["Low Target Price"] is None:
        result["Low Target Price"] = distribution["low_target"]
    if result["High Target Price"] is None:
        result["High Target Price"] = distribution["high_target"]
    if result["Median Target Price"] is None:
        result["Median Target Price"] = distribution["base_target"]

    weighted_target = result["Weighted Target Price"]
    if current_price not in (None, 0) and weighted_target is not None:
        result["Upside/Downside %"] = (weighted_target - current_price) / current_price * 100

    consensus = result["Consensus Target Price"]
    low_target = result["Low Target Price"]
    high_target = result["High Target Price"]
    if consensus not in (None, 0) and low_target is not None and high_target is not None:
        result["Divergence %"] = (high_target - low_target) / consensus * 100

    if db_records:
        result["Analyst Count"] = max(int(result["Analyst Count"] or 0), len(db_records))
        result["Top Analysts influence"] = f"{len(db_records)} broker-level rows"

    result["Analyst Sentiment"] = analyst_sentiment(
        result["Recommendation"],
        result["Upside/Downside %"],
    )
    result["source"] = "yfinance+analyst_db" if aggregate_records or db_records else "fallback"
    return result


def get_macro_data(
    market_indicators: List[Dict[str, Any]],
    fred_indicators: List[Dict[str, Any]],
    fetch_market_indicator,
    fetch_fred_indicator,
) -> List[Dict[str, Any]]:
    panel = []
    for indicator in market_indicators:
        try:
            panel.append({**indicator, **fetch_market_indicator(indicator["symbols"], indicator["format"])})
        except Exception:
            panel.append(default_macro_item(indicator))
    for indicator in fred_indicators:
        try:
            panel.append({**indicator, **fetch_fred_indicator(indicator["series_id"], indicator["format"])})
        except Exception:
            panel.append(default_macro_item(indicator))
    sort_order = [
        "10Y Treasury",
        "Fed Funds Rate",
        "CPI",
        "DXY",
        "VIX",
        "USD/CNY",
        "USD/JPY",
        "EUR/USD",
    ]
    return sorted(panel, key=lambda item: sort_order.index(item["label"]))


def get_technical_data(ticker: Any, period: str = "6mo") -> Dict[str, Any]:
    normalized = normalize_ticker(ticker)
    try:
        init_technical_db()
        data = yf.Ticker(normalized).history(period=period)
        if data is None or data.empty:
            cached = load_cached_technical_history(normalized)
            if cached.empty:
                return empty_technical_data(normalized)
            data = cached
        else:
            data = data.copy()
            data["MA5"] = data["Close"].rolling(5).mean()
            data["MA20"] = data["Close"].rolling(20).mean()
            data["RSI"] = calculate_rsi(data)
            save_technical_history(normalized, data)

        closes = data["Close"].dropna()
        rsi_values = data["RSI"].dropna() if "RSI" in data else pd.Series(dtype=float)
        return {
            "ticker": normalized,
            "history": data,
            "current_price": float(closes.iloc[-1]) if not closes.empty else None,
            "rsi": float(rsi_values.iloc[-1]) if not rsi_values.empty else None,
            "status": "OK",
        }
    except Exception as exc:
        fallback = empty_technical_data(normalized)
        fallback["status"] = str(exc)
        return fallback


def get_options_flow_data(ticker: Any) -> Dict[str, Any]:
    normalized = normalize_ticker(ticker)
    try:
        data = fetch_options_data(normalized)
        if not data:
            return empty_options_data(normalized)
        return {**empty_options_data(normalized), **data, "ticker": normalized, "source": "yfinance"}
    except Exception:
        return empty_options_data(normalized)


def get_options_data(ticker: Any) -> Dict[str, Any]:
    return get_options_flow_data(ticker)
