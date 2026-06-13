from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

import requests
import yfinance as yf

from config import FMP_API_KEY


FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
YFINANCE_FALLBACKS = {
    "DXY": "DX-Y.NYB",
    "WTI": "CL=F",
    "Copper": "HG=F",
}


def date_window(today: Optional[date] = None) -> Tuple[str, str]:
    end = today or date.today()
    return (end - timedelta(days=30)).isoformat(), end.isoformat()


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_fmp_macro(endpoint: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    start, end = date_window()
    try:
        response = requests.get(
            f"{FMP_BASE_URL}/{endpoint}",
            params={"from": start, "to": end, "apikey": api_key or FMP_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def fetch_yfinance_fallback(label: str) -> Dict[str, Any]:
    symbol = YFINANCE_FALLBACKS[label]
    try:
        history = yf.Ticker(symbol).history(period="5d")
        closes = history["Close"].dropna()
        if closes.empty:
            raise ValueError("No close values")
        value = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else None
        return {
            "label": label,
            "value": value,
            "delta": value - previous if previous is not None else None,
            "source": f"yfinance fallback: {symbol}",
        }
    except Exception:
        return {"label": label, "value": None, "delta": None, "source": "N/A"}


def format_macro_value(value: Any) -> str:
    numeric = _safe_float(value)
    return f"{numeric:.2f}" if numeric is not None else "N/A"


def macro_risk_score(items: Dict[str, Any]) -> float:
    values = []
    for name in ("VIX", "DXY", "WTI", "Copper"):
        item = items.get(name, {})
        value = item.get("value") if isinstance(item, dict) else item
        numeric = _safe_float(value)
        if numeric is not None:
            values.append(numeric)
    return sum(values) / len(values) if values else 0.0
