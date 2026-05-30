from config import get_openai_client


def _format_metric(value, formatter):
    return "N/A" if value is None else formatter(value)


def _percent(value):
    return _format_metric(value, lambda item: f"{item * 100:.1f}%")


def analyze_financials(financial_data, macro_summary=None):
    analyses = {}
    client = get_openai_client()
    for company, data in financial_data.items():
        revenue = data["Revenue"] / 1e9
        net_income = data["NetIncome"] / 1e9
        margin = data["Margin"] * 100
        price = _format_metric(data.get("LatestPrice"), lambda value: f"${value:.2f}")
        pe = _format_metric(data.get("PE"), lambda value: f"{value:.2f}")
        pb = _format_metric(data.get("PB"), lambda value: f"{value:.2f}")
        summary = (
            f"{company} ({data['Ticker']}): Revenue ${revenue:.1f}B, "
            f"Net Income ${net_income:.1f}B, Net Margin {margin:.1f}%, "
            f"Latest Price {price}, PE {pe}, PB {pb}, "
            f"Fiscal Date {data.get('FiscalDate') or 'N/A'}, Source {data.get('Source') or 'N/A'}.\n"
            f"Growth: Revenue YoY {_percent(data.get('revenue_growth_yoy'))}, "
            f"Gross Profit {_percent(data.get('gross_profit_growth'))}, "
            f"Operating Income {_percent(data.get('operating_income_growth'))}, "
            f"Net Income {_percent(data.get('net_income_growth'))}, EPS {_percent(data.get('eps_growth'))}.\n"
            f"Analyst targets: Consensus {_format_metric(data.get('analyst_target'), lambda item: f'${item:.2f}')}, "
            f"High {_format_metric(data.get('analyst_target_high'), lambda item: f'${item:.2f}')}, "
            f"Low {_format_metric(data.get('analyst_target_low'), lambda item: f'${item:.2f}')}, "
            f"Upside/downside {_format_metric(data.get('analyst_upside_pct'), lambda item: f'{item:.1f}%')}.\n"
            f"Earnings catalyst: Next date {data.get('next_earnings_date') or 'N/A'}, "
            f"Estimated EPS {_format_metric(data.get('estimated_eps'), lambda item: f'{item:.2f}')}, "
            f"Actual EPS {_format_metric(data.get('actual_eps'), lambda item: f'{item:.2f}')}, "
            f"EPS surprise {_percent(data.get('eps_surprise'))}.\n"
            f"Latest company news: {data.get('LatestNews') or 'N/A'}.\n"
        )

        prompt = f"""
You are a professional US stock analyst.
Analyze the supplied financial metrics for this stock. Use the actual
values below in your answer. If a metric is N/A, state that it is unavailable and continue
the analysis. Do not ask the user to provide financial data.

{summary}

Macro backdrop:
{macro_summary or "N/A"}

Please analyze:
1. Market Summary.
2. Macro Backdrop, including risk score and impact on this stock.
3. Financial performance, valuation, and growth quality.
4. Bull Case.
5. Bear Case.
6. Catalysts, including earnings and supplied news.
7. Risks and supplied-news sentiment.
8. Investment View.

Be concise and professional.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        analyses[data["Ticker"]] = response.choices[0].message.content

    return analyses
