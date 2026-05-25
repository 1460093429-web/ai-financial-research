import yfinance as yf
import numpy as np
from scipy.stats import norm

def black_scholes_gamma(S, K, T, r, sigma):
    """Calculate option gamma using Black-Scholes."""
    if T <= 0 or sigma <= 0:
        return 0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return gamma

def calculate_gex(ticker):
    stock = yf.Ticker(ticker)
    current_price = stock.history(period="1d")["Close"].iloc[-1]
    expirations = stock.options
    
    print(f"\n=== {ticker} Gamma Exposure (GEX) ===")
    print(f"Current Price: ${current_price:.2f}")
    
    total_gex = {}
    
    for exp_date in expirations[:2]:
        chain = stock.option_chain(exp_date)
        calls = chain.calls
        puts = chain.puts
        
        # Days to expiration
        from datetime import datetime
        exp = datetime.strptime(exp_date, "%Y-%m-%d")
        T = max((exp - datetime.now()).days / 365, 0.001)
        r = 0.05  # Risk-free rate
        
        for _, row in calls.iterrows():
            K = row["strike"]
            sigma = row["impliedVolatility"]
            oi = row["openInterest"]
            if sigma > 0 and oi > 0:
                gamma = black_scholes_gamma(current_price, K, T, r, sigma)
                gex = gamma * oi * 100 * current_price  # Dealer GEX (positive for calls)
                total_gex[K] = total_gex.get(K, 0) + gex
        
        for _, row in puts.iterrows():
            K = row["strike"]
            sigma = row["impliedVolatility"]
            oi = row["openInterest"]
            if sigma > 0 and oi > 0:
                gamma = black_scholes_gamma(current_price, K, T, r, sigma)
                gex = gamma * oi * 100 * current_price  # Dealer GEX (negative for puts)
                total_gex[K] = total_gex.get(K, 0) - gex
    
    # Sort by strike
    sorted_gex = sorted(total_gex.items())
    
    # Find key levels
    positive_gex = [(k, v) for k, v in sorted_gex if v > 0]
    negative_gex = [(k, v) for k, v in sorted_gex if v < 0]
    
    # Net GEX
    net_gex = sum(total_gex.values())
    
    print(f"\nNet GEX: ${net_gex:,.0f}")
    if net_gex > 0:
        print("→ Positive GEX: Market maker will SELL into rallies (dampens moves)")
    else:
        print("→ Negative GEX: Market maker will BUY into rallies (amplifies moves)")
    
    # Gamma flip point
    strikes = [k for k, v in sorted_gex]
    gex_values = [v for k, v in sorted_gex]
    
    print(f"\nTop Positive GEX Strikes (Resistance):")
    for k, v in sorted(positive_gex, key=lambda x: x[1], reverse=True)[:3]:
        print(f"  ${k:.0f} | GEX: ${v:,.0f}")
    
    print(f"\nTop Negative GEX Strikes (Support/Acceleration):")
    for k, v in sorted(negative_gex, key=lambda x: x[1])[:3]:
        print(f"  ${k:.0f} | GEX: ${v:,.0f}")
    
    # Gamma squeeze risk
    calls_near = sum(v for k, v in positive_gex if current_price < k < current_price * 1.1)
    print(f"\nGamma Squeeze Risk (Calls within 10% above):")
    print(f"  GEX in zone: ${calls_near:,.0f}")
    if calls_near > 1000000:
        print("  🔥 HIGH - Strong Gamma Squeeze potential!")
    elif calls_near > 500000:
        print("  ⚠️  MEDIUM - Some squeeze potential")
    else:
        print("  ✅ LOW - Limited squeeze potential")
    
    return total_gex

if __name__ == "__main__":
    for ticker in ["NVDA", "MU", "SNDK"]:
        calculate_gex(ticker)