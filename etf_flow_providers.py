from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from etf_flows import SEMICONDUCTOR_ETFS, get_latest_available_flow_date, normalize_etf_flow_columns, parse_etf_flow_csv


PROJECT_ROOT = Path(__file__).resolve().parent
FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_FLOW_ENDPOINTS_TO_PROBE = ("etf-flow", "etf-fund-flows", "fund-flows/etf")
FMP_INFO_TTL_SECONDS = 24 * 60 * 60
FLOW_API_TTL_SECONDS = 6 * 60 * 60
ETF_QUOTE_TTL_SECONDS = 15 * 60
MASSIVE_BASE_URL = "https://api.massive.com"


def _fmp_get(endpoint, api_key, **params):
    try:
        response = requests.get(f"{FMP_BASE_URL}/{endpoint}", params={**params, "apikey": api_key}, timeout=15)
    except requests.RequestException as exc:
        raise ValueError(f"{endpoint} request failed ({type(exc).__name__})") from exc
    if not response.ok:
        detail = response.text.strip().replace(api_key, "***")[:300]
        raise ValueError(f"{endpoint} HTTP {response.status_code}: {detail or 'no response body'}")
    try:
        return response.json()
    except requests.JSONDecodeError as exc:
        raise ValueError(f"{endpoint} returned invalid JSON") from exc


def _get_secret(name):
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def _date_range(days=10):
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _empty_provider_result(source, status):
    return {
        "flows": pd.DataFrame(columns=["date", "ticker", "flow"]),
        "data_source": source,
        "provider_status": status,
        "last_fetch_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_available_date": None,
        "tickers_loaded": [],
        "tickers_missing": list(SEMICONDUCTOR_ETFS),
    }


def _provider_result(flows, source, status, requested_tickers):
    if flows is None:
        flows = pd.DataFrame(columns=["date", "ticker", "flow"])
    tickers = [ticker.upper() for ticker in requested_tickers]
    if not flows.empty:
        flows = normalize_etf_flow_columns(flows)
        flows = flows[flows["ticker"].isin(tickers)].copy()
    loaded = sorted(flows["ticker"].unique().tolist()) if not flows.empty else []
    return {
        "flows": flows,
        "data_source": source,
        "provider_status": status,
        "last_fetch_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_available_date": get_latest_available_flow_date(flows),
        "tickers_loaded": loaded,
        "tickers_missing": [ticker for ticker in tickers if ticker not in loaded],
    }


def fetch_massive_etf_flows(tickers, start_date, end_date):
    api_key = _get_secret("MASSIVE_API_KEY")
    if not api_key:
        return _empty_provider_result("Massive ETF Global", "MASSIVE_API_KEY missing. Using fallback.")
    rows = []
    status_messages = []
    tickers = [ticker.upper() for ticker in tickers]
    current_end = pd.to_datetime(end_date).date()
    for offset in range(0, 11):
        query_date = current_end - timedelta(days=offset)
        try:
            response = requests.get(
                f"{MASSIVE_BASE_URL}/etf-global/v1/fund-flows",
                params={
                    "ticker": ",".join(tickers),
                    "processed_date": query_date.isoformat(),
                    "date": query_date.isoformat(),
                    "start_date": start_date,
                    "end_date": end_date,
                    "apiKey": api_key,
                },
                timeout=20,
            )
            if not response.ok:
                status_messages.append(f"Massive HTTP {response.status_code}")
                continue
            payload = response.json()
        except Exception as exc:
            status_messages.append(f"Massive request failed: {type(exc).__name__}")
            continue
        data = payload.get("results") if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            data = data.get("data") or data.get("fund_flows") or data.get("results")
        if not data:
            continue
        rows.extend(data if isinstance(data, list) else [data])
    if not rows:
        return _empty_provider_result("Massive ETF Global", "; ".join(status_messages[-3:]) or "Massive returned no ETF flow rows. Using fallback.")
    return _provider_result(pd.DataFrame(rows), "Massive ETF Global", "Massive ETF Global fund flows loaded.", tickers)


def fetch_fmp_etf_flow_if_available(tickers, start_date, end_date):
    api_key = _get_secret("FMP_API_KEY")
    if not api_key:
        return _empty_provider_result("FMP ETF Flow", "FMP_API_KEY missing. Using fallback.")
    messages = []
    for endpoint in FMP_FLOW_ENDPOINTS_TO_PROBE:
        try:
            data = _fmp_get(endpoint, api_key, symbol=",".join(tickers), **{"from": start_date, "to": end_date})
        except Exception as exc:
            messages.append(f"{endpoint}: {exc}")
            continue
        if data:
            try:
                return _provider_result(pd.DataFrame(data), "FMP ETF Flow", f"FMP ETF flow endpoint loaded: {endpoint}", tickers)
            except Exception as exc:
                messages.append(f"{endpoint}: unusable payload ({exc})")
    return _empty_provider_result("FMP ETF Flow", "FMP ETF flow endpoint not available. Using fallback.")


def load_local_semiconductor_flow_csv(path="data/semiconductor_etf_flows.csv"):
    csv_path = Path(path)
    if not csv_path.is_absolute():
        csv_path = PROJECT_ROOT / csv_path
    if not csv_path.exists():
        return _empty_provider_result("Local CSV", f"Local CSV not found: {csv_path}")
    try:
        flows = parse_etf_flow_csv(csv_path)
    except Exception as exc:
        return _empty_provider_result("Local CSV", f"Local CSV could not be parsed: {exc}")
    return _provider_result(flows, "Local CSV", f"Loaded local CSV: {csv_path}", SEMICONDUCTOR_ETFS)


def fetch_latest_semiconductor_etf_flows(tickers=None, provider="auto"):
    tickers = tickers or SEMICONDUCTOR_ETFS
    start_date, end_date = _date_range(10)
    provider_key = str(provider or "auto").lower()
    if provider_key in {"fmp", "fmp if available"}:
        return fetch_fmp_etf_flow_if_available(tickers, start_date, end_date)
    if provider_key == "massive":
        return fetch_massive_etf_flows(tickers, start_date, end_date)
    if provider_key in {"local csv", "local"}:
        return load_local_semiconductor_flow_csv()
    if provider_key in {"uploaded csv", "uploaded"}:
        return _empty_provider_result("Uploaded CSV", "Waiting for uploaded CSV.")

    fmp_result = fetch_fmp_etf_flow_if_available(tickers, start_date, end_date)
    if not fmp_result["flows"].empty:
        return fmp_result
    massive_result = fetch_massive_etf_flows(tickers, start_date, end_date)
    if not massive_result["flows"].empty:
        return massive_result
    local_result = load_local_semiconductor_flow_csv()
    if not local_result["flows"].empty:
        local_result["provider_status"] = f"{fmp_result['provider_status']} {massive_result['provider_status']} {local_result['provider_status']}"
        return local_result
    return _empty_provider_result(
        "Fallback unavailable",
        f"{fmp_result['provider_status']} {massive_result['provider_status']} {local_result['provider_status']}",
    )


def get_fmp_etf_info(symbol):
    api_key = _get_secret("FMP_API_KEY")
    if not api_key:
        return {"ticker": symbol, "status": "FMP_API_KEY missing"}
    for endpoint in ("etf/info", "profile"):
        try:
            data = _fmp_get(endpoint, api_key, symbol=symbol)
            row = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
            if row:
                return {
                    "ticker": symbol,
                    "fund_name": row.get("name") or row.get("companyName") or row.get("fundName"),
                    "aum": row.get("aum") or row.get("netAssets") or row.get("marketCap") or row.get("totalAssets"),
                    "expense_ratio": row.get("expenseRatio") or row.get("expense_ratio"),
                    "status": f"FMP {endpoint}",
                }
        except Exception:
            continue
    return {"ticker": symbol, "status": "FMP ETF info unavailable"}


def get_fmp_etf_holdings(symbol):
    api_key = _get_secret("FMP_API_KEY")
    if not api_key:
        return []
    for endpoint in ("etf/holder", "etf-holdings"):
        try:
            data = _fmp_get(endpoint, api_key, symbol=symbol)
            return data if isinstance(data, list) else []
        except Exception:
            continue
    return []


def get_fmp_etf_quote(symbol):
    api_key = _get_secret("FMP_API_KEY")
    if not api_key:
        return {"ticker": symbol, "status": "FMP_API_KEY missing"}
    try:
        data = _fmp_get("quote", api_key, symbol=symbol)
        row = data[0] if isinstance(data, list) and data else {}
        return {"ticker": symbol, **row, "status": "FMP quote"}
    except Exception as exc:
        return {"ticker": symbol, "status": f"FMP quote unavailable: {exc}"}


def get_fmp_etf_price_history(symbol, start_date, end_date):
    api_key = _get_secret("FMP_API_KEY")
    if not api_key:
        return pd.DataFrame(columns=["date", "close"])
    try:
        data = _fmp_get("historical-price-eod/full", api_key, symbol=symbol, **{"from": start_date, "to": end_date})
        if isinstance(data, dict):
            data = data.get("historical") or data.get("results") or []
        frame = pd.DataFrame(data)
        if frame.empty:
            return pd.DataFrame(columns=["date", "close"])
        close_col = "close" if "close" in frame.columns else "price" if "price" in frame.columns else None
        if not close_col:
            return pd.DataFrame(columns=["date", "close"])
        return frame[["date", close_col]].rename(columns={close_col: "close"})
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


def get_fmp_etf_asset_exposure(stock_symbol):
    holdings = []
    for etf in SEMICONDUCTOR_ETFS:
        for row in get_fmp_etf_holdings(etf):
            symbol = str(row.get("asset") or row.get("symbol") or row.get("holdingSymbol") or "").upper()
            if symbol == stock_symbol.upper():
                weight = row.get("weightPercentage") or row.get("weight") or row.get("percentage")
                holdings.append({"ticker": etf, "asset": stock_symbol.upper(), "weight": weight})
    return pd.DataFrame(holdings)


def get_fmp_semiconductor_etf_dataset(tickers=None):
    tickers = tickers or SEMICONDUCTOR_ETFS
    info = pd.DataFrame([get_fmp_etf_info(ticker) for ticker in tickers])
    quotes = pd.DataFrame([get_fmp_etf_quote(ticker) for ticker in tickers])
    holdings_rows = []
    for ticker in tickers:
        for holding in get_fmp_etf_holdings(ticker):
            row = dict(holding)
            row["ticker"] = ticker
            holdings_rows.append(row)
    return {"info": info, "quotes": quotes, "holdings": pd.DataFrame(holdings_rows)}
