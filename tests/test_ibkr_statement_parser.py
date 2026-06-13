import io

import pytest

from ibkr_statement_parser import parse_ibkr_activity_statement_csv


def test_sectioned_csv_with_different_column_counts_does_not_error():
    csv_text = """Statement,Header,Field,Value
Trades,Header,Asset Category,Currency,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
Trades,Data,Stocks,USD,NVDA,2026-06-12 10:00:00,10,BUY,100,-1
Open Positions,Header,Asset Category,Currency,Symbol,Quantity,Close Price
Open Positions,Data,Stocks,USD,NVDA,15,120
Cash Report,Header,Currency,Starting Cash,Ending Cash
Cash Report,Data,USD,1000,1200
Net Asset Value,Header,Currency,Total
Net Asset Value,Data,USD,10000
"""

    parsed = parse_ibkr_activity_statement_csv(io.StringIO(csv_text))

    assert len(parsed["trades"]) == 1
    assert len(parsed["positions"]) == 1
    assert len(parsed["cash"]) == 1
    assert len(parsed["nav"]) == 1
    assert "Trades" in parsed["detected_section_names"]
    assert "Trades" in parsed["recognized_section_names"]


def test_trades_section_can_parse_header_and_data_rows():
    csv_text = """Trades,Header,Asset Category,Currency,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
Trades,Data,Stocks,USD,NVDA,2026-06-12 10:00:00,10,BUY,100,-1
"""

    with pytest.warns(RuntimeWarning):
        parsed = parse_ibkr_activity_statement_csv(csv_text.encode("utf-8-sig"))

    trade = parsed["trades"].iloc[0].to_dict()
    assert trade["Symbol"] == "NVDA"
    assert trade["Quantity"] == "10"
    assert trade["Buy/Sell"] == "BUY"
    assert trade["T. Price"] == "100"


def test_open_positions_section_can_parse_header_and_data_rows():
    csv_text = """Open Positions,Header,Asset Category,Currency,Symbol,Quantity,Close Price,Value,Unrealized P/L
Open Positions,Data,Stocks,USD,MU,7,80,560,20
"""

    with pytest.warns(RuntimeWarning):
        parsed = parse_ibkr_activity_statement_csv(io.StringIO(csv_text))

    position = parsed["positions"].iloc[0].to_dict()
    assert position["Symbol"] == "MU"
    assert position["Quantity"] == "7"
    assert position["Close Price"] == "80"


def test_missing_section_returns_empty_dataframe_and_warning():
    csv_text = """Trades,Header,Symbol,Quantity,Buy/Sell,T. Price
Trades,Data,NVDA,10,BUY,100
"""

    with pytest.warns(RuntimeWarning) as warnings:
        parsed = parse_ibkr_activity_statement_csv(io.StringIO(csv_text))

    messages = [str(item.message) for item in warnings]
    assert any("Open Positions" in message for message in messages)
    assert len(parsed["trades"]) == 1
    assert parsed["positions"].empty
    assert parsed["nav"].empty
    assert parsed["cash"].empty


def test_chinese_section_names_can_parse_header_and_data_rows():
    csv_text = """交易,Header,Asset Category,Currency,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
交易,Data,Stocks,USD,NVDA,2026-06-12 10:00:00,10,BUY,100,-1
持仓,Header,Asset Category,Currency,Symbol,Quantity,Close Price
持仓,Data,Stocks,USD,NVDA,15,120
现金报告,Header,Currency,Starting Cash,Ending Cash
现金报告,Data,USD,1000,1200
资产净值,Header,Currency,Total
资产净值,Data,USD,10000
已实现与未实现盈亏,Header,Symbol,Realized P/L,Unrealized P/L
已实现与未实现盈亏,Data,NVDA,10,20
"""

    parsed = parse_ibkr_activity_statement_csv(io.StringIO(csv_text))

    assert len(parsed["trades"]) == 1
    assert len(parsed["positions"]) == 1
    assert len(parsed["cash"]) == 1
    assert len(parsed["nav"]) == 1
    assert len(parsed["performance"]) == 1
    assert "交易" in parsed["detected_section_names"]
    assert "Trades" in parsed["recognized_section_names"]
    assert "Open Positions" in parsed["recognized_section_names"]


def test_section_names_with_bom_spaces_and_case_variants_can_parse():
    csv_text = """\ufeff trades  , Header ,Symbol,Date/Time,Quantity,Buy/Sell,T. Price,Comm/Fee
 TRADES , Data ,NVDA,2026-06-12 10:00:00,10,BUY,100,-1
  positions , Header ,Symbol,Quantity,Close Price
 Positions , Data ,NVDA,15,120
  nav , Header ,Currency,Total
 NAV , Data ,USD,10000
  cash , Header ,Currency,Starting Cash,Ending Cash
 Cash , Data ,USD,1000,1200
"""

    parsed = parse_ibkr_activity_statement_csv(io.StringIO(csv_text))

    assert len(parsed["trades"]) == 1
    assert len(parsed["positions"]) == 1
    assert len(parsed["cash"]) == 1
    assert len(parsed["nav"]) == 1
    assert parsed["detected_section_names"][0] == "trades"
    assert set(parsed["recognized_section_names"]) >= {"Trades", "Open Positions", "Net Asset Value", "Cash Report"}
