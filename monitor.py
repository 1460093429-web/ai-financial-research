import yfinance as yf
import schedule
import time
from datetime import datetime

WATCHLIST = {
    "NVIDIA": "NVDA",
    "SanDisk": "SNDK",
    "Micron": "MU",
    "DRAM ETF": "DRAM",
}

ALERT_THRESHOLD = 0.02  # 2% change triggers alert

def check_prices():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking prices...")
    
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
                print(f"  ⚠️  {company} moved {change*100:.2f}% - Consider reviewing position!")
        
        except Exception as e:
            print(f"Error checking {company}: {e}")

# Run once immediately
check_prices()

# Schedule every hour
schedule.every(1).hours.do(check_prices)

print("\nMonitor running. Press Ctrl+C to stop.")
while True:
    schedule.run_pending()
    time.sleep(60)