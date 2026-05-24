from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def analyze_financials(financial_data):
    # 把财务数据整理成文字
    summary = ""
    for company, data in financial_data.items():
        revenue = data["Revenue"] / 1e9
        net_income = data["NetIncome"] / 1e9
        margin = data["Margin"] * 100
        summary += f"{company}: 收入 ${revenue:.1f}B, 净利润 ${net_income:.1f}B, 净利率 {margin:.1f}%\n"

    prompt = f"""
你是一位专业的美股分析师。
以下是最新的财务数据：

{summary}

请分析：
1. 哪家公司财务表现更强？
2. 净利率说明了什么？
3. 投资风险和机会？

用中文回答，简洁专业。
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content