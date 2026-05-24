import time
import schedule
from datetime import datetime
from financials import get_financial_data
from ai_analysis import analyze_financials

def run_analysis():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting analysis...")
    
    # Fetch data
    data = get_financial_data()
    print("Financial data fetched.")
    
    # AI analysis
    analysis = analyze_financials(data)
    print("AI analysis complete.")
    
    # Save report
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"AI Financial Research Report\n")
        f.write(f"Generated: {datetime.now()}\n\n")
        for company, info in data.items():
            f.write(f"{company}: Revenue ${info['Revenue']/1e9:.1f}B, ")
            f.write(f"Net Income ${info['NetIncome']/1e9:.1f}B, ")
            f.write(f"Net Margin {info['Margin']*100:.1f}%\n")
        f.write(f"\nAI Analysis:\n{analysis}\n")
    
    print(f"Report saved: {filename}")

# Run once immediately
run_analysis()

# Schedule daily at 9am
schedule.every().day.at("09:00").do(run_analysis)

print("\nAgent running. Press Ctrl+C to stop.")
while True:
    schedule.run_pending()
    time.sleep(60)