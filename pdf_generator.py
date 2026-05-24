from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Paragraph
from reportlab.platypus import Spacer
from reportlab.platypus import Image

from reportlab.lib.styles import getSampleStyleSheet

def create_pdf_report(news, financial_data):

    doc = SimpleDocTemplate(

        "daily_ai_report.pdf"

    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================
    # Title
    # =========================

    title = Paragraph(

        "Semiconductor AI Research Report",

        styles['Title']

    )

    elements.append(title)

    elements.append(Spacer(1, 20))

    # =========================
    # News
    # =========================

    news_title = Paragraph(

        "<b>Latest News</b>",

        styles['Heading2']

    )

    elements.append(news_title)

    elements.append(Spacer(1, 10))

    news_text = news.replace("\n", "<br/>")

    news_paragraph = Paragraph(

        news_text,

        styles['BodyText']

    )

    elements.append(news_paragraph)

    elements.append(Spacer(1, 20))

    # =========================
    # Revenue Chart
    # =========================

    revenue_chart = Image(

        "revenue_chart.png",

        width=400,

        height=250

    )

    elements.append(revenue_chart)

    elements.append(Spacer(1, 20))

    # =========================
    # Margin Chart
    # =========================

    margin_chart = Image(

        "margin_chart.png",

        width=400,

        height=250

    )

    elements.append(margin_chart)

    elements.append(Spacer(1, 20))

    # =========================
    # Financial Summary
    # =========================

    summary_title = Paragraph(

        "<b>Financial Summary</b>",

        styles['Heading2']

    )

    elements.append(summary_title)

    elements.append(Spacer(1, 10))

    for company, data in financial_data.items():

        text = f"""

        <b>{company}</b><br/>

        Revenue: {round(data['Revenue']/1e9, 2)} Billion USD<br/>

        Net Margin: {round(data['Margin']*100, 2)}%<br/><br/>

        """

        paragraph = Paragraph(

            text,

            styles['BodyText']

        )

        elements.append(paragraph)

    # =========================
    # Build PDF
    # =========================

    doc.build(elements)

    print("PDF report created.")