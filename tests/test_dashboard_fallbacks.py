import pytest

from conftest import import_root_dashboard


dashboard = import_root_dashboard()


@pytest.fixture(autouse=True)
def clear_card_financial_cache():
    dashboard.get_card_financial_fields.clear()
    yield
    dashboard.get_card_financial_fields.clear()


def test_card_financials_keep_complete_fmp_payload_without_calling_yahoo(monkeypatch):
    fmp = {
        "ticker": "FMPONLY",
        "name": "FMP Company",
        "market_cap": 1_000,
        "revenue": 500,
        "net_margin": 0.25,
        "financial_source": "FMP",
    }
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    monkeypatch.setattr(dashboard, "_fmp_card_financial_fields", lambda ticker: dict(fmp))
    monkeypatch.setattr(
        dashboard,
        "_yfinance_card_financial_fields",
        lambda ticker: pytest.fail("Yahoo fallback must not run for a complete FMP payload"),
    )

    result = dashboard.get_card_financial_fields(" fmponly ")

    assert result == fmp


def test_card_financials_fill_only_missing_fmp_fields_from_yahoo(monkeypatch):
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    monkeypatch.setattr(
        dashboard,
        "_fmp_card_financial_fields",
        lambda ticker: {
            "ticker": ticker,
            "name": ticker,
            "market_cap": 1_000,
            "revenue": None,
            "net_margin": 0.20,
            "financial_source": "FMP",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "_yfinance_card_financial_fields",
        lambda ticker: {
            "ticker": ticker,
            "name": "Yahoo Company",
            "market_cap": 900,
            "revenue": 450,
            "net_margin": 0.15,
            "financial_source": "yfinance fallback",
        },
    )

    result = dashboard.get_card_financial_fields("partial")

    assert result == {
        "ticker": "PARTIAL",
        "name": "Yahoo Company",
        "market_cap": 1_000,
        "revenue": 450,
        "net_margin": 0.20,
        "financial_source": "FMP",
    }


def test_card_financials_use_explicit_yahoo_fallback_when_fmp_raises(monkeypatch):
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)

    def fail_fmp(ticker):
        raise RuntimeError("FMP unavailable")

    monkeypatch.setattr(dashboard, "_fmp_card_financial_fields", fail_fmp)
    monkeypatch.setattr(
        dashboard,
        "_yfinance_card_financial_fields",
        lambda ticker: {
            "ticker": ticker,
            "name": "Yahoo Company",
            "market_cap": 900,
            "revenue": 450,
            "net_margin": 0.15,
            "financial_source": "yfinance fallback",
        },
    )

    result = dashboard.get_card_financial_fields("fallback")

    assert result["ticker"] == "FALLBACK"
    assert result["financial_source"] == "yfinance fallback"
    assert result["market_cap"] == 900
    assert result["revenue"] == 450
    assert result["net_margin"] == 0.15


def test_card_financials_characterize_empty_yahoo_fallback_after_provider_failures(monkeypatch):
    monkeypatch.setattr(dashboard, "track_cacheable_call", lambda: None)
    monkeypatch.setattr(
        dashboard,
        "_fmp_card_financial_fields",
        lambda ticker: (_ for _ in ()).throw(RuntimeError("FMP unavailable")),
    )
    monkeypatch.setattr(
        dashboard,
        "_yfinance_card_financial_fields",
        lambda ticker: {
            "ticker": ticker,
            "name": ticker,
            "market_cap": None,
            "revenue": None,
            "net_margin": None,
            "financial_source": "yfinance fallback",
        },
    )

    result = dashboard.get_card_financial_fields("empty")

    assert result == {
        "ticker": "EMPTY",
        "name": "EMPTY",
        "market_cap": None,
        "revenue": None,
        "net_margin": None,
        "financial_source": "yfinance fallback",
    }
