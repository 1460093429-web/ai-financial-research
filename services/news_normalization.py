"""Pure normalization helpers for already-retrieved Yahoo news items."""

from datetime import datetime
import html
import re
from urllib.parse import urljoin


def _format_yfinance_datetime(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value).isoformat(timespec="seconds") + "Z"
    return str(value)


def _extract_yfinance_url(item, content):
    canonical_url = content.get("canonicalUrl") if isinstance(content, dict) else None
    click_url = content.get("clickThroughUrl") if isinstance(content, dict) else None
    if isinstance(canonical_url, dict) and canonical_url.get("url"):
        return canonical_url.get("url")
    if isinstance(click_url, dict) and click_url.get("url"):
        return click_url.get("url")
    return item.get("link") or item.get("url")


def _normalize_yfinance_news_item(item, ticker):
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    title = content.get("title") or item.get("title")
    if not title:
        return None
    related_tickers = content.get("finance") or item.get("relatedTickers") or item.get("tickers") or [ticker]
    if isinstance(related_tickers, dict):
        related_tickers = related_tickers.get("stockTickers") or related_tickers.get("tickers") or [ticker]
    if not isinstance(related_tickers, (list, tuple)):
        related_tickers = [ticker]
    related_tickers = [str(symbol).upper() for symbol in related_tickers if symbol]
    if ticker not in related_tickers:
        related_tickers.insert(0, ticker)
    return {
        "title": title,
        "text": content.get("summary") or item.get("summary") or "",
        "published_date": _format_yfinance_datetime(
            content.get("pubDate") or item.get("providerPublishTime") or item.get("published")
        ),
        "url": _extract_yfinance_url(item, content),
        "publisher": provider.get("displayName") or content.get("providerName") or item.get("publisher"),
        "source": "Yahoo/yfinance",
        "ticker": ticker,
        "related_tickers": ", ".join(dict.fromkeys(related_tickers)),
    }


def _match_trendforce_ticker(title, summary):
    text = f"{title or ''} {summary or ''}".lower()
    keyword_map = (
        ("MU", ("micron", "\u7f8e\u5149", "dram", "hbm", "nand", "\u5b58\u50a8\u5668", "\u8bb0\u5fc6\u4f53", "\u5185\u5b58")),
        ("SNDK", ("sandisk", "\u95ea\u8fea", "nand", "flash", "ssd", "\u95ea\u5b58")),
        ("NVDA", ("nvidia", "\u82f1\u4f1f\u8fbe", "gpu", "ai\u670d\u52a1\u5668", "ai server", "\u52a0\u901f\u5668")),
        ("TSM", ("tsmc", "\u53f0\u79ef\u7535", "\u6676\u5706\u4ee3\u5de5", "\u5148\u8fdb\u5236\u7a0b", "wafer", "foundry")),
        ("LITE", ("lumentum", "\u5149\u6a21\u5757", "\u5149\u901a\u4fe1", "\u5149\u6536\u53d1\u5668", "\u5149\u5b66", "photonics", "transceiver")),
        ("RKLB", ("\u536b\u661f", "\u592a\u7a7a", "\u706b\u7bad", "satellite", "space", "rocket")),
    )
    for ticker, keywords in keyword_map:
        if any(keyword.lower() in text for keyword in keywords):
            return ticker
    return "SEMI"


def _clean_trendforce_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_trendforce_date(text):
    text = _clean_trendforce_text(text)
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    match = re.search(
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(20\d{2})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }[month_name.lower()]
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _is_trendforce_article_url(url):
    return re.search(r"/presscenter/news/\d{8}-\d+\.html", url or "", re.IGNORECASE) is not None


def _extract_trendforce_category(text):
    text = _clean_trendforce_text(text)
    for category in ("\u534a\u5bfc\u4f53", "\u65b0\u5174\u79d1\u6280", "Semiconductors", "Emerging Technologies"):
        if category in text:
            return category
    return "\u4ea7\u4e1a\u6d1e\u5bdf"


def _build_trendforce_item(title, url, published_date="", category="", summary=""):
    title = _clean_trendforce_text(title)
    summary = _clean_trendforce_text(summary) or title
    if not title or not url:
        return None
    ticker = _match_trendforce_ticker(title, summary)
    return {
        "title": title,
        "publishedDate": published_date or "",
        "published_date": published_date or "",
        "category": category or "\u4ea7\u4e1a\u6d1e\u5bdf",
        "site": "TrendForce",
        "source": "TrendForce",
        "publisher": "TrendForce\u96c6\u90a6\u54a8\u8be2",
        "ticker": ticker,
        "related_ticker": ticker,
        "related_tickers": ticker,
        "summary": summary,
        "text": summary,
        "url": url,
        "sentiment": "\u4e2d\u6027",
        "credibility": "TrendForce",
    }


def _trendforce_items_from_soup(page_html, base_url, homepage=False):
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None

    soup = BeautifulSoup(page_html, "html.parser")
    roots = []
    if homepage:
        for heading in soup.find_all(["h2", "h3"], string=re.compile(r"\u4ea7\u4e1a\u6d1e\u5bdf")):
            node = heading.parent
            while node and getattr(node, "name", None) not in ("body", "html"):
                article_links = [
                    link for link in node.find_all("a", href=True)
                    if _is_trendforce_article_url(urljoin(base_url, link.get("href")))
                ]
                if len(article_links) >= 3:
                    roots = [node]
                    break
                node = node.parent
            if roots:
                break
    if not roots:
        roots = [soup]

    items = []
    seen = set()
    for root in roots:
        for link in root.find_all("a", href=True):
            title = _clean_trendforce_text(link.get("title") or link.get_text(" ", strip=True))
            href = link.get("href")
            url = urljoin(base_url, href)
            if not _is_trendforce_article_url(url):
                continue
            if not title or len(title) < 8:
                continue
            if "trendforce." not in url.lower() and href.startswith(("http://", "https://")):
                continue
            if not re.search(r"/presscenter|/news|/article|/insight|NewsID=|id=", url, re.IGNORECASE):
                if not re.search(r"TrendForce|集邦|DRAM|HBM|NAND|半导体|晶圆|存储|记忆体|内存|AI", title, re.IGNORECASE):
                    continue
            nearby = ""
            parent = link
            for _ in range(3):
                parent = getattr(parent, "parent", None)
                if not parent:
                    break
                nearby = _clean_trendforce_text(parent.get_text(" ", strip=True))
                if len(nearby) > len(title) + 10:
                    break
            published_date = _extract_trendforce_date(nearby)
            category = _extract_trendforce_category(nearby)
            summary = nearby.replace(title, " ", 1).strip()
            summary = re.sub(r"^\W*\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\W*", "", summary).strip()
            item = _build_trendforce_item(title, url, published_date, category, summary or title)
            if item and item["url"] not in seen:
                seen.add(item["url"])
                items.append(item)
    return items


def _trendforce_items_from_regex(page_html, base_url):
    cleaned_html = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", page_html or "")
    anchors = re.findall(r"(?is)<a\b([^>]*?)href=[\"']([^\"']+)[\"']([^>]*)>(.*?)</a>", cleaned_html)
    items = []
    seen = set()
    for before, href, after, body in anchors:
        attrs = f"{before} {after}"
        title_match = re.search(r"title=[\"']([^\"']+)[\"']", attrs, re.IGNORECASE)
        title = _clean_trendforce_text(title_match.group(1) if title_match else body)
        url = urljoin(base_url, href)
        if not _is_trendforce_article_url(url):
            continue
        if not title or len(title) < 8:
            continue
        if not re.search(r"/presscenter|/news|/article|/insight|NewsID=|id=", url, re.IGNORECASE):
            if not re.search(r"TrendForce|集邦|DRAM|HBM|NAND|半导体|晶圆|存储|记忆体|内存|AI", title, re.IGNORECASE):
                continue
        anchor_start = cleaned_html.find(href)
        nearby = cleaned_html[max(0, anchor_start - 300):anchor_start + 800] if anchor_start >= 0 else body
        published_date = _extract_trendforce_date(nearby)
        item = _build_trendforce_item(title, url, published_date, _extract_trendforce_category(nearby), title)
        if item and item["url"] not in seen:
            seen.add(item["url"])
            items.append(item)
    return items
