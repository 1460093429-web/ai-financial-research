import requests

from config import FMP_API_KEY

tickers = {

    "NVIDIA": "NVDA",
    "AMD": "AMD"

}

def get_financial_data():

    financial_data = {}

    for company, ticker in tickers.items():

        try:

            url = f"https://financialmodelingprep.com/stable/income-statement?symbol={ticker}&apikey={FMP_API_KEY}"

            response = requests.get(url)

            data = response.json()

            print(company)

            print(data)

            if len(data) > 0:

                item = data[0]

                revenue = item.get("revenue", 0)

                net_income = item.get("netIncome", 0)

                # Net Margin calculation
                if revenue > 0:

                    net_margin = net_income / revenue

                else:

                    net_margin = 0

                financial_data[company] = {

                    "Revenue": revenue,

                    "NetIncome": net_income,

                    "Margin": net_margin

                }

        except Exception as e:

            print(f"Error loading {company}")

            print(e)

    return financial_data