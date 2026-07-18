"""Pure normalization for the shared FMP financial truth layer."""

from copy import deepcopy
from datetime import date, datetime, timezone
import math
from numbers import Real
import re
from types import MappingProxyType
from typing import Any


SNDK_MIN_FINANCIAL_DATE = date(2025, 1, 1)
_SAFE_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_SAFE_CIK = re.compile(r"^\d{10}$")
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")
_QUARTERS = frozenset({"Q1", "Q2", "Q3", "Q4"})
_STATEMENT_GROUPS = MappingProxyType({
    "income_quarterly": ("income", "quarterly"),
    "income_annual": ("income", "annual"),
    "balance_quarterly": ("balance", "quarterly"),
    "balance_annual": ("balance", "annual"),
    "cashflow_quarterly": ("cashflow", "quarterly"),
    "cashflow_annual": ("cashflow", "annual"),
})
_MONEY_FIELDS = MappingProxyType({
    "income": MappingProxyType({
        "revenue": "revenue",
        "gross_profit": "grossProfit",
        "operating_income": "operatingIncome",
        "net_income": "netIncome",
        "ebitda": "ebitda",
        "income_before_tax": "incomeBeforeTax",
        "income_tax_expense": "incomeTaxExpense",
    }),
    "balance": MappingProxyType({
        "inventory": "inventory",
        "total_debt": "totalDebt",
        "equity": "totalStockholdersEquity",
        "assets": "totalAssets",
    }),
    "cashflow": MappingProxyType({
        "operating_cash_flow": "operatingCashFlow",
    }),
})
_INCOME_PER_SHARE = MappingProxyType({
    "basic_eps": "eps",
    "diluted_eps": "epsdiluted",
})
_INCOME_SHARES = MappingProxyType({
    "weighted_average_shares": "weightedAverageShsOut",
    "diluted_weighted_average_shares": "weightedAverageShsOutDil",
})
_MARGIN_FIELDS = MappingProxyType({
    "gross_margin": ("grossProfitRatio", "grossMarginPercent", "gross_profit"),
    "operating_margin": (
        "operatingIncomeRatio", "operatingMarginPercent", "operating_income"
    ),
    "net_margin": ("netIncomeRatio", "netMarginPercent", "net_income"),
})
_ERROR_FIELDS = (
    "family", "ticker", "statement_type", "period_type", "field", "code"
)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _number(value: Any) -> Real | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        return value if math.isfinite(float(value)) else None
    except (OverflowError, TypeError, ValueError):
        return None


def _safe_symbol(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    symbol = text.upper()
    return symbol if _SAFE_SYMBOL.fullmatch(symbol) is not None else None


def _currency(value: Any) -> str | None:
    text = _text(value)
    return text if text is not None and _SAFE_CURRENCY.fullmatch(text) else None


def _aware_timestamp(value: Any, *, name: str) -> tuple[datetime, str]:
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.endswith(("Z", "z")):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
    try:
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        normalized = parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise ValueError(f"{name} must be a timezone-aware timestamp") from None
    return normalized, normalized.isoformat()


def _period_end(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [deepcopy(row) for row in value if isinstance(row, dict)]


def _error(
    ticker: str | None,
    code: str,
    *,
    statement_type: str | None = None,
    period_type: str | None = None,
    field: str | None = None,
) -> dict[str, str | None]:
    return {
        "family": "fmp_financial",
        "ticker": ticker,
        "statement_type": statement_type,
        "period_type": period_type,
        "field": field,
        "code": code,
    }


def _sorted_errors(
    errors: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    unique = {
        tuple(error.get(field) for field in _ERROR_FIELDS)
        for error in errors
    }
    return [
        dict(zip(_ERROR_FIELDS, values))
        for values in sorted(unique, key=lambda item: tuple(value or "" for value in item))
    ]


def normalize_monetary_value(
    value: Any, *, raw_unit: Any, currency: Any
) -> dict[str, Any] | None:
    """Normalize a monetary value to full currency units exactly once."""

    number = _number(value)
    currency_text = _currency(currency)
    unit_text = _text(raw_unit)
    if number is None or currency_text is None or unit_text is None:
        return None
    multipliers = {
        currency_text: 1.0,
        f"{currency_text} thousands": 1_000.0,
        f"{currency_text} millions": 1_000_000.0,
        f"{currency_text} billions": 1_000_000_000.0,
    }
    multiplier = multipliers.get(unit_text)
    if multiplier is None:
        return None
    try:
        normalized = float(number) * multiplier
    except OverflowError:
        return None
    if not math.isfinite(normalized):
        return None
    return {
        "raw_value": number,
        "raw_unit": unit_text,
        "normalized_value": normalized,
        "normalized_unit": currency_text,
        "currency": currency_text,
    }


def _scalar_field(
    row: dict[str, Any],
    source_field: str,
    *,
    raw_unit: str,
    normalized_unit: str,
    currency: str | None,
) -> dict[str, Any] | None:
    value = _number(row.get(source_field))
    if value is None:
        return None
    return {
        "source_field": source_field,
        "source_fields": (source_field,),
        "raw_value": value,
        "raw_unit": raw_unit,
        "normalized_value": float(value),
        "normalized_unit": normalized_unit,
        "currency": currency,
        "derived": False,
        "method": "FMP reported field",
    }


def _money_field(
    row: dict[str, Any], source_field: str, *, currency: str
) -> dict[str, Any] | None:
    raw_unit = _text(row.get(f"{source_field}Unit")) or currency
    normalized = normalize_monetary_value(
        row.get(source_field), raw_unit=raw_unit, currency=currency
    )
    if normalized is None:
        return None
    return {
        "source_field": source_field,
        "source_fields": (source_field,),
        **normalized,
        "derived": False,
        "method": "FMP reported field",
    }


def _margin_field(
    row: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    *,
    output_field: str,
    ratio_field: str,
    percent_field: str,
    numerator_field: str,
) -> dict[str, Any] | None:
    ratio = _number(row.get(ratio_field))
    if ratio is not None:
        return {
            "source_field": ratio_field,
            "source_fields": (ratio_field,),
            "raw_value": ratio,
            "raw_unit": "ratio",
            "normalized_value": float(ratio) * 100.0,
            "normalized_unit": "percent",
            "currency": None,
            "derived": False,
            "method": "FMP reported ratio converted once to percent",
        }
    percent = _number(row.get(percent_field))
    if percent is not None:
        return {
            "source_field": percent_field,
            "source_fields": (percent_field,),
            "raw_value": percent,
            "raw_unit": "percent",
            "normalized_value": float(percent),
            "normalized_unit": "percent",
            "currency": None,
            "derived": False,
            "method": "FMP reported percent",
        }
    numerator = fields.get(numerator_field)
    revenue = fields.get("revenue")
    if numerator is None or revenue is None:
        return None
    denominator = revenue["normalized_value"]
    if denominator == 0 or numerator.get("currency") != revenue.get("currency"):
        return None
    value = numerator["normalized_value"] / denominator * 100.0
    return {
        "source_field": f"{numerator['source_field']}/{revenue['source_field']}",
        "source_fields": (numerator["source_field"], revenue["source_field"]),
        "raw_value": None,
        "raw_unit": None,
        "normalized_value": value,
        "normalized_unit": "percent",
        "currency": None,
        "derived": True,
        "method": f"same-statement {output_field} derived from reported fields",
    }


def _identity(raw: dict[str, Any], ticker: str) -> tuple[dict[str, Any] | None, str | None]:
    matches: list[tuple[str, str | None, str | None]] = []
    for row in _rows(raw.get("identity")):
        if _safe_symbol(row.get("symbol")) != ticker:
            continue
        name = _text(row.get("companyName") or row.get("company_name") or row.get("name"))
        cik = _text(row.get("cik"))
        if cik is not None and _SAFE_CIK.fullmatch(cik) is None:
            continue
        if ticker == "SNDK" and (
            name is None
            or re.search(r"\bsan\s*disk\b", name, re.IGNORECASE) is None
            or cik is None
        ):
            continue
        matches.append((name or ticker, cik, _currency(row.get("currency"))))
    identities = set(matches)
    if len(identities) != 1:
        return None, "identity_mismatch"
    name, cik, currency = identities.pop()
    return {
        "symbol": ticker,
        "company_name": name,
        "cik": cik,
        "currency": currency,
    }, None


def _normalize_quote(
    raw: dict[str, Any],
    *,
    ticker: str,
    identity: dict[str, Any],
    retrieved_at: str,
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        row for row in _rows(raw.get("quote"))
        if _safe_symbol(row.get("symbol")) == ticker
    ]
    if len(matches) != 1:
        return None, "quote_identity_mismatch"
    row = matches[0]
    currency = _currency(row.get("currency"))
    if currency is None:
        return None, "missing_currency"
    if identity.get("currency") is not None and identity["currency"] != currency:
        return None, "currency_mismatch"
    price = _number(row.get("price"))
    if price is None or float(price) <= 0:
        return None, "invalid_quote_price"
    timestamp = row.get("timestamp")
    parsed_time: datetime | None = None
    if isinstance(timestamp, Real) and not isinstance(timestamp, bool):
        try:
            parsed_time = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            parsed_time = None
    elif isinstance(timestamp, str):
        try:
            candidate = timestamp[:-1] + "+00:00" if timestamp.endswith(("Z", "z")) else timestamp
            parsed_time = datetime.fromisoformat(candidate)
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                parsed_time = None
            elif parsed_time is not None:
                parsed_time = parsed_time.astimezone(timezone.utc)
        except (OverflowError, ValueError):
            parsed_time = None
    if parsed_time is None:
        return None, "invalid_quote_timestamp"
    quote: dict[str, Any] = {
        "ticker": ticker,
        "price": float(price),
        "currency": currency,
        "as_of": parsed_time.isoformat(),
        "retrieved_at": retrieved_at,
        "source": "FMP",
        "source_document": "quote",
    }
    for output, source, unit in (
        ("market_cap", "marketCap", currency),
        ("enterprise_value", "enterpriseValue", currency),
        ("shares_outstanding", "sharesOutstanding", "shares"),
    ):
        value = _number(row.get(source))
        quote[output] = None if value is None else {
            "source_field": source,
            "raw_value": value,
            "raw_unit": unit,
            "normalized_value": float(value),
            "normalized_unit": unit,
            "currency": currency if unit == currency else None,
            "derived": False,
        }
    return quote, None


def _statement_year(row: dict[str, Any], period_end: date) -> str | None:
    raw_year = row.get("fiscalYear")
    from_calendar = False
    if raw_year is None or (isinstance(raw_year, str) and not raw_year.strip()):
        raw_year = row.get("calendarYear")
        from_calendar = True
    if isinstance(raw_year, bool):
        return None
    year = str(raw_year).strip() if isinstance(raw_year, (str, int)) else ""
    if re.fullmatch(r"(?:19|20)\d{2}", year) is None:
        return None
    if from_calendar and year != str(period_end.year):
        return None
    return year


def _normalize_statement_row(
    row: dict[str, Any],
    *,
    ticker: str,
    identity: dict[str, Any],
    statement_type: str,
    expected_period_type: str,
    retrieved_at: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str | None]]]:
    errors: list[dict[str, str | None]] = []
    if _safe_symbol(row.get("symbol")) != ticker:
        return None, [_error(
            ticker, "statement_identity_mismatch",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    identity_cik = identity.get("cik")
    row_cik = _text(row.get("cik"))
    if (row_cik is not None and identity_cik is not None and row_cik != identity_cik) or (
        ticker == "SNDK" and (row_cik is None or row_cik != identity_cik)
    ):
        return None, [_error(
            ticker, "statement_identity_mismatch",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    end = _period_end(row.get("date"))
    if end is None:
        return None, [_error(
            ticker, "missing_period_end",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    if ticker == "SNDK" and end < SNDK_MIN_FINANCIAL_DATE:
        return None, [_error(
            ticker, "legacy_statement",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    period = (_text(row.get("period")) or "").upper()
    if expected_period_type == "quarterly" and period not in _QUARTERS:
        return None, [_error(
            ticker, "unsupported_period",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    if expected_period_type == "annual" and period != "FY":
        return None, [_error(
            ticker, "unsupported_period",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    year = _statement_year(row, end)
    if year is None:
        return None, [_error(
            ticker, "missing_period_metadata",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    currency = _currency(row.get("reportedCurrency"))
    if currency is None:
        return None, [_error(
            ticker, "missing_currency",
            statement_type=statement_type, period_type=expected_period_type,
        )]
    fields: dict[str, dict[str, Any]] = {}
    for output_field, source_field in _MONEY_FIELDS[statement_type].items():
        field = _money_field(row, source_field, currency=currency)
        if field is not None:
            fields[output_field] = field
    if statement_type == "income":
        for output_field, source_field in _INCOME_PER_SHARE.items():
            field = _scalar_field(
                row, source_field, raw_unit=f"{currency} per share",
                normalized_unit=f"{currency} per share", currency=currency,
            )
            if field is not None:
                fields[output_field] = field
        for output_field, source_field in _INCOME_SHARES.items():
            field = _scalar_field(
                row, source_field, raw_unit="shares",
                normalized_unit="shares", currency=None,
            )
            if field is not None:
                fields[output_field] = field
        for output_field, (
            ratio_field, percent_field, numerator_field
        ) in _MARGIN_FIELDS.items():
            field = _margin_field(
                row, fields, output_field=output_field,
                ratio_field=ratio_field, percent_field=percent_field,
                numerator_field=numerator_field,
            )
            if field is not None:
                fields[output_field] = field
    elif statement_type == "balance":
        cash_candidates = (
            "cashAndCashEquivalentsAndShortTermInvestments",
            "cashAndShortTermInvestments",
            "cashAndCashEquivalents",
        )
        for source_field in cash_candidates:
            field = _money_field(row, source_field, currency=currency)
            if field is not None:
                field["method"] = f"cash definition: {source_field}; no components added"
                fields["cash"] = field
                break
    elif statement_type == "cashflow":
        raw_capex = _number(row.get("capitalExpenditure"))
        if raw_capex is not None:
            if float(raw_capex) <= 0:
                fields["capex"] = {
                    "source_field": "capitalExpenditure",
                    "source_fields": ("capitalExpenditure",),
                    "raw_value": raw_capex,
                    "raw_unit": currency,
                    "normalized_value": abs(float(raw_capex)),
                    "normalized_unit": currency,
                    "currency": currency,
                    "derived": True,
                    "method": "cash outflow magnitude = abs(reported capitalExpenditure)",
                }
            else:
                errors.append(_error(
                    ticker, "positive_capex_sign", statement_type=statement_type,
                    period_type=expected_period_type, field="capex",
                ))
        reported_fcf = _money_field(row, "freeCashFlow", currency=currency)
        ocf = fields.get("operating_cash_flow")
        capex = fields.get("capex")
        if ocf is not None and capex is not None:
            derived_value = ocf["normalized_value"] - capex["normalized_value"]
            if reported_fcf is None:
                fields["free_cash_flow"] = {
                    "source_field": "operatingCashFlow-capitalExpenditureMagnitude",
                    "source_fields": ("operatingCashFlow", "capitalExpenditure"),
                    "raw_value": None,
                    "raw_unit": None,
                    "normalized_value": derived_value,
                    "normalized_unit": currency,
                    "currency": currency,
                    "derived": True,
                    "method": "operating cash flow minus CapEx cash outflow magnitude",
                }
            elif not math.isclose(
                reported_fcf["normalized_value"], derived_value,
                rel_tol=0.01, abs_tol=1e-9,
            ):
                errors.append(_error(
                    ticker, "free_cash_flow_conflict", statement_type=statement_type,
                    period_type=expected_period_type, field="free_cash_flow",
                ))
            else:
                reported_fcf["method"] = "FMP reported freeCashFlow; verified against OCF - CapEx magnitude"
                fields["free_cash_flow"] = reported_fcf
    fiscal_period = year if expected_period_type == "annual" else f"{year} {period}"
    return {
        "ticker": ticker,
        "statement_type": statement_type,
        "period_type": expected_period_type,
        "period": period,
        "fiscal_year": year,
        "fiscal_period": fiscal_period,
        "period_end": end.isoformat(),
        "filing_date": _text(row.get("fillingDate") or row.get("filingDate")),
        "retrieved_at": retrieved_at,
        "currency": currency,
        "source": "FMP",
        "source_document": f"{statement_type}_statement",
        "fields": fields,
    }, errors


def _quarter_key(row: dict[str, Any]) -> int | None:
    period = row.get("period")
    year = row.get("fiscal_year")
    if period not in _QUARTERS or not isinstance(year, str) or not year.isdigit():
        return None
    return int(year) * 4 + int(period[1]) - 1


def _ttm_unavailable(code: str) -> dict[str, Any]:
    return {"record": None, "errors": [{"code": code}], "status": "unavailable"}


def _summed_field(
    rows: list[dict[str, Any]], field_name: str, *, currency: str
) -> dict[str, Any] | None:
    fields = [row.get("fields", {}).get(field_name) for row in rows]
    if any(field is None for field in fields):
        return None
    values = [field["normalized_value"] for field in fields if field is not None]
    if len(values) != 4 or any(_number(value) is None for value in values):
        return None
    unit = fields[0]["normalized_unit"]
    if any(field["normalized_unit"] != unit for field in fields if field is not None):
        return None
    return {
        "source_field": f"{field_name} (sum of 4 quarters)",
        "source_fields": tuple(field["source_field"] for field in fields if field is not None),
        "raw_value": None,
        "raw_unit": None,
        "normalized_value": sum(float(value) for value in values),
        "normalized_unit": unit,
        "currency": currency if unit != "shares" else None,
        "derived": True,
        "method": "sum of four continuous FMP quarterly observations",
    }


def build_ttm_statement(
    rows: Any, *, statement_type: str
) -> dict[str, Any]:
    """Build a TTM flow record from the latest four continuous quarters."""

    copied = _rows(rows)
    if statement_type not in {"income", "cashflow"}:
        return _ttm_unavailable("unsupported_statement_type")
    if len(copied) < 4 or any(row.get("period_type") != "quarterly" for row in copied):
        return _ttm_unavailable("incomplete_ttm")
    if any(row.get("statement_type") != statement_type for row in copied):
        return _ttm_unavailable("mixed_statement_type")
    copied.sort(key=lambda row: row.get("period_end") or "", reverse=True)
    selected = copied[:4]
    ticker = selected[0].get("ticker")
    currency = selected[0].get("currency")
    if any(row.get("ticker") != ticker for row in selected):
        return _ttm_unavailable("mixed_ticker")
    if any(row.get("currency") != currency for row in selected):
        return _ttm_unavailable("mixed_currency")
    ends = [row.get("period_end") for row in selected]
    if len(set(ends)) != 4:
        return _ttm_unavailable("duplicate_period_end")
    keys = [_quarter_key(row) for row in selected]
    if any(key is None for key in keys) or any(
        keys[index] - keys[index + 1] != 1 for index in range(3)
    ):
        return _ttm_unavailable("non_continuous_quarters")
    parsed_ends = [_period_end(end) for end in ends]
    if any(end is None for end in parsed_ends):
        return _ttm_unavailable("invalid_period_end")
    gaps = [
        (parsed_ends[index] - parsed_ends[index + 1]).days
        for index in range(3)
        if parsed_ends[index] is not None and parsed_ends[index + 1] is not None
    ]
    if any(gap < 60 or gap > 120 for gap in gaps):
        return _ttm_unavailable("unreasonable_quarter_gap")
    supported = (
        (
            "revenue", "gross_profit", "operating_income", "net_income",
            "ebitda", "income_before_tax", "income_tax_expense", "diluted_eps",
        )
        if statement_type == "income"
        else ("operating_cash_flow", "capex", "free_cash_flow")
    )
    fields: dict[str, dict[str, Any]] = {}
    for field_name in supported:
        field = _summed_field(selected, field_name, currency=currency)
        if field is not None:
            fields[field_name] = field
    if statement_type == "income":
        for output, numerator in (
            ("gross_margin", "gross_profit"),
            ("operating_margin", "operating_income"),
            ("net_margin", "net_income"),
        ):
            if "revenue" in fields and numerator in fields and fields["revenue"]["normalized_value"] != 0:
                fields[output] = {
                    "source_field": f"TTM {numerator}/revenue",
                    "source_fields": (numerator, "revenue"),
                    "raw_value": None,
                    "raw_unit": None,
                    "normalized_value": fields[numerator]["normalized_value"] / fields["revenue"]["normalized_value"] * 100.0,
                    "normalized_unit": "percent",
                    "currency": None,
                    "derived": True,
                    "method": "TTM numerator divided by TTM revenue",
                }
    return {
        "record": {
            "ticker": ticker,
            "statement_type": statement_type,
            "period_type": "ttm",
            "period": "TTM",
            "fiscal_year": selected[0].get("fiscal_year"),
            "fiscal_period": f"TTM ended {selected[0]['period_end']}",
            "period_end": selected[0]["period_end"],
            "retrieved_at": selected[0].get("retrieved_at"),
            "currency": currency,
            "source": "FMP",
            "source_document": f"{statement_type}_statement",
            "component_period_ends": tuple(ends),
            "fields": fields,
        },
        "errors": [],
        "status": "ok",
    }


def normalize_fmp_financial_data(raw_envelope: Any) -> dict[str, Any]:
    """Normalize one raw FMP envelope without fetching or guessing metadata."""

    if not isinstance(raw_envelope, dict):
        raise TypeError("raw_envelope must be a dictionary")
    raw = deepcopy(raw_envelope)
    ticker = _safe_symbol(raw.get("symbol"))
    if ticker is None:
        raise ValueError("raw envelope symbol is invalid")
    _, retrieval_text = _aware_timestamp(raw.get("retrieved_at"), name="retrieved_at")
    errors: list[dict[str, str | None]] = []
    identity, identity_code = _identity(raw, ticker)
    empty_statements = {
        statement_type: {"quarterly": [], "annual": []}
        for statement_type in ("income", "balance", "cashflow")
    }
    if identity is None:
        errors.append(_error(ticker, identity_code or "identity_mismatch"))
        return {
            "symbol": ticker,
            "identity": None,
            "quote": None,
            "statements": empty_statements,
            "retrieved_at": retrieval_text,
            "source": "FMP",
            "errors": _sorted_errors(errors),
            "status": "error",
        }
    quote, quote_code = _normalize_quote(
        raw, ticker=ticker, identity=identity, retrieved_at=retrieval_text
    )
    if quote is None:
        errors.append(_error(ticker, quote_code or "invalid_quote", statement_type="quote"))
    statements = empty_statements
    for raw_key, (statement_type, period_type) in _STATEMENT_GROUPS.items():
        for row in _rows(raw.get(raw_key)):
            normalized, row_errors = _normalize_statement_row(
                row,
                ticker=ticker,
                identity=identity,
                statement_type=statement_type,
                expected_period_type=period_type,
                retrieved_at=retrieval_text,
            )
            errors.extend(row_errors)
            if normalized is not None:
                statements[statement_type][period_type].append(normalized)
        statements[statement_type][period_type].sort(
            key=lambda row: row["period_end"], reverse=True
        )
    for provider_error in raw.get("errors", []):
        if isinstance(provider_error, dict):
            code = _text(provider_error.get("code"))
            if code is not None and re.fullmatch(r"[a-z0-9_]{1,32}", code):
                errors.append(_error(ticker, code))
    has_data = quote is not None or any(
        rows
        for statement_group in statements.values()
        for rows in statement_group.values()
    )
    safe_errors = _sorted_errors(errors)
    status = "ok" if has_data and not safe_errors else "partial" if has_data else "error"
    return {
        "symbol": ticker,
        "identity": identity,
        "quote": quote,
        "statements": statements,
        "retrieved_at": retrieval_text,
        "source": "FMP",
        "errors": safe_errors,
        "status": status,
    }
