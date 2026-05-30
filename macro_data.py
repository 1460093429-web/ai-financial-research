import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import yfinance as yf

from config import get_fmp_api_key
from financials import _fmp_get, _number

logger = logging.getLogger(__name__)

MARKET_SERIES = {
    "EUR/USD": ("EURUSD", "EURUSD=X"),
    "USD/CNY": ("USDCNY", "CNY=X"),
    "USD/JPY": ("USDJPY", "JPY=X"),
    "DXY": ("DXUSD", "DX-Y.NYB"),
    "Brent crude oil": ("BZUSD", "BZ=F"),
    "WTI crude oil": ("CLUSD", "CL=F"),
    "Gold": ("GCUSD", "GC=F"),
    "Copper": ("HGUSD", "HG=F"),
}

HIGH_IMPORTANCE_US_EVENTS = (
    "cpi", "consumer price", "pce", "personal consumption expenditure",
    "nonfarm payroll", "non-farm payroll", "unemployment rate", "fomc",
    "fed interest rate decision", "federal reserve interest rate decision",
    "gdp", "ism pmi", "retail sales", "ppi", "producer price", "consumer confidence",
)


def _latest(items):
    return items[0] if isinstance(items, list) and items else {}


def _is_high_importance_us_event(country, event):
    return country == "US" and any(keyword in event.lower() for keyword in HIGH_IMPORTANCE_US_EVENTS)


def _yfinance_history(symbol, period="6mo"):
    try:
        frame = yf.Ticker(symbol).history(period=period)
        if frame.empty:
            return pd.DataFrame()
        result = frame.reset_index()
        date_column = "Date" if "Date" in result else result.columns[0]
        result = result[[date_column, "Close"]].rename(columns={date_column: "date", "Close": "value"})
        result["date"] = pd.to_datetime(result["date"]).dt.tz_localize(None)
        return result.dropna()
    except Exception as exc:
        logger.warning("%s: yfinance macro history fallback failed: %s", symbol, exc)
        return pd.DataFrame()


def _fmp_history(symbol, days=180):
    api_key = get_fmp_api_key()
    end = date.today()
    start = end - timedelta(days=days)
    data = _fmp_get("historical-price-eod/full", api_key, symbol=symbol, **{"from": str(start), "to": str(end)})
    if not isinstance(data, list) or not data:
        raise ValueError("historical-price-eod/full returned no usable data")
    frame = pd.DataFrame(data)
    if "date" not in frame or "close" not in frame:
        raise ValueError("historical-price-eod/full missing date or close")
    return frame[["date", "close"]].rename(columns={"close": "value"}).assign(date=lambda item: pd.to_datetime(item["date"])).sort_values("date")


@st.cache_data(ttl=900)
def fetch_market_series(label, days=180):
    fmp_symbol, yf_symbol = MARKET_SERIES[label]
    try:
        api_key = get_fmp_api_key()
        quote = _latest(_fmp_get("quote", api_key, symbol=fmp_symbol))
        if not quote:
            raise ValueError("quote returned no usable data")
        try:
            history = _fmp_history(fmp_symbol, days)
        except Exception as exc:
            logger.warning("%s: FMP macro history lookup failed: %s", label, exc)
            history = _yfinance_history(yf_symbol)
        return {"label": label, "value": _number(quote.get("price")), "source": "FMP", "history": history}
    except Exception as exc:
        logger.warning("%s: FMP macro quote lookup failed; using yfinance fallback: %s", label, exc)
        history = _yfinance_history(yf_symbol)
        value = None if history.empty else float(history["value"].iloc[-1])
        return {"label": label, "value": value, "source": "yfinance fallback", "history": history}


@st.cache_data(ttl=900)
def fetch_treasury_rates(days=180):
    end = date.today()
    start = end - timedelta(days=days)
    try:
        data = _fmp_get("treasury-rates", get_fmp_api_key(), **{"from": str(start), "to": str(end)})
        if not isinstance(data, list) or not data:
            raise ValueError("treasury-rates returned no usable data")
        frame = pd.DataFrame(data).assign(date=lambda item: pd.to_datetime(item["date"])).sort_values("date")
        latest = frame.iloc[-1]
        year10 = _number(latest.get("year10"))
        year2 = _number(latest.get("year2"))
        month3 = _number(latest.get("month3"))
        return {
            "source": "FMP", "history": frame, "year2": year2, "year10": year10,
            "year30": _number(latest.get("year30")), "spread_10y_2y": year10 - year2 if year10 is not None and year2 is not None else None,
            "spread_10y_3m": year10 - month3 if year10 is not None and month3 is not None else None,
        }
    except Exception as exc:
        logger.warning("Treasury rates: FMP lookup failed; using yfinance fallback where available: %s", exc)
        history = _yfinance_history("^TNX")
        year10 = None if history.empty else float(history["value"].iloc[-1])
        return {"source": "yfinance fallback", "history": history, "year2": None, "year10": year10, "year30": None, "spread_10y_2y": None, "spread_10y_3m": None}


@st.cache_data(ttl=86400)
def fetch_indicator(name, days=900):
    end = date.today()
    start = end - timedelta(days=days)
    try:
        data = _fmp_get("economic-indicators", get_fmp_api_key(), name=name, **{"from": str(start), "to": str(end)})
        if not isinstance(data, list) or not data:
            raise ValueError("economic-indicators returned no usable data")
        frame = pd.DataFrame(data).assign(date=lambda item: pd.to_datetime(item["date"])).sort_values("date")
        return {"name": name, "value": _number(frame.iloc[-1]["value"]), "source": "FMP", "history": frame[["date", "value"]]}
    except Exception as exc:
        logger.warning("%s: FMP economic indicator lookup failed: %s", name, exc)
        return {"name": name, "value": None, "source": "unavailable", "history": pd.DataFrame()}


@st.cache_data(ttl=3600)
def fetch_macro_calendar():
    start = date.today()
    end = start + timedelta(days=30)
    try:
        data = _fmp_get("economic-calendar", get_fmp_api_key(), **{"from": str(start), "to": str(end)})
        if not isinstance(data, list):
            raise ValueError("economic-calendar returned no usable data")
    except Exception as exc:
        logger.warning("Economic calendar: FMP lookup failed: %s", exc)
        data = []
    rows = []
    for item in data:
        event = item.get("event") or "N/A"
        country = item.get("country") or "N/A"
        important = _is_high_importance_us_event(country, event)
        event_date, _, event_time = (item.get("date") or "N/A").partition(" ")
        rows.append({
            "Date": event_date, "Time": event_time or "N/A", "Country": country,
            "Event": event, "Actual": item.get("actual"), "Estimate": item.get("estimate"),
            "Previous": item.get("previous"), "Impact": item.get("impact") or ("Important" if important else "N/A"),
            "Unit": item.get("unit") or "N/A", "Important": important,
        })
    rows.sort(key=lambda item: (item["Date"], item["Time"]))
    return {"start_date": str(start), "end_date": str(end), "events": rows, "source": "FMP", "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def build_macro_snapshot():
    rates = fetch_treasury_rates()
    markets = {label: fetch_market_series(label) for label in MARKET_SERIES}
    indicators = {name: fetch_indicator(name) for name in ("CPI", "inflationRate", "unemploymentRate", "GDP")}
    cpi = indicators["CPI"]
    cpi_history = cpi["history"]
    cpi_yoy = indicators["inflationRate"]["value"]
    if len(cpi_history) >= 13:
        cpi_yoy = cpi_yoy if cpi_yoy is not None else (float(cpi_history["value"].iloc[-1]) / float(cpi_history["value"].iloc[-13]) - 1) * 100
    gdp_history = indicators["GDP"]["history"]
    gdp_growth_yoy = None
    if len(gdp_history) >= 5:
        gdp_growth_yoy = (float(gdp_history["value"].iloc[-1]) / float(gdp_history["value"].iloc[-5]) - 1) * 100
    calendar = fetch_macro_calendar()
    event_count = sum(item["Important"] for item in calendar["events"])
    score = 0
    if rates["year10"] is not None:
        score += 2 if rates["year10"] >= 4.5 else 1 if rates["year10"] >= 4 else 0
    if rates["spread_10y_2y"] is not None and rates["spread_10y_2y"] < 0:
        score += 2
    if markets["DXY"]["value"] is not None and markets["DXY"]["value"] >= 105:
        score += 1
    if cpi_yoy is not None and cpi_yoy >= 3:
        score += 2
    if markets["Brent crude oil"]["value"] is not None and markets["Brent crude oil"]["value"] >= 90:
        score += 1
    if event_count:
        score += 2 if event_count >= 3 else 1
    return {
        "rates": rates, "markets": markets, "indicators": indicators, "cpi_yoy": cpi_yoy, "gdp_growth_yoy": gdp_growth_yoy,
        "calendar": calendar, "macro_risk_score": min(score, 10), "important_event_count": event_count,
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
