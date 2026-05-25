import yfinance as yf
import pandas as pd

def analyze_options(ticker):
    stock = yf.Ticker(ticker)
    
    # Get current price
    current_price = stock.history(period="1d")["Close"].iloc[-1]
    
    # Get available expiration dates
    expirations = stock.options
    
    print(f"\n=== {ticker} Options Analysis ===")
    print(f"Current Price: ${current_price:.2f}")
    print(f"Available Expirations: {expirations[:5]}")
    
    # Analyze nearest expiration
    exp_date = expirations[0]
    chain = stock.option_chain(exp_date)
    
    calls = chain.calls
    puts = chain.puts
    
    # Find highest open interest
    top_calls = calls.nlargest(5, "openInterest")[["strike", "openInterest", "volume", "impliedVolatility"]]
    top_puts = puts.nlargest(5, "openInterest")[["strike", "openInterest", "volume", "impliedVolatility"]]
    
    print(f"\nExpiration: {exp_date}")
    
    print(f"\n🟢 Top Call Strikes (Market expects UP):")
    for _, row in top_calls.iterrows():
        print(f"  Strike: ${row['strike']:.0f} | OI: {row['openInterest']:,} | Vol: {row['volume']:,} | IV: {row['impliedVolatility']*100:.1f}%")
    
    print(f"\n🔴 Top Put Strikes (Market expects DOWN):")
    for _, row in top_puts.iterrows():
        print(f"  Strike: ${row['strike']:.0f} | OI: {row['openInterest']:,} | Vol: {row['volume']:,} | IV: {row['impliedVolatility']*100:.1f}%")
    
    # Put/Call Ratio
    total_call_oi = calls["openInterest"].sum()
    total_put_oi = puts["openInterest"].sum()
    pc_ratio = total_put_oi / total_call_oi
    
    print(f"\n📊 Put/Call Ratio: {pc_ratio:.2f}")
    if pc_ratio > 1:
        print("  ⚠️  More Puts than Calls - Bearish sentiment")
    else:
        print("  ✅ More Calls than Puts - Bullish sentiment")

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        analyze_options(ticker)