from datetime import datetime
import io

from what_if_analysis import (
    build_what_if_analysis,
    calculate_trade_value_added,
    parse_activity_statement_csv,
)


def test_buy_contribution_calculation():
    trade = {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": 0}

    assert calculate_trade_value_added(trade, 120) == 200


def test_sell_contribution_calculation():
    trade = {"symbol": "NVDA", "side": "SELL", "quantity": 10, "price": 120, "commission": 0}

    assert calculate_trade_value_added(trade, 100) == 200


def test_commission_is_deducted():
    trade = {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": 3.5}

    assert calculate_trade_value_added(trade, 120) == 196.5


def test_multiple_symbols_are_aggregated():
    result = build_what_if_analysis(
        actual_equity=10_000,
        positions=[
            {"symbol": "NVDA", "quantity": 15},
            {"symbol": "MU", "quantity": 5},
        ],
        trades=[
            {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": 1},
            {"symbol": "NVDA", "side": "SELL", "quantity": 5, "price": 130, "commission": 1},
            {"symbol": "MU", "side": "BUY", "quantity": 5, "price": 80, "commission": 2},
        ],
        current_prices={"NVDA": 120, "MU": 90},
    )

    rows = {row["Symbol"]: row for row in result["rows"]}
    assert rows["NVDA"]["Trading Value Added"] == 248
    assert rows["MU"]["Trading Value Added"] == 48
    assert result["trading_value_added"] == 296
    assert result["no_trade_equity"] == 9704
    assert rows["NVDA"]["No-trade Position"] == 10
    assert rows["MU"]["No-trade Position"] == 0


def test_no_trades_value_added_is_zero():
    result = build_what_if_analysis(
        actual_equity=10_000,
        positions=[{"symbol": "NVDA", "quantity": 15}],
        trades=[],
        current_prices={"NVDA": 120},
    )

    assert result["trading_value_added"] == 0
    assert result["no_trade_equity"] == 10_000
    assert result["rows"][0]["Trading Value Added"] == 0


def test_csv_fallback_data_parsing():
    csv_text = """Section,Date,Symbol,Side,Quantity,Price,Commission,Position,Current Price,Net Liquidation
Trade,2026-06-12,NVDA,BUY,10,100,1,15,120,10000
Trade,2026-06-11,MU,SELL,5,90,2,7,80,10000
Position,2026-06-13,NVDA,,,,,15,120,10000
Position,2026-06-13,MU,,,,,7,80,10000
"""

    parsed = parse_activity_statement_csv(
        io.StringIO(csv_text),
        period_label="1 Week",
        now=datetime(2026, 6, 13),
    )

    assert parsed["actual_equity"] == 10_000
    assert parsed["current_prices"] == {"NVDA": 120, "MU": 80}
    assert {"symbol": "NVDA", "quantity": 15} in parsed["positions"]
    assert {"symbol": "MU", "quantity": 7} in parsed["positions"]
    assert parsed["trades"] == [
        {"symbol": "NVDA", "side": "BUY", "quantity": 10.0, "price": 100.0, "commission": 1.0, "time": datetime(2026, 6, 12)},
        {"symbol": "MU", "side": "SELL", "quantity": 5.0, "price": 90.0, "commission": 2.0, "time": datetime(2026, 6, 11)},
    ]
