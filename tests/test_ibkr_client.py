import threading
from types import SimpleNamespace

from ibkr_client import IBKRReadOnlyClient, ensure_event_loop, get_ibkr_debug_info


def test_ensure_event_loop_creates_loop_in_thread_without_current_loop():
    result = {}

    def worker():
        loop = ensure_event_loop()
        result["closed"] = loop.is_closed()
        result["same_loop"] = loop is ensure_event_loop()
        loop.close()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert result == {"closed": False, "same_loop": True}


def test_ibkr_debug_info_includes_required_fields():
    fields = {row["Field"] for row in get_ibkr_debug_info()}

    assert {
        "sys.executable",
        "ib_insync import status",
        "ib_insync version",
        "event loop status",
        "host",
        "port",
        "clientId",
    } <= fields


def test_ibkr_price_detail_prefers_plprice():
    ticker = SimpleNamespace(plprice=41.04, last=32.95, bid=40, ask=42)

    detail = IBKRReadOnlyClient()._price_detail_from_ticker("LITX", ticker)

    assert detail["price"] == 41.04
    assert detail["price_source"] == "IBKR snapshot plprice"


def test_ibkr_price_detail_uses_last_when_plprice_missing():
    ticker = SimpleNamespace(plprice=None, plPrice=None, last=41.04, bid=40, ask=42)

    detail = IBKRReadOnlyClient()._price_detail_from_ticker("LITX", ticker)

    assert detail["price"] == 41.04
    assert detail["price_source"] == "IBKR snapshot last"


def test_ibkr_price_detail_uses_bid_ask_midpoint_when_last_missing():
    ticker = SimpleNamespace(plprice=None, plPrice=None, last=None, bid=40, ask=42)

    detail = IBKRReadOnlyClient()._price_detail_from_ticker("LITX", ticker)

    assert detail["price"] == 41
    assert detail["price_source"] == "IBKR bid/ask midpoint"
