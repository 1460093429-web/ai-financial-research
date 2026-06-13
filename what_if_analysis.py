from __future__ import annotations

from datetime import datetime, timedelta
import io
import math

import pandas as pd


PERIOD_DAYS = {
    "1 Day": 1,
    "1 Week": 7,
    "1 Month": 30,
}


def period_start(period_label, now=None):
    now = now or datetime.now()
    return now - timedelta(days=PERIOD_DAYS.get(period_label, 1))


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
        return quantity * (current_price - trade_price) - commission
    if side == "SELL":
        return quantity * (trade_price - current_price) - commission
    return 0.0


def build_what_if_analysis(actual_equity, positions, trades, current_prices):
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
    rows = []
    total_value_added = 0.0

    for symbol in symbols:
        actual_position = position_map.get(symbol, 0.0)
        no_trade_position = actual_position
        symbol_value_added = 0.0
        symbol_trades = trades_by_symbol.get(symbol, [])
        current_price = price_map.get(symbol)

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
                "Actual Position": actual_position,
                "No-trade Position": no_trade_position,
                "Current Price": current_price,
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


def parse_activity_statement_csv(file_obj, period_label=None, now=None):
    csv_bytes = file_obj.read() if hasattr(file_obj, "read") else file_obj
    if isinstance(csv_bytes, bytes):
        csv_text = csv_bytes.decode("utf-8-sig")
    else:
        csv_text = str(csv_bytes)
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [_clean_column_name(column) for column in df.columns]

    start = period_start(period_label, now) if period_label else None
    trades = []
    positions = {}
    current_prices = {}
    actual_equity = None

    for _, row in df.iterrows():
        section = str(_get(row, "section", "type", "category") or "").strip().lower()
        symbol = _normalize_symbol(_get(row, "symbol", "ticker", "underlying"))
        if not symbol:
            continue

        row_date = _parse_datetime(_get(row, "date", "datetime", "time", "trade date"))
        if section in {"trade", "trades"} or _has_any(row, "buy/sell", "side", "action"):
            if start and row_date and row_date < start:
                continue
            side = _normalize_side(_get(row, "side", "buy/sell", "action"))
            if side in {"BUY", "SELL"}:
                trades.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(_to_float(_get(row, "quantity", "qty", "shares")) or 0.0),
                        "price": _to_float(_get(row, "price", "trade price", "proceeds price")),
                        "commission": abs(_to_float(_get(row, "commission", "commissions", "ib commission")) or 0.0),
                        "time": row_date,
                    }
                )

        quantity = _to_float(_get(row, "position", "position quantity", "ending quantity", "actual position"))
        if quantity is not None:
            positions[symbol] = quantity

        current_price = _to_float(_get(row, "current price", "mark price", "close price", "last price"))
        if current_price is not None:
            current_prices[symbol] = current_price

        equity = _to_float(_get(row, "net liquidation", "net liquidation value", "actual equity", "equity"))
        if equity is not None:
            actual_equity = equity

    return {
        "actual_equity": actual_equity,
        "positions": [{"symbol": symbol, "quantity": quantity} for symbol, quantity in positions.items()],
        "trades": trades,
        "current_prices": current_prices,
    }


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


def _has_any(row, *names):
    return any(_clean_column_name(name) in row.index for name in names)


def _normalize_symbol(value):
    if _is_missing(value):
        return ""
    return str(value).strip().upper()


def _normalize_side(value):
    side = str(value or "").strip().upper()
    if side in {"BOT", "BUY", "BOUGHT"}:
        return "BUY"
    if side in {"SLD", "SELL", "SOLD"}:
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
