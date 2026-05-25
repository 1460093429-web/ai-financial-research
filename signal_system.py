import yfinance as yf
import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def black_scholes_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return 0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

def score_rsi(rsi):
    """RSI Score: oversold = buy, overbought = sell."""
    if rsi < 30:
        return 20, f"RSI {rsi:.1f} - Oversold (Strong Buy)"
    elif rsi < 50:
        return 15, f"RSI {rsi:.1f} - Neutral Bullish"
    elif rsi < 70:
        return 10, f"RSI {rsi:.1f} - Normal"
    else:
        return 0, f"RSI {rsi:.1f} - Overbought (Avoid)"

def score_ma(data):
    """MA Score: MA5 > MA20 = bullish."""
    ma5 = data["Close"].rolling(5).mean().iloc[-1]
    ma20 = data["Close"].rolling(20).mean().iloc[-1]
    price = data["Close"].iloc[-1]
    
    if ma5 > ma20 and price > ma5:
        return 20, f"MA5 ${ma5:.2f} > MA20 ${ma20:.2f} - Bullish"
    elif ma5 > ma20:
        return 15, f"MA5 > MA20 but price below MA5 - Weak Bullish"
    elif ma5 < ma20 and price < ma5:
        return 0, f"MA5 ${ma5:.2f} < MA20 ${ma20:.2f} - Bearish"
    else:
        return 10, f"Mixed MA signals - Neutral"

def score_volume(data):
    """Volume Score: high volume up = bullish."""
    vol_ratio = data["Volume"].iloc[-1] / data["Volume"].rolling(20).mean().iloc[-1]
    price_change = data["Close"].pct_change().iloc[-1]
    
    if vol_ratio > 1.5 and price_change > 0.02:
        return 20, f"Vol {vol_ratio:.1f}x + Price Up {price_change*100:.1f}% - Strong Buy"
    elif vol_ratio > 1.5 and price_change < -0.02:
        return 0, f"Vol {vol_ratio:.1f}x + Price Down {price_change*100:.1f}% - Strong Sell"
    elif vol_ratio < 0.7 and price_change > 0:
        return 8, f"Vol {vol_ratio:.1f}x + Price Up - Weak signal"
    else:
        return 12, f"Vol {vol_ratio:.1f}x - Normal"

def score_gex(ticker, current_price):
    """GEX Score: negative GEX = amplified moves."""
    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        total_gex = {}
        
        for exp in expirations[:2]:
            chain = stock.option_chain(exp)
            exp_dt = datetime.strptime(exp, "%Y-%m-%d")
            T = max((exp_dt - datetime.now()).days / 365, 0.001)
            
            for _, row in chain.calls.iterrows():
                K, sigma, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
                if sigma > 0 and oi > 0:
                    g = black_scholes_gamma(current_price, K, T, 0.05, sigma)
                    total_gex[K] = total_gex.get(K, 0) + g * oi * 100 * current_price
            
            for _, row in chain.puts.iterrows():
                K, sigma, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
                if sigma > 0 and oi > 0:
                    g = black_scholes_gamma(current_price, K, T, 0.05, sigma)
                    total_gex[K] = total_gex.get(K, 0) - g * oi * 100 * current_price
        
        net_gex = sum(total_gex.values())
        calls_near = sum(v for k, v in total_gex.items() if v > 0 and current_price < k < current_price * 1.1)
        
        if net_gex < 0 and calls_near > 1000000:
            return 20, f"GEX ${net_gex:,.0f} - Negative + High Squeeze Risk"
        elif net_gex < 0:
            return 15, f"GEX ${net_gex:,.0f} - Negative (Amplified moves)"
        else:
            return 8, f"GEX ${net_gex:,.0f} - Positive (Dampened moves)"
    except:
        return 10, "GEX - Data unavailable"

def score_max_pain(ticker, current_price):
    """Max Pain Score: price below max pain = bullish."""
    try:
        stock = yf.Ticker(ticker)
        exp_date = stock.options[0]
        chain = stock.option_chain(exp_date)
        calls, puts = chain.calls, chain.puts
        
        strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        pain = {}
        for strike in strikes:
            call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
            put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
            pain[strike] = call_loss + put_loss
        
        max_pain = min(pain, key=pain.get)
        diff_pct = (max_pain - current_price) / current_price * 100
        
        if diff_pct > 5:
            return 20, f"Max Pain ${max_pain:.0f} is {diff_pct:.1f}% above - Strong Bullish"
        elif diff_pct > 0:
            return 15, f"Max Pain ${max_pain:.0f} is {diff_pct:.1f}% above - Bullish"
        elif diff_pct > -5:
            return 10, f"Max Pain ${max_pain:.0f} is {diff_pct:.1f}% below - Neutral"
        else:
            return 0, f"Max Pain ${max_pain:.0f} is {diff_pct:.1f}% below - Bearish"
    except:
        return 10, "Max Pain - Data unavailable"

def generate_signal(company, ticker):
    """Generate comprehensive signal for a stock."""
    data = yf.Ticker(ticker).history(period="3mo")
    current_price = data["Close"].iloc[-1]
    rsi = calculate_rsi(data).iloc[-1]
    
    # Score each component
    rsi_score, rsi_detail = score_rsi(rsi)
    ma_score, ma_detail = score_ma(data)
    vol_score, vol_detail = score_volume(data)
    gex_score, gex_detail = score_gex(ticker, current_price)
    mp_score, mp_detail = score_max_pain(ticker, current_price)
    
    total_score = rsi_score + ma_score + vol_score + gex_score + mp_score
    
    if total_score >= 70:
        signal = "🟢 STRONG BUY"
    elif total_score >= 50:
        signal = "🟡 NEUTRAL"
    else:
        signal = "🔴 AVOID"
    
    result = {
        "company": company,
        "ticker": ticker,
        "price": current_price,
        "score": total_score,
        "signal": signal,
        "details": {
            "RSI": (rsi_score, rsi_detail),
            "MA": (ma_score, ma_detail),
            "Volume": (vol_score, vol_detail),
            "GEX": (gex_score, gex_detail),
            "MaxPain": (mp_score, mp_detail),
        }
    }
    return result

def send_signal_email(results):
    """Send signal report via email."""
    subject = f"Daily Signal Report - {datetime.now().strftime('%Y-%m-%d')}"
    
    body = f"AI Financial Research System\nDaily Signal Report\n"
    body += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    body += "=" * 50 + "\n\n"
    
    for r in results:
        body += f"{r['signal']} | {r['company']} ({r['ticker']})\n"
        body += f"Price: ${r['price']:.2f} | Score: {r['score']}/100\n"
        for name, (score, detail) in r['details'].items():
            body += f"  {name}: {score}/20 - {detail}\n"
        body += "\n"
    
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS
        
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, EMAIL_ADDRESS, msg.as_string())
        print("Signal email sent!")
    except Exception as e:
        print(f"Email error: {e}")

def run_signal_system():
    print(f"\n{'='*50}")
    print(f"Daily Signal Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    
    results = []
    for company, ticker in WATCHLIST.items():
        print(f"\nAnalyzing {company}...")
        result = generate_signal(company, ticker)
        results.append(result)
        
        print(f"{result['signal']} | Score: {result['score']}/100 | Price: ${result['price']:.2f}")
        for name, (score, detail) in result['details'].items():
            print(f"  {name}: {score}/20 - {detail}")
    
    send_signal_email(results)
    return results

if __name__ == "__main__":
    run_signal_system()