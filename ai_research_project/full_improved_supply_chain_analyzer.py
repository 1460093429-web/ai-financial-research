# Full improved supply chain analyzer
# Generated upgraded version

import argparse
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import feedparser
import streamlit as st
import yfinance as yf
from openai import OpenAI

OPENAI_MODEL = "gpt-4o-mini"

DATA_SOURCE_DISCLAIMER = (
    "Data source disclaimer: Financial statement metrics are pulled from yfinance/Yahoo Finance "
    "and may be delayed, restated, incomplete, or reported in each company's filing currency."
)

USD_FX_SYMBOLS = {
    "KRW": "KRW=X",
}

_FX_RATE_TO_USD_CACHE: Dict[str, float] = {}

NEWS_HEADLINE_LIMIT = 6

YFINANCE_CACHE_DIR = os.path.join(os.getcwd(), "yfinance_cache")
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)


@dataclass(frozen=True)
class Company:
    name: str
    segment: str
    symbol: str
    aliases: List[str]
    notes: str = ""


COMPANIES = [
    Company("Coherent", "Optical modules", "COHR", ["IIVI"]),
    Company("Lumentum", "Optical modules", "LITE", []),
    Company("TTM Technologies", "PCB", "TTMI", []),
    Company("Micron", "HBM memory", "MU", []),
]


def retry_call(func, retries: int = 3, delay: int = 2):

    for attempt in range(retries):

        try:
            return func()

        except Exception:

            if attempt == retries - 1:
                raise

            time.sleep(delay)


def safe_number(value: Any) -> Optional[float]:

    if value is None:
        return None

    try:
        return float(value)

    except (TypeError, ValueError):
        return None


def safe_get_info(ticker: Any) -> Dict[str, Any]:

    try:
        return ticker.get_info()

    except Exception:

        try:
            return ticker.info

        except Exception:
            return {}


def get_openai_api_key() -> Optional[str]:

    try:

        key = st.secrets.get("OPENAI_API_KEY")

        if key:
            return key

    except Exception:
        pass

    return os.getenv("OPENAI_API_KEY")


def percent(value: Optional[float]) -> Optional[float]:

    if value is None:
        return None

    return value * 100


def ratio(
    numerator: Optional[float],
    denominator: Optional[float],
) -> Optional[float]:

    if numerator is None or denominator in (None, 0):
        return None

    return numerator / denominator


def format_statement_date(value: Any) -> str:

    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")

    return str(value)


def get_statement_value(
    statement: Any,
    row_names: List[str],
    column: Any,
) -> Optional[float]:

    if statement is None or statement.empty:
        return None

    if column not in statement.columns:
        return None

    for row_name in row_names:

        if row_name in statement.index:
            return safe_number(statement.loc[row_name, column])

    return None


def get_current_price(ticker: Any) -> Optional[float]:

    try:

        current_price = safe_number(
            ticker.fast_info.get("last_price")
        )

        if current_price is not None:
            return current_price

    except Exception:
        pass

    try:

        history = retry_call(
            lambda: ticker.history(period="5d")
        )

        if history is not None and not history.empty:

            return safe_number(
                history["Close"].dropna().iloc[-1]
            )

    except Exception:
        pass

    return None


def get_analyst_targets(ticker: Any) -> Dict[str, Any]:

    targets = {}

    try:

        raw_targets = ticker.analyst_price_targets

        if isinstance(raw_targets, dict):
            targets = raw_targets

        elif hasattr(raw_targets, "to_dict"):
            targets = raw_targets.to_dict()

    except Exception:
        targets = {}

    current_price = get_current_price(ticker)

    info = safe_get_info(ticker)

    return {
        "current_price": current_price,
        "recommendation": (
            info.get("recommendationKey")
            or info.get("recommendation")
        ),
    }


def fetch_yahoo_finance_headlines(
    symbol: str,
    limit: int = NEWS_HEADLINE_LIMIT,
) -> List[Dict[str, str]]:

    feed_url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?"
        f"s={quote(symbol)}&region=US&lang=en-US"
    )

    try:
        parsed = feedparser.parse(feed_url)

    except Exception:
        return []

    headlines = []

    for entry in parsed.entries[:limit]:

        headlines.append({
            "title": entry.get("title", ""),
            "published": entry.get("published", ""),
        })

    return headlines


def compute_metrics(company: Company) -> Dict[str, Any]:

    ticker = yf.Ticker(company.symbol)

    info = safe_get_info(ticker)

    income = ticker.financials

    if income.empty:
        raise ValueError(
            f"No yfinance financials found for {company.symbol}"
        )

    income_columns = list(income.columns)

    latest_column = (
        income_columns[0]
        if income_columns
        else None
    )

    latest_revenue = get_statement_value(
        income,
        ["Total Revenue", "Operating Revenue"],
        latest_column,
    )

    gross_profit = get_statement_value(
        income,
        ["Gross Profit"],
        latest_column,
    )

    gross_margin = percent(
        ratio(gross_profit, latest_revenue)
    )

    market_cap = safe_number(info.get("marketCap"))

    price_to_sales = ratio(
        market_cap,
        latest_revenue,
    )

    analyst_targets = get_analyst_targets(ticker)

    headlines = fetch_yahoo_finance_headlines(
        company.symbol
    )

    return {
        "name": company.name,
        "symbol": company.symbol,
        "segment": company.segment,
        "market_cap": market_cap,
        "revenue": latest_revenue,
        "gross_margin_pct": gross_margin,
        "price_to_sales": price_to_sales,
        "analyst_targets": analyst_targets,
        "headlines": headlines,
    }


def print_metrics(metrics: List[Dict[str, Any]]):

    print("AI Supply Chain Analyzer")
    print("=" * 40)

    for item in metrics:

        print(
            f"\n{item['name']} ({item['symbol']})"
        )

        print(
            f"Revenue: {item['revenue']}"
        )

        print(
            f"Gross Margin: {item['gross_margin_pct']}"
        )

        print(
            f"P/S: {item['price_to_sales']}"
        )

        print(
            f"Recommendation: "
            f"{item['analyst_targets'].get('recommendation')}"
        )


def run_analyzer():

    metrics = []

    for company in COMPANIES:

        try:
            metrics.append(
                compute_metrics(company)
            )

        except Exception as exc:

            metrics.append({
                "name": company.name,
                "error": str(exc),
            })

    print_metrics(metrics)


if __name__ == "__main__":
    run_analyzer()
