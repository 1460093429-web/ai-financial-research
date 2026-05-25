import yfinance as yf
import pandas as pd

def analyze_options_levels(ticker):
    stock = yf.Ticker(ticker)
    current_price = stock.history(period="1d")["Close"].iloc[-1]
    expirations = stock.options
    
    print(f"\n=== {ticker} Options Levels Analysis ===")
    print(f"Current Price: ${current_price:.2f}")
    
    # Analyze multiple expirations
    for exp_date in expirations[:3]:
        chain = stock.option_chain(exp_date)
        calls = chain.calls
        puts = chain.puts
        
        # Max Pain calculation
        strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        pain = {}
        
        for strike in strikes:
            call_pain = calls[calls["strike"] >= strike]["openInterest"].sum() * 0
            put_pain = puts[puts["strike"] <= strike]["openInterest"].sum() * 0
            
            # Loss to call holders if expire at this strike
            call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
            # Loss to put holders if expire at this strike  
            put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
            
            pain[strike] = call_loss + put_loss
        
        max_pain = min(pain, key=pain.get)
        
        # Key levels
        # Call Wall = highest OI call above current price
        calls_above = calls[calls["strike"] > current_price]
        call_wall = calls_above.loc[calls_above["openInterest"].idxmax(), "strike"] if len(calls_above) > 0 else None
        
        # Put Wall = highest OI put below current price
        puts_below = puts[puts["strike"] < current_price]
        put_wall = puts_below.loc[puts_below["openInterest"].idxmax(), "strike"] if len(puts_below) > 0 else None
        
        # Put/Call ratio
        pc_ratio = puts["openInterest"].sum() / calls["openInterest"].sum()
        
        print(f"\n--- Expiration: {exp_date} ---")
        print(f"Max Pain:   ${max_pain:.0f} ({'Above' if max_pain > current_price else 'Below'} current price)")
        print(f"Call Wall:  ${call_wall:.0f} (Resistance)" if call_wall else "Call Wall: N/A")
        print(f"Put Wall:   ${put_wall:.0f} (Support)" if put_wall else "Put Wall: N/A")
        print(f"P/C Ratio:  {pc_ratio:.2f} ({'Bearish' if pc_ratio > 1 else 'Bullish'})")
        
        # Trading implication
        print(f"\nTrading Implication:")
        if current_price < max_pain:
            print(f"  → Price likely to move UP toward Max Pain ${max_pain:.0f}")
        else:
            print(f"  → Price likely to move DOWN toward Max Pain ${max_pain:.0f}")
        
        if call_wall:
            diff = ((call_wall - current_price) / current_price) * 100
            print(f"  → Call Wall at ${call_wall:.0f} is {diff:.1f}% above - Key resistance")
        
        if put_wall:
            diff = ((current_price - put_wall) / current_price) * 100
            print(f"  → Put Wall at ${put_wall:.0f} is {diff:.1f}% below - Key support")

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        analyze_options_levels(ticker)