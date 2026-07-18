"""Build deterministic UI-facing snapshots from normalized FMP observations."""

from copy import deepcopy
from datetime import date, datetime, timezone
import math
from numbers import Real
from typing import Any

from services.fmp_financial_normalization import build_ttm_statement


FINANCIAL_STALE_DAYS = 180
QUOTE_STALE_DAYS = 180


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _aware_datetime(value: Any, *, name: str) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware ISO 8601 string")
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a timezone-aware ISO 8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    utc = parsed.astimezone(timezone.utc)
    return utc, utc.isoformat()


def _period_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _staleness(
    period_end: str | None,
    *,
    evaluated_at: datetime,
    threshold_days: int = FINANCIAL_STALE_DAYS,
) -> tuple[str, int | None]:
    parsed = _period_date(period_end)
    if parsed is None:
        return "unavailable", None
    days = max(0, (evaluated_at.date() - parsed).days)
    return ("stale" if days > threshold_days else "ok"), days


def _unavailable(
    *,
    unit: str | None,
    notes: str,
    period_type: str | None = None,
    period_end: str | None = None,
    source: str = "FMP",
) -> dict[str, Any]:
    return {
        "source_field": None,
        "source_fields": (),
        "raw_value": None,
        "raw_unit": None,
        "normalized_value": None,
        "normalized_unit": unit,
        "display_value": None,
        "display_unit": unit,
        "currency": None,
        "period_type": period_type,
        "period_end": period_end,
        "retrieved_at": None,
        "source": source,
        "derived": False,
        "proxy": False,
        "method": None,
        "notes": notes,
        "status": "unavailable",
        "staleness_days": None,
    }


def _from_field(
    record: dict[str, Any] | None,
    field_name: str,
    *,
    evaluated_at: datetime,
    period_type: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    field = record.get("fields", {}).get(field_name) if isinstance(record, dict) else None
    if not isinstance(field, dict) or _number(field.get("normalized_value")) is None:
        return _unavailable(
            unit=field.get("normalized_unit") if isinstance(field, dict) else None,
            notes=notes or f"{field_name} is missing from the required observation",
            period_type=period_type or (record.get("period_type") if isinstance(record, dict) else None),
            period_end=record.get("period_end") if isinstance(record, dict) else None,
        )
    end = record.get("period_end")
    status, days = _staleness(end, evaluated_at=evaluated_at)
    value = float(field["normalized_value"])
    return {
        "source_field": field.get("source_field"),
        "source_fields": tuple(field.get("source_fields") or ()),
        "raw_value": field.get("raw_value"),
        "raw_unit": field.get("raw_unit"),
        "normalized_value": value,
        "normalized_unit": field.get("normalized_unit"),
        "display_value": value,
        "display_unit": field.get("normalized_unit"),
        "currency": field.get("currency"),
        "period_type": period_type or record.get("period_type"),
        "period_end": end,
        "retrieved_at": record.get("retrieved_at"),
        "source": record.get("source", "FMP"),
        "derived": bool(field.get("derived")),
        "proxy": False,
        "method": field.get("method"),
        "notes": notes,
        "status": status,
        "staleness_days": days,
    }


def _from_quote(
    quote: dict[str, Any] | None,
    field_name: str,
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    field = quote.get(field_name) if isinstance(quote, dict) else None
    if not isinstance(field, dict) or _number(field.get("normalized_value")) is None:
        return _unavailable(
            unit=None,
            notes=f"current {field_name} is unavailable from the FMP quote",
            period_type="current",
        )
    as_of = quote.get("as_of")
    try:
        quote_time, _ = _aware_datetime(as_of, name="quote as_of")
    except ValueError:
        return _unavailable(
            unit=field.get("normalized_unit"),
            notes="quote observation time is invalid",
            period_type="current",
        )
    days = max(0, (evaluated_at.date() - quote_time.date()).days)
    value = float(field["normalized_value"])
    return {
        "source_field": field.get("source_field"),
        "source_fields": (field.get("source_field"),) if field.get("source_field") else (),
        "raw_value": field.get("raw_value"),
        "raw_unit": field.get("raw_unit"),
        "normalized_value": value,
        "normalized_unit": field.get("normalized_unit"),
        "display_value": value,
        "display_unit": field.get("normalized_unit"),
        "currency": field.get("currency"),
        "period_type": "current",
        "period_end": quote_time.date().isoformat(),
        "retrieved_at": quote.get("retrieved_at"),
        "source": quote.get("source", "FMP"),
        "derived": bool(field.get("derived")),
        "proxy": False,
        "method": "FMP current quote field",
        "notes": "",
        "status": "stale" if days > QUOTE_STALE_DAYS else "ok",
        "staleness_days": days,
    }


def _price_metric(
    quote: dict[str, Any] | None, *, evaluated_at: datetime
) -> dict[str, Any]:
    if not isinstance(quote, dict) or _number(quote.get("price")) is None:
        return _unavailable(
            unit=None, notes="current price is unavailable", period_type="current"
        )
    field = {
        "source_field": "price",
        "raw_value": quote["price"],
        "raw_unit": quote.get("currency"),
        "normalized_value": quote["price"],
        "normalized_unit": quote.get("currency"),
        "currency": quote.get("currency"),
        "derived": False,
    }
    copied = dict(quote)
    copied["price_metric"] = field
    return _from_quote(copied, "price_metric", evaluated_at=evaluated_at)


def _derived_metric(
    value: float | None,
    *,
    unit: str,
    currency: str | None,
    period_type: str,
    period_end: str | None,
    retrieved_at: str | None,
    evaluated_at: datetime,
    source_fields: tuple[str, ...],
    method: str,
    notes: str = "",
    proxy: bool = False,
) -> dict[str, Any]:
    if value is None or not math.isfinite(value):
        return _unavailable(
            unit=unit,
            notes=notes or "required inputs are unavailable or invalid",
            period_type=period_type,
            period_end=period_end,
        )
    status, days = _staleness(period_end, evaluated_at=evaluated_at)
    return {
        "source_field": method,
        "source_fields": source_fields,
        "raw_value": None,
        "raw_unit": None,
        "normalized_value": value,
        "normalized_unit": unit,
        "display_value": value,
        "display_unit": unit,
        "currency": currency,
        "period_type": period_type,
        "period_end": period_end,
        "retrieved_at": retrieved_at,
        "source": "FMP",
        "derived": True,
        "proxy": proxy,
        "method": method,
        "notes": notes,
        "status": status,
        "staleness_days": days,
    }


def _rows(normalized: dict[str, Any], statement: str, period: str) -> list[dict[str, Any]]:
    value = normalized.get("statements", {}).get(statement, {}).get(period, [])
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(rows, key=lambda row: row.get("period_end") or "", default=None)


def _ratio_growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    value = current / prior - 1.0
    return value if math.isfinite(value) else None


def _record_value(record: dict[str, Any] | None, field: str) -> float | None:
    if not isinstance(record, dict):
        return None
    return _number(record.get("fields", {}).get(field, {}).get("normalized_value"))


def _growth_metric(
    rows: list[dict[str, Any]],
    field: str,
    *,
    lag: int,
    name: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if len(rows) <= lag:
        return _unavailable(
            unit="ratio",
            notes=f"{name} requires current and lag-{lag} comparable quarters",
            period_type="quarterly",
        )
    current, prior = rows[0], rows[lag]
    if (
        current.get("ticker") != prior.get("ticker")
        or current.get("currency") != prior.get("currency")
        or current.get("period_type") != "quarterly"
        or prior.get("period_type") != "quarterly"
    ):
        value = None
    else:
        value = _ratio_growth(_record_value(current, field), _record_value(prior, field))
    return _derived_metric(
        value,
        unit="ratio",
        currency=None,
        period_type="quarterly",
        period_end=current.get("period_end"),
        retrieved_at=current.get("retrieved_at"),
        evaluated_at=evaluated_at,
        source_fields=(field, field),
        method=f"{name}: current quarter / comparable prior quarter - 1",
        notes="" if value is not None else f"{name} denominator is missing or zero",
    )


def _point_return(
    ttm: dict[str, Any] | None,
    balance_rows: list[dict[str, Any]],
    *,
    numerator: str,
    denominator: str,
    name: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    current = balance_rows[0] if balance_rows else None
    beginning = balance_rows[4] if len(balance_rows) >= 5 else None
    current_value = _record_value(current, denominator)
    beginning_value = _record_value(beginning, denominator)
    numerator_value = _record_value(ttm, numerator)
    average = None
    if (
        current_value is not None
        and beginning_value is not None
        and current_value > 0
        and beginning_value > 0
        and current is not None
        and beginning is not None
        and ttm is not None
        and current.get("currency") == beginning.get("currency") == ttm.get("currency")
    ):
        average = (current_value + beginning_value) / 2.0
    value = numerator_value / average if numerator_value is not None and average else None
    return _derived_metric(
        value,
        unit="ratio",
        currency=None,
        period_type="ttm_over_average_balance",
        period_end=ttm.get("period_end") if isinstance(ttm, dict) else None,
        retrieved_at=ttm.get("retrieved_at") if isinstance(ttm, dict) else None,
        evaluated_at=evaluated_at,
        source_fields=(numerator, f"beginning_{denominator}", f"ending_{denominator}"),
        method=f"TTM {numerator} divided by average beginning and ending {denominator}",
        notes="" if value is not None else f"{name} requires positive comparable beginning and ending {denominator}",
    )


def _roic(
    income_ttm: dict[str, Any] | None,
    balances: list[dict[str, Any]],
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    operating_income = _record_value(income_ttm, "operating_income")
    pretax = _record_value(income_ttm, "income_before_tax")
    tax = _record_value(income_ttm, "income_tax_expense")
    current = balances[0] if balances else None
    beginning = balances[4] if len(balances) >= 5 else None

    tax_rate = tax / pretax if tax is not None and pretax is not None and pretax > 0 else None
    if tax_rate is None or not 0 <= tax_rate <= 1:
        value = None
    else:
        def invested(record: dict[str, Any] | None) -> float | None:
            debt = _record_value(record, "total_debt")
            equity = _record_value(record, "equity")
            cash = _record_value(record, "cash")
            if debt is None or equity is None or cash is None:
                return None
            result = debt + equity - cash
            return result if result > 0 else None

        current_capital = invested(current)
        beginning_capital = invested(beginning)
        average = (
            (current_capital + beginning_capital) / 2.0
            if current_capital is not None and beginning_capital is not None
            else None
        )
        nopat = operating_income * (1.0 - tax_rate) if operating_income is not None else None
        value = nopat / average if nopat is not None and average else None
    return _derived_metric(
        value,
        unit="ratio",
        currency=None,
        period_type="ttm_over_average_balance",
        period_end=income_ttm.get("period_end") if isinstance(income_ttm, dict) else None,
        retrieved_at=income_ttm.get("retrieved_at") if isinstance(income_ttm, dict) else None,
        evaluated_at=evaluated_at,
        source_fields=(
            "operating_income", "income_tax_expense", "income_before_tax",
            "beginning_total_debt", "beginning_equity", "beginning_cash",
            "ending_total_debt", "ending_equity", "ending_cash",
        ),
        method=(
            "NOPAT divided by average invested capital; invested capital = "
            "total debt + equity - cash"
        ),
        notes="" if value is not None else "ROIC requires a valid actual tax rate and comparable average invested capital",
    )


def _multiple(
    numerator: float | None,
    denominator: float | None,
    *,
    currency_matches: bool,
    period_end: str | None,
    retrieved_at: str | None,
    evaluated_at: datetime,
    source_fields: tuple[str, ...],
    method: str,
) -> dict[str, Any]:
    value = (
        numerator / denominator
        if numerator is not None
        and denominator is not None
        and denominator > 0
        and currency_matches
        else None
    )
    return _derived_metric(
        value,
        unit="multiple",
        currency=None,
        period_type="current_over_financial_period",
        period_end=period_end,
        retrieved_at=retrieved_at,
        evaluated_at=evaluated_at,
        source_fields=source_fields,
        method=method,
        notes="" if value is not None else "valuation inputs are unavailable, non-positive, or use different currencies",
    )


def build_fmp_financial_snapshot(
    normalized_data: Any, *, evaluated_at: str
) -> dict[str, Any]:
    """Return a fresh deterministic snapshot with no raw FMP access or clock reads."""

    if not isinstance(normalized_data, dict):
        raise TypeError("normalized_data must be a dictionary")
    normalized = deepcopy(normalized_data)
    evaluated_dt, evaluated_text = _aware_datetime(evaluated_at, name="evaluated_at")
    ticker = normalized.get("symbol")
    identity = normalized.get("identity")
    if not isinstance(ticker, str) or not isinstance(identity, dict):
        raise ValueError("normalized_data must contain a validated identity")
    _, retrieved_text = _aware_datetime(normalized.get("retrieved_at"), name="retrieved_at")

    income_rows = _rows(normalized, "income", "quarterly")
    balance_rows = _rows(normalized, "balance", "quarterly")
    cashflow_rows = _rows(normalized, "cashflow", "quarterly")
    annual_income = _rows(normalized, "income", "annual")
    income_ttm_result = build_ttm_statement(income_rows, statement_type="income")
    cashflow_ttm_result = build_ttm_statement(cashflow_rows, statement_type="cashflow")
    income_ttm = income_ttm_result.get("record")
    cashflow_ttm = cashflow_ttm_result.get("record")
    latest_balance = _latest(balance_rows)
    balance_rows.sort(key=lambda row: row.get("period_end") or "", reverse=True)
    income_rows.sort(key=lambda row: row.get("period_end") or "", reverse=True)
    annual_income.sort(key=lambda row: row.get("period_end") or "", reverse=True)
    quote = normalized.get("quote") if isinstance(normalized.get("quote"), dict) else None
    currency = identity.get("currency")

    metrics: dict[str, dict[str, Any]] = {}
    for name in (
        "revenue", "gross_profit", "gross_margin", "operating_income",
        "operating_margin", "net_income", "net_margin", "ebitda", "diluted_eps",
    ):
        metrics[name] = _from_field(
            income_ttm,
            name,
            evaluated_at=evaluated_dt,
            period_type="ttm",
            notes="requires four continuous quarters" if income_ttm is None else "",
        )
    for name in ("operating_cash_flow", "capex", "free_cash_flow"):
        metrics[name] = _from_field(
            cashflow_ttm,
            name,
            evaluated_at=evaluated_dt,
            period_type="ttm",
            notes="requires four continuous quarters" if cashflow_ttm is None else "",
        )
    for name in ("inventory", "cash", "total_debt", "equity", "assets"):
        metrics[name] = _from_field(
            latest_balance, name, evaluated_at=evaluated_dt, period_type="latest_balance"
        )

    debt = metrics["total_debt"]["normalized_value"]
    cash = metrics["cash"]["normalized_value"]
    metrics["net_debt"] = _derived_metric(
        debt - cash if debt is not None and cash is not None else None,
        unit=currency,
        currency=currency,
        period_type="latest_balance",
        period_end=latest_balance.get("period_end") if latest_balance else None,
        retrieved_at=retrieved_text,
        evaluated_at=evaluated_dt,
        source_fields=("total_debt", "cash"),
        method="total debt minus cash definition",
        notes="cash uses the first complete FMP cash-and-short-term-investments field without adding components twice",
    )

    metrics["price"] = _price_metric(quote, evaluated_at=evaluated_dt)
    for name in ("market_cap", "enterprise_value", "shares_outstanding"):
        metrics[name] = _from_quote(quote, name, evaluated_at=evaluated_dt)

    metrics["revenue_qoq"] = _growth_metric(
        income_rows, "revenue", lag=1, name="revenue QoQ", evaluated_at=evaluated_dt
    )
    metrics["revenue_yoy"] = _growth_metric(
        income_rows, "revenue", lag=4, name="revenue YoY", evaluated_at=evaluated_dt
    )
    metrics["inventory_qoq"] = _growth_metric(
        balance_rows, "inventory", lag=1, name="inventory QoQ", evaluated_at=evaluated_dt
    )
    metrics["inventory_yoy"] = _growth_metric(
        balance_rows, "inventory", lag=4, name="inventory YoY", evaluated_at=evaluated_dt
    )
    annual_growth = (
        _ratio_growth(_record_value(annual_income[0], "revenue"), _record_value(annual_income[1], "revenue"))
        if len(annual_income) >= 2 else None
    )
    metrics["annual_revenue_yoy"] = _derived_metric(
        annual_growth,
        unit="ratio",
        currency=None,
        period_type="annual",
        period_end=annual_income[0].get("period_end") if annual_income else None,
        retrieved_at=retrieved_text,
        evaluated_at=evaluated_dt,
        source_fields=("annual_revenue", "prior_annual_revenue"),
        method="annual revenue / prior annual revenue - 1",
        notes="requires two comparable annual statements" if annual_growth is None else "",
    )
    metrics["annual_revenue"] = _from_field(
        annual_income[0] if annual_income else None,
        "revenue",
        evaluated_at=evaluated_dt,
        period_type="annual",
    )

    revenue = metrics["revenue"]["normalized_value"]
    fcf = metrics["free_cash_flow"]["normalized_value"]
    inventory = metrics["inventory"]["normalized_value"]
    metrics["fcf_margin"] = _derived_metric(
        fcf / revenue if fcf is not None and revenue not in (None, 0) else None,
        unit="ratio", currency=None, period_type="ttm",
        period_end=income_ttm.get("period_end") if income_ttm else None,
        retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("free_cash_flow", "revenue"),
        method="TTM free cash flow divided by TTM revenue",
    )
    metrics["inventory_to_revenue"] = _derived_metric(
        inventory / revenue if inventory is not None and revenue not in (None, 0) else None,
        unit="ratio", currency=None, period_type="latest_balance_over_ttm",
        period_end=latest_balance.get("period_end") if latest_balance else None,
        retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("latest_inventory", "ttm_revenue"),
        method="latest inventory point value divided by TTM revenue flow",
    )
    metrics["roe"] = _point_return(
        income_ttm, balance_rows, numerator="net_income", denominator="equity",
        name="ROE", evaluated_at=evaluated_dt,
    )
    metrics["roa"] = _point_return(
        income_ttm, balance_rows, numerator="net_income", denominator="assets",
        name="ROA", evaluated_at=evaluated_dt,
    )
    metrics["roic"] = _roic(income_ttm, balance_rows, evaluated_at=evaluated_dt)

    price = metrics["price"]["normalized_value"]
    market_cap = metrics["market_cap"]["normalized_value"]
    enterprise_value = metrics["enterprise_value"]["normalized_value"]
    diluted_eps = metrics["diluted_eps"]["normalized_value"]
    equity = metrics["equity"]["normalized_value"]
    ebitda = metrics["ebitda"]["normalized_value"]
    quote_currency = quote.get("currency") if quote else None
    same_currency = currency is not None and quote_currency == currency
    ttm_end = income_ttm.get("period_end") if income_ttm else None
    metrics["pe"] = _multiple(
        price, diluted_eps, currency_matches=same_currency,
        period_end=ttm_end, retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("current_price", "ttm_diluted_eps"),
        method="current price divided by TTM diluted EPS",
    )
    metrics["ps"] = _multiple(
        market_cap, revenue, currency_matches=same_currency,
        period_end=ttm_end, retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("current_market_cap", "ttm_revenue"),
        method="current market cap divided by TTM revenue",
    )
    metrics["pb"] = _multiple(
        market_cap, equity, currency_matches=same_currency,
        period_end=latest_balance.get("period_end") if latest_balance else None,
        retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("current_market_cap", "latest_equity"),
        method="current market cap divided by latest equity",
    )
    metrics["ev_ebitda"] = _multiple(
        enterprise_value, ebitda, currency_matches=same_currency,
        period_end=ttm_end, retrieved_at=retrieved_text, evaluated_at=evaluated_dt,
        source_fields=("current_enterprise_value", "ttm_ebitda"),
        method="current enterprise value divided by TTM EBITDA",
    )

    successful = sum(metric["normalized_value"] is not None for metric in metrics.values())
    stale = sum(metric["status"] == "stale" for metric in metrics.values())
    unavailable = len(metrics) - successful
    periods = {
        "ttm_end": ttm_end,
        "balance_end": latest_balance.get("period_end") if latest_balance else None,
        "annual_end": annual_income[0].get("period_end") if annual_income else None,
    }
    required_available = all(
        metrics[name]["normalized_value"] is not None
        for name in ("revenue", "net_income", "inventory")
    )
    status = "ok" if normalized.get("status") == "ok" and required_available else "partial"
    return {
        "ticker": ticker,
        "company_name": identity.get("company_name"),
        "cik": identity.get("cik"),
        "source": "FMP",
        "retrieved_at": retrieved_text,
        "evaluated_at": evaluated_text,
        "currency": currency,
        "periods": periods,
        "metrics": metrics,
        "quality": {
            "successful_metric_count": successful,
            "unavailable_metric_count": unavailable,
            "stale_metric_count": stale,
            "total_metric_count": len(metrics),
            "normalization_status": normalized.get("status"),
            "errors": deepcopy(normalized.get("errors", [])),
            "ttm_income_status": income_ttm_result.get("status"),
            "ttm_cashflow_status": cashflow_ttm_result.get("status"),
        },
        "status": status,
    }
