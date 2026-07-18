"""Regression coverage for the Phase 4.7 metadata-complete provider boundary."""

import ast
from copy import deepcopy
import importlib
import inspect
import json
import math
from pathlib import Path

import pytest

from providers import memory_cycle_data as provider
from services.memory_cycle_production import build_company_financial_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_PATH = PROJECT_ROOT / "providers" / "memory_cycle_data.py"
RETRIEVED_AT = "2026-07-18T20:01:00+00:00"
MARKET_TIME = 1_784_404_800


def _yahoo_quote(ticker="MU", **overrides):
    quote = {
        "symbol": ticker,
        "regularMarketPrice": 123.45,
        "currency": "USD",
        "regularMarketTime": MARKET_TIME,
    }
    quote.update(overrides)
    return quote


def _fmp_quote(ticker="MU", **overrides):
    quote = {
        "symbol": ticker,
        "price": 122.75,
        "currency": "USD",
        "timestamp": MARKET_TIME - 60,
    }
    quote.update(overrides)
    return [quote]


def _market_error_codes(result):
    return [error["code"] for error in result["errors"]]


def _statement(ticker="MU", **overrides):
    statement = {
        "symbol": ticker,
        "cik": "0000000002" if ticker == "SNDK" else "0000000001",
        "date": "2026-05-29",
        "calendarYear": "2026",
        "period": "Q3",
        "reportedCurrency": "USD",
        "revenue": 9_300_000_000,
        "grossProfitRatio": 0.452,
        "operatingIncomeRatio": 0.301,
    }
    statement.update(overrides)
    return statement


def _identity(
    ticker="SNDK", name="SanDisk Corporation", cik="0000000002"
):
    return [{"symbol": ticker, "companyName": name, "cik": cik}]


def _financial_error_codes(result, *, field=None):
    return [
        error["code"]
        for error in result["errors"]
        if field is None or error["field"] == field
    ]


def test_provider_module_imports_without_executing_work():
    module = importlib.import_module("providers.memory_cycle_data")

    assert module.__name__ == "providers.memory_cycle_data"


def test_provider_module_has_no_external_or_stateful_imports():
    tree = ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(
        {
            "config",
            "dashboard",
            "dotenv",
            "financials",
            "ib_insync",
            "openai",
            "os",
            "pathlib",
            "requests",
            "streamlit",
            "yfinance",
        }
    )


def test_provider_source_has_no_hidden_io_clock_cache_or_ui_access():
    source = PROVIDER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "load_dotenv",
        "os.environ",
        "os.getenv",
        "st.secrets",
        "session_state",
        "st.cache",
        "lru_cache",
        "requests.",
        "yfinance",
        "yf.",
        "openai",
        "IBKR",
    )

    assert all(marker not in source for marker in forbidden)


def test_provider_public_scope_and_signatures_are_stable():
    module = importlib.import_module("providers.memory_cycle_data")

    assert module.SUPPORTED_MARKET_TICKERS == ("MU", "SNDK", "SMH", "SOXX")
    assert module.SUPPORTED_FINANCIAL_TICKERS == ("MU", "SNDK")
    assert module.SUPPORTED_FINANCIAL_FIELDS == (
        "revenue",
        "gross_margin",
        "operating_margin",
    )
    market_parameters = inspect.signature(
        module.fetch_market_observations
    ).parameters
    financial_parameters = inspect.signature(
        module.fetch_financial_observations
    ).parameters
    assert tuple(market_parameters) == (
        "tickers",
        "yahoo_quote_fetcher",
        "retrieved_at",
        "fmp_quote_fetcher",
    )
    assert tuple(financial_parameters) == (
        "tickers",
        "fmp_income_statement_fetcher",
        "retrieved_at",
        "fmp_identity_fetcher",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for name, parameter in market_parameters.items()
        if name != "tickers"
    )


# Gate 3: actual Yahoo/FMP quote shapes, exact metadata, and fallback isolation.
@pytest.mark.parametrize("ticker", provider.SUPPORTED_MARKET_TICKERS)
def test_complete_yahoo_quote_becomes_metadata_complete_observation(ticker):
    calls = []

    result = provider.fetch_market_observations(
        [ticker],
        yahoo_quote_fetcher=lambda symbol: calls.append(symbol)
        or _yahoo_quote(symbol),
        retrieved_at=RETRIEVED_AT,
    )

    assert calls == [ticker]
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["observations"] == [
        {
            "ticker": ticker,
            "value": 123.45,
            "metric_kind": "latest_price",
            "unit": "USD",
            "currency": "USD",
            "as_of": "2026-07-18T20:00:00+00:00",
            "retrieved_at": RETRIEVED_AT,
            "source": "Yahoo Finance",
            "source_field": "regularMarketPrice",
            "source_document": "quote",
            "provenance": None,
            "is_fallback": False,
            "fallback_from": None,
        }
    ]


def test_market_output_order_is_canonical_and_input_is_not_modified():
    tickers = ["SOXX", "MU", "SMH", "SNDK"]
    original = list(tickers)

    result = provider.fetch_market_observations(
        tickers,
        yahoo_quote_fetcher=_yahoo_quote,
        retrieved_at=RETRIEVED_AT,
    )

    assert tickers == original
    assert [item["ticker"] for item in result["observations"]] == [
        "MU",
        "SNDK",
        "SMH",
        "SOXX",
    ]


def test_primary_success_never_calls_fallback():
    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=_yahoo_quote,
        fmp_quote_fetcher=lambda ticker: pytest.fail("fallback must not run"),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"][0]["source"] == "Yahoo Finance"
    assert result["observations"][0]["is_fallback"] is False


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda item: item.pop("regularMarketPrice"), "missing_value"),
        (lambda item: item.update(regularMarketPrice=True), "invalid_value"),
        (lambda item: item.update(regularMarketPrice=math.nan), "invalid_value"),
        (lambda item: item.update(regularMarketPrice=math.inf), "invalid_value"),
        (lambda item: item.pop("currency"), "missing_currency"),
        (lambda item: item.pop("regularMarketTime"), "missing_market_timestamp"),
        (
            lambda item: item.update(regularMarketTime="2026-07-18T20:00:00"),
            "naive_market_timestamp",
        ),
    ],
)
def test_incomplete_yahoo_quote_is_rejected_without_guessing(mutator, expected_code):
    quote = _yahoo_quote()
    mutator(quote)

    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: quote,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert result["status"] == "error"
    assert _market_error_codes(result) == [expected_code]


@pytest.mark.parametrize(
    "unsafe_currency",
    ("USD sk-secret", "USD /Users/private", "US_D", "usd"),
)
def test_market_currency_must_be_safe_uppercase_iso_metadata(unsafe_currency):
    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: _yahoo_quote(
            ticker, currency=unsafe_currency
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert _market_error_codes(result) == ["unsupported_currency"]
    assert unsafe_currency not in json.dumps(result)


def test_safe_non_usd_market_currency_is_preserved_for_phase_46_rejection():
    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: _yahoo_quote(ticker, currency="EUR"),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["status"] == "ok"
    assert result["observations"][0]["currency"] == "EUR"
    assert result["observations"][0]["unit"] == "EUR"


@pytest.mark.parametrize(
    ("metadata", "expected_code"),
    [
        ({"source": None}, "missing_source"),
        ({"source_field": None}, "missing_source_field"),
        ({"source_document": None}, "missing_source_document"),
    ],
)
def test_market_normalizer_rejects_missing_source_metadata(metadata, expected_code):
    settings = {
        "source": "Yahoo Finance",
        "source_field": "regularMarketPrice",
        "market_time_field": "regularMarketTime",
        "source_document": "quote",
    }
    settings.update(metadata)

    observation, code = provider._normalize_market_quote(
        ticker="MU",
        raw_quote=_yahoo_quote(),
        retrieved_at=RETRIEVED_AT,
        is_fallback=False,
        fallback_from=None,
        **settings,
    )

    assert observation is None
    assert code == expected_code


def test_primary_exception_uses_complete_fmp_fallback_and_preserves_its_time():
    calls = []

    def broken_primary(ticker):
        calls.append(("yahoo", ticker))
        raise RuntimeError("Authorization: Bearer secret response body")

    def fallback(ticker):
        calls.append(("fmp", ticker))
        return _fmp_quote(ticker)

    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=broken_primary,
        fmp_quote_fetcher=fallback,
        retrieved_at=RETRIEVED_AT,
    )

    assert calls == [("yahoo", "MU"), ("fmp", "MU")]
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["observations"] == [
        {
            "ticker": "MU",
            "value": 122.75,
            "metric_kind": "latest_price",
            "unit": "USD",
            "currency": "USD",
            "as_of": "2026-07-18T19:59:00+00:00",
            "retrieved_at": RETRIEVED_AT,
            "source": "FMP",
            "source_field": "price",
            "source_document": "quote",
            "provenance": None,
            "is_fallback": True,
            "fallback_from": "Yahoo Finance",
        }
    ]


def test_incomplete_primary_also_uses_fallback():
    calls = []
    incomplete = _yahoo_quote()
    incomplete.pop("currency")

    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: calls.append("primary") or incomplete,
        fmp_quote_fetcher=lambda ticker: calls.append("fallback")
        or _fmp_quote(ticker),
        retrieved_at=RETRIEVED_AT,
    )

    assert calls == ["primary", "fallback"]
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["observations"][0]["source"] == "FMP"


def test_fallback_without_market_timestamp_is_rejected():
    fallback = _fmp_quote()[0]
    fallback.pop("timestamp")

    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: (_ for _ in ()).throw(RuntimeError()),
        fmp_quote_fetcher=lambda ticker: [fallback],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert _market_error_codes(result) == ["missing_market_timestamp"]


def test_unsupported_ticker_and_one_ticker_failure_do_not_hide_other_results():
    def fetcher(ticker):
        if ticker == "SNDK":
            raise RuntimeError("https://example.test/?apikey=do-not-leak")
        return _yahoo_quote(ticker)

    result = provider.fetch_market_observations(
        ["NVDA", "SNDK", "MU"],
        yahoo_quote_fetcher=fetcher,
        retrieved_at=RETRIEVED_AT,
    )

    assert [item["ticker"] for item in result["observations"]] == ["MU"]
    assert result["status"] == "partial"
    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": "NVDA",
            "field": None,
            "code": "unsupported_ticker",
        },
        {
            "family": "market_proxy",
            "ticker": "SNDK",
            "field": None,
            "code": "fetch_failed",
        },
    ]
    serialized = json.dumps(result)
    assert "apikey" not in serialized
    assert "example.test" not in serialized


@pytest.mark.parametrize(
    "unsafe_ticker",
    (
        "sk-secret",
        "XSK-FAKE",
        "sk_live_FAKE",
        "sk_test_FAKE",
        "rk_live_FAKE",
        "rk_test_FAKE",
        "whsec_FAKE",
        "ghp_SECRET",
        "AKIAABCDEFGHIJKLMNOP",
        ".env",
        "secret.env",
    ),
)
def test_unsupported_secret_like_ticker_is_never_echoed(unsafe_ticker):
    result = provider.fetch_market_observations(
        [unsafe_ticker],
        yahoo_quote_fetcher=lambda ticker: pytest.fail("fetch must not run"),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": None,
            "field": None,
            "code": "unsupported_ticker",
        }
    ]
    assert provider._safe_identity(unsafe_ticker) is None
    assert unsafe_ticker.casefold() not in json.dumps(result).casefold()


def test_market_errors_have_exact_safe_fields():
    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError("Traceback /Users/person/key.env response_body sk-secret")
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": "MU",
            "field": None,
            "code": "fetch_failed",
        }
    ]
    assert set(result["errors"][0]) == {"family", "ticker", "field", "code"}
    serialized = json.dumps(result)
    assert "Traceback" not in serialized
    assert "/Users/" not in serialized
    assert "sk-secret" not in serialized


def test_naive_retrieval_time_fails_before_any_fetch():
    calls = []

    with pytest.raises(ValueError, match="retrieved_at"):
        provider.fetch_market_observations(
            ["MU"],
            yahoo_quote_fetcher=lambda ticker: calls.append(ticker),
            retrieved_at="2026-07-18T20:01:00",
        )

    assert calls == []


@pytest.mark.parametrize("market_time", ("20260717", 0, -1))
def test_numeric_string_and_nonpositive_market_epochs_are_not_guessed(market_time):
    result = provider.fetch_market_observations(
        ["MU"],
        yahoo_quote_fetcher=lambda ticker: _yahoo_quote(
            ticker, regularMarketTime=market_time
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert _market_error_codes(result) == ["invalid_market_timestamp"]


def test_numeric_string_retrieval_time_is_rejected_before_fetch():
    calls = []

    with pytest.raises(ValueError, match="retrieved_at"):
        provider.fetch_market_observations(
            ["MU"],
            yahoo_quote_fetcher=lambda ticker: calls.append(ticker),
            retrieved_at="1784404860",
        )

    assert calls == []


def test_market_timestamp_utc_overflow_isolated_from_valid_ticker():
    result = provider.fetch_market_observations(
        ["MU", "SNDK"],
        yahoo_quote_fetcher=lambda ticker: _yahoo_quote(
            ticker,
            regularMarketTime=(
                "0001-01-01T00:00:00+14:00"
                if ticker == "MU"
                else MARKET_TIME
            ),
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert [item["ticker"] for item in result["observations"]] == ["SNDK"]
    assert result["status"] == "partial"
    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": "MU",
            "field": None,
            "code": "invalid_market_timestamp",
        }
    ]


def test_retrieval_timestamp_utc_overflow_fails_before_fetch():
    calls = []

    with pytest.raises(ValueError, match="retrieved_at"):
        provider.fetch_market_observations(
            ["MU"],
            yahoo_quote_fetcher=lambda ticker: calls.append(ticker),
            retrieved_at="0001-01-01T00:00:00+14:00",
        )

    assert calls == []


def test_extreme_market_number_isolated_from_valid_ticker():
    result = provider.fetch_market_observations(
        ["MU", "SNDK"],
        yahoo_quote_fetcher=lambda ticker: _yahoo_quote(
            ticker, regularMarketPrice=10**10_000 if ticker == "MU" else 82.1
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert [item["ticker"] for item in result["observations"]] == ["SNDK"]
    assert result["status"] == "partial"
    assert result["errors"] == [
        {
            "family": "market_proxy",
            "ticker": "MU",
            "field": None,
            "code": "invalid_value",
        }
    ]


def test_required_market_retrieval_time_cannot_be_omitted():
    with pytest.raises(TypeError, match="retrieved_at"):
        provider.fetch_market_observations(
            ["MU"], yahoo_quote_fetcher=_yahoo_quote
        )


def test_market_raw_response_is_unchanged_and_calls_return_fresh_objects():
    raw = _yahoo_quote()
    original = deepcopy(raw)

    first = provider.fetch_market_observations(
        ["MU"], yahoo_quote_fetcher=lambda ticker: raw, retrieved_at=RETRIEVED_AT
    )
    second = provider.fetch_market_observations(
        ["MU"], yahoo_quote_fetcher=lambda ticker: raw, retrieved_at=RETRIEVED_AT
    )

    assert raw == original
    assert first == second
    assert first is not second
    assert first["observations"] is not second["observations"]
    assert first["observations"][0] is not second["observations"][0]


def test_empty_market_scope_performs_no_fetch_and_returns_empty():
    result = provider.fetch_market_observations(
        [],
        yahoo_quote_fetcher=lambda ticker: pytest.fail("fetch must not run"),
        retrieved_at=RETRIEVED_AT,
    )

    assert result == {"observations": [], "errors": [], "status": "empty"}


# Gate 5: one verified FMP statement row supplies all three sibling fields.
@pytest.mark.parametrize("ticker", provider.SUPPORTED_FINANCIAL_TICKERS)
def test_complete_statement_becomes_three_metadata_complete_observations(ticker):
    calls = []

    result = provider.fetch_financial_observations(
        [ticker],
        fmp_income_statement_fetcher=lambda symbol: calls.append(
            ("statement", symbol)
        )
        or [_statement(symbol)],
        fmp_identity_fetcher=(
            lambda symbol: calls.append(("identity", symbol))
            or _identity(symbol)
        ),
        retrieved_at=RETRIEVED_AT,
    )

    expected_calls = (
        [("statement", "MU")]
        if ticker == "MU"
        else [("identity", "SNDK"), ("statement", "SNDK")]
    )
    assert calls == expected_calls
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert [item["field"] for item in result["observations"]] == [
        "revenue",
        "gross_margin",
        "operating_margin",
    ]
    by_field = {item["field"]: item for item in result["observations"]}
    assert by_field["revenue"]["value"] == 9_300_000_000
    assert by_field["revenue"]["unit"] == "USD"
    assert by_field["revenue"]["currency"] == "USD"
    assert by_field["revenue"]["source_field"] == "revenue"
    assert by_field["gross_margin"]["value"] == 0.452
    assert by_field["gross_margin"]["unit"] == "ratio"
    assert by_field["gross_margin"]["currency"] is None
    assert by_field["gross_margin"]["source_field"] == "grossProfitRatio"
    assert by_field["operating_margin"]["value"] == 0.301
    assert by_field["operating_margin"]["unit"] == "ratio"
    assert by_field["operating_margin"]["currency"] is None
    assert by_field["operating_margin"]["source_field"] == (
        "operatingIncomeRatio"
    )
    for observation in result["observations"]:
        assert observation["ticker"] == ticker
        assert observation["fiscal_period"] == "2026 Q3"
        assert observation["period_type"] == "quarterly"
        assert observation["as_of"] == "2026-05-29"
        assert observation["retrieved_at"] == RETRIEVED_AT
        assert observation["source"] == "FMP"
        assert observation["source_document"] == "income_statement"
        assert "income statement" in observation["provenance"].lower()
        assert observation["source_reference"] is None
        assert observation["is_fallback"] is False
        assert observation["fallback_from"] is None


def test_provider_ratios_are_converted_to_percent_only_by_phase_46_service():
    provider_result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [_statement(ticker)],
        retrieved_at=RETRIEVED_AT,
    )

    production_result = build_company_financial_metrics(
        provider_result["observations"], evaluated_at="2026-07-18T20:10:00+00:00"
    )
    values = {metric["metric_id"]: metric["value"] for metric in production_result["metrics"][:3]}

    assert values == {
        "company_revenue": 9_300.0,
        "gross_margin": 45.2,
        "operating_margin": 30.099999999999998,
    }


def test_annual_period_uses_neutral_provider_year_label():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, date="2025-08-28", calendarYear="2025", period="FY")
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["fiscal_period"] for item in result["observations"]} == {"2025"}
    assert {item["period_type"] for item in result["observations"]} == {"annual"}


def test_explicit_fiscal_year_takes_priority_without_using_mu_calendar_rules():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, calendarYear="2025", fiscalYear="2026")
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["fiscal_period"] for item in result["observations"]} == {
        "2026 Q3"
    }


def test_mixed_statement_rows_select_latest_verifiable_period_end_not_list_order():
    rows = [
        _statement("MU", date="2025-08-28", calendarYear="2025", period="FY"),
        _statement("MU", date="2026-05-29", calendarYear="2026", period="Q3"),
    ]

    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: list(reversed(rows)),
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["as_of"] for item in result["observations"]} == {"2026-05-29"}
    assert {item["period_type"] for item in result["observations"]} == {
        "quarterly"
    }


def test_ambiguous_same_date_statement_rows_are_rejected():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, period="Q4"),
            _statement(ticker, period="FY"),
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"ambiguous_statement"}


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda row: row.pop("date"), "missing_as_of"),
        (lambda row: row.pop("calendarYear"), "missing_period_metadata"),
        (lambda row: row.update(period="TTM"), "unsupported_period"),
        (lambda row: row.pop("reportedCurrency"), "missing_currency"),
    ],
)
def test_missing_shared_statement_metadata_rejects_all_fields(mutator, expected_code):
    row = _statement()
    mutator(row)

    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [row],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {expected_code}
    assert {error["field"] for error in result["errors"]} == set(
        provider.SUPPORTED_FINANCIAL_FIELDS
    )


def test_calendar_year_must_match_period_end_year_when_no_fiscal_year_exists():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, date="2026-05-29", calendarYear="1999")
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"period_year_mismatch"}


def test_invalid_statement_errors_are_independent_of_raw_list_order():
    rows = [
        _statement("MU", date=None),
        _statement("MU", period="TTM"),
    ]

    first = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: rows,
        retrieved_at=RETRIEVED_AT,
    )
    second = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: list(reversed(rows)),
        retrieved_at=RETRIEVED_AT,
    )

    assert first == second


def test_empty_statement_response_is_not_presented_as_empty_request_scope():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert result["status"] == "error"
    assert set(_financial_error_codes(result)) == {"empty_response"}


@pytest.mark.parametrize(
    "unsafe_currency",
    ("USD sk-secret", "USD /Users/private", "US_D", "usd"),
)
def test_financial_currency_must_be_safe_uppercase_iso_metadata(unsafe_currency):
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, reportedCurrency=unsafe_currency)
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"unsupported_currency"}
    assert unsafe_currency not in json.dumps(result)


def test_safe_non_usd_financial_currency_is_preserved_for_phase_46_rejection():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, reportedCurrency="EUR")
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["status"] == "ok"
    revenue = next(
        item for item in result["observations"] if item["field"] == "revenue"
    )
    assert revenue["currency"] == "EUR"
    assert revenue["unit"] == "EUR"


@pytest.mark.parametrize(
    ("field", "raw_field"),
    [
        ("revenue", "revenue"),
        ("gross_margin", "grossProfitRatio"),
        ("operating_margin", "operatingIncomeRatio"),
    ],
)
def test_one_missing_financial_field_preserves_sibling_fields(field, raw_field):
    row = _statement()
    row.pop(raw_field)

    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [row],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["status"] == "partial"
    assert {item["field"] for item in result["observations"]} == (
        set(provider.SUPPORTED_FINANCIAL_FIELDS) - {field}
    )
    assert _financial_error_codes(result, field=field) == ["missing_value"]


@pytest.mark.parametrize("bad_value", [True, math.nan, math.inf])
@pytest.mark.parametrize(
    ("field", "raw_field"),
    [
        ("gross_margin", "grossProfitRatio"),
        ("operating_margin", "operatingIncomeRatio"),
    ],
)
def test_invalid_ratio_is_rejected_without_hiding_siblings(
    field, raw_field, bad_value
):
    row = _statement(**{raw_field: bad_value})

    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [row],
        retrieved_at=RETRIEVED_AT,
    )

    assert field not in {item["field"] for item in result["observations"]}
    assert _financial_error_codes(result, field=field) == ["invalid_value"]


def test_extreme_revenue_is_invalid_without_losing_margin_siblings():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, revenue=10**10_000)
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["field"] for item in result["observations"]} == {
        "gross_margin",
        "operating_margin",
    }
    assert _financial_error_codes(result, field="revenue") == ["invalid_value"]


def test_unsupported_margin_source_field_is_not_substituted():
    row = _statement()
    row.pop("grossProfitRatio")
    row["grossProfitMargin"] = 0.452

    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: [row],
        retrieved_at=RETRIEVED_AT,
    )

    assert _financial_error_codes(result, field="gross_margin") == [
        "unsupported_source_field"
    ]
    assert "gross_margin" not in {
        item["field"] for item in result["observations"]
    }


def test_sndk_requires_current_sandisk_identity_and_never_maps_wdc():
    calls = []

    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: calls.append(
            ("statement", ticker)
        )
        or [_statement(ticker)],
        fmp_identity_fetcher=lambda ticker: calls.append(("identity", ticker))
        or _identity("WDC", "Western Digital Corporation"),
        retrieved_at=RETRIEVED_AT,
    )

    assert calls == [("identity", "SNDK")]
    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"identity_unverified"}
    assert "WDC" not in json.dumps(result)


def test_sndk_profile_name_requires_a_complete_sandisk_word_match():
    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: pytest.fail(
            "statement must not run"
        ),
        fmp_identity_fetcher=lambda ticker: _identity(
            ticker, "San Diskette Holdings"
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"identity_unverified"}


@pytest.mark.parametrize("reverse_identity_rows", (False, True))
def test_sndk_distinct_valid_profile_ciks_are_ambiguous_independent_of_order(
    reverse_identity_rows,
):
    identity_rows = [
        _identity(cik="0000000002")[0],
        _identity(name="San Disk Holdings", cik="0000000003")[0],
    ]
    if reverse_identity_rows:
        identity_rows.reverse()

    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: pytest.fail(
            "statement must not run for ambiguous identity"
        ),
        fmp_identity_fetcher=lambda ticker: identity_rows,
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"identity_unverified"}


def test_sndk_duplicate_profile_rows_with_the_same_cik_are_deduplicated():
    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: [_statement(ticker)],
        fmp_identity_fetcher=lambda ticker: [
            _identity(ticker, cik="0000000002")[0],
            _identity(
                ticker, name="San Disk Corporation", cik="0000000002"
            )[0],
        ],
        retrieved_at=RETRIEVED_AT,
    )

    assert result["status"] == "ok"
    assert len(result["observations"]) == 3
    assert result["errors"] == []


def test_sndk_statement_cik_must_match_profile_cik():
    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, cik="0000009999")
        ],
        fmp_identity_fetcher=lambda ticker: _identity(ticker, cik="0000000002"),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {
        "statement_identity_mismatch"
    }


def test_sndk_without_identity_fetcher_is_unavailable_without_fetching_statement():
    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: pytest.fail(
            "statement must not run before identity is verified"
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"identity_unverified"}


def test_sndk_legacy_period_is_rejected_instead_of_spliced():
    result = provider.fetch_financial_observations(
        ["SNDK"],
        fmp_income_statement_fetcher=lambda ticker: [
            _statement(ticker, date="2024-12-31", calendarYear="2024")
        ],
        fmp_identity_fetcher=lambda ticker: _identity(ticker),
        retrieved_at=RETRIEVED_AT,
    )

    assert result["observations"] == []
    assert set(_financial_error_codes(result)) == {"legacy_statement"}


def test_one_company_failure_does_not_hide_the_other_company():
    def statements(ticker):
        if ticker == "MU":
            raise RuntimeError("response_body https://host.test?apikey=secret")
        return [_statement(ticker)]

    result = provider.fetch_financial_observations(
        ["SNDK", "MU"],
        fmp_income_statement_fetcher=statements,
        fmp_identity_fetcher=lambda ticker: _identity(ticker),
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["ticker"] for item in result["observations"]} == {"SNDK"}
    assert set(_financial_error_codes(result)) == {"fetch_failed"}
    serialized = json.dumps(result)
    assert "response_body" not in serialized
    assert "apikey" not in serialized


def test_sndk_failure_does_not_hide_mu():
    result = provider.fetch_financial_observations(
        ["MU", "SNDK"],
        fmp_income_statement_fetcher=lambda ticker: [_statement(ticker)],
        fmp_identity_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError("SNDK identity unavailable")
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert {item["ticker"] for item in result["observations"]} == {"MU"}
    assert {
        (error["ticker"], error["code"]) for error in result["errors"]
    } == {("SNDK", "identity_unverified")}


def test_financial_errors_have_only_safe_contract_fields():
    result = provider.fetch_financial_observations(
        ["MU"],
        fmp_income_statement_fetcher=lambda ticker: (_ for _ in ()).throw(
            RuntimeError("Traceback /Users/person/.env Authorization sk-secret")
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert len(result["errors"]) == 3
    assert all(
        set(error) == {"family", "ticker", "field", "code"}
        for error in result["errors"]
    )
    serialized = json.dumps(result)
    assert "Traceback" not in serialized
    assert "/Users/" not in serialized
    assert "sk-secret" not in serialized


def test_financial_raw_response_and_ticker_input_are_not_modified():
    tickers = ["MU"]
    raw = [_statement()]
    original_tickers = list(tickers)
    original_raw = deepcopy(raw)

    first = provider.fetch_financial_observations(
        tickers,
        fmp_income_statement_fetcher=lambda ticker: raw,
        retrieved_at=RETRIEVED_AT,
    )
    second = provider.fetch_financial_observations(
        tickers,
        fmp_income_statement_fetcher=lambda ticker: raw,
        retrieved_at=RETRIEVED_AT,
    )

    assert tickers == original_tickers
    assert raw == original_raw
    assert first == second
    assert first is not second
    assert first["observations"] is not second["observations"]
    assert first["observations"][0] is not second["observations"][0]


def test_naive_financial_retrieval_time_fails_before_fetch():
    calls = []

    with pytest.raises(ValueError, match="retrieved_at"):
        provider.fetch_financial_observations(
            ["MU"],
            fmp_income_statement_fetcher=lambda ticker: calls.append(ticker),
            retrieved_at="2026-07-18T20:01:00",
        )

    assert calls == []


def test_required_financial_retrieval_time_cannot_be_omitted():
    with pytest.raises(TypeError, match="retrieved_at"):
        provider.fetch_financial_observations(
            ["MU"], fmp_income_statement_fetcher=lambda ticker: []
        )


def test_empty_financial_scope_performs_no_fetch_and_returns_empty():
    result = provider.fetch_financial_observations(
        [],
        fmp_income_statement_fetcher=lambda ticker: pytest.fail(
            "fetch must not run"
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert result == {"observations": [], "errors": [], "status": "empty"}
