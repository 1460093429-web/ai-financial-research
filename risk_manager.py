import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import os
import smtplib
from email.mime.text import MIMEText

load_dotenv()
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# ============================================================
# Portfolio Settings
# ============================================================
PORTFOLIO = {
    "total_capital": 100000,    # Total capital in USD
    "max_risk_per_trade": 0.02, # Max 2% loss per trade
    "max_portfolio_risk": 0.10, # Max 10% total portfolio loss
    "stop_loss_pct": 0.08,      # 8% stop loss per position
    "take_profit_pct": 0.20,    # 20% take profit
}

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

# ============================================================
# Position Sizing
# ============================================================
def calculate_position_size(ticker, entry_price, portfolio):
    """
    Kelly-inspired position sizing based on risk per trade.
    Max loss per trade = total_capital * max_risk_per_trade
    """
    capital = portfolio["total_capital"]
    max_risk = portfolio["max_risk_per_trade"]
    stop_loss = portfolio["stop_loss_pct"]
    
    # Max dollar risk per trade
    max_dollar_risk = capital * max_risk
    
    # Risk per share = entry price * stop loss %
    risk_per_share = entry_price * stop_loss
    
    # Number of shares
    shares = max_dollar_risk / risk_per_share
    
    # Position value
    position_value = shares * entry_price
    position_pct = position_value / capital * 100
    
    # Stop loss price
    stop_loss_price = entry_price * (1 - stop_loss)
    take_profit_price = entry_price * (1 + portfolio["take_profit_pct"])
    
    return {
        "ticker": ticker,
        "entry_price": entry_price,
        "shares": shares,
        "position_value": position_value,
        "position_pct": position_pct,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "max_dollar_risk": max_dollar_risk,
        "risk_reward_ratio": portfolio["take_profit_pct"] / stop_loss,
    }

# ============================================================
# Volatility Analysis
# ============================================================
def calculate_volatility(ticker, period="3mo"):
    """Calculate historical volatility and ATR."""
    data = yf.Ticker(ticker).history(period=period)
    
    # Daily returns volatility
    returns = data["Close"].pct_change().dropna()
    daily_vol = returns.std()
    annual_vol = daily_vol * np.sqrt(252)
    
    # ATR (Average True Range)
    data["H-L"] = data["High"] - data["Low"]
    data["H-PC"] = abs(data["High"] - data["Close"].shift(1))
    data["L-PC"] = abs(data["Low"] - data["Close"].shift(1))
    data["TR"] = data[["H-L", "H-PC", "L-PC"]].max(axis=1)
    atr = data["TR"].rolling(14).mean().iloc[-1]
    atr_pct = atr / data["Close"].iloc[-1] * 100
    
    return {
        "daily_vol": daily_vol,
        "annual_vol": annual_vol,
        "atr": atr,
        "atr_pct": atr_pct,
        "current_price": data["Close"].iloc[-1],
    }

# ============================================================
# Drawdown Analysis
# ============================================================
def calculate_max_drawdown(ticker, period="1y"):
    """Calculate maximum drawdown."""
    data = yf.Ticker(ticker).history(period=period)
    prices = data["Close"]
    
    rolling_max = prices.cummax()
    drawdown = (prices - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()
    current_drawdown = drawdown.iloc[-1]
    
    return {
        "max_drawdown": max_drawdown,
        "current_drawdown": current_drawdown,
    }

# ============================================================
# Full Risk Report
# ============================================================
def generate_risk_report():
    print(f"\n{'='*60}")
    print(f"Risk Management Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Total Capital: ${PORTFOLIO['total_capital']:,.0f}")
    print(f"Max Risk Per Trade: {PORTFOLIO['max_risk_per_trade']*100:.0f}%")
    print(f"Stop Loss: {PORTFOLIO['stop_loss_pct']*100:.0f}%")
    print(f"Take Profit: {PORTFOLIO['take_profit_pct']*100:.0f}%")
    print(f"{'='*60}")
    
    report_lines = []
    
    for company, ticker in WATCHLIST.items():
        print(f"\n--- {company} ({ticker}) ---")
        
        # Volatility
        vol = calculate_volatility(ticker)
        price = vol["current_price"]
        
        # Position sizing
        pos = calculate_position_size(ticker, price, PORTFOLIO)
        
        # Drawdown
        dd = calculate_max_drawdown(ticker)
        
        # Risk level
        if vol["annual_vol"] > 0.8:
            risk_level = "🔴 HIGH RISK"
        elif vol["annual_vol"] > 0.4:
            risk_level = "🟡 MEDIUM RISK"
        else:
            risk_level = "🟢 LOW RISK"
        
        print(f"Current Price:     ${price:.2f}")
        print(f"Annual Volatility: {vol['annual_vol']*100:.1f}% {risk_level}")
        print(f"ATR (14d):         ${vol['atr']:.2f} ({vol['atr_pct']:.1f}% of price)")
        print(f"Max Drawdown (1y): {dd['max_drawdown']:.1f}%")
        print(f"Current Drawdown:  {dd['current_drawdown']:.1f}%")
        print(f"\nPosition Sizing (if buying today):")
        print(f"  Shares to buy:   {pos['shares']:.1f} shares")
        print(f"  Position value:  ${pos['position_value']:,.2f} ({pos['position_pct']:.1f}% of capital)")
        print(f"  Stop Loss:       ${pos['stop_loss_price']:.2f} (-{PORTFOLIO['stop_loss_pct']*100:.0f}%)")
        print(f"  Take Profit:     ${pos['take_profit_price']:.2f} (+{PORTFOLIO['take_profit_pct']*100:.0f}%)")
        print(f"  Max Loss:        ${pos['max_dollar_risk']:,.2f}")
        print(f"  Risk/Reward:     1:{pos['risk_reward_ratio']:.1f}")
        
        report_lines.append(
            f"{company} ({ticker})\n"
            f"  Price: ${price:.2f} | Vol: {vol['annual_vol']*100:.1f}% | {risk_level}\n"
            f"  Buy: {pos['shares']:.1f} shares (${pos['position_value']:,.0f})\n"
            f"  Stop: ${pos['stop_loss_price']:.2f} | Target: ${pos['take_profit_price']:.2f}\n"
            f"  Max Loss: ${pos['max_dollar_risk']:,.0f} | R/R: 1:{pos['risk_reward_ratio']:.1f}\n"
            f"  Max Drawdown: {dd['max_drawdown']:.1f}%\n"
        )
    
    # Send email
    send_risk_email("\n".join(report_lines))

def send_risk_email(body):
    try:
        full_body = f"Risk Management Report\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{body}"
        msg = MIMEText(full_body, "plain", "utf-8")
        msg["Subject"] = f"Risk Report - {datetime.now().strftime('%Y-%m-%d')}"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, EMAIL_ADDRESS, msg.as_string())
        print("\nRisk report email sent!")
    except Exception as e:
        print(f"Email error: {e}")

if __name__ == "__main__":
    generate_risk_report()