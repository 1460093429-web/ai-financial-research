from datetime import datetime
import io

from what_if_analysis import (
    CSV_FALLBACK_SOURCE,
    PRICE_MODE_REALTIME,
    activity_statement_frames_to_what_if_data,
    build_what_if_analysis,
    calculate_trade_value_added,
    make_price_detail,
    normalize_ibkr_trades_df,
    parse_activity_statement_csv,
    price_details_to_prices,
    resolve_current_price_details,
    summarize_activity_statement_frames,
)
from ibkr_statement_parser import parse_ibkr_activity_statement_csv


def test_buy_contribution_calculation():
    trade = {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": 0}

    assert calculate_trade_value_added(trade, 120) == 200


def test_sell_contribution_calculation():
    trade = {"symbol": "NVDA", "side": "SELL", "quantity": 10, "price": 120, "commission": 0}

    assert calculate_trade_value_added(trade, 100) == 200


def test_commission_is_deducted():
    trade = {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": -3.5}

    assert calculate_trade_value_added(trade, 120) == 196.5


def test_multiple_symbols_are_aggregated():
    result = build_what_if_analysis(
        actual_equity=10_000,
        positions=[
            {"symbol": "NVDA", "quantity": 15},
            {"symbol": "MU", "quantity": 5},
        ],
        trades=[
            {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": -1},
            {"symbol": "NVDA", "side": "SELL", "quantity": 5, "price": 130, "commission": -1},
            {"symbol": "MU", "side": "BUY", "quantity": 5, "price": 80, "commission": -2},
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
        {
            "trade_datetime": datetime(2026, 6, 12),
            "symbol": "NVDA",
            "side": "BUY",
            "quantity": 10.0,
            "price": 100.0,
            "commission": 1.0,
            "currency": None,
            "time": datetime(2026, 6, 12),
        },
        {
            "trade_datetime": datetime(2026, 6, 11),
            "symbol": "MU",
            "side": "SELL",
            "quantity": 5.0,
            "price": 90.0,
            "commission": 2.0,
            "currency": None,
            "time": datetime(2026, 6, 11),
        },
    ]


def test_sectioned_activity_statement_filters_large_csv_to_selected_week():
    csv_text = """Trades,Header,Asset Category,Currency,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
Trades,Data,Stocks,USD,NVDA,2025-11-01 10:00:00,3,BUY,90,-1
Trades,Data,Stocks,USD,NVDA,2026-06-10 10:00:00,10,BUY,100,-1
Trades,Data,Stocks,USD,MU,2026-06-12 10:00:00,5,SELL,80,-1
Open Positions,Header,Asset Category,Currency,Symbol,Quantity,Close Price
Open Positions,Data,Stocks,USD,NVDA,15,120
Net Asset Value,Header,Currency,Total
Net Asset Value,Data,USD,10000
Cash Report,Header,Currency,Starting Cash,Ending Cash
Cash Report,Data,USD,1000,1200
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="1 Week",
        now=datetime(2026, 6, 13, 12, 0),
    )

    assert [trade["time"] for trade in data["trades"]] == [
        datetime(2026, 6, 10, 10, 0),
        datetime(2026, 6, 12, 10, 0),
    ]


def test_sectioned_activity_statement_filters_custom_date_range():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
Trades,Data,NVDA,2025-10-31 23:59:59,1,BUY,90,-1
Trades,Data,NVDA,2025-11-01 00:00:00,3,BUY,90,-1
Trades,Data,NVDA,2026-06-11 12:00:00,10,BUY,100,-1
Trades,Data,MU,2026-06-12 00:00:00,5,SELL,80,-1
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,15,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="Custom",
        start_date=datetime(2025, 11, 1).date(),
        end_date=datetime(2026, 6, 11).date(),
    )

    assert [trade["time"] for trade in data["trades"]] == [
        datetime(2025, 11, 1, 0, 0),
        datetime(2026, 6, 11, 12, 0),
    ]


def test_sectioned_activity_statement_summary_uses_full_csv_dates_and_counts():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,Buy/Sell,T. Price
Trades,Data,NVDA,2025-01-15 10:00:00,1,BUY,90
Trades,Data,MU,2026-06-12 10:00:00,5,SELL,80
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,15,120
Open Positions,Data,MU,7,80
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    summary = summarize_activity_statement_frames(sectioned)

    assert summary == {
        "csv_start_date": datetime(2025, 1, 15).date(),
        "csv_end_date": datetime(2026, 6, 12).date(),
        "total_trades_parsed": 2,
        "positions_parsed": 2,
    }


def test_sectioned_activity_statement_uses_csv_max_date_for_period_bounds():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,Buy/Sell,T. Price
Trades,Data,NVDA,2026-05-12 10:00:00,1,BUY,90
Trades,Data,NVDA,2026-05-13 10:00:00,2,BUY,95
Trades,Data,MU,2026-06-12 10:00:00,5,SELL,80
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,15,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="1 Month",
        now=datetime(2030, 1, 1, 12, 0),
    )

    assert data["period_start"] == datetime(2026, 5, 13).date()
    assert data["period_end"] == datetime(2026, 6, 12).date()
    assert data["trades_used"] == 2
    assert [trade["symbol"] for trade in data["trades"]] == ["NVDA", "MU"]


def test_sectioned_activity_statement_normalizes_chinese_trade_sides():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,Buy/Sell,T. Price
Trades,Data,NVDA,2026-06-11 10:00:00,1,买入,90
Trades,Data,MU,2026-06-12 10:00:00,5,卖出,80
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,15,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(sectioned, period_label="1 Week")

    assert [trade["side"] for trade in data["trades"]] == ["BUY", "SELL"]


def test_normalize_ibkr_raw_columns_and_quantity_signs():
    frame = parse_ibkr_activity_statement_csv(
        """Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Stocks,USD,NVDA,2026-06-10 10:00:00,10,100,120,-1000,-1,1000,0,200,O
Trades,Data,Order,Stocks,USD,MU,2026-06-11 10:00:00,-5,80,90,400,-0.5,500,10,-50,C
""",
        emit_warnings=False,
    )["trades"]

    normalized = normalize_ibkr_trades_df(frame)

    assert list(normalized.columns) == [
        "trade_datetime",
        "symbol",
        "side",
        "quantity",
        "price",
        "commission",
        "currency",
        "proceeds",
        "realized_pnl",
        "mtm_pnl",
        "csv_last_price",
    ]
    assert normalized.loc[0, "trade_datetime"] == datetime(2026, 6, 10, 10, 0)
    assert normalized.loc[0, "side"] == "BUY"
    assert normalized.loc[0, "quantity"] == 10
    assert normalized.loc[0, "price"] == 100
    assert normalized.loc[0, "commission"] == -1
    assert normalized.loc[1, "side"] == "SELL"
    assert normalized.loc[1, "quantity"] == 5


def test_custom_range_uses_trade_datetime_date_and_quantity_inferred_sides():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,T. Price,Comm/Fee,C. Price
Trades,Data,SNXX,2026-06-04 23:59:59,1,10,-1,11
Trades,Data,LITX,2026-06-05 00:00:00,-2,20,-1,25
Trades,Data,NVDA,2026-06-12 23:59:59,3,100,-1,120
Trades,Data,MUU,2026-06-13 00:00:00,4,30,-1,35
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,3,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="Custom",
        start_date=datetime(2026, 6, 5).date(),
        end_date=datetime(2026, 6, 12).date(),
    )

    assert data["trades_used"] == 2
    assert [trade["symbol"] for trade in data["trades"]] == ["LITX", "NVDA"]
    assert [trade["side"] for trade in data["trades"]] == ["SELL", "BUY"]


def test_sell_after_current_price_rises_is_negative_and_buy_is_positive():
    sell = {"symbol": "NVDA", "side": "SELL", "quantity": 10, "price": 100, "commission": -1}
    buy = {"symbol": "NVDA", "side": "BUY", "quantity": 10, "price": 100, "commission": -1}

    assert calculate_trade_value_added(sell, 120) == -201
    assert calculate_trade_value_added(buy, 120) == 199


def test_current_prices_include_positions_and_selected_trade_symbols_with_fallbacks():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,T. Price,Comm/Fee,C. Price
Trades,Data,SNXX,2026-06-10 10:00:00,-2,10,-1,12
Trades,Data,LITX,2026-06-11 10:00:00,-3,20,-1,25
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,5,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="Custom",
        start_date=datetime(2026, 6, 5).date(),
        end_date=datetime(2026, 6, 12).date(),
    )

    assert data["current_prices"] == {"SNXX": 12.0, "LITX": 25.0, "NVDA": 120.0}
    assert data["price_fallback_symbols"] == ["LITX", "SNXX"]


def test_sold_out_symbol_uses_realtime_price_when_available():
    csv_text = """Trades,Header,Symbol,Date/Time,Quantity,T. Price,Comm/Fee,C. Price
Trades,Data,LITX,2026-06-11 10:00:00,-3,20,-1,32.95
Open Positions,Header,Symbol,Quantity,Close Price
Open Positions,Data,NVDA,5,120
"""

    sectioned = parse_ibkr_activity_statement_csv(csv_text, emit_warnings=False)
    data = activity_statement_frames_to_what_if_data(
        sectioned,
        period_label="Custom",
        start_date=datetime(2026, 6, 5).date(),
        end_date=datetime(2026, 6, 12).date(),
    )
    symbols = {item["symbol"] for item in data["positions"] + data["trades"]} | set(data["price_details"])
    price_details = resolve_current_price_details(
        symbols,
        price_mode=PRICE_MODE_REALTIME,
        ibkr_details={"LITX": make_price_detail(41.04, "IBKR snapshot plprice", "2026-06-13 16:10:00")},
        csv_details=data["price_details"],
    )
    result = build_what_if_analysis(
        data["actual_equity"],
        data["positions"],
        data["trades"],
        price_details_to_prices(price_details),
        price_details=price_details,
    )

    rows = {row["Symbol"]: row for row in result["rows"]}
    assert rows["LITX"]["Current Price"] == 41.04
    assert rows["LITX"]["Actual Position"] == 0
    assert rows["LITX"]["No-trade Position"] == 3
    assert rows["LITX"]["price_source"] == "IBKR snapshot plprice"
    assert rows["LITX"]["is_fallback"] is False


def test_realtime_price_falls_back_to_csv_only_after_live_sources_fail():
    resolved = resolve_current_price_details(
        ["LITX"],
        price_mode=PRICE_MODE_REALTIME,
        ibkr_details={"LITX": make_price_detail(None, "IBKR snapshot unavailable")},
        yahoo_details={},
        fmp_details={},
        csv_details={"LITX": make_price_detail(32.95, CSV_FALLBACK_SOURCE, is_fallback=True)},
    )

    assert resolved["LITX"]["price"] == 32.95
    assert resolved["LITX"]["price_source"] == CSV_FALLBACK_SOURCE
    assert resolved["LITX"]["is_fallback"] is True


def test_price_source_prefers_ibkr_then_yahoo_then_fmp_then_csv():
    resolved = resolve_current_price_details(
        ["LITX", "MU", "NVDA"],
        price_mode=PRICE_MODE_REALTIME,
        ibkr_details={"LITX": make_price_detail(41.04, "IBKR snapshot plprice")},
        yahoo_details={"MU": make_price_detail(90.5, "Yahoo Finance postMarketPrice")},
        fmp_details={"NVDA": make_price_detail(120.5, "FMP quote price")},
        csv_details={
            "LITX": make_price_detail(32.95, CSV_FALLBACK_SOURCE, is_fallback=True),
            "MU": make_price_detail(80, CSV_FALLBACK_SOURCE, is_fallback=True),
            "NVDA": make_price_detail(119, CSV_FALLBACK_SOURCE, is_fallback=True),
        },
    )

    assert resolved["LITX"]["price_source"] == "IBKR snapshot plprice"
    assert resolved["MU"]["price_source"] == "Yahoo Finance postMarketPrice"
    assert resolved["NVDA"]["price_source"] == "FMP quote price"
