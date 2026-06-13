import logging
import unittest
from unittest.mock import Mock, patch

import requests

import financials


class FakeResponse:
    def __init__(self, payload=None, status_error=None, json_error=None):
        self.payload = payload
        self.status_error = status_error
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FinancialTests(unittest.TestCase):
    def setUp(self):
        self.yfinance_info = {
            "totalRevenue": 50,
            "netIncomeToCommon": 5,
        }

    def get_data(self, response):
        stock = Mock(info=self.yfinance_info)
        with patch.object(financials, "get_tickers", return_value={"NVIDIA": "NVDA"}), patch.object(
            financials.requests, "get", return_value=response
        ), patch.object(financials.yf, "Ticker", return_value=stock):
            return financials.get_financial_data(api_key="secret")["NVIDIA"]

    def test_fmp_first_behavior_and_source(self):
        record = self.get_data(FakeResponse([{"revenue": 100, "netIncome": 25}]))
        self.assertEqual(record["Revenue"], 100)
        self.assertEqual(record["Margin"], 0.25)
        self.assertEqual(record["Source"], "FMP")

    def test_yfinance_fallback_for_empty_malformed_or_missing_fmp_data(self):
        responses = [
            FakeResponse([]),
            FakeResponse(json_error=ValueError("malformed JSON")),
            FakeResponse([{"revenue": 100}]),
        ]
        for response in responses:
            with self.subTest(response=response):
                record = self.get_data(response)
                self.assertEqual(record["Revenue"], 50)
                self.assertEqual(record["Source"], "yfinance fallback")

    def test_yfinance_fallback_for_retriable_and_auth_statuses(self):
        for status in (402, 403, 429):
            error = requests.HTTPError(f"{status} response")
            with self.subTest(status=status):
                record = self.get_data(FakeResponse(status_error=error))
                self.assertEqual(record["Source"], "yfinance fallback")

    def test_api_key_is_redacted_in_logs(self):
        error = requests.HTTPError("403 https://example.test?apikey=secret")
        with self.assertLogs(financials.logger, logging.WARNING) as logs:
            self.get_data(FakeResponse(status_error=error))
        output = "\n".join(logs.output)
        self.assertNotIn("secret", output)
        self.assertIn("[REDACTED]", output)


if __name__ == "__main__":
    unittest.main()
