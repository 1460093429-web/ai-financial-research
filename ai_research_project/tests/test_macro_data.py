from datetime import date
import unittest
from unittest.mock import Mock, patch

import pandas as pd

import macro_data


class MacroDataTests(unittest.TestCase):
    def test_date_window_is_dynamic_and_30_days(self):
        self.assertEqual(
            macro_data.date_window(date(2026, 6, 2)),
            ("2026-05-03", "2026-06-02"),
        )
        response = Mock()
        response.json.return_value = {}
        with patch.object(macro_data, "date_window", return_value=("2026-05-03", "2026-06-02")), patch.object(
            macro_data.requests, "get", return_value=response
        ) as get:
            macro_data.fetch_fmp_macro("economic", api_key="secret")
        self.assertEqual(
            get.call_args.kwargs["params"],
            {"from": "2026-05-03", "to": "2026-06-02", "apikey": "secret"},
        )

    def test_failed_fmp_endpoint_and_na_rendering(self):
        with patch.object(macro_data.requests, "get", side_effect=RuntimeError("offline")):
            self.assertEqual(macro_data.fetch_fmp_macro("economic"), {})
        self.assertEqual(macro_data.format_macro_value(None), "N/A")
        self.assertEqual(macro_data.format_macro_value("bad-value"), "N/A")

    def test_yfinance_fallbacks_for_dxy_wti_and_copper(self):
        history = pd.DataFrame({"Close": [100.0, 102.0]})
        with patch.object(macro_data.yf, "Ticker", return_value=Mock(history=Mock(return_value=history))) as ticker:
            for label, symbol in macro_data.YFINANCE_FALLBACKS.items():
                with self.subTest(label=label):
                    result = macro_data.fetch_yfinance_fallback(label)
                    self.assertEqual(result["value"], 102.0)
                    self.assertEqual(result["delta"], 2.0)
                    self.assertIn(symbol, result["source"])
        self.assertEqual(ticker.call_count, 3)

    def test_macro_risk_score_ignores_missing_fields(self):
        self.assertEqual(macro_data.macro_risk_score({}), 0.0)
        self.assertEqual(
            macro_data.macro_risk_score({"VIX": {"value": "20"}, "DXY": {"value": None}}),
            20.0,
        )


if __name__ == "__main__":
    unittest.main()
