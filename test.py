import feedparser
import json
import matplotlib.pyplot as plt
import yfinance as yf

from config import get_openai_client

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image
)

from reportlab.lib.styles import getSampleStyleSheet

# =========================
# OPENAI CLIENT
# =========================

client = get_openai_client()

# =========================
# RSS FEEDS
# =========================

rss_feeds = {

    "NVIDIA":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US",

    "AMD":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AMD&region=US&lang=en-US",

    "Micron":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MU&region=US&lang=en-US",

    "SanDisk":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SNDK&region=US&lang=en-US",

    "CNBC Tech":
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",

    "MarketWatch":
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",

    "Seeking Alpha":
    "https://seekingalpha.com/feed.xml"

}

# =========================
# COLLECT NEWS
# =========================

all_news = ""

for company, url in rss_feeds.items():

    feed = feedparser.parse(url)

    all_news += f"\n\n{company} NEWS:\n"

    for entry in feed.entries[:3]:

        all_news += f"- {entry.title}\n"

# =========================
# PRINT NEWS
# =========================

print("\nLATEST NEWS:\n")

print(all_news)

# =========================
# GPT ANALYSIS
# =========================

response = client.chat.completions.create(

    model="gpt-4.1-mini",

    messages=[

        {
            "role": "system",

            "content":
            "You are a semiconductor equity research analyst."
        },

        {
            "role": "user",

            "content":
            f"""

Return ONLY valid JSON.

Format:

{{
  "summary": "market summary here",

  "risks": "main risks here",

  "investment_view": "investment view here"
}}

Analyze the semiconductor AI and memory market.

News:

{all_news}

"""
        }

    ]

)

# =========================
# GPT RESULT
# =========================

report = response.choices[0].message.content

print("\nGPT OUTPUT:\n")

print(report)

# =========================
# JSON PARSE
# =========================

data = json.loads(report)

summary = data["summary"]

risks = data["risks"]

investment_view = data["investment_view"]

# =========================
# SAVE JSON
# =========================

with open(

    "semiconductor_report.json",

    "w",

    encoding="utf-8"

) as file:

    json.dump(data, file, indent=4)

print("\nJSON report exported.")

# =========================
# FINANCIAL DATA
# =========================

tickers = {

    "NVIDIA": "NVDA",
    "AMD": "AMD",
    "Micron": "MU",
    "SanDisk": "SNDK"

}

companies = []

revenues = []

net_margins = []

pe_ratios = []

pb_ratios = []

for company, ticker in tickers.items():

    try:

        stock = yf.Ticker(ticker)

        info = stock.info

        print("\n================")

        print(company)

        # 公司名
        companies.append(company)

        # Revenue
        revenue = info.get("totalRevenue", 0)

        currency = info.get("currency", "USD")

        # 韩元转换 USD
        if currency == "KRW":

            revenue = revenue / 1300

        revenues.append(revenue / 1e9)

        # Net Margin
        margin = info.get("profitMargins", 0)

        if margin is None:

            margin = 0

        net_margins.append(margin * 100)

        # PE
        pe = info.get("trailingPE", 0)

        if pe is None:

            pe = 0

        pe_ratios.append(pe)

        # PB
        pb = info.get("priceToBook", 0)

        if pb is None:

            pb = 0

        pb_ratios.append(pb)

        print("Revenue:", revenue)

        print("Margin:", margin)

        print("PE:", pe)

        print("PB:", pb)

    except Exception as e:

        print(f"\nERROR loading {company}")

        print(e)

# =========================
# REVENUE CHART
# =========================

plt.figure(figsize=(10,5))

plt.bar(companies, revenues)

plt.title("Revenue Comparison")

plt.ylabel("Revenue (USD Billions)")

plt.savefig("revenue_chart.png")

# =========================
# NET MARGIN CHART
# =========================

plt.figure(figsize=(10,5))

plt.bar(companies, net_margins)

plt.title("Net Margin Comparison")

plt.ylabel("Net Margin %")

plt.savefig("margin_chart.png")

# =========================
# PE CHART
# =========================

plt.figure(figsize=(10,5))

plt.bar(companies, pe_ratios)

plt.title("PE Ratio Comparison")

plt.ylabel("PE Ratio")

plt.savefig("pe_chart.png")

# =========================
# PB CHART
# =========================

plt.figure(figsize=(10,5))

plt.bar(companies, pb_ratios)

plt.title("PB Ratio Comparison")

plt.ylabel("PB Ratio")

plt.savefig("pb_chart.png")

print("\nFinancial charts exported.")

# =========================
# CREATE PDF
# =========================

doc = SimpleDocTemplate(

    "daily_ai_research_report.pdf"

)

styles = getSampleStyleSheet()

elements = []

# TITLE

title = Paragraph(

    "Semiconductor AI Research Report",

    styles['Title']

)

elements.append(title)

elements.append(Spacer(1,20))

# SUMMARY

summary_paragraph = Paragraph(

    f"<b>Market Summary:</b><br/>{summary}",

    styles['BodyText']

)

elements.append(summary_paragraph)

elements.append(Spacer(1,20))

# RISKS

risk_paragraph = Paragraph(

    f"<b>Risks:</b><br/>{risks}",

    styles['BodyText']

)

elements.append(risk_paragraph)

elements.append(Spacer(1,20))

# INVESTMENT VIEW

investment_paragraph = Paragraph(

    f"<b>Investment View:</b><br/>{investment_view}",

    styles['BodyText']

)

elements.append(investment_paragraph)

elements.append(Spacer(1,20))

# Revenue Chart

elements.append(Image(

    "revenue_chart.png",

    width=400,

    height=220

))

elements.append(Spacer(1,20))

# Margin Chart

elements.append(Image(

    "margin_chart.png",

    width=400,

    height=220

))

elements.append(Spacer(1,20))

# PE Chart

elements.append(Image(

    "pe_chart.png",

    width=400,

    height=220

))

elements.append(Spacer(1,20))

# PB Chart

elements.append(Image(

    "pb_chart.png",

    width=400,

    height=220

))

# BUILD PDF

doc.build(elements)

print("\nPDF report exported.")
