from datetime import datetime
import logging
from typing import Any, Dict, Optional

import requests
import yfinance as yf

from config import FMP_API_KEY


logger = logging.getLogger(__name__)
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


def get_tickers() -> Dict[str, str]:
    return {
        "NVIDIA": "NVDA",
        "Micron": "MU",
        "AMD": "AMD",
        "Intel": "INTC",
        "TSMC": "TSM",
        "Sandisk": "SNDK",
    }


def _safe_number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _financial_record(
    ticker: str,
    revenue: Any,
    net_income: Any,
    source: str,
) -> Dict[str, Any]:
    revenue_value = _safe_number(revenue) or 0
    net_income_value = _safe_number(net_income) or 0
    return {
        "Ticker": ticker,
        "Revenue": revenue_value,
        "NetIncome": net_income_value,
        "Margin": net_income_value / revenue_value if revenue_value else 0,
        "Source": source,
        "data_source": source,
        "timestamp": datetime.now().isoformat(),
    }


def _redact(value: Any, api_key: Optional[str]) -> str:
    text = str(value)
    return text.replace(api_key, "[REDACTED]") if api_key else text


def _get_fmp_financials(ticker: str, api_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None

    url = f"{FMP_BASE_URL}/income-statement/{ticker}"
    try:
        response = requests.get(
            url,
            params={"limit": 1, "apikey": api_key},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        if not isinstance(row, dict) or "revenue" not in row or "netIncome" not in row:
            return None
        return _financial_record(ticker, row["revenue"], row["netIncome"], "FMP")
    except Exception as exc:
        logger.warning(
            "FMP financial request failed: ticker=%s error=%s",
            ticker,
            _redact(exc, api_key),
        )
        return None


def _get_yfinance_financials(ticker: str) -> Dict[str, Any]:
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("yfinance financial fallback failed: ticker=%s error=%s", ticker, exc)
        info = {}
    return _financial_record(
        ticker,
        info.get("totalRevenue"),
        info.get("netIncomeToCommon"),
        "yfinance fallback",
    )


def get_financial_data(api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    key = FMP_API_KEY if api_key is None else api_key
    data = {}
    for name, ticker in get_tickers().items():
        data[name] = _get_fmp_financials(ticker, key) or _get_yfinance_financials(ticker)
    return data
