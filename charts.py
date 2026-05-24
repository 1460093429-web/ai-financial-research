import matplotlib.pyplot as plt

def create_all_charts(financial_data):

    companies = []

    revenues = []

    margins = []

    for company, data in financial_data.items():

        companies.append(company)

        # Revenue 转成 billions
        revenues.append(data["Revenue"] / 1e9)

        # Net Margin 转百分比
        margins.append(data["Margin"] * 100)

    # =========================
    # Revenue Chart
    # =========================

    plt.figure(figsize=(10,5))

    plt.bar(companies, revenues)

    plt.title("Revenue Comparison")

    plt.ylabel("Revenue (USD Billions)")

    plt.savefig("revenue_chart.png")

    # =========================
    # Margin Chart
    # =========================

    plt.figure(figsize=(10,5))

    plt.bar(companies, margins)

    plt.title("Net Margin Comparison")

    plt.ylabel("Net Margin (%)")

    plt.savefig("margin_chart.png")

    print("All charts created.")