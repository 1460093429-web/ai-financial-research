from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def analyze_financials(financial_data):
    summary = ""
    for company, data in financial_data.items():
        revenue = data["Revenue"] / 1e9
        net_income = data["NetIncome"] / 1e9
        margin = data["Margin"] * 100
        summary += f"{company}: Revenue ${revenue:.1f}B, Net Income ${net_income:.1f}B, Net Margin {margin:.1f}%\n"

    prompt = f"""
You are a professional US stock analyst.
Here is the latest financial data:

{summary}

Please analyze:
1. Which company has stronger financial performance?
2. What does the net margin indicate?
3. Investment risks and opportunities?

Be concise and professional.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content