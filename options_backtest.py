import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Historical MU earnings dates
MU_EARNINGS = [
    "2025-06-25",
    "2025-09-24",
    "2025-12-17",
    "2026-03-19",
]

def simulate_iron_condor(ticker, earnings_date, days_after=1, wing_width=0.10, spread_width=0.05):
    """
    Simulate Iron Condor after earnings.
    - Enter 1 day after earnings
    - Short strikes at wing_width% away from price
    - Long strikes at spread_width further out
    - Hold until expiration (next monthly expiry)
    """
    stock = yf.Ticker(ticker)
    
    try:
        earnings_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
        entry_dt = earnings_dt + timedelta(days=days_after)
        
        # Get price on entry day
        start = entry_dt - timedelta(days=5)
        end = entry_dt + timedelta(days=60)
        
        hist = stock.history(start=start.strftime("%Y-%m-%d"), 
                           end=end.strftime("%Y-%m-%d"))
        
        if hist.empty:
            return None
        
        # Find entry price (day after earnings)
        entry_prices = hist[hist.index >= entry_dt.strftime("%Y-%m-%d")]
        if entry_prices.empty:
            return None
        
        entry_price = entry_prices["Close"].iloc[0]
        entry_date = entry_prices.index[0].strftime("%Y-%m-%d")
        
        # Define strikes
        short_call = entry_price * (1 + wing_width)
        long_call = entry_price * (1 + wing_width + spread_width)
        short_put = entry_price * (1 - wing_width)
        long_put = entry_price * (1 - wing_width - spread_width)
        
        # Estimate premium collected (simplified)
        # Use IV crush assumption: IV drops ~40% after earnings
        # Premium = ~2% of spread width per side (simplified)
        spread_dollar = entry_price * spread_width
        premium_collected = spread_dollar * 0.4  # Collect ~40% of spread as premium
        max_profit = premium_collected * 2  # Both sides
        max_loss = (spread_dollar - premium_collected) * 2
        
        # Find expiration (30 days out)
        exp_dt = entry_dt + timedelta(days=30)
        exp_prices = hist[hist.index >= exp_dt.strftime("%Y-%m-%d")]
        
        if exp_prices.empty:
            exit_price = hist["Close"].iloc[-1]
            exit_date = hist.index[-1].strftime("%Y-%m-%d")
        else:
            exit_price = exp_prices["Close"].iloc[0]
            exit_date = exp_prices.index[0].strftime("%Y-%m-%d")
        
        # Calculate P&L
        if short_put <= exit_price <= short_call:
            # Price stayed in range - max profit
            pnl = max_profit
            result = "✅ MAX PROFIT - Price in range"
        elif exit_price > short_call:
            # Price broke above call
            if exit_price < long_call:
                pnl = max_profit - (exit_price - short_call) * 2
                result = "⚠️ PARTIAL LOSS - Broke above short call"
            else:
                pnl = -max_loss
                result = "🔴 MAX LOSS - Broke above long call"
        else:
            # Price broke below put
            if exit_price > long_put:
                pnl = max_profit - (short_put - exit_price) * 2
                result = "⚠️ PARTIAL LOSS - Broke below short put"
            else:
                pnl = -max_loss
                result = "🔴 MAX LOSS - Broke below long put"
        
        return {
            "earnings_date": earnings_date,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "short_call": short_call,
            "short_put": short_put,
            "long_call": long_call,
            "long_put": long_put,
            "premium_collected": max_profit,
            "max_loss": max_loss,
            "pnl": pnl,
            "pnl_pct": pnl / max_loss * 100,
            "result": result,
            "price_change_pct": (exit_price - entry_price) / entry_price * 100,
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return None

def simulate_straddle(ticker, earnings_date, days_before=3):
    """
    Simulate buying Straddle before earnings.
    - Enter 3 days before earnings
    - Exit day after earnings
    """
    stock = yf.Ticker(ticker)
    
    try:
        earnings_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
        entry_dt = earnings_dt - timedelta(days=days_before)
        exit_dt = earnings_dt + timedelta(days=1)
        
        hist = stock.history(
            start=(entry_dt - timedelta(days=5)).strftime("%Y-%m-%d"),
            end=(exit_dt + timedelta(days=5)).strftime("%Y-%m-%d")
        )
        
        if hist.empty:
            return None
        
        # Entry price
        entry_prices = hist[hist.index >= entry_dt.strftime("%Y-%m-%d")]
        if entry_prices.empty:
            return None
        entry_price = entry_prices["Close"].iloc[0]
        
        # Exit price
        exit_prices = hist[hist.index >= exit_dt.strftime("%Y-%m-%d")]
        if exit_prices.empty:
            return None
        exit_price = exit_prices["Close"].iloc[0]
        
        # Straddle cost (simplified: ~8% of stock price for high IV stock)
        straddle_cost = entry_price * 0.08
        
        # P&L: profit from price move minus cost
        price_move = abs(exit_price - entry_price)
        pnl = price_move - straddle_cost
        pnl_pct = pnl / straddle_cost * 100
        
        if pnl > 0:
            result = f"✅ PROFIT - Price moved {((exit_price-entry_price)/entry_price*100):+.1f}%"
        else:
            result = f"🔴 LOSS - Price moved {((exit_price-entry_price)/entry_price*100):+.1f}% (not enough)"
        
        return {
            "earnings_date": earnings_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "straddle_cost": straddle_cost,
            "price_move_pct": (exit_price - entry_price) / entry_price * 100,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "result": result,
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("MU Options Strategy Backtest")
    print("=" * 60)
    
    # Iron Condor backtest
    print("\n📊 IRON CONDOR BACKTEST (Enter day after earnings)")
    print("Strategy: Sell 10% OTM Call + Put spreads, hold 30 days")
    print("-" * 60)
    
    ic_results = []
    for earnings_date in MU_EARNINGS:
        result = simulate_iron_condor("MU", earnings_date)
        if result:
            print(f"\nEarnings: {result['earnings_date']}")
            print(f"Entry: {result['entry_date']} @ ${result['entry_price']:.2f}")
            print(f"Exit:  {result['exit_date']} @ ${result['exit_price']:.2f} ({result['price_change_pct']:+.1f}%)")
            print(f"Range: ${result['short_put']:.0f} - ${result['short_call']:.0f}")
            print(f"P&L:   ${result['pnl']:+.2f} | {result['result']}")
            ic_results.append(result)
    
    if ic_results:
        total_pnl = sum(r["pnl"] for r in ic_results)
        wins = sum(1 for r in ic_results if r["pnl"] > 0)
        print(f"\n{'='*60}")
        print(f"Iron Condor Summary:")
        print(f"  Trades: {len(ic_results)}")
        print(f"  Wins: {wins}/{len(ic_results)} ({wins/len(ic_results)*100:.0f}%)")
        print(f"  Total P&L: ${total_pnl:+.2f}")
    
    # Straddle backtest
    print(f"\n\n📊 STRADDLE BACKTEST (Enter 3 days before earnings)")
    print("Strategy: Buy ATM Straddle, exit day after earnings")
    print("-" * 60)
    
    st_results = []
    for earnings_date in MU_EARNINGS:
        result = simulate_straddle("MU", earnings_date)
        if result:
            print(f"\nEarnings: {result['earnings_date']}")
            print(f"Entry: ${result['entry_price']:.2f} | Exit: ${result['exit_price']:.2f}")
            print(f"Move: {result['price_move_pct']:+.1f}% | Cost: ${result['straddle_cost']:.2f}")
            print(f"P&L: ${result['pnl']:+.2f} ({result['pnl_pct']:+.1f}%) | {result['result']}")
            st_results.append(result)
    
    if st_results:
        total_pnl = sum(r["pnl"] for r in st_results)
        wins = sum(1 for r in st_results if r["pnl"] > 0)
        print(f"\n{'='*60}")
        print(f"Straddle Summary:")
        print(f"  Trades: {len(st_results)}")
        print(f"  Wins: {wins}/{len(st_results)} ({wins/len(st_results)*100:.0f}%)")
        print(f"  Total P&L: ${total_pnl:+.2f}")