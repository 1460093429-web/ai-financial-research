import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

import backtest


WATCHLIST = ["NVDA", "MU", "SNDK", "LITE", "RKLB"]


def fmp_history(close_values=None):
    closes = close_values or ["100", "101", "102", "103"]
    dates = ["2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01"]
    return {
        "historical": [
            {
                "date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": "1000",
                "symbol": "TEST",
                "calendarYear": "2026",
                "period": "FY",
                "reportedCurrency": "USD",
            }
            for day, close in zip(dates, closes)
        ]
    }


def pending_rows(tickers):
    return pd.DataFrame(
        [
            {
                "date": "2026-05-27",
                "ticker": ticker,
                "signal": "BULLISH",
                "confidence": "0.8",
                "price": "100",
                "horizon_days": "3",
                "future_date": None,
                "future_price": None,
                "return_pct": None,
                "result": "PENDING",
                "trend_alignment": "1",
                "score": "0.7",
            }
            for ticker in tickers
        ]
    )


class FakeTicker:
    def __init__(self, ticker, payload):
        self.ticker = ticker
        self.payload = payload

    def history(self, **kwargs):
        return self.payload


class BacktestRegressionTests(unittest.TestCase):
    def test_fmp_payload_keeps_date_columns_non_numeric_for_watchlist(self):
        with TemporaryDirectory() as tmp:
            signals_file = Path(tmp) / "signals.csv"
            pending_rows(WATCHLIST).to_csv(signals_file, index=False)
            factory = lambda ticker: FakeTicker(ticker, fmp_history())
            with patch.object(backtest, "SIGNALS_FILE", signals_file), patch.object(
                backtest.yf, "Ticker", side_effect=factory
            ):
                for ticker in WATCHLIST:
                    result = backtest.backtest_signals(ticker)
                    row = result["signals"].iloc[0]
                    self.assertEqual(row["future_date"], "2026-06-01")
                    self.assertEqual(row["result"], "WIN")

                loaded = backtest.load_signals()
                self.assertNotEqual(str(loaded["date"].dtype), "float64")
                self.assertNotEqual(str(loaded["future_date"].dtype), "float64")
                self.assertEqual(str(loaded["future_price"].dtype), "float64")

    def test_bad_close_logs_field_and_degrades_to_pending(self):
        with TemporaryDirectory() as tmp:
            signals_file = Path(tmp) / "signals.csv"
            pending_rows(["NVDA"]).to_csv(signals_file, index=False)
            payload = fmp_history(["100", "bad-close", "102", "103"])
            factory = lambda ticker: FakeTicker(ticker, payload)
            with patch.object(backtest, "SIGNALS_FILE", signals_file), patch.object(
                backtest.yf, "Ticker", side_effect=factory
            ), self.assertLogs(backtest.logger, logging.WARNING) as logs:
                result = backtest.backtest_signals("NVDA")

            self.assertEqual(result["signals"].iloc[0]["result"], "PENDING")
            self.assertIn("ticker=NVDA field=close", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
