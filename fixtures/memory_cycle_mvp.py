"""Reviewed static records for Memory Cycle MVP view-model tests and demos.

These deliberately synthetic fixtures are not current market data and are not
loaded by the production Dashboard path.  Every observable record is built by
the existing pure adapters with fixed, caller-injected timestamps.
"""

from services.memory_cycle_adapters import (
    adapt_company_financial_metric,
    adapt_market_proxy_metric,
    adapt_news_signal_metric,
    build_unavailable_metric,
)


FIXTURE_EVALUATED_AT = "2025-02-15T12:00:00Z"
FIXTURE_RETRIEVED_AT = "2025-02-15T10:00:00Z"
FIXTURE_NOTICE = "TEST/DEMO FIXTURE — synthetic, reviewed, and not current market data."


def _company(ticker, metric_id, label, value, unit, as_of, source_field, *, fallback=False):
    return adapt_company_financial_metric(
        ticker=ticker,
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        currency="USD" if unit == "USD millions" else None,
        currency_required=unit == "USD millions",
        fiscal_period="quarterly",
        as_of=as_of,
        retrieved_at=FIXTURE_RETRIEVED_AT,
        source="Reviewed test/demo company fixture",
        source_field=source_field,
        source_document=FIXTURE_NOTICE,
        frequency="event_driven",
        evaluated_at=FIXTURE_EVALUATED_AT,
        is_fallback=fallback,
        confidence="medium",
    )


def _proxy(metric_id, label, value, as_of, method, *, fallback=False):
    return adapt_market_proxy_metric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit="%",
        as_of=as_of,
        retrieved_at=FIXTURE_RETRIEVED_AT,
        source="Reviewed test/demo market fixture",
        method=f"{method}; {FIXTURE_NOTICE}",
        frequency="daily",
        evaluated_at=FIXTURE_EVALUATED_AT,
        is_fallback=fallback,
        confidence="medium",
    )


def _news(metric_id, label, value, as_of, topic):
    return adapt_news_signal_metric(
        metric_id=metric_id,
        label=label,
        value=value,
        citation=f"Reviewed synthetic {topic} evidence. {FIXTURE_NOTICE}",
        source="Reviewed test/demo news fixture",
        as_of=as_of,
        retrieved_at=FIXTURE_RETRIEVED_AT,
        method="Human-assigned canonical direction for deterministic view-model testing",
        frequency="event_driven",
        evaluated_at=FIXTURE_EVALUATED_AT,
        confidence="medium",
    )


MEMORY_CYCLE_MVP_FIXTURES = (
    # Synthetic company-reported observations; values are test inputs only.
    _company("MU", "company_revenue", "MU Revenue", 7200.0, "USD millions", "2025-01-31", "revenue"),
    _company("MU", "gross_margin", "MU Gross Margin", 38.0, "%", "2025-01-31", "gross_margin"),
    _company("MU", "operating_margin", "MU Operating Margin", 24.0, "%", "2025-01-31", "operating_margin"),
    _company("SNDK", "company_revenue", "SNDK Revenue", 1800.0, "USD millions", "2025-01-31", "revenue", fallback=True),
    _company("SNDK", "gross_margin", "SNDK Gross Margin", 22.0, "%", "2025-01-31", "gross_margin", fallback=True),
    _company("SNDK", "operating_margin", "SNDK Operating Margin", 0.0, "%", "2025-01-31", "operating_margin", fallback=True),
    # Synthetic return observations, explicitly adapted as market proxies.
    _proxy("memory_company_equity_trend", "MU Price Trend", 4.2, "2025-02-14", "Fixed-window MU total return"),
    _proxy("memory_company_equity_trend", "SNDK Price Trend", -1.5, "2025-02-14", "Fixed-window SNDK total return"),
    _proxy("semiconductor_etf_trend", "SMH Trend", 2.4, "2025-02-14", "Fixed-window SMH total return"),
    _proxy("semiconductor_etf_trend", "SOXX Trend", 1.8, "2025-02-14", "Fixed-window SOXX total return"),
    # Synthetic qualitative evidence; none is a direct product-price series.
    _news("dram_price_direction", "DRAM Pricing Signal", "improving", "2025-02-10", "DRAM pricing"),
    _news("nand_price_direction", "NAND Pricing Signal", "stable", "2025-02-09", "NAND pricing"),
    _news("hbm_demand", "HBM Demand Signal", "strong", "2025-02-11", "HBM demand"),
    _news("production_cuts_or_supply_discipline", "Supply Discipline Signal", "disciplined", "2025-02-08", "supply discipline"),
    _news("channel_inventory", "Inventory Signal", "improving", "2025-02-07", "inventory"),
    _news("cloud_capex_news", "Cloud CapEx Signal", "increasing", "2025-02-12", "cloud CapEx"),
    # Audited source gaps remain explicit rather than becoming zeroes.
    build_unavailable_metric(metric_id="dram_spot_price", label="DRAM Spot Price", notes=f"{FIXTURE_NOTICE} No approved direct series."),
    build_unavailable_metric(metric_id="nand_contract_price", label="NAND Contract Price", notes=f"{FIXTURE_NOTICE} No approved direct series."),
    build_unavailable_metric(metric_id="hbm_price", label="HBM Exact Price", notes=f"{FIXTURE_NOTICE} No standardized exact series."),
    build_unavailable_metric(metric_id="dram_bit_supply_growth", label="Precise Bit Supply Growth", notes=f"{FIXTURE_NOTICE} No normalized exact series."),
    build_unavailable_metric(metric_id="capacity_utilization", label="Capacity Utilization", notes=f"{FIXTURE_NOTICE} No verified field."),
)

# Short alias for callers that prefer a generic fixture name.  The tuple is
# immutable; the view-model builder also copies every input record.
MEMORY_CYCLE_FIXTURES = MEMORY_CYCLE_MVP_FIXTURES


def get_memory_cycle_mvp_fixtures():
    """Return fresh record dictionaries without performing any I/O."""
    return [dict(metric) for metric in MEMORY_CYCLE_MVP_FIXTURES]

