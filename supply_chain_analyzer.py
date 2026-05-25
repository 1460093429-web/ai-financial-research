import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import feedparser
import streamlit as st
import yfinance as yf
from openai import OpenAI

import streamlit as st


OPENAI_MODEL = "gpt-4o-mini"
DATA_SOURCE_DISCLAIMER = (
    "Data source disclaimer: Financial statement metrics are pulled from yfinance/Yahoo Finance "
    "and may be delayed, restated, incomplete, or reported in each company's filing currency. "
    "Non-USD free cash flow is converted to USD using the latest available Yahoo Finance FX close. "
    "Analyst targets and RSS headlines are also sourced from Yahoo Finance/yfinance."
)
USD_FX_SYMBOLS = {
    "KRW": "KRW=X",
}
_FX_RATE_TO_USD_CACHE: Dict[str, float] = {}
NEWS_HEADLINE_LIMIT = 6
YFINANCE_CACHE_DIR = r"C:\Temp\yfinance_cache"
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
yf.cache.set_cache_location(YFINANCE_CACHE_DIR)


@dataclass(frozen=True)
class Company:
    name: str
    segment: str
    symbol: str
    aliases: List[str]
    notes: str = ""


COMPANIES = [
    Company("Coherent", "Optical modules", "COHR", ["IIVI"], "II-VI rebranded as Coherent; IIVI is tracked as a legacy alias."),
    Company("Lumentum", "Optical modules", "LITE", []),
    Company("TTM Technologies", "PCB", "TTMI", []),
    Company("Micron", "HBM memory", "MU", []),
    Company(
        "SK Hynix",
        "HBM memory",
        "000660.KS",
        ["HXSCF", "HYNIX"],
        "Uses the Korea listing first, then OTC proxy HXSCF if yfinance data is unavailable.",
    ),
]


def safe_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value * 100


def ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def format_statement_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def get_statement_value(statement: Any, row_names: List[str], column: Any) -> Optional[float]:
    if statement is None or statement.empty or column not in statement.columns:
        return None
    for row_name in row_names:
        if row_name in statement.index:
            return safe_number(statement.loc[row_name, column])
    return None


def get_quarterly_financials_trend(ticker: Any) -> List[Dict[str, Any]]:
    quarterly_income = ticker.quarterly_financials
    if quarterly_income is None or quarterly_income.empty:
        return []

    trend = []
    for column in list(quarterly_income.columns)[:4]:
        revenue = get_statement_value(quarterly_income, ["Total Revenue", "Operating Revenue"], column)
        gross_profit = get_statement_value(quarterly_income, ["Gross Profit"], column)
        trend.append({
            "date": format_statement_date(column),
            "revenue": revenue,
            "gross_margin_pct": percent(ratio(gross_profit, revenue)),
        })
    return trend


def get_current_price(ticker: Any) -> Optional[float]:
    try:
        current_price = safe_number(ticker.fast_info.get("last_price"))
        if current_price is not None:
            return current_price
    except Exception:
        pass

    try:
        history = ticker.history(period="5d")
        if history is not None and not history.empty:
            return safe_number(history["Close"].dropna().iloc[-1])
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

    def target_value(*keys: str) -> Optional[float]:
        normalized = {str(key).lower().replace(" ", "_"): value for key, value in targets.items()}
        for key in keys:
            value = safe_number(normalized.get(key.lower().replace(" ", "_")))
            if value is not None:
                return value
        return None

    current_price = get_current_price(ticker)
    target_price = target_value("mean", "target_mean_price", "mean_target", "median", "target_median_price")
    upside_pct = percent(ratio(
        None if current_price is None or target_price is None else target_price - current_price,
        current_price,
    ))

    recommendation = None
    recommendation_mean = None
    try:
        info = ticker.get_info()
        recommendation = info.get("recommendationKey") or info.get("recommendation")
        recommendation_mean = safe_number(info.get("recommendationMean"))
    except Exception:
        try:
            info = ticker.info
            recommendation = info.get("recommendationKey") or info.get("recommendation")
            recommendation_mean = safe_number(info.get("recommendationMean"))
        except Exception:
            pass

    return {
        "current_price": current_price,
        "target_price": target_price,
        "upside_pct": upside_pct,
        "recommendation": recommendation,
        "recommendation_mean": recommendation_mean,
    }


def fetch_yahoo_finance_headlines(symbol: str, limit: int = NEWS_HEADLINE_LIMIT) -> List[Dict[str, str]]:
    feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote(symbol)}&region=US&lang=en-US"
    parsed = feedparser.parse(feed_url)
    headlines = []
    for entry in parsed.entries[:limit]:
        headlines.append({
            "title": entry.get("title", ""),
            "published": entry.get("published", ""),
            "link": entry.get("link", ""),
        })
    return headlines


def get_ticker_currency(ticker: Any) -> str:
    try:
        currency = ticker.get_info().get("financialCurrency")
    except Exception:
        currency = None
    if not currency:
        try:
            currency = ticker.info.get("financialCurrency")
        except Exception:
            currency = None
    return str(currency or "USD").upper()


def get_fx_rate_to_usd(currency: str) -> float:
    currency = currency.upper()
    if currency == "USD":
        return 1.0
    if currency in _FX_RATE_TO_USD_CACHE:
        return _FX_RATE_TO_USD_CACHE[currency]

    fx_symbol = USD_FX_SYMBOLS.get(currency)
    if not fx_symbol:
        raise ValueError(f"No USD FX mapping configured for {currency}")

    fx_history = yf.Ticker(fx_symbol).history(period="5d")
    if fx_history is None or fx_history.empty:
        raise ValueError(f"No yfinance FX data found for {fx_symbol}")

    latest_close = safe_number(fx_history["Close"].dropna().iloc[-1])
    if latest_close in (None, 0):
        raise ValueError(f"No valid yfinance FX close found for {fx_symbol}")

    rate_to_usd = 1 / latest_close
    _FX_RATE_TO_USD_CACHE[currency] = rate_to_usd
    return rate_to_usd


def has_financial_data(symbol: str) -> bool:
    ticker = yf.Ticker(symbol)
    return not ticker.financials.empty


def find_first_available_symbol(company: Company) -> str:
    for symbol in [company.symbol] + company.aliases:
        try:
            if has_financial_data(symbol):
                return symbol
        except Exception:
            continue
    return company.symbol


def compute_metrics(company: Company) -> Dict[str, Any]:
    symbol = find_first_available_symbol(company)
    ticker = yf.Ticker(symbol)
    financial_currency = get_ticker_currency(ticker)
    income = ticker.financials
    balance_sheet = ticker.balance_sheet
    cash_flow = ticker.cashflow
    quarterly_financials_trend = get_quarterly_financials_trend(ticker)
    analyst_targets = get_analyst_targets(ticker)
    news_headlines = fetch_yahoo_finance_headlines(symbol)

    if income.empty:
        raise ValueError(f"No yfinance financials found for {symbol}")

    income_columns = list(income.columns)
    latest_column = income_columns[0] if income_columns else None
    prior_column = income_columns[1] if len(income_columns) > 1 else None

    latest_revenue = get_statement_value(income, ["Total Revenue", "Operating Revenue"], latest_column)
    prior_revenue = get_statement_value(income, ["Total Revenue", "Operating Revenue"], prior_column)
    revenue_growth_yoy = percent(ratio(
        None if latest_revenue is None or prior_revenue is None else latest_revenue - prior_revenue,
        prior_revenue,
    ))

    gross_margin_trend = []
    for column in income_columns[:3]:
        revenue = get_statement_value(income, ["Total Revenue", "Operating Revenue"], column)
        gross_profit = get_statement_value(income, ["Gross Profit"], column)
        gross_margin = percent(ratio(gross_profit, revenue))
        gross_margin_trend.append({
            "date": format_statement_date(column),
            "gross_margin_pct": gross_margin,
        })

    cash_flow_columns = list(cash_flow.columns) if cash_flow is not None and not cash_flow.empty else []
    latest_cash_flow_column = cash_flow_columns[0] if cash_flow_columns else None
    free_cash_flow = get_statement_value(cash_flow, ["Free Cash Flow"], latest_cash_flow_column)
    if free_cash_flow is None:
        operating_cash_flow = get_statement_value(cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"], latest_cash_flow_column)
        capital_expenditure = get_statement_value(cash_flow, ["Capital Expenditure", "Capital Expenditures"], latest_cash_flow_column)
        if operating_cash_flow is not None and capital_expenditure is not None:
            free_cash_flow = operating_cash_flow + capital_expenditure
    free_cash_flow_source = free_cash_flow
    free_cash_flow_fx_rate_to_usd = None
    if free_cash_flow is not None:
        free_cash_flow_fx_rate_to_usd = get_fx_rate_to_usd(financial_currency)
        free_cash_flow = free_cash_flow * free_cash_flow_fx_rate_to_usd

    balance_columns = list(balance_sheet.columns) if balance_sheet is not None and not balance_sheet.empty else []
    latest_balance_column = balance_columns[0] if balance_columns else None
    total_debt = get_statement_value(balance_sheet, ["Total Debt"], latest_balance_column)
    total_equity = get_statement_value(
        balance_sheet,
        ["Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest"],
        latest_balance_column,
    )
    debt_to_equity = ratio(total_debt, total_equity)

    return {
        "name": company.name,
        "segment": company.segment,
        "requested_symbol": company.symbol,
        "symbol_used": symbol,
        "aliases": company.aliases,
        "notes": company.notes,
        "financial_currency": financial_currency,
        "fiscal_date": format_statement_date(latest_column) if latest_column is not None else None,
        "revenue_growth_yoy_pct": revenue_growth_yoy,
        "gross_margin_trend_3y": gross_margin_trend,
        "quarterly_financials_trend": quarterly_financials_trend,
        "analyst_targets": analyst_targets,
        "news_headlines": news_headlines,
        "news_sentiment_summary": None,
        "free_cash_flow": free_cash_flow,
        "free_cash_flow_currency": "USD" if free_cash_flow is not None else None,
        "free_cash_flow_source": free_cash_flow_source,
        "free_cash_flow_source_currency": financial_currency if free_cash_flow_source is not None else None,
        "free_cash_flow_fx_rate_to_usd": free_cash_flow_fx_rate_to_usd,
        "debt_to_equity": debt_to_equity,
    }


def build_analysis_prompt(company_metrics: List[Dict[str, Any]]) -> str:
    metrics_json = json.dumps(company_metrics, indent=2)
    return f"""
You are a value investing analyst focused on AI infrastructure supply chains.

Analyze these optical module, PCB, and HBM memory companies using the financial metrics below.
Also evaluate qualitative moat factors:
- Order backlog sustainability
- Pricing power
- Customer concentration risk

For each company, return:
1. Moat score from 1-10
2. Investment thesis
3. Key risks
4. What evidence would change the thesis

Use a disciplined value-investing lens. Be direct about weak data, cyclical risk, and balance-sheet risk.

Financial metrics:
{metrics_json}
""".strip()


def analyze_with_openai(company_metrics: List[Dict[str, Any]]) -> str:
   

    client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY")))
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a rigorous value investing analyst."},
            {"role": "user", "content": build_analysis_prompt(company_metrics)},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


def summarize_news_sentiment(symbol: str, headlines: List[Dict[str, str]], client: OpenAI) -> str:
    if not headlines:
        return "Neutral: no recent Yahoo Finance RSS headlines were available."

    headline_text = "\n".join(
        f"{index + 1}. {item.get('title', '')}"
        for index, item in enumerate(headlines[:NEWS_HEADLINE_LIMIT])
        if item.get("title")
    )
    if not headline_text:
        return "Neutral: recent Yahoo Finance RSS items did not include usable headlines."

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a concise financial news sentiment classifier. "
                    "Return exactly one sentence starting with Positive:, Negative:, or Neutral:."
                ),
            },
            {
                "role": "user",
                "content": f"Classify the sentiment for {symbol} from these Yahoo Finance headlines:\n{headline_text}",
            },
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


def add_news_sentiment(company_metrics: List[Dict[str, Any]]) -> None:
    if not OPENAI_API_KEY:
        raise ValueError("Missing OPENAI_API_KEY in config.py/.env")

    client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY")))
    for item in company_metrics:
        if item.get("error"):
            continue
        try:
            item["news_sentiment_summary"] = summarize_news_sentiment(
                item["symbol_used"],
                item.get("news_headlines") or [],
                client,
            )
        except Exception as exc:
            item["news_sentiment_summary"] = f"News sentiment unavailable: {exc}"


def format_metric(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}{suffix}"


def format_fx_rate(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.6f}"


def format_large_number(value: Optional[float], currency: str = "") -> str:
    if value is None:
        return "N/A"
    prefix = f"{currency} " if currency else ""
    abs_value = abs(value)
    if abs_value >= 1e12:
        return f"{prefix}{value / 1e12:,.2f}T"
    if abs_value >= 1e9:
        return f"{prefix}{value / 1e9:,.2f}B"
    if abs_value >= 1e6:
        return f"{prefix}{value / 1e6:,.2f}M"
    return f"{prefix}{value:,.2f}"


def print_metrics(company_metrics: List[Dict[str, Any]]) -> None:
    print("AI Supply Chain Value Metrics")
    print("=" * 31)
    for item in company_metrics:
        print(f"\n{item['name']} ({item['symbol_used']}) - {item['segment']}")
        if item.get("error"):
            print(f"Error: {item['error']}")
            continue
        if item.get("notes"):
            print(f"Notes: {item['notes']}")
        print(f"Fiscal date: {item.get('fiscal_date') or 'N/A'}")
        print(f"Revenue growth YoY: {format_metric(item.get('revenue_growth_yoy_pct'), '%')}")
        free_cash_flow_currency = item.get("free_cash_flow_currency") or "USD"
        print(f"Free cash flow: {free_cash_flow_currency} {format_metric(item.get('free_cash_flow'))}")
        if item.get("free_cash_flow_source_currency") and item.get("free_cash_flow_source_currency") != free_cash_flow_currency:
            print(
                "Free cash flow source: "
                f"{item['free_cash_flow_source_currency']} {format_metric(item.get('free_cash_flow_source'))} "
                f"(1 {item['free_cash_flow_source_currency']} = USD "
                f"{format_fx_rate(item.get('free_cash_flow_fx_rate_to_usd'))})"
            )
        print(f"Debt/Equity: {format_metric(item.get('debt_to_equity'))}")
        print("Gross margin trend:")
        for margin in item["gross_margin_trend_3y"]:
            print(f"  {margin.get('date') or 'N/A'}: {format_metric(margin.get('gross_margin_pct'), '%')}")
        print("Quarterly revenue and gross margin trend:")
        for quarter in item.get("quarterly_financials_trend", []):
            print(
                f"  {quarter.get('date') or 'N/A'}: "
                f"Revenue {format_large_number(quarter.get('revenue'), item.get('financial_currency') or '')}, "
                f"Gross margin {format_metric(quarter.get('gross_margin_pct'), '%')}"
            )
        analyst_targets = item.get("analyst_targets") or {}
        print(
            "Analyst targets: "
            f"Current {format_metric(analyst_targets.get('current_price'))}, "
            f"Target {format_metric(analyst_targets.get('target_price'))}, "
            f"Upside {format_metric(analyst_targets.get('upside_pct'), '%')}, "
            f"Recommendation {analyst_targets.get('recommendation') or 'N/A'}"
        )
        if analyst_targets.get("recommendation_mean") is not None:
            print(f"Analyst recommendation mean: {format_metric(analyst_targets.get('recommendation_mean'))}")
        print(f"News sentiment: {item.get('news_sentiment_summary') or 'N/A'}")
        headlines = item.get("news_headlines") or []
        if headlines:
            print("Latest Yahoo Finance headlines:")
            for headline in headlines[:3]:
                print(f"  - {headline.get('title') or 'N/A'}")
    print(f"\n{DATA_SOURCE_DISCLAIMER}")


def run_analyzer(skip_ai: bool = False, output_json: bool = False) -> Dict[str, Any]:
    company_metrics = []

    for company in COMPANIES:
        try:
            company_metrics.append(compute_metrics(company))
        except Exception as exc:
            company_metrics.append({
                "name": company.name,
                "segment": company.segment,
                "requested_symbol": company.symbol,
                "symbol_used": company.symbol,
                "aliases": company.aliases,
                "error": str(exc),
            })

    if skip_ai:
        for item in company_metrics:
            if not item.get("error"):
                item["news_sentiment_summary"] = "Skipped because --skip-ai was used."
    else:
        add_news_sentiment(company_metrics)
    analysis = None if skip_ai else analyze_with_openai(company_metrics)
    result = {"metrics": company_metrics, "analysis": analysis, "data_source_disclaimer": DATA_SOURCE_DISCLAIMER}

    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print_metrics(company_metrics)
        if analysis:
            print("\nOpenAI Value Investing Analysis")
            print("=" * 32)
            print(analysis)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze AI supply chain companies using yfinance and OpenAI.")
    parser.add_argument("--skip-ai", action="store_true", help="Fetch metrics only and skip OpenAI analysis.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON output.")
    args = parser.parse_args()
    run_analyzer(skip_ai=args.skip_ai, output_json=args.json)


if __name__ == "__main__":
    main()
