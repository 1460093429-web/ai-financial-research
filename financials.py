import logging
import math
from datetime import date, datetime, timezone
from numbers import Real

import pandas as pd
import requests
import yfinance as yf

from config import get_fmp_api_key

logger = logging.getLogger(__name__)
FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_ACCESS_LIMIT_NOTE = "FMP unavailable due to subscription/API access limits; yfinance fallback used."
SNDK_FINANCIAL_SOURCE_NOTE = "SNDK financial metrics use yfinance or N/A because FMP may contain reused-symbol/legacy data."

tickers = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
    "Lumentum": "LITE",
    "Rocket Lab": "RKLB",
}
company_names_by_ticker = {ticker: company for company, ticker in tickers.items()}
SNDK_MIN_FINANCIAL_DATE = "2025-01-01"


def _number(value):
    return value if isinstance(value, Real) and math.isfinite(value) else None


def _first(*values):
    return next((value for value in values if value is not None), None)


def _ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator else None


def _is_fmp_access_limit_error(exc):
    message = str(exc)
    return any(f"HTTP {status}" in message for status in (401, 402, 403))


def _validate_company_identity(ticker, *names):
    if ticker == "SNDK" and not any("sandisk" in (name or "").lower() for name in names):
        raise ValueError("SNDK provider identity did not match SanDisk")


def _current_financial_record(ticker, record):
    if ticker != "SNDK":
        return record
    fiscal_date = record.get("date") if isinstance(record, dict) else None
    if not fiscal_date or fiscal_date < SNDK_MIN_FINANCIAL_DATE:
        return {}
    return record


def _empty_snapshot(ticker):
    return {
        "ticker": ticker, "name": company_names_by_ticker.get(ticker) or ticker, "price": None, "change_pct": None, "market_cap": None,
        "sector": None, "industry": None, "description": None, "revenue": None, "net_income": None,
        "net_margin": None, "trailing_pe": None, "forward_pe": None, "price_to_book": None,
        "price_to_sales": None, "current_ratio": None, "quick_ratio": None, "debt_to_equity": None,
        "gross_margin": None, "operating_margin": None, "return_on_equity": None,
        "return_on_assets": None, "analyst_target": None, "analyst_target_high": None,
        "analyst_target_low": None, "fiscal_date": None, "source": "yfinance fallback",
    }


def _fmp_get(endpoint, api_key, **params):
    try:
        response = requests.get(
            f"{FMP_BASE_URL}/{endpoint}",
            params={**params, "apikey": api_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ValueError(f"{endpoint} request failed ({type(exc).__name__})") from exc
    if not response.ok:
        detail = response.text.strip().replace(api_key, "***")[:300]
        raise ValueError(f"{endpoint} HTTP {response.status_code}: {detail or 'no response body'}")
    try:
        return response.json()
    except requests.JSONDecodeError as exc:
        raise ValueError(f"{endpoint} returned invalid JSON") from exc


def _fmp_first(ticker, endpoint, api_key, **params):
    data = _fmp_get(endpoint, api_key, symbol=ticker, **params)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError(f"{endpoint} returned no usable data")
    return data[0]


def _fetch_yfinance_snapshot(ticker):
    stock = yf.Ticker(ticker)
    try:
        history = stock.history(period="5d")
        close = history["Close"].dropna()
        price = float(close.iloc[-1]) if not close.empty else None
        previous = float(close.iloc[-2]) if len(close) > 1 else price
    except Exception as exc:
        logger.warning("%s: yfinance price lookup failed: %s", ticker, exc)
        price = previous = None
    try:
        info = stock.info
    except Exception as exc:
        logger.warning("%s: yfinance profile lookup failed: %s", ticker, exc)
        info = {}
    try:
        _validate_company_identity(ticker, info.get("longName"), info.get("shortName"))
    except ValueError as exc:
        logger.warning("%s: yfinance data ignored: %s", ticker, exc)
        return _empty_snapshot(ticker)
    financial_info = info
    statement_revenue = statement_net_income = statement_date = None
    for statement_name in ("income_stmt", "financials", "quarterly_income_stmt", "quarterly_financials"):
        try:
            statement = getattr(stock, statement_name)
            if statement.empty:
                continue
            if ticker == "SNDK" and str(statement.columns[0])[:10] < SNDK_MIN_FINANCIAL_DATE:
                continue
            statement_revenue = _number(statement.loc["Total Revenue"].iloc[0])
            statement_net_income = _number(statement.loc["Net Income"].iloc[0])
            statement_date = str(statement.columns[0])
            break
        except Exception as exc:
            logger.warning("%s: yfinance %s lookup failed: %s", ticker, statement_name, exc)
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or company_names_by_ticker.get(ticker) or ticker,
        "price": price,
        "change_pct": _ratio(price - previous, previous) * 100 if price is not None and previous else None,
        "market_cap": _number(info.get("marketCap")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "description": info.get("longBusinessSummary"),
        "revenue": _first(statement_revenue, _number(financial_info.get("totalRevenue"))),
        "net_income": _first(statement_net_income, _number(financial_info.get("netIncomeToCommon"))),
        "net_margin": _first(_ratio(statement_net_income, statement_revenue), _number(financial_info.get("profitMargins"))),
        "trailing_pe": _number(financial_info.get("trailingPE")),
        "forward_pe": _number(financial_info.get("forwardPE")),
        "price_to_book": _number(financial_info.get("priceToBook")),
        "price_to_sales": _number(financial_info.get("priceToSalesTrailing12Months")),
        "current_ratio": _number(financial_info.get("currentRatio")),
        "quick_ratio": _number(financial_info.get("quickRatio")),
        "debt_to_equity": _number(financial_info.get("debtToEquity")),
        "gross_margin": _number(financial_info.get("grossMargins")),
        "operating_margin": _number(financial_info.get("operatingMargins")),
        "return_on_equity": _number(financial_info.get("returnOnEquity")),
        "return_on_assets": _number(financial_info.get("returnOnAssets")),
        "ev_to_ebitda": _number(financial_info.get("enterpriseToEbitda")) if ticker == "SNDK" else None,
        "free_cash_flow_margin": _ratio(_number(financial_info.get("freeCashflow")), _number(financial_info.get("totalRevenue"))) if ticker == "SNDK" else None,
        "revenue_growth_yoy": _number(financial_info.get("revenueGrowth")) if ticker == "SNDK" else None,
        "gross_profit_growth": None,
        "operating_income_growth": None,
        "net_income_growth": _number(financial_info.get("earningsGrowth")) if ticker == "SNDK" else None,
        "eps_growth": _number(financial_info.get("earningsGrowth")) if ticker == "SNDK" else None,
        "analyst_target": _number(financial_info.get("targetMeanPrice")),
        "analyst_target_high": _number(financial_info.get("targetHighPrice")),
        "analyst_target_low": _number(financial_info.get("targetLowPrice")),
        "fiscal_date": statement_date,
        "source": "yfinance fallback",
    }


def _overlay_fmp(snapshot, ticker, api_key):
    if ticker == "SNDK":
        profile = _fmp_first(ticker, "profile", api_key, limit=1)
        quote = _fmp_first(ticker, "quote", api_key, limit=1)
        _validate_company_identity(ticker, profile.get("companyName"), quote.get("name"))
        snapshot.update({
            "name": profile.get("companyName") or quote.get("name") or snapshot["name"],
            "sector": profile.get("sector") or snapshot["sector"],
            "industry": profile.get("industry") or snapshot["industry"],
            "description": profile.get("description") or snapshot["description"],
        })
        return

    income = _fmp_first(ticker, "income-statement", api_key, limit=1)
    for endpoint in ("profile", "quote", "ratios", "key-metrics", "income-statement-growth"):
        try:
            snapshot[endpoint] = _fmp_first(ticker, endpoint, api_key, limit=1)
        except Exception as exc:
            logger.warning("%s: FMP %s lookup failed: %s", ticker, endpoint, exc)
            snapshot[endpoint] = {}

    profile = snapshot["profile"]
    quote = snapshot["quote"]
    _validate_company_identity(ticker, profile.get("companyName"), quote.get("name"))
    ratios = snapshot["ratios"]
    metrics = snapshot["key-metrics"]
    growth = snapshot["income-statement-growth"]
    revenue = _number(income.get("revenue"))
    net_income = _number(income.get("netIncome"))
    free_cash_flow = _number(metrics.get("freeCashFlowToFirm"))
    snapshot.update({
        "name": profile.get("companyName") or quote.get("name") or snapshot["name"],
        "price": _first(_number(quote.get("price")), _number(profile.get("price")), snapshot["price"]),
        "change_pct": _first(_number(quote.get("changePercentage")), _number(profile.get("changePercentage")), snapshot["change_pct"]),
        "market_cap": _first(_number(quote.get("marketCap")), _number(profile.get("marketCap")), _number(metrics.get("marketCap")), snapshot["market_cap"]),
        "sector": profile.get("sector") or snapshot["sector"],
        "industry": profile.get("industry") or snapshot["industry"],
        "description": profile.get("description") or snapshot["description"],
        "revenue": _first(revenue, snapshot["revenue"]),
        "net_income": _first(net_income, snapshot["net_income"]),
        "net_margin": _first(_number(ratios.get("netProfitMargin")), _ratio(net_income, revenue), snapshot["net_margin"]),
        "trailing_pe": _first(_number(ratios.get("priceToEarningsRatio")), snapshot["trailing_pe"]),
        "price_to_book": _first(_number(ratios.get("priceToBookRatio")), snapshot["price_to_book"]),
        "price_to_sales": _first(_number(ratios.get("priceToSalesRatio")), snapshot["price_to_sales"]),
        "ev_to_ebitda": _first(_number(metrics.get("evToEBITDA")), _number(ratios.get("enterpriseValueMultiple"))),
        "return_on_equity": _first(_number(metrics.get("returnOnEquity")), snapshot["return_on_equity"]),
        "return_on_assets": _first(_number(metrics.get("returnOnAssets")), snapshot["return_on_assets"]),
        "gross_margin": _first(_number(ratios.get("grossProfitMargin")), snapshot["gross_margin"]),
        "operating_margin": _first(_number(ratios.get("operatingProfitMargin")), snapshot["operating_margin"]),
        "current_ratio": _first(_number(ratios.get("currentRatio")), _number(metrics.get("currentRatio")), snapshot["current_ratio"]),
        "quick_ratio": _first(_number(ratios.get("quickRatio")), snapshot["quick_ratio"]),
        "debt_to_equity": _first(_number(ratios.get("debtToEquityRatio")), snapshot["debt_to_equity"]),
        "free_cash_flow_margin": _ratio(free_cash_flow, revenue),
        "revenue_growth_yoy": _number(growth.get("growthRevenue")),
        "gross_profit_growth": _number(growth.get("growthGrossProfit")),
        "operating_income_growth": _number(growth.get("growthOperatingIncome")),
        "net_income_growth": _number(growth.get("growthNetIncome")),
        "eps_growth": _number(growth.get("growthEPS")),
        "fiscal_date": income.get("date"),
        "source": "FMP",
    })


def _add_analyst_data(snapshot, ticker, api_key):
    try:
        target = _fmp_first(ticker, "price-target-consensus", api_key)
        snapshot.update({
            "analyst_target": _number(target.get("targetConsensus")),
            "analyst_target_high": _number(target.get("targetHigh")),
            "analyst_target_low": _number(target.get("targetLow")),
        })
    except Exception as exc:
        logger.warning("%s: FMP analyst target lookup failed: %s", ticker, exc)
    try:
        rating = _fmp_first(ticker, "grades-consensus", api_key)
        snapshot["analyst_rating"] = rating.get("consensus")
    except Exception as exc:
        logger.warning("%s: FMP analyst rating lookup failed: %s", ticker, exc)
    snapshot["analyst_upside_pct"] = (
        _ratio(snapshot.get("analyst_target") - snapshot["price"], snapshot["price"]) * 100
        if snapshot.get("analyst_target") is not None and snapshot.get("price")
        else None
    )


def _add_earnings_data(snapshot, ticker, api_key):
    try:
        earnings = _fmp_get("earnings", api_key, symbol=ticker, limit=20)
        earnings = earnings if isinstance(earnings, list) else []
        today = date.today().isoformat()
        upcoming = sorted((item for item in earnings if item.get("date", "") >= today), key=lambda item: item["date"])
        reported = sorted(
            (
                item for item in earnings
                if item.get("epsActual") is not None
                and (ticker != "SNDK" or item.get("date", "") >= SNDK_MIN_FINANCIAL_DATE)
            ),
            key=lambda item: item.get("date", ""),
            reverse=True,
        )
        next_item = upcoming[0] if upcoming else {}
        last_item = reported[0] if reported else {}
        actual_eps = _number(last_item.get("epsActual"))
        estimated_eps = _number(last_item.get("epsEstimated"))
        snapshot.update({
            "next_earnings_date": next_item.get("date"),
            "days_until_earnings": (date.fromisoformat(next_item["date"]) - date.today()).days if next_item.get("date") else None,
            "estimated_eps": _first(_number(next_item.get("epsEstimated")), estimated_eps),
            "actual_eps": actual_eps,
            "eps_surprise": _ratio(actual_eps - estimated_eps, abs(estimated_eps)) if actual_eps is not None and estimated_eps else None,
        })
    except Exception as exc:
        logger.warning("%s: FMP earnings lookup failed: %s", ticker, exc)


def fetch_historical_prices(ticker, start_date, end_date, period=None):
    ticker = ticker.upper()
    try:
        data = _fmp_get(
            "historical-price-eod/full",
            get_fmp_api_key(),
            symbol=ticker,
            **{"from": str(start_date), "to": str(end_date)},
        )
        if not isinstance(data, list) or not data:
            raise ValueError("historical-price-eod/full returned no usable data")
        frame = pd.DataFrame(data)
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(frame.columns):
            raise ValueError("historical-price-eod/full missing OHLCV fields")
        return (
            frame.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
            .assign(Date=lambda item: pd.to_datetime(item["Date"]))
            .set_index("Date")
            .sort_index()[["Open", "High", "Low", "Close", "Volume"]]
        ), "FMP"
    except Exception as exc:
        logger.warning("%s: FMP historical price lookup failed; using yfinance fallback: %s", ticker, exc)
        if period:
            frame = yf.Ticker(ticker).history(period=period, interval="1d")
        else:
            frame = yf.Ticker(ticker).history(start=str(start_date), end=str(end_date), interval="1d")
        if frame.empty:
            raise ValueError("No historical prices returned by FMP or yfinance")
        return frame, "yfinance fallback"


def fetch_company_news(ticker, limit=5):
    ticker = ticker.upper()
    try:
        api_key = get_fmp_api_key()
        data = _fmp_get("news/stock", api_key, symbols=ticker, limit=limit)
        if isinstance(data, list) and data:
            logger.info("%s: loaded news from FMP", ticker)
            return [
                {
                    "title": item.get("title"),
                    "text": item.get("text"),
                    "published_date": item.get("publishedDate"),
                    "url": item.get("url"),
                    "publisher": item.get("publisher") or item.get("site"),
                    "source": "FMP",
                    "ticker": ticker,
                }
                for item in data[:limit]
            ]
    except Exception as exc:
        logger.warning("%s: FMP news lookup failed: %s", ticker, exc)
    try:
        news = yf.Ticker(ticker).news or []
        if news:
            logger.info("%s: loaded news from yfinance fallback", ticker)
            return [
                {
                    "title": (item.get("content") or {}).get("title") or item.get("title"),
                    "text": (item.get("content") or {}).get("summary") or item.get("summary"),
                    "published_date": (item.get("content") or {}).get("pubDate"),
                    "url": ((item.get("content") or {}).get("canonicalUrl") or {}).get("url") or item.get("link"),
                    "publisher": (item.get("content") or {}).get("provider", {}).get("displayName") or item.get("publisher"),
                    "source": "yfinance fallback",
                    "ticker": ticker,
                }
                for item in news[:limit]
            ]
    except Exception as exc:
        logger.warning("%s: yfinance news lookup failed: %s", ticker, exc)
    return []


def fetch_general_news(limit=100):
    api_key = get_fmp_api_key()
    data = _fmp_get("news/general-latest", api_key, page=0, limit=limit)
    if not isinstance(data, list):
        raise ValueError("news/general-latest returned no usable data")
    return [
        {
            "title": item.get("title"),
            "text": item.get("text"),
            "published_date": item.get("publishedDate"),
            "url": item.get("url"),
            "publisher": item.get("publisher") or item.get("site"),
            "source": "FMP",
            "ticker": "Market",
        }
        for item in data[:limit]
        if isinstance(item, dict)
    ]


def get_company_snapshot(ticker):
    ticker = ticker.upper()
    snapshot = _empty_snapshot(ticker)
    snapshot.update({
        "analyst_upside_pct": None, "ev_to_ebitda": None, "free_cash_flow_margin": None,
        "revenue_growth_yoy": None, "gross_profit_growth": None, "operating_income_growth": None,
        "net_income_growth": None, "eps_growth": None, "next_earnings_date": None,
        "estimated_eps": None, "actual_eps": None, "eps_surprise": None,
        "analyst_rating": None, "days_until_earnings": None,
        "diagnostic_note": None,
    })
    try:
        api_key = get_fmp_api_key()
        _overlay_fmp(snapshot, ticker, api_key)
        logger.info("%s: loaded normalized snapshot from FMP", ticker)
    except Exception as exc:
        logger.warning("%s: FMP core snapshot failed; using yfinance fallback: %s", ticker, exc)
        if _is_fmp_access_limit_error(exc):
            snapshot["diagnostic_note"] = FMP_ACCESS_LIMIT_NOTE
        api_key = None
    fallback = _fetch_yfinance_snapshot(ticker)
    for field, value in fallback.items():
        if snapshot.get(field) is None:
            snapshot[field] = value
    if api_key:
        _add_analyst_data(snapshot, ticker, api_key)
        if ticker != "SNDK":
            _add_earnings_data(snapshot, ticker, api_key)
    snapshot["analyst_upside_pct"] = (
        _ratio(snapshot.get("analyst_target") - snapshot["price"], snapshot["price"]) * 100
        if snapshot.get("analyst_target") is not None and snapshot.get("price")
        else None
    )
    snapshot["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if ticker == "SNDK":
        snapshot["name"] = company_names_by_ticker[ticker]
        snapshot["diagnostic_note"] = SNDK_FINANCIAL_SOURCE_NOTE
    snapshot["company_name"] = snapshot["name"]
    return snapshot


def get_financial_data(selected_ticker=None):
    selected_ticker = selected_ticker.upper() if selected_ticker else None
    result = {}
    for fallback_company, ticker in tickers.items():
        if selected_ticker and selected_ticker != ticker:
            continue
        try:
            snapshot = get_company_snapshot(ticker)
            if snapshot["revenue"] is None or snapshot["net_income"] is None:
                raise ValueError("revenue or net income is missing")
            result[snapshot["name"] or fallback_company] = {
                "Ticker": ticker,
                "Revenue": snapshot["revenue"],
                "NetIncome": snapshot["net_income"],
                "Margin": snapshot["net_margin"] or 0,
                "FiscalDate": snapshot["fiscal_date"],
                "LatestPrice": snapshot["price"],
                "PE": snapshot["trailing_pe"],
                "PB": snapshot["price_to_book"],
                "Source": snapshot["source"],
                **snapshot,
            }
        except Exception as exc:
            logger.error("%s: financial data unavailable: %s", ticker, exc)
    return result
