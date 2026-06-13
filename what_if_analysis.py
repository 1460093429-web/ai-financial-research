from __future__ import annotations

from datetime import date, datetime, time, timedelta
import io
import math

import pandas as pd

from ibkr_statement_parser import parse_ibkr_activity_statement_csv, read_uploaded_file_text


PERIOD_DAYS = {
    "1 Day": 1,
    "1 Week": 7,
    "1 Month": 30,
}

PRICE_MODE_REALTIME = "Realtime / Extended Hours Price"
PRICE_MODE_REGULAR_CLOSE = "Regular Close Price"
PRICE_MODE_CSV_FALLBACK = "CSV Last Price Fallback"
PRICE_MODES = [
    PRICE_MODE_REALTIME,
    PRICE_MODE_REGULAR_CLOSE,
    PRICE_MODE_CSV_FALLBACK,
]
CSV_FALLBACK_SOURCE = "CSV last price fallback"


def period_start(period_label, now=None):
    now = now or datetime.now()
    if period_label == "YTD":
        return datetime.combine(date(now.year, 1, 1), time.min)
    return now - timedelta(days=PERIOD_DAYS.get(period_label, 1))


def period_bounds(period_label=None, start_date=None, end_date=None, now=None):
    if not period_label:
        return None, None

    now = now or datetime.now()
    if period_label == "Custom":
        start = start_date or now.date()
        end = end_date or now.date()
        if isinstance(start, datetime):
            start = start.date()
        if isinstance(end, datetime):
            end = end.date()
        if start > end:
            start, end = end, start
        return datetime.combine(start, time.min), datetime.combine(end, time.max)

    if period_label == "YTD":
        return datetime.combine(date(now.year, 1, 1), time.min), now

    return period_start(period_label, now), now


def period_date_bounds(period_label=None, start_date=None, end_date=None, now=None, anchor_date=None):
    if not period_label:
        return None, None

    if anchor_date is None:
        now = now or datetime.now()
        anchor = now.date() if isinstance(now, datetime) else now
    else:
        anchor = anchor_date.date() if isinstance(anchor_date, datetime) else anchor_date

    if period_label == "Custom":
        start = start_date or anchor
        end = end_date or anchor
        if isinstance(start, datetime):
            start = start.date()
        if isinstance(end, datetime):
            end = end.date()
        if start > end:
            start, end = end, start
        return start, end

    if period_label == "YTD":
        return date(anchor.year, 1, 1), anchor
    if period_label == "1 Day":
        return anchor, anchor
    return anchor - timedelta(days=PERIOD_DAYS.get(period_label, 1)), anchor


def calculate_trade_value_added(trade, current_price):
    quantity = _to_float(trade.get("quantity"))
    trade_price = _to_float(trade.get("price"))
    commission = _to_float(trade.get("commission"))
    current_price = _to_float(current_price)
    side = str(trade.get("side") or "").upper()

    if current_price is None or quantity is None or trade_price is None:
        return 0.0
    commission = commission or 0.0
    if side == "BUY":
        return quantity * (current_price - trade_price) + commission
    if side == "SELL":
        return quantity * (trade_price - current_price) + commission
    return 0.0


def build_what_if_analysis(actual_equity, positions, trades, current_prices, price_details=None):
    position_map = {}
    for item in positions or []:
        symbol = _normalize_symbol(item.get("symbol"))
        if not symbol:
            continue
        position_map[symbol] = position_map.get(symbol, 0.0) + (_to_float(item.get("quantity")) or 0.0)

    trades_by_symbol = {}
    for trade in trades or []:
        symbol = _normalize_symbol(trade.get("symbol"))
        if not symbol:
            continue
        normalized = dict(trade)
        normalized["symbol"] = symbol
        normalized["side"] = str(normalized.get("side") or "").upper()
        trades_by_symbol.setdefault(symbol, []).append(normalized)

    symbols = sorted(set(position_map) | set(trades_by_symbol) | {_normalize_symbol(key) for key in (current_prices or {}) if _normalize_symbol(key)})
    price_map = {_normalize_symbol(key): _to_float(value) for key, value in (current_prices or {}).items()}
    detail_map = {
        _normalize_symbol(key): _normalize_price_detail(value)
        for key, value in (price_details or {}).items()
        if _normalize_symbol(key)
    }
    rows = []
    total_value_added = 0.0

    for symbol in symbols:
        actual_position = position_map.get(symbol, 0.0)
        no_trade_position = actual_position
        symbol_value_added = 0.0
        symbol_trades = trades_by_symbol.get(symbol, [])
        current_price = price_map.get(symbol)
        price_detail = detail_map.get(symbol, {})

        for trade in symbol_trades:
            quantity = _to_float(trade.get("quantity")) or 0.0
            side = str(trade.get("side") or "").upper()
            if side == "BUY":
                no_trade_position -= quantity
            elif side == "SELL":
                no_trade_position += quantity
            symbol_value_added += calculate_trade_value_added(trade, current_price)

        total_value_added += symbol_value_added
        rows.append(
            {
                "Symbol": symbol,
                "Trades in period": len(symbol_trades),
                "Buy quantity": sum((_to_float(trade.get("quantity")) or 0.0) for trade in symbol_trades if trade.get("side") == "BUY"),
                "Sell quantity": sum((_to_float(trade.get("quantity")) or 0.0) for trade in symbol_trades if trade.get("side") == "SELL"),
                "Actual Position": actual_position,
                "No-trade Position": no_trade_position,
                "Current Price": current_price,
                "price_source": price_detail.get("price_source"),
                "price_time": price_detail.get("price_time"),
                "is_fallback": bool(price_detail.get("is_fallback")),
                "Trading Value Added": symbol_value_added,
            }
        )

    actual_equity_value = _to_float(actual_equity) or 0.0
    no_trade_equity = actual_equity_value - total_value_added
    return {
        "actual_equity": actual_equity_value,
        "no_trade_equity": no_trade_equity,
        "trading_value_added": total_value_added,
        "rows": rows,
    }


def parse_activity_statement_csv(file_obj, period_label=None, now=None, start_date=None, end_date=None):
    csv_text = read_uploaded_file_text(file_obj)
    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    if any(not sectioned[key].empty for key in ("trades", "positions", "nav", "cash")):
        return activity_statement_frames_to_what_if_data(
            sectioned,
            period_label=period_label,
            now=now,
            start_date=start_date,
            end_date=end_date,
        )

    return _parse_rectangular_activity_statement_csv(
        csv_text,
        period_label=period_label,
        now=now,
        start_date=start_date,
        end_date=end_date,
    )


def activity_statement_frames_to_what_if_data(sectioned, period_label=None, now=None, start_date=None, end_date=None):
    trades_frame = _clean_frame(sectioned.get("trades"))
    positions_frame = _clean_frame(sectioned.get("positions"))
    nav_frame = _clean_frame(sectioned.get("nav"))
    cash_frame = _clean_frame(sectioned.get("cash"))
    normalized_trades = normalize_ibkr_trades_df(trades_frame)
    all_trade_datetimes = list(normalized_trades["trade_datetime"]) if not normalized_trades.empty else []
    csv_max_date = max(all_trade_datetimes).date() if all_trade_datetimes else None
    start, end = period_date_bounds(
        period_label,
        start_date=start_date,
        end_date=end_date,
        now=now,
        anchor_date=csv_max_date,
    )

    trades = []
    positions = {}
    current_prices = {}
    price_details = {}
    position_market_values = {}
    used_trade_datetimes = []
    price_fallback_symbols = set()

    filtered_trades = _filter_trades_by_date(normalized_trades, start, end)
    if not filtered_trades.empty:
        used_trade_datetimes = list(filtered_trades["trade_datetime"])
        trades = _trades_frame_to_records(filtered_trades)
        for _, row in _last_rows_by_symbol(filtered_trades).iterrows():
            symbol = row["symbol"]
            fallback_price = _to_float(row.get("csv_last_price"))
            if symbol and fallback_price is not None:
                current_prices[symbol] = fallback_price
                price_details[symbol] = make_price_detail(
                    fallback_price,
                    CSV_FALLBACK_SOURCE,
                    row.get("trade_datetime"),
                    is_fallback=True,
                )
                price_fallback_symbols.add(symbol)

    for _, row in positions_frame.iterrows():
        symbol = _normalize_symbol(_get(row, "symbol", "ticker", "underlying"))
        if not symbol:
            continue

        quantity = _to_float(_get(row, "position", "position quantity", "ending quantity", "actual position", "quantity"))
        if quantity is not None:
            positions[symbol] = quantity

        current_price = _to_float(_get(row, "current price", "mark price", "close price", "last price"))
        if current_price is not None:
            current_prices[symbol] = current_price
            price_details[symbol] = make_price_detail(
                current_price,
                "Regular close price",
                _get(row, "date", "date/time", "as of date"),
                is_fallback=False,
            )
            price_fallback_symbols.discard(symbol)
        market_value = _to_float(_get(row, "market value", "value", "position value"))
        if market_value is not None:
            position_market_values[symbol] = market_value

    actual_equity = _extract_actual_equity(nav_frame)
    if actual_equity is None:
        actual_equity = _estimate_equity_from_positions_and_cash(position_market_values, positions, current_prices, cash_frame)

    return {
        "data_source": "CSV",
        "actual_equity": actual_equity,
        "positions": [{"symbol": symbol, "quantity": quantity} for symbol, quantity in positions.items()],
        "trades": trades,
        "current_prices": current_prices,
        "price_details": price_details,
        "price_fallback_symbols": sorted(price_fallback_symbols),
        "period_start": start,
        "period_end": end,
        "trades_used": len(trades),
        "first_trade_date_used": min(used_trade_datetimes).date() if used_trade_datetimes else None,
        "last_trade_date_used": max(used_trade_datetimes).date() if used_trade_datetimes else None,
        "parsed_trade_min_date": min(all_trade_datetimes).date() if all_trade_datetimes else None,
        "parsed_trade_max_date": csv_max_date,
        "trades_columns": list(trades_frame.columns),
        "trades_preview": normalized_trades.head(20).to_dict("records"),
    }


def summarize_activity_statement_frames(sectioned):
    trades_frame = _clean_frame(sectioned.get("trades"))
    positions_frame = _clean_frame(sectioned.get("positions"))
    normalized_trades = normalize_ibkr_trades_df(trades_frame)
    trade_dates = list(normalized_trades["trade_datetime"]) if not normalized_trades.empty else []

    return {
        "csv_start_date": min(trade_dates).date() if trade_dates else None,
        "csv_end_date": max(trade_dates).date() if trade_dates else None,
        "total_trades_parsed": len(trades_frame),
        "positions_parsed": len(positions_frame),
    }


def make_price_detail(price, price_source, price_time=None, is_fallback=False):
    price = _to_float(price)
    return {
        "price": price,
        "price_source": price_source,
        "price_time": _format_price_time(price_time),
        "is_fallback": bool(is_fallback),
    }


def resolve_current_price_details(
    symbols,
    price_mode=PRICE_MODE_REALTIME,
    ibkr_details=None,
    yahoo_details=None,
    fmp_details=None,
    csv_details=None,
):
    resolved = {}
    for symbol in sorted({_normalize_symbol(symbol) for symbol in symbols or [] if _normalize_symbol(symbol)}):
        detail = None
        if price_mode == PRICE_MODE_CSV_FALLBACK:
            detail = _first_price_detail(symbol, csv_details)
        elif price_mode == PRICE_MODE_REGULAR_CLOSE:
            detail = _first_price_detail(symbol, yahoo_details, fmp_details, csv_details)
        else:
            detail = _first_price_detail(symbol, ibkr_details, yahoo_details, fmp_details, csv_details)
        if detail and detail.get("price") is not None:
            resolved[symbol] = detail
    return resolved


def price_details_to_prices(price_details):
    return {
        symbol: detail.get("price")
        for symbol, detail in (price_details or {}).items()
        if detail and detail.get("price") is not None
    }


def price_fallback_symbols(price_details):
    return sorted(
        symbol
        for symbol, detail in (price_details or {}).items()
        if detail and detail.get("price_source") == CSV_FALLBACK_SOURCE
    )


def _parse_rectangular_activity_statement_csv(csv_text, period_label=None, now=None, start_date=None, end_date=None):
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [_clean_column_name(column) for column in df.columns]
    trade_rows = df[df.apply(_row_is_trade, axis=1)] if not df.empty else pd.DataFrame()
    normalized_trades = normalize_ibkr_trades_df(trade_rows)
    all_trade_datetimes = list(normalized_trades["trade_datetime"]) if not normalized_trades.empty else []
    csv_max_date = max(all_trade_datetimes).date() if all_trade_datetimes else None
    start, end = period_date_bounds(period_label, start_date=start_date, end_date=end_date, now=now, anchor_date=csv_max_date)
    trades = []
    positions = {}
    current_prices = {}
    price_details = {}
    position_market_values = {}
    actual_equity = None
    used_trade_datetimes = []
    price_fallback_symbols = set()

    filtered_trades = _filter_trades_by_date(normalized_trades, start, end)
    if not filtered_trades.empty:
        used_trade_datetimes = list(filtered_trades["trade_datetime"])
        trades = _trades_frame_to_records(filtered_trades)
        for _, row in _last_rows_by_symbol(filtered_trades).iterrows():
            symbol = row["symbol"]
            fallback_price = _to_float(row.get("csv_last_price"))
            if symbol and fallback_price is not None:
                current_prices[symbol] = fallback_price
                price_details[symbol] = make_price_detail(
                    fallback_price,
                    CSV_FALLBACK_SOURCE,
                    row.get("trade_datetime"),
                    is_fallback=True,
                )
                price_fallback_symbols.add(symbol)

    for _, row in df.iterrows():
        section = str(_get(row, "section", "type", "category") or "").strip().lower()
        symbol = _normalize_symbol(_get(row, "symbol", "ticker", "underlying"))
        if not symbol:
            continue

        quantity = _to_float(_get(row, "position", "position quantity", "ending quantity", "actual position"))
        if quantity is not None:
            positions[symbol] = quantity

        current_price = _to_float(_get(row, "current price", "mark price", "close price", "last price"))
        if current_price is not None:
            current_prices[symbol] = current_price
            price_details[symbol] = make_price_detail(
                current_price,
                "Regular close price",
                _get(row, "date", "date/time", "as of date"),
                is_fallback=False,
            )
            price_fallback_symbols.discard(symbol)
        market_value = _to_float(_get(row, "market value", "value", "position value"))
        if market_value is not None:
            position_market_values[symbol] = market_value

        equity = _to_float(_get(row, "net liquidation", "net liquidation value", "actual equity", "equity"))
        if equity is not None:
            actual_equity = equity

    if actual_equity is None:
        actual_equity = _estimate_equity_from_positions_and_cash(position_market_values, positions, current_prices, pd.DataFrame())

    return {
        "data_source": "CSV",
        "actual_equity": actual_equity,
        "positions": [{"symbol": symbol, "quantity": quantity} for symbol, quantity in positions.items()],
        "trades": trades,
        "current_prices": current_prices,
        "price_details": price_details,
        "price_fallback_symbols": sorted(price_fallback_symbols),
        "period_start": start,
        "period_end": end,
        "trades_used": len(trades),
        "first_trade_date_used": min(used_trade_datetimes).date() if used_trade_datetimes else None,
        "last_trade_date_used": max(used_trade_datetimes).date() if used_trade_datetimes else None,
        "parsed_trade_min_date": min(all_trade_datetimes).date() if all_trade_datetimes else None,
        "parsed_trade_max_date": csv_max_date,
        "trades_columns": list(df.columns),
        "trades_preview": normalized_trades.head(20).to_dict("records"),
    }


def _first_price_detail(symbol, *detail_maps):
    symbol = _normalize_symbol(symbol)
    for details in detail_maps:
        if not details:
            continue
        detail = _normalize_price_detail(details.get(symbol) or details.get(symbol.upper()) or details.get(symbol.lower()))
        if detail.get("price") is not None:
            return detail
    return None


def _normalize_price_detail(value):
    if isinstance(value, dict):
        price = _to_float(value.get("price"))
        return {
            "price": price,
            "price_source": value.get("price_source") or value.get("source"),
            "price_time": _format_price_time(value.get("price_time") or value.get("time")),
            "is_fallback": bool(value.get("is_fallback")),
        }
    price = _to_float(value)
    return {
        "price": price,
        "price_source": None,
        "price_time": None,
        "is_fallback": False,
    }


def _format_price_time(value):
    if _is_missing(value):
        return None
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.isoformat(sep=" ", timespec="seconds")
    return str(value)


def normalize_ibkr_trades_df(trades):
    if trades is None or getattr(trades, "empty", True):
        return pd.DataFrame(
            columns=[
                "trade_datetime",
                "symbol",
                "side",
                "quantity",
                "price",
                "commission",
                "currency",
                "csv_last_price",
            ]
        )

    df = trades.copy()
    df.columns = [_clean_column_name(column) for column in df.columns]

    quantity_raw = _numeric_series(_first_column(df, "quantity"))
    trade_datetime = pd.to_datetime(
        _first_column(df, "date/time", "date", "trade date"),
        errors="coerce",
    )
    price = _numeric_series(_first_column(df, "t. price", "trade price", "price"))
    close_price = _numeric_series(_first_column(df, "c. price", "close price", "current price", "mark price", "last price"))
    price = price.fillna(close_price)
    commission = _numeric_series(_first_column(df, "comm/fee", "commission", "commissions", "fees", "ib commission")).fillna(0.0)
    side_source = _first_column(df, "side", "buy/sell", "action")
    side = side_source.map(_normalize_side) if side_source is not None else pd.Series("", index=df.index, dtype="object")
    inferred_side = quantity_raw.map(lambda value: "BUY" if pd.notna(value) and value > 0 else ("SELL" if pd.notna(value) and value < 0 else ""))
    side = side.where(side.isin(["BUY", "SELL"]), inferred_side)

    normalized = pd.DataFrame(
        {
            "trade_datetime": trade_datetime,
            "symbol": _first_column(df, "symbol", "ticker", "underlying").map(_normalize_symbol)
            if _first_column(df, "symbol", "ticker", "underlying") is not None
            else pd.Series("", index=df.index, dtype="object"),
            "side": side,
            "quantity": quantity_raw.abs(),
            "price": price,
            "commission": commission,
            "currency": _first_column(df, "currency", "cur")
            if _first_column(df, "currency", "cur") is not None
            else pd.Series(None, index=df.index, dtype="object"),
            "proceeds": _numeric_series(_first_column(df, "proceeds")),
            "realized_pnl": _numeric_series(_first_column(df, "realized p/l")),
            "mtm_pnl": _numeric_series(_first_column(df, "mtm p/l")),
            "csv_last_price": close_price.fillna(price),
        }
    )

    normalized = normalized[
        normalized["trade_datetime"].notna()
        & normalized["symbol"].astype(bool)
        & normalized["side"].isin(["BUY", "SELL"])
        & normalized["quantity"].notna()
        & (normalized["quantity"] != 0)
        & normalized["price"].notna()
    ].copy()
    normalized["trade_datetime"] = normalized["trade_datetime"].dt.to_pydatetime()
    return normalized.reset_index(drop=True)


def _filter_trades_by_date(trades, start, end):
    if trades is None or trades.empty:
        return pd.DataFrame()
    trade_dates = pd.to_datetime(trades["trade_datetime"], errors="coerce").dt.date
    mask = pd.Series(True, index=trades.index)
    if start is not None:
        mask &= trade_dates >= start
    if end is not None:
        mask &= trade_dates <= end
    return trades[mask].copy()


def _trades_frame_to_records(trades):
    records = []
    for _, row in trades.iterrows():
        trade = {
            "trade_datetime": row["trade_datetime"],
            "symbol": row["symbol"],
            "side": row["side"],
            "quantity": _to_float(row["quantity"]),
            "price": _to_float(row["price"]),
            "commission": _to_float(row["commission"]) or 0.0,
            "currency": None if _is_missing(row.get("currency")) else row.get("currency"),
            "time": row["trade_datetime"],
        }
        records.append(trade)
    return records


def _last_rows_by_symbol(trades):
    if trades is None or trades.empty:
        return pd.DataFrame()
    ordered = trades.sort_values("trade_datetime")
    return ordered.drop_duplicates("symbol", keep="last")


def _clean_frame(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()
    cleaned = frame.copy()
    cleaned.columns = [_clean_column_name(column) for column in cleaned.columns]
    return cleaned


def _extract_actual_equity(nav_frame):
    if nav_frame is None or nav_frame.empty:
        return None

    preferred_columns = ("total", "ending value", "net liquidation", "net liquidation value", "net asset value", "value", "equity")
    rows = _rows_latest_first(nav_frame)
    for _, row in rows:
        for column in preferred_columns:
            value = _to_float(_get(row, column))
            if value is not None:
                return value

    for _, row in rows:
        for value in row:
            number = _to_float(value)
            if number is not None:
                return number

    return None


def _datetime_in_bounds(value, start, end):
    if start is None and end is None:
        return True
    if value is None:
        return False
    if getattr(value, "tzinfo", None) is not None:
        value = value.replace(tzinfo=None)
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _datetime_in_date_bounds(value, start, end):
    if start is None and end is None:
        return True
    if value is None:
        return False
    value_date = value.date() if isinstance(value, datetime) else value
    if start is not None and value_date < start:
        return False
    if end is not None and value_date > end:
        return False
    return True


def _standardize_trade_row(row):
    row_date = _parse_datetime(_get(row, "trade_datetime", "date", "datetime", "time", "trade date", "date/time"))
    quantity_raw = _to_float(_get(row, "quantity", "qty", "shares"))
    side = _normalize_side(_get(row, "side", "buy/sell", "action"))
    if side not in {"BUY", "SELL"} and quantity_raw is not None:
        if quantity_raw > 0:
            side = "BUY"
        elif quantity_raw < 0:
            side = "SELL"
    return {
        "trade_datetime": row_date,
        "symbol": _normalize_symbol(_get(row, "symbol", "ticker", "underlying")),
        "side": side,
        "quantity": abs(quantity_raw or 0.0),
        "price": _to_float(_get(row, "price", "trade price", "proceeds price", "t. price", "c. price")),
        "commission": _to_float(_get(row, "commission", "commissions", "ib commission", "comm/fee", "fees")) or 0.0,
        "currency": _get(row, "currency", "cur"),
    }


def _extract_trade_datetimes(trades_frame):
    dates = []
    if trades_frame is None or trades_frame.empty:
        return dates
    for _, row in trades_frame.iterrows():
        row_date = _parse_datetime(_get(row, "trade_datetime", "date", "datetime", "time", "trade date", "date/time"))
        if row_date is not None:
            dates.append(row_date)
    return dates


def _row_is_trade(row):
    section = str(_get(row, "section", "type", "category") or "").strip().lower()
    if section in {"trade", "trades"}:
        return True
    return _has_any(row, "buy/sell", "side", "action") or (
        _has_any(row, "date/time", "date", "trade date")
        and _has_any(row, "quantity")
        and _has_any(row, "t. price", "trade price", "price")
    )


def _estimate_equity_from_positions_and_cash(position_market_values, positions, current_prices, cash_frame):
    position_total = 0.0
    has_position_value = False
    for symbol, market_value in (position_market_values or {}).items():
        if market_value is not None:
            position_total += market_value
            has_position_value = True

    if not has_position_value:
        for symbol, quantity in (positions or {}).items():
            price = _to_float((current_prices or {}).get(symbol))
            if price is not None:
                position_total += (_to_float(quantity) or 0.0) * price
                has_position_value = True

    cash_total = _extract_cash_total(cash_frame)
    if not has_position_value and cash_total is None:
        return None
    return position_total + (cash_total or 0.0)


def _extract_cash_total(cash_frame):
    if cash_frame is None or cash_frame.empty:
        return None
    preferred_columns = (
        "ending cash",
        "ending settled cash",
        "ending value",
        "total",
        "cash",
        "value",
    )
    rows = _rows_latest_first(cash_frame)
    selected = []
    latest_date = None
    dated_rows = []
    for idx, row in rows:
        row_date = _parse_datetime(_get(row, "date", "date/time", "period"))
        if row_date is not None:
            dated_rows.append((idx, row, row_date.date()))
    if dated_rows:
        latest_date = max(item[2] for item in dated_rows)
        selected = [(idx, row) for idx, row, row_date in dated_rows if row_date == latest_date]
    else:
        selected = rows

    total = 0.0
    found = False
    for _, row in selected:
        for column in preferred_columns:
            value = _to_float(_get(row, column))
            if value is not None:
                total += value
                found = True
                break
    return total if found else None


def _rows_latest_first(frame):
    rows = []
    for idx, row in frame.iterrows():
        row_date = _parse_datetime(_get(row, "date", "date/time", "period", "as of date"))
        rows.append((idx, row, row_date))
    if any(row_date is not None for _, _, row_date in rows):
        rows.sort(key=lambda item: item[2] or datetime.min, reverse=True)
    else:
        rows.reverse()
    return [(idx, row) for idx, row, _ in rows]


def _clean_column_name(column):
    return str(column or "").strip().lower()


def _get(row, *names):
    for name in names:
        key = _clean_column_name(name)
        if key in row.index:
            value = row[key]
            if not _is_missing(value):
                return value
    return None


def _first_column(df, *names):
    if df is None or df.empty:
        return None
    for name in names:
        key = _clean_column_name(name)
        if key in df.columns:
            return df[key]
    return None


def _numeric_series(series):
    if series is None:
        return pd.Series(dtype="float64")
    return series.map(_to_float)


def _has_any(row, *names):
    return any(_clean_column_name(name) in row.index for name in names)


def _normalize_symbol(value):
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _normalize_side(value):
    side = str(value or "").strip().upper()
    if side in {"BOT", "BUY", "BOUGHT", "买入"}:
        return "BUY"
    if side in {"SLD", "SELL", "SOLD", "卖出"}:
        return "SELL"
    return side


def _to_float(value):
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if math.isnan(value) else float(value)
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("$", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _parse_datetime(value):
    if _is_missing(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _is_missing(value):
    try:
        return pd.isna(value)
    except (TypeError, ValueError):
        return value is None
