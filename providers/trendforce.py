"""TrendForce news retrieval and source fallback orchestration."""

import feedparser
import requests

from services.news_normalization import (
    _build_trendforce_item,
    _extract_trendforce_date,
    _trendforce_items_from_regex,
    _trendforce_items_from_soup,
)


def get_trendforce_news(limit=20, track_api_call_fn=None):
    if track_api_call_fn is not None:
        track_api_call_fn("trendforce_news")
    limit = min(int(limit or 10), 10)
    headers = {"User-Agent": "Mozilla/5.0"}
    chinese_urls = [
        "https://www.trendforce.cn",
        "https://www.trendforce.cn/presscenter/news",
        "https://www.trendforce.cn/presscenter/news/Semiconductors",
        "https://www.trendforce.cn/presscenter",
    ]
    english_urls = [
        "https://www.trendforce.com/presscenter/news",
        "https://www.trendforce.com/presscenter/news/Semiconductors",
        "https://www.trendforce.com/presscenter/rss.html",
    ]

    def fetch_html_items(url, homepage=False):
        response = requests.get(url, headers=headers, timeout=6)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        soup_items = _trendforce_items_from_soup(response.text, url, homepage=homepage)
        return soup_items if soup_items is not None else _trendforce_items_from_regex(response.text, url)

    for index, url in enumerate(chinese_urls):
        try:
            items = fetch_html_items(url, homepage=index == 0)
            if items:
                return items[:limit]
        except Exception:
            continue

    for url in english_urls:
        try:
            response = requests.get(url, headers=headers, timeout=6)
            response.raise_for_status()
            if url.endswith("rss.html"):
                feed = feedparser.parse(response.content)
                items = []
                for entry in feed.entries[:limit]:
                    published_date = _extract_trendforce_date(entry.get("published") or entry.get("updated") or "")
                    item = _build_trendforce_item(
                        entry.get("title") or "",
                        entry.get("link") or url,
                        published_date,
                        entry.get("category") or "Semiconductors",
                        entry.get("summary") or entry.get("description") or entry.get("title") or "",
                    )
                    if item:
                        items.append(item)
                if items:
                    return items[:limit]
            else:
                response.encoding = response.apparent_encoding or response.encoding
                soup_items = _trendforce_items_from_soup(response.text, url, homepage=False)
                items = soup_items if soup_items is not None else _trendforce_items_from_regex(response.text, url)
                if items:
                    return items[:limit]
        except Exception:
            continue
    return []
