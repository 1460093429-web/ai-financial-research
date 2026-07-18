"""Regression coverage for the Phase 4.6 pure production pipeline."""

import ast
from copy import deepcopy
from datetime import date, datetime, timezone
import importlib
import inspect
import json
import math
from pathlib import Path

import pytest

import services.memory_cycle_production as production
from services.memory_cycle_contract import REQUIRED_METRIC_FIELDS, validate_metric_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PATH = PROJECT_ROOT / "services" / "memory_cycle_production.py"
EVALUATED_AT = "2026-07-18T20:10:00+00:00"


def _market_observation(ticker="MU", **overrides):
    observation = {
        "ticker": ticker,
        "value": 123.45,
        "metric_kind": "latest_price",
        "unit": "USD",
        "currency": "USD",
        "as_of": "2026-07-18T20:00:00+00:00",
        "retrieved_at": "2026-07-18T20:01:00+00:00",
        "source": "Yahoo Finance",
        "source_field": "regularMarketPrice",
        "source_document": "quote",
        "provenance": None,
        "is_fallback": False,
        "fallback_from": None,
    }
    observation.update(overrides)
    return observation


def _financial_observation(ticker="MU", field="revenue", **overrides):
    field_values = {
        "revenue": {
            "value": 7_200_000_000.0,
            "unit": "USD",
            "currency": "USD",
            "source_field": "revenue",
        },
        "gross_margin": {
            "value": 0.452,
            "unit": "ratio",
            "currency": None,
            "source_field": "grossProfitRatio",
        },
        "operating_margin": {
            "value": 0.301,
            "unit": "ratio",
            "currency": None,
            "source_field": "operatingIncomeRatio",
        },
    }
    observation = {
        "ticker": ticker,
        "field": field,
        **field_values.get(field, field_values["revenue"]),
        "fiscal_period": "FY2026 Q3",
        "period_type": "quarterly",
        "as_of": "2026-07-10",
        "retrieved_at": "2026-07-18T20:00:00+00:00",
        "source": "FMP",
        "source_document": "income_statement",
        "source_reference": None,
        "provenance": None,
        "is_fallback": False,
        "fallback_from": None,
    }
    observation.update(overrides)
    return observation


def _all_market_observations():
    return [
        _market_observation(ticker, value=value)
        for ticker, value in zip(production.SUPPORTED_MARKET_TICKERS, (123.45, 82.1, 301.2, 250.4))
    ]


def _all_financial_observations():
    return [
        _financial_observation(ticker, field)
        for ticker in production.SUPPORTED_FINANCIAL_TICKERS
        for field in production.SUPPORTED_FINANCIAL_FIELDS
    ]


def _metric_for(result, metric_id, *, label_prefix=None):
    matches = [
        metric
        for metric in result["metrics"]
        if metric["metric_id"] == metric_id
        and (label_prefix is None or metric["label"].startswith(label_prefix))
    ]
    assert len(matches) == 1
    return matches[0]


def _error_codes(result):
    return [error["code"] for error in result["errors"]]


def _serialized(result):
    return json.dumps(result, sort_keys=True, default=str)


def _assert_contract(metric):
    assert tuple(metric) == REQUIRED_METRIC_FIELDS
    assert validate_metric_record(metric, evaluated_at=EVALUATED_AT) == []


# Cases 1-11: import, supported scope, stable constants, and forbidden outputs.
def test_production_module_imports_without_executing_work():
    assert importlib.import_module("services.memory_cycle_production") is production


def test_supported_market_tickers_and_financial_fields_are_stable_tuples():
    assert production.SUPPORTED_MARKET_TICKERS == ("MU", "SNDK", "SMH", "SOXX")
    assert production.SUPPORTED_FINANCIAL_TICKERS == ("MU", "SNDK")
    assert production.SUPPORTED_FINANCIAL_FIELDS == (
        "revenue",
        "gross_margin",
        "operating_margin",
    )
    assert production.MARKET_METRIC_KIND == "latest_price"


def test_module_level_metric_and_normalization_mappings_are_immutable():
    with pytest.raises(TypeError):
        production.MARKET_METRIC_IDS["MU"] = "changed"
    with pytest.raises(TypeError):
        production.FINANCIAL_METRIC_IDS["revenue"] = "changed"
    with pytest.raises(TypeError):
        production._REVENUE_TO_USD_MILLIONS["USD"] = 1
    with pytest.raises(TypeError):
        production._MARGIN_SOURCE_FIELDS["gross_margin"]["grossProfitRatio"] = (
            "percent"
        )


def test_canonical_metric_order_is_stable_and_contains_exactly_ten_slots():
    assert production.CANONICAL_METRIC_ORDER == (
        ("market_proxy", "MU", None),
        ("market_proxy", "SNDK", None),
        ("market_proxy", "SMH", None),
        ("market_proxy", "SOXX", None),
        ("company_financial", "MU", "revenue"),
        ("company_financial", "MU", "gross_margin"),
        ("company_financial", "MU", "operating_margin"),
        ("company_financial", "SNDK", "revenue"),
        ("company_financial", "SNDK", "gross_margin"),
        ("company_financial", "SNDK", "operating_margin"),
    )


def test_module_defines_no_score_or_cycle_phase_constant():
    tree = ast.parse(PRODUCTION_PATH.read_text(encoding="utf-8"))
    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    normalized = {name.casefold() for name in assigned_names}
    assert not any("score" in name or "cycle_phase" in name for name in normalized)


# Cases 12-28: complete market observations and proxy semantics.
@pytest.mark.parametrize("ticker", ("MU", "SNDK", "SMH", "SOXX"))
def test_complete_market_observation_succeeds_for_each_supported_ticker(ticker):
    result = production.build_market_proxy_metrics(
        [_market_observation(ticker)], evaluated_at=EVALUATED_AT
    )
    metric = _metric_for(result, f"{ticker.lower()}_market_price_proxy")
    _assert_contract(metric)
    assert metric["value"] == 123.45
    assert metric["source_type"] == "proxy"
    assert metric["is_estimate"] is True
    assert metric["confidence"] == "medium"
    assert metric["status"] == "ok"


def test_all_four_market_observations_succeed_in_canonical_order():
    observations = list(reversed(_all_market_observations()))
    result = production.build_market_proxy_metrics(observations, evaluated_at=EVALUATED_AT)

    assert [metric["metric_id"] for metric in result["metrics"]] == [
        "mu_market_price_proxy",
        "sndk_market_price_proxy",
        "smh_market_price_proxy",
        "soxx_market_price_proxy",
    ]
    assert all(metric["status"] == "ok" for metric in result["metrics"])
    assert result["errors"] == []


def test_market_metric_preserves_times_and_explicit_provenance():
    observation = _market_observation(
        as_of="2026-07-18T19:59:01+00:00",
        retrieved_at="2026-07-18T20:02:03+00:00",
        source_field="regularMarketPrice",
        source_document="Yahoo quote response",
    )
    result = production.build_market_proxy_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]

    assert metric["as_of"] == observation["as_of"]
    assert metric["retrieved_at"] == observation["retrieved_at"]
    assert "Currency: USD" in metric["notes"]
    assert "Source field: regularMarketPrice" in metric["notes"]
    assert "Source document: Yahoo quote response" in metric["notes"]
    assert "latest market price" in metric["notes"].lower()
    assert "proxy" in metric["notes"].lower()


def test_market_provenance_can_replace_source_document():
    result = production.build_market_proxy_metrics(
        [_market_observation(source_document=None, provenance="verified quote lineage")],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "ok"
    assert "Provenance: verified quote lineage" in metric["notes"]


def test_market_output_contains_no_fundamental_inference_or_trading_signal():
    result = production.build_market_proxy_metrics(
        _all_market_observations(), evaluated_at=EVALUATED_AT
    )
    for metric in result["metrics"]:
        identity = f"{metric['metric_id']} {metric['label']}".casefold()
        assert all(term not in identity for term in ("dram", "nand", "hbm", "score", "cycle_phase"))
        assert all(term not in identity for term in ("buy", "sell", "bullish", "bearish"))


# Cases 29-52: market validation and isolated failures.
@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda item: item.pop("ticker"), "unsupported_ticker"),
        (lambda item: item.update(ticker="NVDA"), "unsupported_ticker"),
        (lambda item: item.pop("value"), "missing_value"),
        (lambda item: item.update(value=None), "missing_value"),
        (lambda item: item.update(value=""), "missing_value"),
        (lambda item: item.update(value=True), "invalid_value"),
        (lambda item: item.update(value=math.nan), "invalid_value"),
        (lambda item: item.update(value=math.inf), "invalid_value"),
        (lambda item: item.update(value=-math.inf), "invalid_value"),
        (lambda item: item.pop("metric_kind"), "missing_metric_kind"),
        (lambda item: item.update(metric_kind="last_close"), "unsupported_metric_kind"),
        (lambda item: item.pop("unit"), "missing_unit"),
        (lambda item: item.pop("currency"), "missing_currency"),
        (lambda item: item.pop("as_of"), "missing_price_time"),
        (lambda item: item.update(as_of="2026-07-18T20:00:00"), "naive_price_time"),
        (lambda item: item.pop("retrieved_at"), "missing_retrieved_at"),
        (lambda item: item.update(retrieved_at="2026-07-18T20:01:00"), "naive_retrieved_at"),
        (lambda item: item.pop("source"), "missing_source"),
        (lambda item: item.pop("source_field"), "missing_source_field"),
        (
            lambda item: (item.pop("source_document"), item.update(provenance=None)),
            "missing_source_document",
        ),
        (lambda item: item.pop("is_fallback"), "invalid_fallback_metadata"),
        (
            lambda item: item.update(is_fallback=True, fallback_from=None),
            "invalid_fallback_metadata",
        ),
    ],
)
def test_invalid_market_observation_returns_stable_code(mutator, expected_code):
    observation = _market_observation()
    mutator(observation)
    before = deepcopy(observation)

    result = production.build_market_proxy_metrics([observation], evaluated_at=EVALUATED_AT)

    assert expected_code in _error_codes(result)
    assert observation == before
    assert all(set(error) == {"family", "ticker", "field", "code"} for error in result["errors"])
    assert all(metric["status"] in {"missing", "unavailable"} for metric in result["metrics"])
    assert _serialized(result).find(repr(before)) == -1


def test_invalid_market_observation_does_not_affect_other_tickers():
    invalid_mu = _market_observation("MU", value=math.nan)
    valid_soxx = _market_observation("SOXX", value=250.4)
    result = production.build_market_proxy_metrics(
        [valid_soxx, invalid_mu], evaluated_at=EVALUATED_AT
    )

    assert result["metrics"][0]["status"] == "missing"
    assert result["metrics"][3]["status"] == "ok"
    assert result["metrics"][3]["value"] == 250.4
    assert "invalid_value" in _error_codes(result)


def test_extreme_integer_is_invalid_without_crashing_market_siblings():
    result = production.build_market_proxy_metrics(
        [_market_observation("MU", value=10**400), _market_observation("SOXX")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert result["metrics"][3]["status"] == "ok"
    assert "invalid_value" in _error_codes(result)


def test_market_error_never_contains_the_raw_observation():
    observation = _market_observation(value="TOP_SECRET_RAW_PAYLOAD")
    result = production.build_market_proxy_metrics([observation], evaluated_at=EVALUATED_AT)
    assert "TOP_SECRET_RAW_PAYLOAD" not in _serialized(result)


@pytest.mark.parametrize("value", (0.0, -123.45))
def test_latest_market_price_must_be_positive(value):
    result = production.build_market_proxy_metrics(
        [_market_observation(value=value)], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_value" in _error_codes(result)


def test_unrelated_market_source_field_is_rejected():
    result = production.build_market_proxy_metrics(
        [_market_observation(source_field="marketCap")], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source_field" in _error_codes(result)


@pytest.mark.parametrize(
    ("source", "source_document"),
    [
        ("Static fixture", "quote"),
        ("Demo data", "quote"),
        ("Daily Brief", "news article"),
    ],
)
def test_market_rejects_fixture_demo_and_news_provenance(source, source_document):
    result = production.build_market_proxy_metrics(
        [_market_observation(source=source, source_document=source_document)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source" in _error_codes(result)


@pytest.mark.parametrize(
    "source",
    (
        "IBKR",
        "Interactive Brokers",
        "Yahoo",
        "Yahoo Finance",
        "yfinance",
        "FMP",
        "Financial Modeling Prep",
    ),
)
def test_market_accepts_each_approved_provider_name(source):
    result = production.build_market_proxy_metrics(
        [_market_observation(source=source)], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["errors"] == []


@pytest.mark.parametrize("source", ("Seeking Alpha", "Unknown Provider"))
def test_market_rejects_sources_outside_the_approved_provider_set(source):
    result = production.build_market_proxy_metrics(
        [_market_observation(source=source)], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source" in _error_codes(result)


def test_market_fallback_from_unapproved_provider_is_rejected():
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                source="FMP",
                is_fallback=True,
                fallback_from="Seeking Alpha",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_fallback_metadata" in _error_codes(result)


@pytest.mark.parametrize(
    ("source", "fallback_from"),
    (
        ("FMP", "FMP"),
        ("FMP", "Financial Modeling Prep"),
        ("Yahoo", "Yahoo Finance"),
        ("yfinance", "Yahoo"),
        ("IBKR", "Interactive Brokers"),
    ),
)
def test_market_fallback_source_must_be_a_different_canonical_provider(
    source, fallback_from
):
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                source=source,
                is_fallback=True,
                fallback_from=fallback_from,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert result["metrics"][0]["is_fallback"] is False
    assert "invalid_fallback_metadata" in _error_codes(result)


def test_rejected_market_source_cannot_retain_a_fallback_badge():
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                source="Unknown Provider",
                is_fallback=True,
                fallback_from="Yahoo Finance",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["source"] == "unavailable"
    assert metric["is_fallback"] is False


@pytest.mark.parametrize("fallback_from", (123, True, {"source": "FMP"}, ["FMP"]))
def test_nonfallback_market_observation_rejects_nonmissing_fallback_metadata(
    fallback_from
):
    result = production.build_market_proxy_metrics(
        [_market_observation(is_fallback=False, fallback_from=fallback_from)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_fallback_metadata" in _error_codes(result)


@pytest.mark.parametrize(
    ("source_document", "provenance"),
    (
        ("income_statement", None),
        ("Form 10-Q income statement", None),
        ("annual report", None),
        (None, "SEC filing income statement"),
    ),
)
def test_market_rejects_non_price_source_evidence(source_document, provenance):
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                source_document=source_document,
                provenance=provenance,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source_document" in _error_codes(result)


@pytest.mark.parametrize(
    "evidence",
    ("quote", "market data response", "price snapshot", "historical close"),
)
def test_market_accepts_explicit_price_evidence(evidence):
    result = production.build_market_proxy_metrics(
        [_market_observation(source_document=evidence)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["errors"] == []


@pytest.mark.parametrize(
    ("ticker", "source_document"),
    (
        ("MU", "SNDK quote"),
        ("SNDK", "Micron quote response"),
        ("SMH", "SOXX price snapshot"),
        ("SOXX", "MU market data response"),
    ),
)
def test_market_evidence_cannot_explicitly_name_another_supported_ticker(
    ticker, source_document
):
    result = production.build_market_proxy_metrics(
        [_market_observation(ticker, source_document=source_document)],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, f"{ticker.lower()}_market_price_proxy")
    assert metric["status"] == "missing"
    assert "ticker_identity_mismatch" in _error_codes(result)
    assert source_document not in _serialized(result)


def test_market_identity_conflict_cannot_retain_source_or_fallback_lineage():
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                "MU",
                source="FMP",
                source_document="SNDK quote",
                is_fallback=True,
                fallback_from="Yahoo Finance",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["source"] == "unavailable"
    assert metric["is_fallback"] is False
    assert "Fallback from:" not in metric["notes"]


def test_normal_asian_market_evidence_is_not_treated_as_a_secret_token():
    result = production.build_market_proxy_metrics(
        [_market_observation(source_document="Asian market data quote")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["errors"] == []


def test_non_usd_market_currency_is_mismatch_not_missing():
    result = production.build_market_proxy_metrics(
        [_market_observation(currency="EUR")], evaluated_at=EVALUATED_AT
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert "currency_unit_mismatch" in _error_codes(result)
    assert "missing_currency" not in _error_codes(result)
    assert "Reported currency: EUR" in metric["notes"]


# Cases 53-61: stale values and fallback lineage.
def test_stale_market_fallback_preserves_value_age_source_and_lineage():
    observation = _market_observation(
        value=118.2,
        as_of="2026-07-10T20:00:00+00:00",
        retrieved_at="2026-07-18T20:01:00+00:00",
        source="FMP",
        source_field="price",
        source_document="quote",
        is_fallback=True,
        fallback_from="Yahoo Finance",
    )
    result = production.build_market_proxy_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]

    assert metric["value"] == 118.2
    assert metric["status"] == "stale"
    assert metric["staleness_days"] == 8
    assert metric["source"] == "FMP"
    assert metric["as_of"] == observation["as_of"]
    assert metric["is_fallback"] is True
    assert metric["confidence"] == "low"
    assert "Fallback from: Yahoo Finance" in metric["notes"]


@pytest.mark.parametrize(
    "as_of",
    (None, "2026-07-10T20:00:00"),
)
def test_fallback_without_reliable_price_time_is_rejected(as_of):
    result = production.build_market_proxy_metrics(
        [
            _market_observation(
                as_of=as_of,
                is_fallback=True,
                fallback_from="Yahoo Finance",
                source="FMP",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert set(_error_codes(result)) & {"missing_price_time", "naive_price_time"}


def test_invalid_market_value_retains_other_verified_fallback_metadata():
    observation = _market_observation(
        value=None,
        source="FMP",
        source_field="price",
        source_document="quote",
        is_fallback=True,
        fallback_from="Yahoo Finance",
    )
    result = production.build_market_proxy_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["source"] == "FMP"
    assert metric["as_of"] == observation["as_of"]
    assert metric["retrieved_at"] == observation["retrieved_at"]
    assert metric["is_fallback"] is True
    assert "Fallback from: Yahoo Finance" in metric["notes"]


# Cases 62-78: complete company financial observations and metadata.
@pytest.mark.parametrize("ticker", ("MU", "SNDK"))
@pytest.mark.parametrize(
    ("field", "expected_value", "expected_unit"),
    [
        ("revenue", 7200.0, "USD millions"),
        ("gross_margin", 45.2, "percent"),
        ("operating_margin", 30.1, "percent"),
    ],
)
def test_complete_company_financial_observation_succeeds(
    ticker, field, expected_value, expected_unit
):
    result = production.build_company_financial_metrics(
        [_financial_observation(ticker, field)], evaluated_at=EVALUATED_AT
    )
    metric_id = production.FINANCIAL_METRIC_IDS[field]
    metric = _metric_for(result, metric_id, label_prefix=ticker)
    _assert_contract(metric)
    assert metric["value"] == pytest.approx(expected_value)
    assert metric["unit"] == expected_unit
    assert metric["source_type"] == "company_reported"
    assert metric["status"] == "ok"


def test_all_six_financial_metrics_succeed_in_canonical_order():
    observations = list(reversed(_all_financial_observations()))
    result = production.build_company_financial_metrics(
        observations, evaluated_at=EVALUATED_AT
    )

    assert [(metric["label"].split()[0], metric["metric_id"]) for metric in result["metrics"]] == [
        ("MU", "company_revenue"),
        ("MU", "gross_margin"),
        ("MU", "operating_margin"),
        ("SNDK", "company_revenue"),
        ("SNDK", "gross_margin"),
        ("SNDK", "operating_margin"),
    ]
    assert all(metric["status"] == "ok" for metric in result["metrics"])
    assert result["errors"] == []


def test_financial_metric_preserves_period_currency_and_provenance_in_contract_fields():
    observation = _financial_observation(
        fiscal_period="FY2026 Q3",
        period_type="quarterly",
        as_of="2026-07-10",
        retrieved_at="2026-07-18T20:00:00+00:00",
        source_field="revenue",
        source_document="Form 10-Q income statement",
        source_reference="https://filings.example.com/filing",
    )
    result = production.build_company_financial_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]

    assert metric["as_of"] == observation["as_of"]
    assert metric["retrieved_at"] == observation["retrieved_at"]
    assert metric["source"] == "FMP"
    assert "Fiscal period label: FY2026 Q3" in metric["notes"]
    assert "Fiscal period: quarterly" in metric["notes"]
    assert "Period type: quarterly" in metric["notes"]
    assert "Currency: USD" in metric["notes"]
    assert "Source field: revenue" in metric["notes"]
    assert "Source document: Form 10-Q income statement" in metric["notes"]
    assert "Source reference: https://filings.example.com/filing" in metric["notes"]


def test_financial_source_document_and_provenance_are_both_preserved():
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source_document="Form 10-Q income statement",
                provenance="SEC filing accession verified",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "ok"
    assert "Source document: Form 10-Q income statement" in metric["notes"]
    assert "Provenance: SEC filing accession verified" in metric["notes"]


def test_financial_verified_provenance_can_replace_source_document():
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source_document=None,
                provenance="SEC filing accession verified",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "ok"
    assert "Provenance: SEC filing accession verified" in metric["notes"]


# Cases 79-103: financial validation and isolation.
@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda item: item.pop("ticker"), "unsupported_ticker"),
        (lambda item: item.update(ticker="NVDA"), "unsupported_ticker"),
        (lambda item: item.pop("field"), "unsupported_field"),
        (lambda item: item.update(field="eps"), "unsupported_field"),
        (lambda item: item.pop("value"), "missing_value"),
        (lambda item: item.update(value=None), "missing_value"),
        (lambda item: item.update(value=True), "invalid_value"),
        (lambda item: item.update(value=math.nan), "invalid_value"),
        (lambda item: item.update(value=math.inf), "invalid_value"),
        (lambda item: item.pop("unit"), "missing_unit"),
        (lambda item: item.pop("currency"), "missing_currency"),
        (lambda item: item.pop("fiscal_period"), "missing_fiscal_period"),
        (lambda item: item.update(fiscal_period="latest"), "invalid_fiscal_period"),
        (lambda item: item.pop("period_type"), "missing_period_type"),
        (lambda item: item.update(period_type="ttm"), "unsupported_period_type"),
        (lambda item: item.pop("as_of"), "missing_as_of"),
        (lambda item: item.pop("retrieved_at"), "missing_retrieved_at"),
        (lambda item: item.update(retrieved_at="2026-07-18T20:00:00"), "naive_retrieved_at"),
        (lambda item: item.pop("source"), "missing_source"),
        (lambda item: item.pop("source_field"), "missing_source_field"),
        (
            lambda item: item.update(source_field="unknownRevenueField"),
            "unsupported_source_field",
        ),
        (
            lambda item: (item.pop("source_document"), item.update(provenance=None)),
            "missing_source_document",
        ),
        (lambda item: item.pop("is_fallback"), "invalid_fallback_metadata"),
        (
            lambda item: item.update(is_fallback=True, fallback_from=None),
            "invalid_fallback_metadata",
        ),
    ],
)
def test_invalid_revenue_observation_returns_stable_code(mutator, expected_code):
    observation = _financial_observation()
    mutator(observation)
    before = deepcopy(observation)

    result = production.build_company_financial_metrics(
        [observation], evaluated_at=EVALUATED_AT
    )

    assert expected_code in _error_codes(result)
    assert observation == before
    assert all(set(error) == {"family", "ticker", "field", "code"} for error in result["errors"])


def test_margin_currency_can_be_explicitly_null():
    result = production.build_company_financial_metrics(
        [_financial_observation(field="gross_margin", currency=None)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["status"] == "ok"


@pytest.mark.parametrize("currency", (False, 0, math.nan, {}, []))
def test_margin_currency_nonstring_values_are_not_treated_as_null(currency):
    result = production.build_company_financial_metrics(
        [_financial_observation(field="gross_margin", currency=currency)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["status"] == "missing"
    assert "currency_unit_mismatch" in _error_codes(result)


@pytest.mark.parametrize("currency", (False, 0, math.nan, {}, []))
def test_revenue_currency_nonstring_values_are_mismatch_not_missing(currency):
    result = production.build_company_financial_metrics(
        [_financial_observation(currency=currency)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "currency_unit_mismatch" in _error_codes(result)
    assert "missing_currency" not in _error_codes(result)


def test_invalid_financial_field_does_not_affect_same_company_other_fields():
    result = production.build_company_financial_metrics(
        [
            _financial_observation("MU", "revenue", value=math.nan),
            _financial_observation("MU", "gross_margin"),
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert result["metrics"][1]["status"] == "ok"


def test_extreme_integer_is_invalid_without_crashing_financial_siblings():
    result = production.build_company_financial_metrics(
        [
            _financial_observation("MU", "revenue", value=10**400),
            _financial_observation("MU", "gross_margin"),
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert result["metrics"][1]["status"] == "ok"
    assert "invalid_value" in _error_codes(result)


@pytest.mark.parametrize(
    ("field", "overrides"),
    (
        ("revenue", {"value": 1e308, "unit": "USD billions"}),
        (
            "gross_margin",
            {
                "value": 1e308,
                "unit": "ratio",
                "source_field": "grossProfitRatio",
            },
        ),
    ),
)
def test_nonfinite_normalized_financial_value_is_invalid_and_isolated(
    field, overrides
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation("MU", field, **overrides),
            _financial_observation("SNDK", field),
        ],
        evaluated_at=EVALUATED_AT,
    )
    failed = _metric_for(
        result, production.FINANCIAL_METRIC_IDS[field], label_prefix="MU"
    )
    sibling = _metric_for(
        result, production.FINANCIAL_METRIC_IDS[field], label_prefix="SNDK"
    )
    assert failed["status"] == "missing"
    assert sibling["status"] == "ok"
    assert {
        (error["ticker"], error["field"], error["code"])
        for error in result["errors"]
    } >= {("MU", field, "invalid_value")}
    assert not any(
        error["ticker"] == "MU"
        and error["field"] == field
        and error["code"] == "adapter_failed"
        for error in result["errors"]
    )


@pytest.mark.parametrize("period_type", (None, "ttm"))
def test_invalid_period_type_never_fabricates_quarterly_metadata(period_type):
    observation = _financial_observation(period_type=period_type)
    result = production.build_company_financial_metrics(
        [observation], evaluated_at=EVALUATED_AT
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert "Fiscal period: quarterly" not in metric["notes"]
    assert "Period type: quarterly" not in metric["notes"]


@pytest.mark.parametrize(("failed", "successful"), [("MU", "SNDK"), ("SNDK", "MU")])
def test_one_company_failure_does_not_affect_the_other(failed, successful):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(failed, "revenue", value=math.nan),
            _financial_observation(successful, "revenue"),
        ],
        evaluated_at=EVALUATED_AT,
    )
    failed_metric = _metric_for(result, "company_revenue", label_prefix=failed)
    successful_metric = _metric_for(result, "company_revenue", label_prefix=successful)
    assert failed_metric["status"] == "missing"
    assert successful_metric["status"] == "ok"


@pytest.mark.parametrize(
    ("source", "source_document", "is_estimate"),
    [
        ("Daily Brief", "news article", False),
        ("Static fixture", "income_statement", False),
        ("Analyst service", "analyst article", False),
        ("FMP", "consensus estimate", True),
    ],
)
def test_financial_rejects_news_fixture_analyst_and_estimated_inputs(
    source, source_document, is_estimate
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source=source,
                source_document=source_document,
                is_estimate=is_estimate,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert set(_error_codes(result)) & {
        "unsupported_source",
        "unsupported_source_document",
        "estimated_value_not_supported",
    }


@pytest.mark.parametrize(
    ("field_name", "value", "expected_code", "extra"),
    (
        ("source", "Test Financial API", "unsupported_source", {}),
        ("source", "Fake Financial API", "unsupported_source", {}),
        ("source", "Sample Yahoo Finance", "unsupported_source", {}),
        ("source", "Mock Financial API", "unsupported_source", {}),
        ("source", "Open AI Financial API", "unsupported_source", {}),
        ("source", "ChatGPT Financial API", "unsupported_source", {}),
        ("source", "Valuation Model Financial API", "unsupported_source", {}),
        (
            "source_document",
            "test income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "source_document",
            "sample income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "source_document",
            "mock income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "source_document",
            "Open AI income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "source_document",
            "model income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "fallback_from",
            "Fake Financial API",
            "invalid_fallback_metadata",
            {"is_fallback": True},
        ),
        (
            "source_reference",
            "sample filing reference",
            "invalid_source_reference",
            {},
        ),
        (
            "source_reference",
            "llm filing reference",
            "invalid_source_reference",
            {},
        ),
        (
            "source_document",
            "guidance earnings release",
            "unsupported_source_document",
            {},
        ),
        (
            "provenance",
            "forecast income_statement",
            "unsupported_source_document",
            {},
        ),
        (
            "source_reference",
            "projected",
            "invalid_source_reference",
            {},
        ),
        (
            "source_document",
            "consensus earnings release",
            "unsupported_source_document",
            {},
        ),
        (
            "fallback_from",
            "consensus",
            "invalid_fallback_metadata",
            {"is_fallback": True},
        ),
    ),
)
def test_financial_rejects_declared_test_fake_and_sample_provenance(
    field_name, value, expected_code, extra
):
    overrides = {field_name: value, **extra}
    result = production.build_company_financial_metrics(
        [_financial_observation(**overrides)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert expected_code in _error_codes(result)
    assert value not in _serialized(result)


@pytest.mark.parametrize(
    "source",
    (
        "Seeking Alpha FMP data",
        "Unknown SEC filing service",
        "Third Party Yahoo Finance data",
    ),
)
def test_financial_rejects_composite_source_names_that_launder_provider_markers(
    source
):
    result = production.build_company_financial_metrics(
        [_financial_observation(source=source)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source" in _error_codes(result)
    assert source not in _serialized(result)


@pytest.mark.parametrize(
    "source_document",
    (
        "test quote",
        "fake quote",
        "sample quote",
        "mock quote",
        "Open AI quote",
        "ChatGPT quote",
        "valuation model quote",
    ),
)
def test_market_rejects_declared_test_fake_and_sample_evidence(source_document):
    result = production.build_market_proxy_metrics(
        [_market_observation(source_document=source_document)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "unsupported_source_document" in _error_codes(result)
    assert source_document not in _serialized(result)


@pytest.mark.parametrize(
    ("source", "source_document", "source_reference", "fiscal_period"),
    [
        ("Yahoo News", "income_statement", None, "FY2026 Q3"),
        ("Seeking Alpha", "income statement analysis article", None, "FY2026 Q3"),
        ("FMP", "income_statement", "static fixture", "FY2026 Q3"),
        ("FMP", "income_statement", "analyst estimate", "FY2026 Q3"),
        ("FMP", "income_statement", None, "FY2026 Q3 estimate"),
    ],
)
def test_financial_requires_approved_source_report_and_reference_provenance(
    source, source_document, source_reference, fiscal_period
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source=source,
                source_document=source_document,
                source_reference=source_reference,
                fiscal_period=fiscal_period,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert set(_error_codes(result)) & {
        "unsupported_source",
        "unsupported_source_document",
        "invalid_source_reference",
        "invalid_fiscal_period",
    }


@pytest.mark.parametrize(
    ("ticker", "overrides"),
    (
        ("MU", {"source": "Sandisk"}),
        ("SNDK", {"source": "Micron Technology"}),
        (
            "SNDK",
            {"source": "FMP", "source_document": "Micron Form 10-Q income statement"},
        ),
        (
            "MU",
            {"source": "FMP", "source_document": "Sandisk Form 10-Q income statement"},
        ),
        (
            "SNDK",
            {
                "source": "FMP",
                "source_reference": "https://investors.micron.com/filing",
            },
        ),
        (
            "MU",
            {"source": "FMP", "provenance": "Sandisk SEC filing income statement"},
        ),
        (
            "SNDK",
            {
                "source": "FMP",
                "is_fallback": True,
                "fallback_from": "Micron Technology",
            },
        ),
    ),
)
def test_explicit_financial_company_identity_must_match_ticker(ticker, overrides):
    result = production.build_company_financial_metrics(
        [_financial_observation(ticker, **overrides)],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, "company_revenue", label_prefix=ticker)
    assert metric["status"] == "missing"
    assert "company_identity_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    ("ticker", "overrides"),
    (
        ("MU", {"source_document": "SNDK Form 10-Q income statement"}),
        (
            "SNDK",
            {"provenance": "MU SEC filing income statement"},
        ),
        (
            "MU",
            {
                "source_reference": "https://filings.example.com/sndk/filing",
            },
        ),
        (
            "SNDK",
            {
                "is_fallback": True,
                "fallback_from": "MU",
            },
        ),
    ),
)
def test_financial_company_identity_checks_supported_ticker_tokens(ticker, overrides):
    result = production.build_company_financial_metrics(
        [_financial_observation(ticker, **overrides)],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, "company_revenue", label_prefix=ticker)
    assert metric["status"] == "missing"
    assert "company_identity_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    ("ticker", "source"),
    (("MU", "Micron Technology"), ("SNDK", "Sandisk")),
)
def test_matching_direct_company_source_is_accepted(ticker, source):
    result = production.build_company_financial_metrics(
        [_financial_observation(ticker, source=source)],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, "company_revenue", label_prefix=ticker)
    assert metric["status"] == "ok"
    assert result["errors"] == []


@pytest.mark.parametrize(
    "overrides",
    (
        {
            "fiscal_period": "FY2026 Q3",
            "period_type": "quarterly",
            "source_document": "Form 10-K annual report income statement",
        },
        {
            "fiscal_period": "FY2026",
            "period_type": "annual",
            "source_document": "Form 10-Q quarterly report income statement",
        },
        {
            "fiscal_period": "FY2026 Q3",
            "period_type": "quarterly",
            "source_document": "income_statement",
            "provenance": "SEC Form 10-K annual report filing",
        },
        {
            "fiscal_period": "FY2026",
            "period_type": "annual",
            "source_reference": "https://sec.example.com/form-10-q/filing",
        },
    ),
)
def test_explicit_financial_evidence_cadence_must_match_period_type(overrides):
    result = production.build_company_financial_metrics(
        [_financial_observation(**overrides)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "period_evidence_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    "overrides",
    (
        {
            "fiscal_period": "FY2026",
            "period_type": "annual",
            "source_document": "FY2026 Q3 income_statement",
        },
        {
            "fiscal_period": "FY2026 Q3",
            "period_type": "quarterly",
            "source_document": "annual income_statement",
        },
    ),
)
def test_financial_evidence_rejects_explicit_opposite_cadence(overrides):
    result = production.build_company_financial_metrics(
        [_financial_observation(**overrides)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "period_evidence_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    "source_document",
    (
        "FY2026Q3 income_statement",
        "2026Q3 income_statement",
        "3Q2026 income_statement",
        "Q32026 income_statement",
    ),
)
def test_annual_financial_observation_rejects_compact_quarter_evidence(
    source_document
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period="FY2026",
                period_type="annual",
                source_document=source_document,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "period_evidence_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    "source_document",
    (
        "third quarter FY2026 earnings release",
        "third-quarter FY2026 earnings release",
        "3rd quarter FY2026 earnings release",
    ),
)
def test_annual_financial_observation_rejects_spelled_quarter_evidence(
    source_document
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period="FY2026",
                period_type="annual",
                source_document=source_document,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "period_evidence_mismatch" in _error_codes(result)


@pytest.mark.parametrize(
    "source_document",
    (
        "full-year FY2026 earnings release",
        "full year FY2026 earnings release",
    ),
)
def test_quarterly_financial_observation_rejects_full_year_evidence(
    source_document
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period="FY2026 Q3",
                period_type="quarterly",
                source_document=source_document,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "period_evidence_mismatch" in _error_codes(result)


def test_invalid_financial_value_retains_other_verified_fallback_metadata():
    observation = _financial_observation(
        value=None,
        source="FMP",
        source_document="income_statement",
        is_fallback=True,
        fallback_from="Yahoo Finance",
    )
    result = production.build_company_financial_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["source"] == "FMP"
    assert metric["as_of"] == observation["as_of"]
    assert metric["retrieved_at"] == observation["retrieved_at"]
    assert metric["is_fallback"] is True
    assert "Fallback from: Yahoo Finance" in metric["notes"]


def test_complete_stale_financial_fallback_preserves_lineage_and_low_confidence():
    observation = _financial_observation(
        as_of="2026-05-01",
        source="FMP",
        source_document="Form 10-Q income statement",
        is_fallback=True,
        fallback_from="Yahoo Finance",
    )
    result = production.build_company_financial_metrics([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]
    assert metric["status"] == "stale"
    assert metric["value"] == 7200.0
    assert metric["as_of"] == observation["as_of"]
    assert metric["source"] == "FMP"
    assert metric["is_fallback"] is True
    assert metric["confidence"] == "low"
    assert "Fallback from: Yahoo Finance" in metric["notes"]


@pytest.mark.parametrize(
    ("source", "fallback_from"),
    (
        ("FMP", "FMP"),
        ("FMP", "Financial Modeling Prep"),
        ("Yahoo", "Yahoo Finance"),
        ("SEC EDGAR", "EDGAR"),
        ("Micron", "Micron Technology"),
    ),
)
def test_financial_fallback_source_must_be_a_different_canonical_provider(
    source, fallback_from
):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source=source,
                is_fallback=True,
                fallback_from=fallback_from,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["is_fallback"] is False
    assert "invalid_fallback_metadata" in _error_codes(result)


def test_rejected_financial_source_cannot_retain_a_fallback_badge():
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                source="Fake Financial API",
                is_fallback=True,
                fallback_from="FMP",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["source"] == "unavailable"
    assert metric["is_fallback"] is False


@pytest.mark.parametrize("fallback_from", (123, True, {"source": "FMP"}, ["FMP"]))
def test_nonfallback_financial_observation_rejects_nonmissing_fallback_metadata(
    fallback_from
):
    result = production.build_company_financial_metrics(
        [_financial_observation(is_fallback=False, fallback_from=fallback_from)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_fallback_metadata" in _error_codes(result)


# Cases 104-112: explicit margin source mappings and no heuristic scaling.
@pytest.mark.parametrize(
    ("field", "source_field"),
    [
        ("gross_margin", "grossProfitRatio"),
        ("gross_margin", "grossProfitMargin"),
        ("operating_margin", "operatingIncomeRatio"),
        ("operating_margin", "operatingProfitMargin"),
    ],
)
def test_ratio_margin_fields_convert_once_to_percent(field, source_field):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                field=field,
                value=0.452,
                unit="ratio",
                source_field=source_field,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, production.FINANCIAL_METRIC_IDS[field], label_prefix="MU")
    assert metric["value"] == pytest.approx(45.2)
    assert metric["unit"] == "percent"


@pytest.mark.parametrize(
    ("field", "source_field"),
    [
        ("gross_margin", "grossMarginPercent"),
        ("operating_margin", "operatingMarginPercent"),
    ],
)
def test_percent_margin_fields_remain_percent_without_double_scaling(field, source_field):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                field=field,
                value=45.2,
                unit="percent",
                source_field=source_field,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = _metric_for(result, production.FINANCIAL_METRIC_IDS[field], label_prefix="MU")
    assert metric["value"] == pytest.approx(45.2)


def test_ratio_named_field_with_percent_unit_is_ambiguous_not_rescaled():
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                field="gross_margin",
                value=45.2,
                unit="percent",
                source_field="grossProfitRatio",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["status"] in {"missing", "unavailable"}
    assert "ambiguous_margin_unit" in _error_codes(result)


def test_unsupported_margin_source_field_is_unavailable():
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                field="gross_margin",
                source_field="unverifiedMargin",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["status"] == "unavailable"
    assert "unsupported_source_field" in _error_codes(result)


@pytest.mark.parametrize("unit", ("%", "decimal", "unknown"))
def test_ambiguous_margin_unit_is_rejected(unit):
    result = production.build_company_financial_metrics(
        [_financial_observation(field="gross_margin", unit=unit)],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["status"] in {"missing", "unavailable"}
    assert "ambiguous_margin_unit" in _error_codes(result)


@pytest.mark.parametrize("value", (0.0, -12.5, 245.2))
def test_percent_margin_zero_negative_and_extreme_values_are_not_clamped(value):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                field="gross_margin",
                value=value,
                unit="percent",
                source_field="grossMarginPercent",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][1]["value"] == value


# Cases 113-120: explicit Revenue conversion and cross-company consistency.
@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (7_200_000_000.0, "USD", 7200.0),
        (7_200_000.0, "USD thousands", 7200.0),
        (7200.0, "USD millions", 7200.0),
        (7.2, "USD billions", 7200.0),
        (0.0, "USD", 0.0),
        (-1_000_000.0, "USD", -1.0),
    ],
)
def test_revenue_units_convert_once_to_usd_millions(value, unit, expected):
    result = production.build_company_financial_metrics(
        [_financial_observation(value=value, unit=unit)], evaluated_at=EVALUATED_AT
    )
    metric = result["metrics"][0]
    assert metric["value"] == pytest.approx(expected)
    assert metric["unit"] == "USD millions"
    assert f"Original unit: {unit}" in metric["notes"]


def test_unknown_revenue_unit_is_rejected():
    result = production.build_company_financial_metrics(
        [_financial_observation(unit="USD mn")], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_unit" in _error_codes(result)


def test_revenue_currency_and_unit_mismatch_is_rejected():
    result = production.build_company_financial_metrics(
        [_financial_observation(currency="EUR", unit="USD millions")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "currency_unit_mismatch" in _error_codes(result)


def test_mu_and_sndk_revenue_use_the_same_scaling_rule():
    result = production.build_company_financial_metrics(
        [
            _financial_observation("MU", value=7.2, unit="USD billions"),
            _financial_observation("SNDK", value=7.2, unit="USD billions"),
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["value"] == result["metrics"][3]["value"] == 7200.0


def test_annual_period_is_accepted_only_with_an_explicit_annual_label():
    valid = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period="FY2026",
                period_type="annual",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    invalid = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period="FY2026 Q3",
                period_type="annual",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert valid["metrics"][0]["status"] == "ok"
    assert "Fiscal period: annual" in valid["metrics"][0]["notes"]
    assert "invalid_fiscal_period" in _error_codes(invalid)


@pytest.mark.parametrize("value", ("7200", "0.452"))
def test_numeric_strings_are_never_silently_converted(value):
    market = production.build_market_proxy_metrics(
        [_market_observation(value=value)], evaluated_at=EVALUATED_AT
    )
    financial = production.build_company_financial_metrics(
        [_financial_observation(value=value)], evaluated_at=EVALUATED_AT
    )
    assert "invalid_value" in _error_codes(market)
    assert "invalid_value" in _error_codes(financial)


@pytest.mark.parametrize("label", ("latest", "recent", "current", "TTM", "unknown"))
def test_all_vague_fiscal_labels_are_rejected(label):
    result = production.build_company_financial_metrics(
        [_financial_observation(fiscal_period=label)], evaluated_at=EVALUATED_AT
    )
    assert "invalid_fiscal_period" in _error_codes(result)


@pytest.mark.parametrize(
    "label",
    (
        "FY2026E",
        "FY2026F",
        "FY2026 Q0",
        "FY2026 Q5",
        "FY2026 QX",
        "FY2026 Q4E",
        "FY2026 quarterly",
    ),
)
def test_annual_period_rejects_estimate_and_quarter_like_labels(label):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period=label,
                period_type="annual",
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert "invalid_fiscal_period" in _error_codes(result)
    assert f"Fiscal period label: {label}" not in metric["notes"]
    assert "Fiscal period: annual" not in metric["notes"]


@pytest.mark.parametrize(
    ("label", "period_type"),
    (
        ("FY2026 Q3 and FY2026 Q4", "quarterly"),
        ("FY2026 Q3 Q4", "quarterly"),
        ("FY2025 and FY2026", "annual"),
        ("annual Q3", "annual"),
    ),
)
def test_fiscal_label_must_identify_exactly_one_period(label, period_type):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period=label,
                period_type=period_type,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "missing"
    assert "invalid_fiscal_period" in _error_codes(result)


@pytest.mark.parametrize(
    ("label", "period_type"),
    (
        ("FY2026 Q3", "quarterly"),
        ("Q1 2026", "quarterly"),
        ("FY2025", "annual"),
        ("2025", "annual"),
    ),
)
def test_supported_fiscal_label_shapes_remain_accepted(label, period_type):
    result = production.build_company_financial_metrics(
        [
            _financial_observation(
                fiscal_period=label,
                period_type=period_type,
            )
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["errors"] == []


@pytest.mark.parametrize("label", ("FY2026/Q3", "Q3/2026"))
def test_supported_slash_fiscal_label_is_preserved_in_notes(label):
    result = production.build_company_financial_metrics(
        [_financial_observation(fiscal_period=label)],
        evaluated_at=EVALUATED_AT,
    )
    metric = result["metrics"][0]
    assert metric["status"] == "ok"
    assert result["errors"] == []
    assert f"Fiscal period label: {label}" in metric["notes"]
    assert "Fiscal period label: None" not in metric["notes"]


# Cases 121-134: orchestration, status, counts, order, and fresh objects.
def test_complete_production_result_is_ok_with_all_counts():
    result = production.build_memory_cycle_production_metrics(
        market_observations=_all_market_observations(),
        financial_observations=_all_financial_observations(),
        evaluated_at=EVALUATED_AT,
    )

    assert set(result) == {
        "metrics",
        "status",
        "expected_metric_count",
        "successful_metric_count",
        "stale_metric_count",
        "missing_metric_count",
        "unavailable_metric_count",
        "errors",
    }
    assert result["status"] == "ok"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 10
    assert result["stale_metric_count"] == 0
    assert result["missing_metric_count"] == 0
    assert result["unavailable_metric_count"] == 0
    assert result["errors"] == []


def test_partial_result_preserves_success_and_counts_missing_slots():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[_market_observation("MU")],
        financial_observations=[_financial_observation("SNDK", "revenue")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 2
    assert result["missing_metric_count"] == 8
    assert result["unavailable_metric_count"] == 0
    assert (
        result["successful_metric_count"]
        + result["missing_metric_count"]
        + result["unavailable_metric_count"]
        == 10
    )


def test_empty_input_returns_empty_status_and_ten_missing_placeholders():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[],
        financial_observations=[],
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "empty"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 0
    assert result["missing_metric_count"] == 10
    assert result["unavailable_metric_count"] == 0
    assert result["errors"] == []


def test_single_observation_failure_is_partial_not_system_error():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[_market_observation("MU", value=math.nan)],
        financial_observations=[_financial_observation("SNDK", "revenue")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 1
    assert "invalid_value" in _error_codes(result)


def test_catastrophic_internal_failure_is_the_only_error_status(monkeypatch):
    def fail_safely(*args, **kwargs):
        raise RuntimeError("/Users/private/path?apikey=DO_NOT_LEAK")

    monkeypatch.setattr(production, "build_market_proxy_metrics", fail_safely)
    result = production.build_memory_cycle_production_metrics(
        market_observations=_all_market_observations(),
        financial_observations=_all_financial_observations(),
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "error"
    assert result["expected_metric_count"] == 10
    assert result["successful_metric_count"] == 0
    assert result["errors"] == [
        {"family": "production", "ticker": None, "field": None, "code": "internal_error"}
    ]
    serialized = _serialized(result)
    assert "/Users/" not in serialized
    assert "DO_NOT_LEAK" not in serialized


def test_stale_values_remain_successful_and_are_counted_separately():
    stale_market = _market_observation(as_of="2026-07-10T20:00:00+00:00")
    result = production.build_memory_cycle_production_metrics(
        market_observations=[stale_market],
        financial_observations=[],
        evaluated_at=EVALUATED_AT,
    )
    assert result["successful_metric_count"] == 1
    assert result["stale_metric_count"] == 1
    assert result["missing_metric_count"] == 9
    assert result["metrics"][0]["value"] == 123.45


def test_all_ten_usable_metrics_remain_ok_when_one_is_stale():
    market = _all_market_observations()
    market[0]["as_of"] = "2026-07-10T20:00:00+00:00"
    result = production.build_memory_cycle_production_metrics(
        market_observations=market,
        financial_observations=_all_financial_observations(),
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "ok"
    assert result["successful_metric_count"] == 10
    assert result["stale_metric_count"] == 1
    assert result["missing_metric_count"] == 0


def test_unavailable_count_and_count_partition_are_correct():
    financial = _all_financial_observations()
    financial[1]["source_field"] = "unverifiedMargin"
    result = production.build_memory_cycle_production_metrics(
        market_observations=_all_market_observations(),
        financial_observations=financial,
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 9
    assert result["unavailable_metric_count"] == 1
    assert result["missing_metric_count"] == 0
    assert (
        result["successful_metric_count"]
        + result["missing_metric_count"]
        + result["unavailable_metric_count"]
        == result["expected_metric_count"]
    )


def test_full_output_order_is_independent_of_provider_order():
    result = production.build_memory_cycle_production_metrics(
        market_observations=list(reversed(_all_market_observations())),
        financial_observations=list(reversed(_all_financial_observations())),
        evaluated_at=EVALUATED_AT,
    )
    identities = [(metric["metric_id"], metric["label"].split()[0]) for metric in result["metrics"]]
    assert identities == [
        ("mu_market_price_proxy", "MU"),
        ("sndk_market_price_proxy", "SNDK"),
        ("smh_market_price_proxy", "SMH"),
        ("soxx_market_price_proxy", "SOXX"),
        ("company_revenue", "MU"),
        ("gross_margin", "MU"),
        ("operating_margin", "MU"),
        ("company_revenue", "SNDK"),
        ("gross_margin", "SNDK"),
        ("operating_margin", "SNDK"),
    ]


def test_errors_use_stable_family_ticker_field_code_sorting():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[_market_observation("SOXX", value=math.nan)],
        financial_observations=[
            _financial_observation("SNDK", "operating_margin", value=math.inf),
            _financial_observation("MU", "gross_margin", source_field="unknown"),
        ],
        evaluated_at=EVALUATED_AT,
    )
    keys = [
        (error["family"], error["ticker"] or "", error["field"] or "", error["code"])
        for error in result["errors"]
    ]
    assert keys == sorted(keys)


def test_each_call_returns_fresh_result_metric_and_error_objects():
    kwargs = {
        "market_observations": [_market_observation(value=math.nan)],
        "financial_observations": [_financial_observation()],
        "evaluated_at": EVALUATED_AT,
    }
    first = production.build_memory_cycle_production_metrics(**kwargs)
    second = production.build_memory_cycle_production_metrics(**kwargs)

    assert first == second
    assert first is not second
    assert first["metrics"] is not second["metrics"]
    assert first["errors"] is not second["errors"]
    assert all(left is not right for left, right in zip(first["metrics"], second["metrics"]))
    assert all(left is not right for left, right in zip(first["errors"], second["errors"]))


def test_duplicate_observations_are_rejected_deterministically():
    market = production.build_market_proxy_metrics(
        [_market_observation("MU", value=1), _market_observation("MU", value=2)],
        evaluated_at=EVALUATED_AT,
    )
    financial = production.build_company_financial_metrics(
        [_financial_observation(), _financial_observation(value=1)],
        evaluated_at=EVALUATED_AT,
    )
    assert market["metrics"][0]["status"] == "missing"
    assert financial["metrics"][0]["status"] == "missing"
    assert "duplicate_observation" in _error_codes(market)
    assert "duplicate_observation" in _error_codes(financial)


def test_nonempty_invalid_only_input_is_recoverable_partial():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[_market_observation(value=math.nan)],
        financial_observations=[],
        evaluated_at=EVALUATED_AT,
    )
    assert result["status"] == "partial"
    assert result["successful_metric_count"] == 0
    assert result["missing_metric_count"] == 10


# Cases 135-144: sanitized exceptions and stable error envelopes.
def test_fetch_failure_envelope_is_sanitized_for_both_families():
    secret_exception = RuntimeError(
        "Authorization: Bearer SECRET at /Users/private/file response_body=private"
    )
    result = production.build_memory_cycle_production_metrics(
        market_observations=[{"ticker": "MU", "error": secret_exception}],
        financial_observations=[
            {"ticker": "SNDK", "field": "revenue", "error": secret_exception}
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert _error_codes(result).count("fetch_failed") == 2
    serialized = _serialized(result)
    for forbidden in ("Authorization", "SECRET", "/Users/", "response_body", "Bearer"):
        assert forbidden not in serialized


def test_adapter_failure_is_sanitized_and_does_not_break_sibling_metric(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_adapter_failure(**kwargs):
        if kwargs["metric_id"] == "mu_market_price_proxy":
            raise ValueError("https://provider.test?apikey=SECRET response body private")
        return original(**kwargs)

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_adapter_failure)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU"), _market_observation("SOXX")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)
    serialized = _serialized(result)
    assert "SECRET" not in serialized
    assert "response body" not in serialized
    assert "traceback" not in serialized.casefold()


def test_financial_adapter_failure_is_sanitized_and_isolated(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_adapter_failure(**kwargs):
        if kwargs["ticker"] == "MU" and kwargs["metric_id"] == "company_revenue":
            raise ValueError("Authorization: Bearer SECRET /Users/private")
        return original(**kwargs)

    monkeypatch.setattr(production, "adapt_company_financial_metric", selective_adapter_failure)
    result = production.build_company_financial_metrics(
        [_financial_observation("MU"), _financial_observation("SNDK")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)
    assert "SECRET" not in _serialized(result)


def test_market_adapter_non_mapping_result_is_isolated(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_invalid_result(**kwargs):
        if kwargs["metric_id"] == "mu_market_price_proxy" and kwargs["value"] is not None:
            return None
        return original(**kwargs)

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_invalid_result)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU"), _market_observation("SOXX")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)


def test_financial_adapter_non_mapping_result_is_isolated(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_invalid_result(**kwargs):
        if (
            kwargs["ticker"] == "MU"
            and kwargs["metric_id"] == "company_revenue"
            and kwargs["value"] is not None
        ):
            return None
        return original(**kwargs)

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_invalid_result
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU"), _financial_observation("SNDK")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)


def test_market_adapter_malformed_mapping_is_isolated(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_malformed_result(**kwargs):
        if kwargs["metric_id"] == "mu_market_price_proxy" and kwargs["value"] is not None:
            return {"status": "ok"}
        return original(**kwargs)

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_malformed_result)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU"), _market_observation("SOXX")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)


def test_financial_adapter_malformed_mapping_is_isolated(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_malformed_result(**kwargs):
        if (
            kwargs["ticker"] == "MU"
            and kwargs["metric_id"] == "company_revenue"
            and kwargs["value"] is not None
        ):
            return {"status": "ok"}
        return original(**kwargs)

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_malformed_result
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU"), _financial_observation("SNDK")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)


def test_market_adapter_cannot_add_fields_outside_contract(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_extended_result(**kwargs):
        metric = original(**kwargs)
        if kwargs["metric_id"] == "mu_market_price_proxy" and kwargs["value"] is not None:
            metric["raw_response"] = "Authorization: Bearer SECRET"
        return metric

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_extended_result)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU"), _market_observation("SOXX")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)
    assert "SECRET" not in _serialized(result)
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])


def test_financial_adapter_cannot_add_fields_outside_contract(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_extended_result(**kwargs):
        metric = original(**kwargs)
        if (
            kwargs["ticker"] == "MU"
            and kwargs["metric_id"] == "company_revenue"
            and kwargs["value"] is not None
        ):
            metric["raw_response"] = "Authorization: Bearer SECRET"
        return metric

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_extended_result
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU"), _financial_observation("SNDK")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "unavailable"
    assert result["metrics"][3]["status"] == "ok"
    assert "adapter_failed" in _error_codes(result)
    assert "SECRET" not in _serialized(result)
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])


def test_market_missing_placeholder_adapter_failure_does_not_escape(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_placeholder_failure(**kwargs):
        if kwargs["metric_id"] == "sndk_market_price_proxy":
            raise RuntimeError("private adapter detail")
        return original(**kwargs)

    monkeypatch.setattr(
        production, "adapt_market_proxy_metric", selective_placeholder_failure
    )
    result = production.build_market_proxy_metrics(
        [_market_observation("MU")], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert {
        (error["ticker"], error["code"]) for error in result["errors"]
    } >= {("SNDK", "adapter_failed")}


def test_financial_missing_placeholder_adapter_failure_does_not_escape(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_placeholder_failure(**kwargs):
        if kwargs["ticker"] == "MU" and kwargs["metric_id"] == "gross_margin":
            raise RuntimeError("private adapter detail")
        return original(**kwargs)

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_placeholder_failure
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU", "revenue")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert {
        (error["ticker"], error["field"], error["code"])
        for error in result["errors"]
    } >= {("MU", "gross_margin", "adapter_failed")}


def test_market_missing_placeholder_malformed_mapping_is_rejected(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_malformed_result(**kwargs):
        if kwargs["metric_id"] == "sndk_market_price_proxy":
            return {"status": "missing"}
        return original(**kwargs)

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_malformed_result)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU")], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert {
        (error["ticker"], error["code"]) for error in result["errors"]
    } >= {("SNDK", "adapter_failed")}


def test_financial_missing_placeholder_malformed_mapping_is_rejected(monkeypatch):
    original = production.adapt_company_financial_metric

    def selective_malformed_result(**kwargs):
        if kwargs["ticker"] == "MU" and kwargs["metric_id"] == "gross_margin":
            return {"status": "missing"}
        return original(**kwargs)

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_malformed_result
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU", "revenue")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert {
        (error["ticker"], error["field"], error["code"])
        for error in result["errors"]
    } >= {("MU", "gross_margin", "adapter_failed")}


def test_market_missing_placeholder_cannot_add_fields_outside_contract(monkeypatch):
    original = production.adapt_market_proxy_metric

    def selective_extended_result(**kwargs):
        metric = original(**kwargs)
        if kwargs["metric_id"] == "sndk_market_price_proxy":
            metric["raw_response"] = "Authorization: Bearer SECRET"
        return metric

    monkeypatch.setattr(production, "adapt_market_proxy_metric", selective_extended_result)
    result = production.build_market_proxy_metrics(
        [_market_observation("MU")], evaluated_at=EVALUATED_AT
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert "adapter_failed" in _error_codes(result)
    assert "SECRET" not in _serialized(result)
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])


def test_financial_missing_placeholder_cannot_add_fields_outside_contract(
    monkeypatch,
):
    original = production.adapt_company_financial_metric

    def selective_extended_result(**kwargs):
        metric = original(**kwargs)
        if kwargs["ticker"] == "MU" and kwargs["metric_id"] == "gross_margin":
            metric["raw_response"] = "Authorization: Bearer SECRET"
        return metric

    monkeypatch.setattr(
        production, "adapt_company_financial_metric", selective_extended_result
    )
    result = production.build_company_financial_metrics(
        [_financial_observation("MU", "revenue")],
        evaluated_at=EVALUATED_AT,
    )
    assert result["metrics"][0]["status"] == "ok"
    assert result["metrics"][1]["status"] == "unavailable"
    assert "adapter_failed" in _error_codes(result)
    assert "SECRET" not in _serialized(result)
    assert all(tuple(metric) == REQUIRED_METRIC_FIELDS for metric in result["metrics"])


@pytest.mark.parametrize(
    ("builder", "observation"),
    (
        (
            production.build_market_proxy_metrics,
            _market_observation(source="Unknown Provider"),
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(source="Unknown Provider"),
        ),
    ),
)
def test_metadata_only_rejection_uses_neutral_missing_notes(builder, observation):
    result = builder([observation], evaluated_at=EVALUATED_AT)
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert "no complete production" in metric["notes"].casefold()
    assert "value must" not in metric["notes"].casefold()


def test_error_objects_contain_only_the_allowlisted_fields():
    result = production.build_company_financial_metrics(
        [_financial_observation(value=math.nan)], evaluated_at=EVALUATED_AT
    )
    assert result["errors"]
    assert all(tuple(error) == ("family", "ticker", "field", "code") for error in result["errors"])


# Cases 145-156: explicit evaluation time and input/output immutability.
def test_evaluated_at_is_a_required_keyword_for_all_public_builders():
    with pytest.raises(TypeError):
        production.build_market_proxy_metrics([])
    with pytest.raises(TypeError):
        production.build_company_financial_metrics([])
    with pytest.raises(TypeError):
        production.build_memory_cycle_production_metrics(
            market_observations=[], financial_observations=[]
        )


@pytest.mark.parametrize("evaluated_at", (None, "", "2026-07-18T20:10:00", "2026-07-18"))
def test_invalid_or_naive_evaluated_at_is_rejected(evaluated_at):
    builders = (
        lambda: production.build_market_proxy_metrics([], evaluated_at=evaluated_at),
        lambda: production.build_company_financial_metrics([], evaluated_at=evaluated_at),
        lambda: production.build_memory_cycle_production_metrics(
            market_observations=[],
            financial_observations=[],
            evaluated_at=evaluated_at,
        ),
    )
    for build in builders:
        with pytest.raises(ValueError, match="evaluated_at"):
            build()


def test_injected_evaluation_time_controls_staleness_without_rewriting_retrieval():
    observation = _market_observation(as_of="2026-07-15T20:00:00+00:00")
    fresh = production.build_market_proxy_metrics(
        [observation], evaluated_at="2026-07-18T20:10:00+00:00"
    )
    stale = production.build_market_proxy_metrics(
        [observation], evaluated_at="2026-07-19T20:10:00+00:00"
    )
    assert fresh["metrics"][0]["status"] == "ok"
    assert stale["metrics"][0]["status"] == "stale"
    assert fresh["metrics"][0]["retrieved_at"] == stale["metrics"][0]["retrieved_at"]


def test_aware_datetime_and_date_inputs_are_accepted():
    market = production.build_market_proxy_metrics(
        [
            _market_observation(
                as_of=datetime(2026, 7, 18, 20, tzinfo=timezone.utc),
                retrieved_at=datetime(2026, 7, 18, 20, 1, tzinfo=timezone.utc),
            )
        ],
        evaluated_at=datetime(2026, 7, 18, 20, 10, tzinfo=timezone.utc),
    )
    financial = production.build_company_financial_metrics(
        [
            _financial_observation(
                as_of=date(2026, 7, 10),
                retrieved_at=datetime(2026, 7, 18, 20, tzinfo=timezone.utc),
            )
        ],
        evaluated_at=datetime(2026, 7, 18, 20, 10, tzinfo=timezone.utc),
    )
    assert market["metrics"][0]["status"] == "ok"
    assert financial["metrics"][0]["status"] == "ok"


def test_production_source_uses_no_hidden_current_time():
    source = PRODUCTION_PATH.read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "datetime.utcnow", "date.today", "time.time"):
        assert forbidden not in source


def test_market_and_financial_inputs_are_not_modified_or_reused():
    market = _all_market_observations()
    financial = _all_financial_observations()
    before_market = deepcopy(market)
    before_financial = deepcopy(financial)

    result = production.build_memory_cycle_production_metrics(
        market_observations=market,
        financial_observations=financial,
        evaluated_at=EVALUATED_AT,
    )

    assert market == before_market
    assert financial == before_financial
    assert result["metrics"] is not market
    assert result["metrics"] is not financial
    input_dict_ids = {id(item) for item in market + financial}
    assert all(id(metric) not in input_dict_ids for metric in result["metrics"])


def test_mutating_one_output_cannot_change_a_later_call():
    kwargs = {
        "market_observations": _all_market_observations(),
        "financial_observations": _all_financial_observations(),
        "evaluated_at": EVALUATED_AT,
    }
    first = production.build_memory_cycle_production_metrics(**kwargs)
    first["metrics"][0]["value"] = -999
    first["errors"].append({"family": "x", "ticker": "x", "field": None, "code": "x"})
    second = production.build_memory_cycle_production_metrics(**kwargs)
    assert second["metrics"][0]["value"] == 123.45
    assert second["errors"] == []


def test_missing_unavailable_and_stale_placeholders_still_validate_contract():
    result = production.build_memory_cycle_production_metrics(
        market_observations=[_market_observation(as_of="2026-07-10T20:00:00+00:00")],
        financial_observations=[
            _financial_observation(field="gross_margin", source_field="unknown")
        ],
        evaluated_at=EVALUATED_AT,
    )
    assert {metric["status"] for metric in result["metrics"]} >= {
        "stale",
        "missing",
        "unavailable",
    }
    for metric in result["metrics"]:
        _assert_contract(metric)


# Cases 157-173: no network/provider/cache/UI/environment/file side effects.
def test_production_module_imports_only_pure_standard_and_memory_cycle_modules():
    tree = ast.parse(PRODUCTION_PATH.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    allowed = {
        "datetime",
        "math",
        "numbers",
        "re",
        "types",
        "typing",
        "services.memory_cycle_adapters",
        "services.memory_cycle_contract",
    }
    assert imports <= allowed
    assert all(not name.startswith(("providers", "components", "fixtures")) for name in imports)
    assert "services.memory_cycle_view_model" not in imports


def test_import_time_calls_are_limited_to_pure_constant_construction():
    tree = ast.parse(PRODUCTION_PATH.read_text(encoding="utf-8"))
    allowed_calls = {"MappingProxyType", "re.compile", "frozenset"}
    calls = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            for nested in ast.walk(value):
                if isinstance(nested, ast.Call):
                    calls.add(ast.unparse(nested.func))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            calls.add(ast.unparse(node.value.func))
    assert calls <= allowed_calls


def test_production_source_has_no_provider_cache_session_route_or_secret_access():
    source = PRODUCTION_PATH.read_text(encoding="utf-8").casefold()
    forbidden = (
        "requests.",
        "yf.",
        "openai",
        "session_state",
        "st.cache",
        "st.secrets",
        "os.environ",
        "getenv(",
        "load_dotenv",
        "watchlist.json",
        "dashboard.py",
        "sidebar",
        "query_params",
        "streamlit",
    )
    assert all(term not in source for term in forbidden)

    tree = ast.parse(PRODUCTION_PATH.read_text(encoding="utf-8"))
    call_names = {
        ast.unparse(node.func).casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    forbidden_call_roots = (
        "requests",
        "yfinance",
        "yf",
        "ibkr",
        "openai",
        "streamlit",
    )
    assert not any(
        name == root or name.startswith(f"{root}.")
        for name in call_names
        for root in forbidden_call_roots
    )


def test_builders_do_not_read_or_write_files(monkeypatch, tmp_path):
    before = set(tmp_path.iterdir())

    def forbidden_open(*args, **kwargs):
        pytest.fail("production builder must not access files")

    monkeypatch.setattr("builtins.open", forbidden_open)
    production.build_memory_cycle_production_metrics(
        market_observations=_all_market_observations(),
        financial_observations=_all_financial_observations(),
        evaluated_at=EVALUATED_AT,
    )
    assert set(tmp_path.iterdir()) == before


def test_production_source_has_no_file_or_cache_primitive():
    tree = ast.parse(PRODUCTION_PATH.read_text(encoding="utf-8"))
    call_names = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    forbidden_suffixes = (
        "open",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
        "touch",
        "mkdir",
        "makedirs",
        "dump",
        "dumps",
    )
    assert not any(name.endswith(forbidden_suffixes) for name in call_names)


@pytest.mark.parametrize(
    "source_reference",
    (
        "https://provider.test/filing?api-key=ABCD1234",
        "https://provider.test/filing?key=ABCD1234",
        "https://provider.test/filing?credential=ABCD1234",
        "https://provider.test/filing?auth=ABCD1234",
        "https://provider.test/filing?sig=ABCD1234",
        "https://provider.test/filing#token-fragment",
        "/Users/private/filing.json",
        "/private/tmp/provider-response.json",
        "sk-proj-ABC123456789",
        "ghp_ABC123456789",
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "https://user:pass@provider.test/filing",
        "./filing.json",
        "../data/filing.json",
        "tmp/filing.json",
        "filing.json",
        "cache.csv",
    ),
)
def test_secret_and_local_path_variants_never_enter_output(source_reference):
    result = production.build_company_financial_metrics(
        [_financial_observation(source_reference=source_reference)],
        evaluated_at=EVALUATED_AT,
    )
    serialized = _serialized(result)
    assert source_reference not in serialized
    assert "ABCD1234" not in serialized
    assert "/Users/private" not in serialized
    assert "invalid_source_reference" in _error_codes(result)


@pytest.mark.parametrize(
    ("builder", "observation", "sensitive_value"),
    (
        (
            production.build_market_proxy_metrics,
            _market_observation(source="Yahoo Finance sk-proj-FAKE123"),
            "Yahoo Finance sk-proj-FAKE123",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_field="regularMarketPrice ghp_FAKE123"),
            "regularMarketPrice ghp_FAKE123",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote at /private/tmp/raw.json"),
            "quote at /private/tmp/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote at /root/raw.json"),
            "quote at /root/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote at /Volumes/data/raw.json"),
            "quote at /Volumes/data/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote path:/opt/raw.json"),
            "quote path:/opt/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote file:/opt/raw.json"),
            "quote file:/opt/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(
                source_document=r"quote at \\server\share\raw.json"
            ),
            r"quote at \\server\share\raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(
                source_document=None,
                provenance="quote\nTraceback (most recent call last)",
            ),
            "quote\nTraceback (most recent call last)",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote response body private"),
            "quote response body private",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote \u202e payload"),
            "quote \u202e payload",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote \u0085 payload"),
            "quote \u0085 payload",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote \u200b payload"),
            "quote \u200b payload",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(
                source_document="quote",
                provenance="quote sk-proj-FAKE123",
            ),
            "quote sk-proj-FAKE123",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote signature=ABCD1234"),
            "quote signature=ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api key ABCD1234"),
            "quote api key ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api-key ABCD1234"),
            "quote api-key ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote token ABCD1234"),
            "quote token ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote credential ABCD1234"),
            "quote credential ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote access token ABCD1234"),
            "quote access token ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote signature ABCD1234"),
            "quote signature ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api key is ABCD1234"),
            "quote api key is ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote token is ABCD1234"),
            "quote token is ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote credential was ABCD1234"),
            "quote credential was ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api key - ABCD1234"),
            "quote api key - ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api-key(ABCD1234)"),
            "quote api-key(ABCD1234)",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote token-ABCD1234"),
            "quote token-ABCD1234",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote api key abc"),
            "quote api key abc",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from data/raw.json"),
            "quote loaded from data/raw.json",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from repo/module.py"),
            "quote loaded from repo/module.py",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(
                source_document='quote loaded from "repo/module.py"'
            ),
            'quote loaded from "repo/module.py"',
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from repo/module.py!"),
            "quote loaded from repo/module.py!",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote (repo/module.py)"),
            "quote (repo/module.py)",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote:repo/module.py"),
            "quote:repo/module.py",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded=repo/module.py"),
            "quote loaded=repo/module.py",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from repo/"),
            "quote loaded from repo/",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from .env"),
            "quote loaded from .env",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from .env.local"),
            "quote loaded from .env.local",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(source_document="quote loaded from .env.production"),
            "quote loaded from .env.production",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(
                is_fallback=True,
                fallback_from="Yahoo Finance see https://u:p@host.example/x",
            ),
            "Yahoo Finance see https://u:p@host.example/x",
        ),
        (
            production.build_market_proxy_metrics,
            _market_observation(currency="USD AKIAFAKE1234567890"),
            "USD AKIAFAKE1234567890",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(source="FMP sk-proj-FAKE123"),
            "FMP sk-proj-FAKE123",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(source_field="revenue ghp_FAKE123"),
            "revenue ghp_FAKE123",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement at /private/tmp/raw.json"
            ),
            "income_statement at /private/tmp/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement at /opt/raw.json"
            ),
            "income_statement at /opt/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement path:/opt/raw.json"
            ),
            "income_statement path:/opt/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement at /mnt/data/raw.json"
            ),
            "income_statement at /mnt/data/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement",
                provenance="income_statement at /srv/raw.json",
            ),
            "income_statement at /srv/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                provenance='income_statement {"raw":"body"}'
            ),
            'income_statement {"raw":"body"}',
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                provenance="<income_statement><raw>body</raw></income_statement>"
            ),
            "<income_statement><raw>body</raw></income_statement>",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                provenance="income_statement loaded from /var/tmp/raw.json"
            ),
            "income_statement loaded from /var/tmp/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(unit="USD millions sk-proj-FAKE123"),
            "USD millions sk-proj-FAKE123",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(currency="USD sk_test_FAKE1234567890"),
            "USD sk_test_FAKE1234567890",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(currency="USD rk_test_FAKE1234567890"),
            "USD rk_test_FAKE1234567890",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(unit="USD millions sig=ABCD1234"),
            "USD millions sig=ABCD1234",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income_statement loaded from cache/raw.csv"
            ),
            "income_statement loaded from cache/raw.csv",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                source_document="income statement loaded from repo/module"
            ),
            "income statement loaded from repo/module",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(currency="USD AKIAFAKE1234567890"),
            "USD AKIAFAKE1234567890",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(fiscal_period="FY2026 Q3 ../private/raw.json"),
            "FY2026 Q3 ../private/raw.json",
        ),
        (
            production.build_company_financial_metrics,
            _financial_observation(
                is_fallback=True,
                fallback_from="FMP https://u:p@host.example/x",
            ),
            "FMP https://u:p@host.example/x",
        ),
    ),
)
def test_sensitive_content_in_any_echoed_metadata_is_withheld(
    builder, observation, sensitive_value
):
    result = builder([observation], evaluated_at=EVALUATED_AT)
    assert sensitive_value not in _serialized(result)
    assert all(metric["status"] in {"missing", "unavailable"} for metric in result["metrics"])


def test_secret_looking_ticker_and_field_are_not_copied_into_errors():
    secret_ticker = "AKIAFAKE1234567890"
    secret_field = "ghp_FAKE123"
    market = production.build_market_proxy_metrics(
        [_market_observation(secret_ticker)], evaluated_at=EVALUATED_AT
    )
    financial = production.build_company_financial_metrics(
        [_financial_observation(field=secret_field)],
        evaluated_at=EVALUATED_AT,
    )
    assert secret_ticker.casefold() not in _serialized(market).casefold()
    assert secret_field.casefold() not in _serialized(financial).casefold()
    assert market["errors"][0]["ticker"] is None
    assert financial["errors"][0]["field"] is None


def test_public_builders_are_plain_functions_with_no_cache_wrapper():
    for function in (
        production.build_market_proxy_metrics,
        production.build_company_financial_metrics,
        production.build_memory_cycle_production_metrics,
    ):
        assert inspect.isfunction(function)
        assert not hasattr(function, "clear")
        assert "cache" not in repr(function).casefold()


def test_pipeline_emits_only_the_ten_approved_metric_families():
    result = production.build_memory_cycle_production_metrics(
        market_observations=_all_market_observations(),
        financial_observations=_all_financial_observations(),
        evaluated_at=EVALUATED_AT,
    )
    assert len(result["metrics"]) == 10
    assert {metric["source_type"] for metric in result["metrics"]} == {
        "proxy",
        "company_reported",
    }
    assert all(metric["metric_id"] not in {
        "dram_spot_price",
        "nand_spot_price",
        "hbm_price",
        "inventory_days",
        "cycle_score",
        "cycle_phase",
    } for metric in result["metrics"])
