# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ETF_COM_DAILY_FLOWS_URL = "https://www.etf.com/sections/daily-etf-flows"
ETF_COM_WEEKLY_FLOWS_URL = "https://www.etf.com/sections/weekly-etf-flows"
ETF_COM_BASE_URL = "https://www.etf.com"
ETF_COM_BLOCKED_MESSAGE = (
    "ETF.com blocks automated requests. Paste article URL or key table rows manually."
)

DEFAULT_HIGHLIGHT_TICKERS = {
    "SMH", "SOXX", "SOXL", "DRAM", "QQQ", "IVV", "SPY", "ARKK", "IBIT", "GLD",
    "NVDA", "NVDL", "MU", "AMD", "AVGO", "TSM",
}

SEMICONDUCTOR_TICKERS = {"SMH", "SOXX", "SOXL", "NVDA", "MU", "AMD", "AVGO", "TSM", "DRAM"}
AI_GROWTH_TICKERS = {"QQQ", "ARKK", "SMH", "SOXX", "SOXL", "NVDA", "AMD", "AVGO"}
LEVERAGED_ETF_TICKERS = {"NVDL", "SOXL", "TQQQ", "SQQQ", "SOXS", "NVDS", "QLD", "SSO", "UPRO", "SPXU"}
BOND_TERMS = {"bond", "treasury", "fixed income", "tlt", "ief", "agg", "bnd", "lqd", "hyg"}
GOLD_TICKERS = {"GLD", "IAU"}
CRYPTO_TICKERS = {"IBIT", "FBTC", "GBTC", "BITB", "ETHA", "ETHE"}


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _request_text(url: str, timeout: int = 15) -> tuple[str | None, dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text, {"ok": True, "url": url, "status_code": response.status_code}
    except requests.RequestException as exc:
        return None, {
            "ok": False,
            "url": url,
            "error": str(exc),
            "message": ETF_COM_BLOCKED_MESSAGE,
        }


def _parse_section_articles(html: str, section: str, source_url: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    articles = []
    seen_urls = set()
    section_slug = "daily-etf-flows" if section == "Daily" else "weekly-etf-flows"

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""
        text = _clean_text(link.get_text(" "))
        if not text or len(text) < 8:
            continue
        if section_slug not in href and "/news/" not in href and "/sections/" not in href:
            continue
        if "flow" not in f"{href} {text}".lower():
            continue
        url = urljoin(ETF_COM_BASE_URL, href)
        if url in seen_urls or url.rstrip("/") == source_url.rstrip("/"):
            continue

        container = link.find_parent(["article", "li", "div", "section"]) or link.parent
        date_text = _extract_date_from_node(container)
        articles.append({
            "title": text,
            "url": url,
            "published_date": date_text,
            "section": section,
            "source_url": url,
            "provider_status": {"ok": True, "source": source_url},
        })
        seen_urls.add(url)
        if len(articles) >= limit:
            break

    return articles


def _extract_date_from_node(node) -> str:
    if not node:
        return ""
    time_tag = node.find("time") if hasattr(node, "find") else None
    if time_tag:
        return _clean_text(time_tag.get("datetime") or time_tag.get_text(" "))
    text = _clean_text(node.get_text(" ") if hasattr(node, "get_text") else node)
    patterns = [
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def fetch_etfcom_flow_articles(
    sections: Iterable[str] | None = None,
    limit: int = 5,
    fetch_article_pages: bool = True,
) -> list[dict]:
    requested = {str(item).lower() for item in (sections or ["daily", "weekly"])}
    section_urls = []
    if "daily" in requested:
        section_urls.append(("Daily", ETF_COM_DAILY_FLOWS_URL))
    if "weekly" in requested:
        section_urls.append(("Weekly", ETF_COM_WEEKLY_FLOWS_URL))

    articles: list[dict] = []
    for section, url in section_urls:
        html, status = _request_text(url)
        if not html:
            articles.append({
                "title": f"ETF.com {section} ETF Flows",
                "url": url,
                "source_url": url,
                "section": section,
                "published_date": "",
                "tables": [],
                "provider_status": status,
            })
            continue
        articles.extend(_parse_section_articles(html, section, url, max(limit, 1)))

    articles = articles[: max(int(limit or 1), 1)]
    if not fetch_article_pages:
        return articles

    enriched = []
    for article in articles:
        if not article.get("provider_status", {}).get("ok", True):
            enriched.append(article)
            continue
        detail = fetch_etfcom_article(article.get("url") or article.get("source_url"))
        merged = {**article, **{key: value for key, value in detail.items() if value not in (None, "", [])}}
        if article.get("published_date") and not detail.get("published_date"):
            merged["published_date"] = article["published_date"]
        if article.get("section"):
            merged["section"] = article["section"]
        enriched.append(merged)
    return enriched


def fetch_etfcom_article(url: str) -> dict:
    html, status = _request_text(url)
    if not html:
        return {
            "title": "",
            "url": url,
            "source_url": url,
            "tables": [],
            "provider_status": status,
        }

    metadata = parse_etfcom_article_metadata(html)
    tables = parse_etfcom_flow_tables(html)
    return {
        **metadata,
        "url": url,
        "source_url": url,
        "tables": tables,
        "provider_status": {
            "ok": True,
            "url": url,
            "table_status": "ok" if tables else "Table not found; summary based on title and subtitle only.",
        },
    }


def parse_manual_etf_flow_text(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        line = _clean_text(line)
        if not line:
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        else:
            parts = _merge_manual_csv_number_parts([part.strip() for part in line.split(",") if part.strip()])
        if len(parts) < 3:
            parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        if len(parts) < 3:
            continue

        ticker_match = re.search(r"\b[A-Z][A-Z0-9]{1,5}\b", parts[0])
        if not ticker_match:
            continue

        rows.append({
            "Ticker": ticker_match.group(0),
            "Name": parts[1] if len(parts) > 1 else "",
            "Net Flows ($, mm)": parts[2] if len(parts) > 2 else "",
            "AUM ($, mm)": parts[3] if len(parts) > 3 else "",
            "AUM % Change": parts[4] if len(parts) > 4 else "",
        })

    if not rows:
        return []
    return [{
        "title": "User-provided ETF flow rows",
        "columns": ["Ticker", "Name", "Net Flows ($, mm)", "AUM ($, mm)", "AUM % Change"],
        "rows": rows,
    }]


def _merge_manual_csv_number_parts(parts: list[str]) -> list[str]:
    if len(parts) <= 3:
        return parts
    merged = parts[:2]
    index = 2
    while index < len(parts):
        value = parts[index]
        while (
            index + 1 < len(parts)
            and re.fullmatch(r"[-$]?\d{1,3}", value.replace("$", ""))
            and re.fullmatch(r"\d{3}(?:\.\d+)?%?", parts[index + 1])
        ):
            value = f"{value},{parts[index + 1]}"
            index += 1
        merged.append(value)
        index += 1
    return merged


def parse_etfcom_article_metadata(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    title_tag = soup.find(["h1", "title"])
    if title_tag:
        title = _clean_text(title_tag.get_text(" "))
    if not title:
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
        title = _clean_text(og_title.get("content") if og_title else "")

    description_tag = (
        soup.find("meta", property="og:description")
        or soup.find("meta", attrs={"name": "description"})
    )
    subtitle = _clean_text(description_tag.get("content") if description_tag else "")
    if not subtitle:
        subtitle_node = soup.find(["h2", "p"], class_=re.compile("dek|subtitle|description|summary", re.I))
        subtitle = _clean_text(subtitle_node.get_text(" ") if subtitle_node else "")

    author = ""
    author_tag = soup.find("meta", attrs={"name": re.compile("author", re.I)})
    if author_tag:
        author = _clean_text(author_tag.get("content"))
    if not author:
        author_node = soup.find(attrs={"rel": "author"}) or soup.find(class_=re.compile("author|byline", re.I))
        author = _clean_text(author_node.get_text(" ") if author_node else "")
        author = re.sub(r"^By\s+", "", author, flags=re.I)

    published_date = ""
    date_tag = (
        soup.find("meta", property=re.compile("published_time|modified_time", re.I))
        or soup.find("meta", attrs={"name": re.compile("date|published", re.I)})
        or soup.find("time")
    )
    if date_tag:
        published_date = _clean_text(date_tag.get("content") or date_tag.get("datetime") or date_tag.get_text(" "))
    if not published_date:
        published_date = _extract_date_from_node(soup)

    return {
        "title": title,
        "subtitle": subtitle,
        "published_date": published_date,
        "author": author,
    }


def parse_etfcom_flow_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    tables = []
    for index, table in enumerate(soup.find_all("table")):
        rows = []
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [_clean_text(cell.get_text(" ")) for cell in header_row.find_all(["th", "td"])]
        if not headers:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = [_clean_text(cell.get_text(" ")) for cell in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            row = {}
            for column_index, header in enumerate(headers):
                row[header or f"Column {column_index + 1}"] = cells[column_index] if column_index < len(cells) else ""
            rows.append(row)

        if not rows:
            continue
        tables.append({
            "title": _table_title(table) or f"Table {index + 1}",
            "columns": headers,
            "rows": rows,
        })
    return tables


def _table_title(table) -> str:
    caption = table.find("caption")
    if caption:
        return _clean_text(caption.get_text(" "))
    for previous in table.find_all_previous(["h2", "h3", "h4", "strong"], limit=4):
        text = _clean_text(previous.get_text(" "))
        if text:
            return text
    return ""


def _number_from_text(value: object) -> float | None:
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text or text in {"-", "N/A", "NA"}:
        return None
    multiplier = 1.0
    lowered = text.lower()
    if "b" in lowered:
        multiplier = 1000.0
    elif "k" in lowered:
        multiplier = 0.001
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) * multiplier if match else None


def _first_matching_key(row: dict, candidates: Iterable[str]) -> str | None:
    normalized = {str(key).strip().lower(): key for key in row}
    for candidate in candidates:
        for normalized_key, original_key in normalized.items():
            if candidate.lower() in normalized_key:
                return original_key
    return None


def _row_ticker(row: dict) -> str:
    ticker_key = _first_matching_key(row, ["ticker", "symbol"])
    value = row.get(ticker_key) if ticker_key else ""
    match = re.search(r"\b[A-Z][A-Z0-9]{1,5}\b", str(value or ""))
    return match.group(0) if match else ""


def _row_flow_value(row: dict) -> float | None:
    flow_key = _first_matching_key(row, ["net flows", "net flow", "flows", "flow"])
    if flow_key:
        return _number_from_text(row.get(flow_key))
    for value in row.values():
        number = _number_from_text(value)
        if number is not None:
            return number
    return None


def _collect_flow_candidates(tables: list[dict]) -> list[dict]:
    candidates = []
    for table in tables or []:
        table_title = table.get("title", "")
        for row in table.get("rows", []):
            ticker = _row_ticker(row)
            flow_value = _row_flow_value(row)
            if not ticker or flow_value is None:
                continue
            lowered = f"{table_title} {' '.join(str(value) for value in row.values())}".lower()
            signed_flow = flow_value
            if "redemption" in lowered or "outflow" in lowered:
                signed_flow = -abs(flow_value)
            elif "creation" in lowered or "inflow" in lowered:
                signed_flow = abs(flow_value)
            candidates.append({"ticker": ticker, "flow": signed_flow, "row": row, "table": table_title})
    return candidates


def _find_extreme_flow_rows(tables: list[dict]) -> tuple[dict | None, dict | None]:
    candidates = _collect_flow_candidates(tables)
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item["flow"]), min(candidates, key=lambda item: item["flow"])


def _find_biggest_inflow_for_tickers(tables: list[dict], tickers: set[str]) -> dict | None:
    candidates = [
        item for item in _collect_flow_candidates(tables)
        if item.get("ticker") in tickers and item.get("flow", 0) > 0
    ]
    return max(candidates, key=lambda item: item["flow"], default=None)


def _find_biggest_outflow_for_tickers(tables: list[dict], tickers: set[str]) -> dict | None:
    candidates = [
        item for item in _collect_flow_candidates(tables)
        if item.get("ticker") in tickers and item.get("flow", 0) < 0
    ]
    return min(candidates, key=lambda item: item["flow"], default=None)


def _extract_tickers_from_text(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", text or ""))


def extract_etf_flow_signals(article_data: dict, watchlist: Iterable[str] | None = None) -> dict:
    watchlist_set = {str(item).upper() for item in (watchlist or [])}
    highlight_set = DEFAULT_HIGHLIGHT_TICKERS | watchlist_set
    tables = article_data.get("tables") or []
    text_blob = " ".join([
        article_data.get("title") or "",
        article_data.get("subtitle") or "",
        " ".join(
            " ".join(str(value) for row in table.get("rows", []) for value in row.values())
            for table in tables
        ),
    ])
    tickers = _extract_tickers_from_text(text_blob)
    highlighted = sorted(tickers & highlight_set)
    watchlist_hits = sorted(tickers & watchlist_set)
    biggest_inflow, biggest_outflow = _find_extreme_flow_rows(tables)
    biggest_semiconductor_inflow = _find_biggest_inflow_for_tickers(tables, SEMICONDUCTOR_TICKERS)
    biggest_leveraged_outflow = _find_biggest_outflow_for_tickers(tables, LEVERAGED_ETF_TICKERS)
    lowered = text_blob.lower()
    themes = []
    if tickers & SEMICONDUCTOR_TICKERS or any(term in lowered for term in ["semiconductor", "chip", "dram", "ai"]):
        themes.append("Semiconductor / AI")
    if tickers & AI_GROWTH_TICKERS or "growth" in lowered:
        themes.append("Growth / Risk appetite")
    if tickers & CRYPTO_TICKERS or "bitcoin" in lowered or "crypto" in lowered:
        themes.append("Crypto")
    if tickers & GOLD_TICKERS or "gold" in lowered:
        themes.append("Gold")
    if any(term in lowered for term in BOND_TERMS):
        themes.append("Bonds")

    return {
        "tickers": sorted(tickers),
        "highlighted_tickers": highlighted,
        "watchlist_hits": watchlist_hits,
        "watchlist_hit_count": len(watchlist_hits),
        "biggest_inflow": biggest_inflow,
        "biggest_outflow": biggest_outflow,
        "biggest_semiconductor_inflow": biggest_semiconductor_inflow,
        "biggest_leveraged_outflow": biggest_leveraged_outflow,
        "semiconductor_related": bool((tickers & SEMICONDUCTOR_TICKERS) or "semiconductor" in lowered or "dram" in lowered),
        "themes": themes or ["General ETF flows"],
    }


def format_etf_flow_metric(flow_row: dict | None) -> str:
    if not flow_row:
        return ""
    ticker = flow_row.get("ticker") or "N/A"
    flow = flow_row.get("flow")
    if flow is None:
        return ticker
    abs_flow = abs(float(flow))
    if abs_flow >= 1000:
        amount = f"${abs_flow / 1000:,.2f}B"
    else:
        amount = f"${abs_flow:,.1f}M"
    if flow < 0:
        amount = f"-{amount}"
    return f"{ticker} {amount}"


def _format_flow(flow_row: dict | None) -> str:
    return format_etf_flow_metric(flow_row)


def summarize_etf_flow_article(article_data: dict, language: str = "zh") -> str:
    signals = article_data.get("signals") or extract_etf_flow_signals(article_data)
    title = article_data.get("title") or "ETF.com flows article"
    if not article_data.get("tables"):
        if language.lower().startswith("zh"):
            return "检测到 ETF.com 资金流栏目链接，但未能自动提取文章数据。"
        return "Detected an ETF.com flow link, but article data was not automatically extracted."

    inflow = _format_flow(signals.get("biggest_inflow"))
    outflow = _format_flow(signals.get("biggest_outflow"))
    semiconductor_inflow = _format_flow(signals.get("biggest_semiconductor_inflow"))
    leveraged_outflow = _format_flow(signals.get("biggest_leveraged_outflow"))
    themes = "、".join(signals.get("themes") or ["General ETF flows"])
    hits = "、".join(signals.get("watchlist_hits") or signals.get("highlighted_tickers") or [])

    if language.lower().startswith("zh"):
        emphasis = []
        if semiconductor_inflow:
            emphasis.append(f"更值得关注的是半导体相关 ETF 中 {semiconductor_inflow}，显示半导体主线资金较强。")
        if leveraged_outflow:
            emphasis.append(f"同时杠杆 ETF 中 {leveraged_outflow}，说明部分短线杠杆资金可能在降风险或获利了结。")
        if semiconductor_inflow and leveraged_outflow:
            emphasis.append("整体看，资金进入半导体和核心 ETF 的迹象较强，但短线杠杆资金并非无脑追涨。")
        elif semiconductor_inflow:
            emphasis.append("整体看，资金更偏向进入半导体方向和普通 ETF 风险资产。")
        elif leveraged_outflow:
            emphasis.append("整体看，普通 ETF 资金流需要和杠杆 ETF 降风险信号一起观察。")
        watchlist_sentence = (
            f"与观察列表或重点 ticker 的交集包括 {hits}，需要结合价格趋势、成交量、期权 GEX、PCR 和宏观利率继续验证。"
            if hits else
            "暂未识别到与观察列表或重点 ticker 的直接交集，影响更偏市场背景。"
        )
        return (
            f"ETF.com 资金流数据《{title}》显示，当前主线偏向 {themes}。"
            f"提取到的最大流入 ETF 为 {inflow or '未识别'}，最大流出 ETF 为 {outflow or '未识别'}。"
            f"{''.join(emphasis)}"
            f"{watchlist_sentence}"
            "ETF flows 只反映 ETF 申购赎回资金流，不能单独证明股价会继续上涨或下跌。"
        )

    return (
        f"ETF.com flow data '{title}' points to {themes}. "
        f"Biggest extracted inflow: {inflow or 'not identified'}; "
        f"biggest extracted outflow: {outflow or 'not identified'}. "
        f"Biggest semiconductor inflow: {semiconductor_inflow or 'not identified'}; "
        f"biggest leveraged ETF outflow: {leveraged_outflow or 'not identified'}. "
        "ETF flows reflect creations and redemptions only and should be checked against price, volume, options GEX, PCR, and rates."
    )


def build_etf_flow_news_digest(articles: list[dict], watchlist: Iterable[str] | None = None) -> dict:
    enriched = []
    warnings = []
    for article in articles or []:
        article_copy = dict(article)
        signals = extract_etf_flow_signals(article_copy, watchlist)
        article_copy["signals"] = signals
        article_copy["summary_zh"] = summarize_etf_flow_article(article_copy, language="zh")
        status = article_copy.get("provider_status") or {}
        if not status.get("ok", True) or status.get("table_status", "").startswith("Table not found"):
            warnings.append(status.get("message") or status.get("table_status") or "ETF.com provider returned incomplete data.")
        enriched.append(article_copy)

    real_data_articles = [item for item in enriched if item.get("tables")]
    latest = real_data_articles[0] if real_data_articles else {}
    all_inflows = [item["signals"].get("biggest_inflow") for item in enriched if item.get("signals")]
    all_outflows = [item["signals"].get("biggest_outflow") for item in enriched if item.get("signals")]
    all_semiconductor_inflows = [
        item["signals"].get("biggest_semiconductor_inflow") for item in enriched if item.get("signals")
    ]
    all_leveraged_outflows = [
        item["signals"].get("biggest_leveraged_outflow") for item in enriched if item.get("signals")
    ]
    all_inflows = [item for item in all_inflows if item]
    all_outflows = [item for item in all_outflows if item]
    all_semiconductor_inflows = [item for item in all_semiconductor_inflows if item]
    all_leveraged_outflows = [item for item in all_leveraged_outflows if item]

    return {
        "articles": enriched,
        "latest_article_date": latest.get("published_date") or "",
        "biggest_inflow": max(all_inflows, key=lambda item: item.get("flow", 0), default=None),
        "biggest_outflow": min(all_outflows, key=lambda item: item.get("flow", 0), default=None),
        "biggest_semiconductor_inflow": max(
            all_semiconductor_inflows, key=lambda item: item.get("flow", 0), default=None
        ),
        "biggest_leveraged_outflow": min(
            all_leveraged_outflows, key=lambda item: item.get("flow", 0), default=None
        ),
        "semiconductor_related": any(item.get("signals", {}).get("semiconductor_related") for item in enriched),
        "watchlist_hit_count": sum(item.get("signals", {}).get("watchlist_hit_count", 0) for item in enriched),
        "has_real_data": bool(real_data_articles or all_inflows or all_outflows),
        "provider_status": {"ok": not warnings, "warnings": sorted(set(filter(None, warnings)))},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
