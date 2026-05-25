import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

EARNINGS_DATES = {
    "NVDA": "2026-08-26",
    "MU": "2026-06-26",
    "SNDK": "2026-07-30",
}

def get_earnings_info(ticker):
    stock = yf.Ticker(ticker)
    calendar = stock.calendar
    info = stock.info

    print(f"\n=== {ticker} Earnings Analysis ===")

    # Earnings date
    try:
        earnings_date = calendar.get("Earnings Date", [None])[0]
        if not earnings_date and ticker in EARNINGS_DATES:
            earnings_date = datetime.strptime(EARNINGS_DATES[ticker], "%Y-%m-%d")
        if earnings_date:
            try:
                days_until = (earnings_date.replace(tzinfo=None) - datetime.now()).days
            except:
                days_until = (earnings_date - datetime.now()).days
            print(f"Next Earnings: {earnings_date.strftime('%Y-%m-%d')} ({days_until} days away)")
        else:
            print("Earnings date: Not available")
            days_until = 999
    except:
        earnings_date = datetime.strptime(EARNINGS_DATES.get(ticker, "2099-01-01"), "%Y-%m-%d")
        days_until = (earnings_date - datetime.now()).days
        print(f"Next Earnings: {earnings_date.strftime('%Y-%m-%d')} ({days_until} days away)")

    # Current price
    try:
        current_price = stock.history(period="1d")["Close"].iloc[-1]
        print(f"Current Price: ${current_price:.2f}")
    except:
        current_price = 0

    # Options data
    try:
        expirations = stock.options

        # Find expiration closest to earnings
        if earnings_date:
            try:
                earnings_dt = earnings_date.replace(tzinfo=None)
            except:
                earnings_dt = earnings_date
            best_exp = None
            best_diff = 9999

            for exp in expirations:
                exp_dt = datetime.strptime(exp, "%Y-%m-%d")
                diff = abs((exp_dt - earnings_dt).days)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp
        else:
            best_exp = expirations[0] if expirations else None

        if best_exp:
            chain = stock.option_chain(best_exp)
            calls = chain.calls
            puts = chain.puts

            atm_calls = calls[abs(calls["strike"] - current_price) < current_price * 0.05]

            avg_iv = 0
            if len(atm_calls) > 0:
                avg_iv = atm_calls["impliedVolatility"].mean() * 100

            print(f"Closest Expiry to Earnings: {best_exp}")
            print(f"ATM Implied Volatility: {avg_iv:.1f}%")

            if avg_iv > 100:
                iv_signal = "🔥 EXTREMELY HIGH - Market expects big move"
            elif avg_iv > 70:
                iv_signal = "⚠️ HIGH - Significant move expected"
            elif avg_iv > 40:
                iv_signal = "🟡 ELEVATED - Some uncertainty"
            else:
                iv_signal = "✅ NORMAL"
            print(f"IV Signal: {iv_signal}")

            # Expected move
            if avg_iv > 0 and days_until < 999:
                expected_move_pct = avg_iv / 100 * (days_until / 365) ** 0.5
                expected_move_dollar = current_price * expected_move_pct
                print(f"Expected Move by Earnings: ±${expected_move_dollar:.2f} (±{expected_move_pct*100:.1f}%)")

            print(f"\n📋 Options Strategy Suggestions:")

            if days_until < 999 and days_until > 0:
                if avg_iv > 80:
                    print(f"  1. SELL Straddle/Strangle (IV crush after earnings)")
                    print(f"     → Sell {best_exp} ATM Call + ATM Put")
                    print(f"     → Profit if stock stays within expected range")
                    print(f"     → Risk: Big unexpected move")
                    print(f"")
                    print(f"  2. Iron Condor (limited risk version)")
                    print(f"     → Sell Call spread + Put spread around current price")
                    print(f"     → Max profit if stock stays in range")
                elif avg_iv > 50:
                    print(f"  1. Buy Straddle (if expecting big move)")
                    print(f"     → Buy {best_exp} ATM Call + ATM Put")
                    print(f"     → Profit if stock moves more than expected")
                    print(f"")
                    print(f"  2. Directional Play")
                    print(f"     → Buy Call if bullish, Buy Put if bearish")
                else:
                    print(f"  1. Buy Call or Put based on your view")
                    print(f"     → IV is not too high, options reasonably priced")

            if days_until < 7 and days_until > 0:
                print(f"\n⚠️  EARNINGS IN {days_until} DAYS - High priority!")
            elif days_until < 30:
                print(f"\n📅 Earnings in {days_until} days - Start monitoring!")

    except Exception as e:
        print(f"Options data error: {e}")

if __name__ == "__main__":
    print("Earnings Monitor & Options Strategy")
    print("=" * 50)
    for company, ticker in WATCHLIST.items():
        get_earnings_info(ticker)