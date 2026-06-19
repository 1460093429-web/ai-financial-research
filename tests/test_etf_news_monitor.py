import pytest
import requests

from etf_news_monitor import (
    ETF_COM_BLOCKED_MESSAGE,
    build_etf_flow_news_digest,
    extract_etf_flow_signals,
    fetch_etfcom_article,
    format_etf_flow_metric,
    parse_manual_etf_flow_text,
    parse_etfcom_article_metadata,
    parse_etfcom_flow_tables,
    summarize_etf_flow_article,
)


MOCK_ARTICLE_HTML = """
<html>
  <head>
    <meta property="og:title" content="Daily ETF Flows: SMH Pulls In Billions">
    <meta property="og:description" content="Semiconductor ETFs led daily creations.">
    <meta name="author" content="ETF.com Staff">
    <meta property="article:published_time" content="2026-06-18T09:30:00Z">
  </head>
  <body>
    <h1>Daily ETF Flows: SMH Pulls In Billions</h1>
    <h2>Top 10 Creations</h2>
    <table>
      <tr>
        <th>Ticker</th>
        <th>Name</th>
        <th>Net Flows ($, mm)</th>
        <th>AUM ($, mm)</th>
        <th>AUM % Change</th>
      </tr>
      <tr>
        <td>SMH</td>
        <td>VanEck Semiconductor ETF</td>
        <td>$6,900</td>
        <td>$35,000</td>
        <td>19.7%</td>
      </tr>
      <tr>
        <td>QQQ</td>
        <td>Invesco QQQ Trust</td>
        <td>$1,250</td>
        <td>$300,000</td>
        <td>0.4%</td>
      </tr>
    </table>
    <h2>Top 10 Redemptions</h2>
    <table>
      <tr>
        <th>Ticker</th>
        <th>Name</th>
        <th>Net Flows</th>
        <th>AUM</th>
        <th>% of AUM</th>
      </tr>
      <tr>
        <td>GLD</td>
        <td>SPDR Gold Shares</td>
        <td>$850</td>
        <td>$70,000</td>
        <td>1.2%</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_parse_etfcom_article_metadata_extracts_title_and_date():
    metadata = parse_etfcom_article_metadata(MOCK_ARTICLE_HTML)

    assert metadata["title"] == "Daily ETF Flows: SMH Pulls In Billions"
    assert metadata["published_date"] == "2026-06-18T09:30:00Z"
    assert metadata["author"] == "ETF.com Staff"


def test_parse_etfcom_flow_tables_extracts_top_10_creations():
    tables = parse_etfcom_flow_tables(MOCK_ARTICLE_HTML)

    assert len(tables) == 2
    assert tables[0]["title"] == "Top 10 Creations"
    assert tables[0]["rows"][0]["Ticker"] == "SMH"
    assert tables[0]["rows"][0]["Net Flows ($, mm)"] == "$6,900"


def test_extract_etf_flow_signals_identifies_tickers_and_watchlist_hits():
    article = {
        **parse_etfcom_article_metadata(MOCK_ARTICLE_HTML),
        "tables": parse_etfcom_flow_tables(MOCK_ARTICLE_HTML),
    }

    signals = extract_etf_flow_signals(article, watchlist=["NVDA", "SMH", "QQQ"])

    assert "SMH" in signals["highlighted_tickers"]
    assert "QQQ" in signals["watchlist_hits"]
    assert signals["watchlist_hit_count"] == 2
    assert signals["semiconductor_related"] is True
    assert signals["biggest_inflow"]["ticker"] == "SMH"
    assert signals["biggest_outflow"]["ticker"] == "GLD"


def test_summarize_etf_flow_article_generates_chinese_summary():
    article = {
        **parse_etfcom_article_metadata(MOCK_ARTICLE_HTML),
        "tables": parse_etfcom_flow_tables(MOCK_ARTICLE_HTML),
    }
    article["signals"] = extract_etf_flow_signals(article, watchlist=["SMH"])

    summary = summarize_etf_flow_article(article, language="zh")

    assert "ETF.com 最新资金流文章" in summary
    assert "SMH" in summary
    assert "ETF flows" in summary


def test_empty_html_does_not_crash():
    metadata = parse_etfcom_article_metadata("")
    tables = parse_etfcom_flow_tables("")
    signals = extract_etf_flow_signals({"tables": tables}, watchlist=["NVDA"])

    assert metadata["title"] == ""
    assert tables == []
    assert signals["watchlist_hit_count"] == 0


def test_missing_tables_does_not_crash_and_summary_mentions_fallback():
    article = {
        "title": "Weekly ETF Flows: Bonds Gain Assets",
        "subtitle": "Bond ETFs led the week.",
        "tables": [],
    }

    summary = summarize_etf_flow_article(article, language="zh")

    assert "表格未成功提取" in summary
    assert "Bonds" in summary


def test_build_digest_preserves_source_and_warning_for_missing_table():
    articles = [{
        "title": "Weekly ETF Flows",
        "url": "https://www.etf.com/example",
        "source_url": "https://www.etf.com/example",
        "published_date": "2026-06-18",
        "tables": [],
        "provider_status": {"ok": True, "table_status": "Table not found; summary based on title and subtitle only."},
    }]

    digest = build_etf_flow_news_digest(articles, watchlist=["SMH"])

    assert digest["articles"][0]["source_url"] == "https://www.etf.com/example"
    assert digest["provider_status"]["warnings"]


def test_network_failure_fallback_does_not_crash(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("etf_news_monitor.requests.get", raise_timeout)

    article = fetch_etfcom_article("https://www.etf.com/example")

    assert article["provider_status"]["ok"] is False
    assert article["tables"] == []
    assert "rate-limited" in article["provider_status"]["message"]


def test_summarize_etf_flow_article_generates_chinese_summary():
    article = {
        **parse_etfcom_article_metadata(MOCK_ARTICLE_HTML),
        "tables": parse_etfcom_flow_tables(MOCK_ARTICLE_HTML),
    }
    article["signals"] = extract_etf_flow_signals(article, watchlist=["SMH"])

    summary = summarize_etf_flow_article(article, language="zh")

    assert "ETF.com 资金流数据" in summary
    assert "SMH" in summary
    assert "ETF flows" in summary


def test_missing_tables_does_not_crash_and_summary_mentions_fallback():
    article = {
        "title": "Weekly ETF Flows: Bonds Gain Assets",
        "subtitle": "Bond ETFs led the week.",
        "tables": [],
    }

    summary = summarize_etf_flow_article(article, language="zh")

    assert summary == "检测到 ETF.com 资金流栏目链接，但未能自动提取文章数据。"


def test_network_failure_fallback_does_not_crash(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("etf_news_monitor.requests.get", raise_timeout)

    article = fetch_etfcom_article("https://www.etf.com/example")

    assert article["provider_status"]["ok"] is False
    assert article["tables"] == []
    assert article["provider_status"]["message"] == ETF_COM_BLOCKED_MESSAGE


def test_manual_text_table_parsing_extracts_flow_rows():
    tables = parse_manual_etf_flow_text(
        "IVV, iShares Core S&P 500 ETF, 20,444.21, 635,100, 3.2%\n"
        "SMH, VanEck Semiconductor ETF, 6,932.93, 78,937.90, 8.78%\n"
        "NVDL, GraniteShares 2x Long NVDA Daily ETF, -824.39, 5,200, -15.8%\n"
        "SOXL, Direxion Daily Semiconductor Bull 3X Shares, -270.0, 12,100, -2.2%"
    )

    assert len(tables) == 1
    assert tables[0]["rows"][0]["Ticker"] == "IVV"
    assert tables[0]["rows"][0]["Net Flows ($, mm)"] == "20,444.21"

    article = {"title": "Manual table", "tables": tables}
    signals = extract_etf_flow_signals(article, watchlist=["SMH"])
    assert signals["biggest_inflow"]["ticker"] == "IVV"
    assert signals["biggest_semiconductor_inflow"]["ticker"] == "SMH"
    assert signals["biggest_leveraged_outflow"]["ticker"] == "NVDL"
    assert signals["semiconductor_related"] is True

    digest = build_etf_flow_news_digest([{**article, "published_date": "2026-06-19"}], watchlist=["SMH"])
    assert digest["latest_article_date"] == "2026-06-19"
    assert format_etf_flow_metric(digest["biggest_inflow"]) == "IVV $20.44B"
    assert format_etf_flow_metric(digest["biggest_semiconductor_inflow"]) == "SMH $6.93B"
    assert format_etf_flow_metric(digest["biggest_leveraged_outflow"]) == "NVDL -$824.4M"

    summary = summarize_etf_flow_article(digest["articles"][0], language="zh")
    assert "半导体" in summary
    assert "杠杆" in summary
    assert "降风险" in summary


def test_manual_url_parse_failure_does_not_crash(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("etf_news_monitor.requests.get", raise_timeout)

    article = fetch_etfcom_article("https://www.etf.com/bad-url")

    assert article["source_url"] == "https://www.etf.com/bad-url"
    assert article["provider_status"]["ok"] is False
    assert article["tables"] == []


def test_blocked_request_fallback_keeps_source_link_without_fake_data(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("etf_news_monitor.requests.get", raise_timeout)

    article = fetch_etfcom_article("https://www.etf.com/sections/daily-etf-flows")
    digest = build_etf_flow_news_digest([article], watchlist=["SMH"])

    assert digest["articles"][0]["source_url"] == "https://www.etf.com/sections/daily-etf-flows"
    assert digest["has_real_data"] is False
    assert digest["biggest_inflow"] is None
    assert digest["biggest_outflow"] is None
    assert digest["latest_article_date"] == ""
    assert "N/A" not in summarize_etf_flow_article(article, language="zh")


def test_empty_data_no_crash_and_no_na_fake_summary():
    digest = build_etf_flow_news_digest([], watchlist=["SMH"])

    assert digest["articles"] == []
    assert digest["has_real_data"] is False
    assert digest["latest_article_date"] == ""
    assert digest["biggest_inflow"] is None
    assert digest["biggest_outflow"] is None
