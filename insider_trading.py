import requests
import pandas as pd
from datetime import datetime, timedelta

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

CIK_MAP = {
    "NVDA": "0001045810",
    "MU": "0000723125",
    "SNDK": "0000106040",
}

HEADERS = {
    "User-Agent": "AI Financial Research System contact@example.com"
}

def get_insider_trading(ticker, days=180):
    cik = CIK_MAP.get(ticker)
    if not cik:
        return

    # Use SEC EDGAR full-text search for Form 4
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={(datetime.now()-timedelta(days=days)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&forms=4"
    
    response = requests.get(
        f"https://efts.sec.gov/LATEST/search-index?forms=4&dateRange=custom&startdt={(datetime.now()-timedelta(days=days)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&entity={ticker}",
        headers=HEADERS
    )

    # Alternative: use EDGAR company facts
    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    facts_response = requests.get(facts_url, headers=HEADERS)
    
    print(f"\n=== {ticker} Insider Trading ===")
    
    # Get recent Form 4 filings
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    sub_response = requests.get(submissions_url, headers=HEADERS)
    sub_data = sub_response.json()
    
    company_name = sub_data.get("name", ticker)
    print(f"Company: {company_name}")
    
    filings = sub_data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    
    cutoff = datetime.now() - timedelta(days=days)
    
    buys = []
    sells = []
    
    for i, form in enumerate(forms):
        if form != "4":
            continue
        try:
            date = datetime.strptime(dates[i], "%Y-%m-%d")
            if date < cutoff:
                continue
            
            acc_clean = accessions[i].replace("-", "")
            cik_int = int(cik)
            doc = primary_docs[i]
            
            # Try to get the actual document
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{doc}"
            r = requests.get(doc_url, headers=HEADERS, timeout=5)
            
            if r.status_code == 200:
                content = r.text
                # Check for buy/sell indicators
                if any(code in content for code in ["<transactionCode>P</transactionCode>", ">P<", "Purchase"]):
                    buys.append({"date": dates[i], "url": doc_url})
                elif any(code in content for code in ["<transactionCode>S</transactionCode>", ">S<", "Sale"]):
                    sells.append({"date": dates[i], "url": doc_url})
        except:
            continue
    
    print(f"Period: Last {days} days")
    print(f"\n🟢 Buy transactions: {len(buys)}")
    for b in buys[:5]:
        print(f"  {b['date']}")
    
    print(f"\n🔴 Sell transactions: {len(sells)}")
    for s in sells[:5]:
        print(f"  {s['date']}")
    
    print(f"\n📊 Signal:")
    if len(buys) > len(sells):
        print(f"  🟢 Insiders buying more than selling")
    elif len(sells) > len(buys) * 2:
        print(f"  🔴 Heavy insider selling")
    else:
        print(f"  ⚪ NEUTRAL")

if __name__ == "__main__":
    for company, ticker in WATCHLIST.items():
        get_insider_trading(ticker)