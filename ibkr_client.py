from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import sys

import nest_asyncio

nest_asyncio.apply()


PERIOD_DAYS = {
    "1 Day": 1,
    "1 Week": 7,
    "1 Month": 30,
}


def period_bounds(period_label, start_date=None, end_date=None, now=None):
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
    return now - timedelta(days=PERIOD_DAYS.get(period_label, 1)), now


class IBKRConnectionError(RuntimeError):
    """Raised when IBKR read-only data is not available."""


def ensure_event_loop():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def get_ibkr_debug_info(host="127.0.0.1", port=7497, client_id=19):
    try:
        import ib_insync

        ib_insync_status = "ok"
        ib_insync_version = getattr(ib_insync, "__version__", "unknown")
    except ImportError as exc:
        ib_insync_status = f"ImportError: {exc}"
        ib_insync_version = "unavailable"
    except Exception as exc:
        ib_insync_status = f"import failed: {exc}"
        ib_insync_version = "unavailable"

    try:
        loop = ensure_event_loop()
        event_loop_status = f"ok: running={loop.is_running()}, closed={loop.is_closed()}"
    except Exception as exc:
        event_loop_status = f"unavailable: {exc}"

    return [
        {"Field": "sys.executable", "Value": sys.executable},
        {"Field": "ib_insync import status", "Value": ib_insync_status},
        {"Field": "ib_insync version", "Value": ib_insync_version},
        {"Field": "event loop status", "Value": event_loop_status},
        {"Field": "host", "Value": host},
        {"Field": "port", "Value": port},
        {"Field": "clientId", "Value": client_id},
    ]


class IBKRReadOnlyClient:
    def __init__(self, host="127.0.0.1", port=7497, client_id=19, timeout=5):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self._ib = None

    def connect(self):
        try:
            from ib_insync import IB, Stock
        except ImportError as exc:
            raise IBKRConnectionError("ib_insync is not installed.") from exc

        ensure_event_loop()
        ib = IB()
        try:
            ensure_event_loop()
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=self.timeout)
        except Exception as exc:
            raise IBKRConnectionError("TWS/Gateway is not connected") from exc
        self._ib = ib
        return ib

    def disconnect(self):
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None

    def load_snapshot(self, period_label, start_date=None, end_date=None):
        ib = self.connect()
        try:
            positions = self._get_positions(ib)
            trades = self._get_trades(ib, period_label, start_date=start_date, end_date=end_date)
            symbols = sorted({item["symbol"] for item in positions} | {item["symbol"] for item in trades})
            current_price_details = self._get_current_price_details(ib, symbols)
            return {
                "data_source": "IBKR",
                "actual_equity": self._get_net_liquidation(ib),
                "positions": positions,
                "trades": trades,
                "current_prices": {
                    symbol: detail["price"]
                    for symbol, detail in current_price_details.items()
                    if detail.get("price") is not None
                },
                "price_details": current_price_details,
            }
        finally:
            self.disconnect()

    def _get_net_liquidation(self, ib):
        ensure_event_loop()
        for item in ib.accountSummary():
            if getattr(item, "tag", "") == "NetLiquidation" and getattr(item, "currency", "") in ("USD", "BASE", ""):
                try:
                    return float(item.value)
                except (TypeError, ValueError):
                    continue
        raise IBKRConnectionError("NetLiquidation was not available from IBKR.")

    def _get_positions(self, ib):
        rows = []
        ensure_event_loop()
        if hasattr(ib, "reqPositions"):
            positions = ib.reqPositions()
        else:
            positions = ib.positions()
        for position in positions:
            contract = getattr(position, "contract", None)
            symbol = str(getattr(contract, "symbol", "") or "").upper()
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "quantity": float(getattr(position, "position", 0) or 0),
                }
            )
        return rows

    def _get_trades(self, ib, period_label, start_date=None, end_date=None):
        try:
            from ib_insync import ExecutionFilter
        except ImportError as exc:
            raise IBKRConnectionError("ib_insync ExecutionFilter is not available.") from exc

        start, end = period_bounds(period_label, start_date=start_date, end_date=end_date)
        execution_filter = ExecutionFilter(time=start.strftime("%Y%m%d %H:%M:%S"))
        ensure_event_loop()
        fills = ib.reqExecutions(execution_filter)
        rows = []
        for fill in fills:
            execution = getattr(fill, "execution", None)
            contract = getattr(fill, "contract", None)
            commission_report = getattr(fill, "commissionReport", None)
            symbol = str(getattr(contract, "symbol", "") or "").upper()
            side = str(getattr(execution, "side", "") or "").upper()
            if side == "BOT":
                side = "BUY"
            elif side == "SLD":
                side = "SELL"
            execution_time = getattr(execution, "time", None)
            if getattr(execution_time, "tzinfo", None) is not None:
                execution_time = execution_time.replace(tzinfo=None)
            if execution_time and end and execution_time > end:
                continue
            if symbol and side in {"BUY", "SELL"}:
                rows.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(float(getattr(execution, "shares", 0) or 0)),
                        "price": float(getattr(execution, "price", 0) or 0),
                        "commission": abs(float(getattr(commission_report, "commission", 0) or 0)),
                        "time": execution_time,
                    }
                )
        return rows

    def _get_current_prices(self, ib, symbols):
        return {
            symbol: detail["price"]
            for symbol, detail in self._get_current_price_details(ib, symbols).items()
            if detail.get("price") is not None
        }

    def _get_current_price_details(self, ib, symbols):
        try:
            from ib_insync import Stock
        except ImportError as exc:
            raise IBKRConnectionError("ib_insync Stock contract is not available.") from exc

        prices = {}
        for symbol in symbols:
            contract = Stock(symbol, "SMART", "USD")
            try:
                ensure_event_loop()
                ib.qualifyContracts(contract)
                ensure_event_loop()
                ticker = ib.reqMktData(contract, "", False, False)
                ensure_event_loop()
                ib.sleep(1)
                detail = self._price_detail_from_ticker(symbol, ticker)
                if detail.get("price") is not None:
                    prices[symbol] = detail
                ensure_event_loop()
                ib.cancelMktData(contract)
            except Exception:
                prices[symbol] = {
                    "price": None,
                    "price_source": "IBKR snapshot unavailable",
                    "price_time": None,
                    "is_fallback": False,
                }
        return prices

    def _price_detail_from_ticker(self, symbol, ticker):
        price_time = getattr(ticker, "time", None) or getattr(ticker, "rtTime", None)
        for attr_name, source in (
            ("plprice", "IBKR snapshot plprice"),
            ("plPrice", "IBKR snapshot plprice"),
            ("last", "IBKR snapshot last"),
        ):
            price = _finite_float(getattr(ticker, attr_name, None))
            if price is not None:
                return {
                    "price": price,
                    "price_source": source,
                    "price_time": _format_price_time(price_time),
                    "is_fallback": False,
                }

        bid = _finite_float(getattr(ticker, "bid", None))
        ask = _finite_float(getattr(ticker, "ask", None))
        if bid is not None and ask is not None:
            return {
                "price": (bid + ask) / 2,
                "price_source": "IBKR bid/ask midpoint",
                "price_time": _format_price_time(price_time),
                "is_fallback": False,
            }

        return {
            "price": None,
            "price_source": "IBKR snapshot unavailable",
            "price_time": _format_price_time(price_time),
            "is_fallback": False,
        }


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _format_price_time(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)
