from __future__ import annotations

from datetime import datetime, timedelta


PERIOD_DAYS = {
    "1 Day": 1,
    "1 Week": 7,
    "1 Month": 30,
}


class IBKRConnectionError(RuntimeError):
    """Raised when IBKR read-only data is not available."""


class IBKRReadOnlyClient:
    def __init__(self, host="127.0.0.1", port=7497, client_id=19, timeout=5):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self._ib = None

    def connect(self):
        try:
            from ib_insync import IB
        except Exception as exc:
            raise IBKRConnectionError("ib_insync is not installed.") from exc

        ib = IB()
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=self.timeout)
        except Exception as exc:
            raise IBKRConnectionError(f"Could not connect to IBKR: {exc}") from exc
        self._ib = ib
        return ib

    def disconnect(self):
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None

    def load_snapshot(self, period_label):
        ib = self.connect()
        try:
            positions = self._get_positions(ib)
            trades = self._get_trades(ib, period_label)
            symbols = sorted({item["symbol"] for item in positions} | {item["symbol"] for item in trades})
            return {
                "actual_equity": self._get_net_liquidation(ib),
                "positions": positions,
                "trades": trades,
                "current_prices": self._get_current_prices(ib, symbols),
            }
        finally:
            self.disconnect()

    def _get_net_liquidation(self, ib):
        for item in ib.accountSummary():
            if getattr(item, "tag", "") == "NetLiquidation" and getattr(item, "currency", "") in ("USD", "BASE", ""):
                try:
                    return float(item.value)
                except (TypeError, ValueError):
                    continue
        raise IBKRConnectionError("NetLiquidation was not available from IBKR.")

    def _get_positions(self, ib):
        rows = []
        for position in ib.positions():
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

    def _get_trades(self, ib, period_label):
        try:
            from ib_insync import ExecutionFilter
        except Exception as exc:
            raise IBKRConnectionError("ib_insync ExecutionFilter is not available.") from exc

        start = datetime.now() - timedelta(days=PERIOD_DAYS.get(period_label, 1))
        execution_filter = ExecutionFilter(time=start.strftime("%Y%m%d %H:%M:%S"))
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
            if symbol and side in {"BUY", "SELL"}:
                rows.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(float(getattr(execution, "shares", 0) or 0)),
                        "price": float(getattr(execution, "price", 0) or 0),
                        "commission": abs(float(getattr(commission_report, "commission", 0) or 0)),
                        "time": getattr(execution, "time", None),
                    }
                )
        return rows

    def _get_current_prices(self, ib, symbols):
        try:
            from ib_insync import Stock
        except Exception as exc:
            raise IBKRConnectionError("ib_insync Stock contract is not available.") from exc

        prices = {}
        for symbol in symbols:
            contract = Stock(symbol, "SMART", "USD")
            try:
                ib.qualifyContracts(contract)
                ticker = ib.reqMktData(contract, "", False, False)
                ib.sleep(1)
                price = ticker.marketPrice()
                if price is None or price != price:
                    price = getattr(ticker, "close", None)
                if price is not None and price == price:
                    prices[symbol] = float(price)
                ib.cancelMktData(contract)
            except Exception:
                prices[symbol] = None
        return prices
