import yfinance as yf
import numpy as np
import pandas as pd


def get_options_data(ticker):

    try:
        ticker = str(ticker or "").upper().strip()
        stock = yf.Ticker(ticker)

        expirations = stock.options
        if not expirations:
            return None

        exp = expirations[0]
        chain = stock.option_chain(exp)

        calls = chain.calls.fillna(0)
        puts = chain.puts.fillna(0)

        # =========================
        #  Basic Flow Data (V2)
        # =========================
        call_oi = calls["openInterest"].sum()
        put_oi = puts["openInterest"].sum()

        call_vol = calls["volume"].sum()
        put_vol = puts["volume"].sum()

        pc_ratio = put_oi / (call_oi + 1)

        # =========================
        #  Max Pain (V2 core)
        # =========================
        strikes = np.unique(
            np.concatenate([calls["strike"], puts["strike"]])
        )

        if len(strikes) == 0:
            max_pain = 0.0
        else:
            pains = []

            for s in strikes:
                call_loss = (
                    (calls["strike"] > s)
                    * calls["openInterest"]
                    * (calls["strike"] - s)
                ).sum()
                put_loss = (
                    (puts["strike"] < s)
                    * puts["openInterest"]
                    * (s - puts["strike"])
                ).sum()
                pains.append(call_loss + put_loss)

            max_pain = float(strikes[np.argmin(pains)])

        # =========================
        #  Bias Score (V3 core)
        # =========================
        bias_score = (put_oi - call_oi) / (put_oi + call_oi + 1)

        # =========================
        #  Trading Signal (V3 core)
        # =========================
        if bias_score > 0.15:
            signal = "BEARISH"
            confidence = min(0.9, abs(bias_score))
        elif bias_score < -0.15:
            signal = "BULLISH"
            confidence = min(0.9, abs(bias_score))
        else:
            signal = "NEUTRAL"
            confidence = 0.5

        return {
            "expiry": exp,
            "calls": calls,
            "puts": puts,

            # V2 data
            "call_oi": int(call_oi),
            "put_oi": int(put_oi),
            "call_volume": int(call_vol),
            "put_volume": int(put_vol),
            "pc_ratio": float(pc_ratio),
            "max_pain": max_pain,

            # V3 intelligence layer
            "bias_score": float(bias_score),
            "signal": signal,
            "confidence": float(confidence),
        }

    except Exception as e:
        print("Options error:", e)
        return {
            "expiry": "N/A",
            "calls": pd.DataFrame(
                columns=["strike", "openInterest", "volume", "impliedVolatility"]
            ),
            "puts": pd.DataFrame(
                columns=["strike", "openInterest", "volume", "impliedVolatility"]
            ),
            "call_oi": 0,
            "put_oi": 0,
            "call_volume": 0,
            "put_volume": 0,
            "pc_ratio": 0.0,
            "max_pain": 0.0,
            "bias_score": 0.0,
            "signal": "NEUTRAL",
            "confidence": 0.0,
        }
