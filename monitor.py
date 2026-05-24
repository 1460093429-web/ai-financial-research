import yfinance as yf
import schedule
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

WATCHLIST = {
    "NVIDIA": "NVDA",
    "SanDisk": "SNDK",
    "Micron": "MU",
    "DRAM ETF": "DRAM",
}

ALERT_THRESHOLD = 0.02  # 2% change triggers alert

def send_email(subject, body):
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS

        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, EMAIL_ADDRESS, msg.as_string())
        print("  📧 Alert email sent!")
    except Exception as e:
        print(f"  Email error: {e}")

def check_prices():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking prices...")
    alerts = []

    for company, ticker in WATCHLIST.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")

            if len(hist) < 2:
                continue

            prev_close = hist["Close"].iloc[-2]
            current = hist["Close"].iloc[-1]
            change = (current - prev_close) / prev_close

            status = "🔴 ALERT" if abs(change) >= ALERT_THRESHOLD else "✅ Normal"
            print(f"{status} | {company} ({ticker}): ${current:.2f} | Change: {change*100:.2f}%")

            if abs(change) >= ALERT_THRESHOLD:
                alerts.append(f"{company} ({ticker}): ${current:.2f} | Change: {change*100:.2f}%")

        except Exception as e:
            print(f"Error checking {company}: {e}")

    if alerts:
        body = "Stock Alert!\n\n" + "\n".join(alerts)
        send_email("Stock Price Alert", body)

# Run once immediately
check_prices()

# Schedule every hour
schedule.every(1).hours.do(check_prices)

print("\nMonitor running. Press Ctrl+C to stop.")
while True:
    schedule.run_pending()
    time.sleep(60)