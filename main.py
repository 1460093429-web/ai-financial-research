from news import collect_news

from financials import get_financial_data

from charts import create_all_charts

from pdf_generator import create_pdf_report

# News
news = collect_news()

# Financial Data
financials = get_financial_data()

# Charts
create_all_charts(financials)

# PDF Report
create_pdf_report(news, financials)