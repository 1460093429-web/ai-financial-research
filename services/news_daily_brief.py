"""Deterministic preparation and AI generation for one daily technology brief."""

from datetime import datetime, timezone
import hashlib
import json
import re

from services.news_schema import normalize_news_item


TECHNOLOGY_KEYWORDS = (
    "ai chip", "artificial intelligence", "gpu", "cpu", "asic", "accelerator",
    "data center", "datacenter", "cloud capex", "capital expenditure",
    "semiconductor", "chip", "foundry", "wafer", "lithography", "etch",
    "deposition", "inspection", "advanced packaging", "cowos", "hbm", "dram",
    "nand", "memory", "export control", "芯片", "半导体", "人工智能", "算力",
    "数据中心", "晶圆", "光刻", "刻蚀", "沉积", "先进封装", "存储",
)

IMPACT_KEYWORDS = (
    "revenue", "earnings", "order", "demand", "supply", "capacity", "capex",
    "investment", "launch", "regulation", "restriction", "export", "产能", "订单",
    "需求", "供给", "营收", "资本开支", "投资", "监管", "出口", "发布",
)

PROVIDER_RELIABILITY = {"trendforce": 3, "fmp": 2, "yahoo": 2}


def _parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_view(item):
    if not isinstance(item, dict):
        return normalize_news_item({})
    embedded = item.get("_normalized")
    if isinstance(embedded, dict):
        base = normalize_news_item(item)
        for key, value in embedded.items():
            if key in base:
                base[key] = value
        return base
    return normalize_news_item(item)


def normalize_daily_brief_candidates(items) -> list[dict]:
    """Return fresh unified candidate dictionaries from legacy or envelope items."""
    if not isinstance(items, (list, tuple)):
        return []
    candidates = []
    for item in items:
        normalized = _normalized_view(item)
        if not normalized.get("title"):
            continue
        normalized["related_tickers"] = list(normalized.get("related_tickers") or [])
        candidates.append(normalized)
    return candidates


def _candidate_text(item):
    return " ".join(str(item.get(key) or "") for key in (
        "title", "summary", "category", "ticker", "related_tickers",
    )).lower()


def filter_technology_semiconductor_news(items) -> list[dict]:
    """Keep candidates with an explicit technology or semiconductor signal."""
    candidates = normalize_daily_brief_candidates(items)
    return [
        item for item in candidates
        if any(keyword in _candidate_text(item) for keyword in TECHNOLOGY_KEYWORDS)
    ]


def _normalized_title(value):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").lower()).strip()


def deduplicate_daily_brief_news(items) -> list[dict]:
    """Deduplicate in order by URL, falling back to a normalized title."""
    candidates = normalize_daily_brief_candidates(items)
    seen = set()
    result = []
    for item in candidates:
        url = str(item.get("url") or "").strip().lower()
        key = ("url", url) if url else ("title", _normalized_title(item.get("title")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _ranking_key(item, now):
    text = _candidate_text(item)
    relevance = sum(keyword in text for keyword in TECHNOLOGY_KEYWORDS)
    impact = sum(keyword in text for keyword in IMPACT_KEYWORDS)
    ticker_count = len(item.get("related_tickers") or [])
    published = _parse_datetime(item.get("published_at"))
    recency = 0
    timestamp = float("-inf")
    if published is not None:
        age_hours = max(0.0, (now - published).total_seconds() / 3600)
        recency = 4 if age_hours <= 24 else 2 if age_hours <= 48 else 0
        timestamp = published.timestamp()
    provider = str(item.get("provider") or "").lower()
    return (
        recency + relevance * 2 + min(impact, 4) + min(ticker_count, 3)
        + PROVIDER_RELIABILITY.get(provider, 1),
        timestamp,
        _normalized_title(item.get("title")),
    )


def rank_daily_brief_news(items, *, now=None) -> list[dict]:
    """Rank deterministically by relevance, impact, recency, and source quality."""
    now = _parse_datetime(now) or datetime.now(timezone.utc)
    candidates = deduplicate_daily_brief_news(filter_technology_semiconductor_news(items))
    return sorted(candidates, key=lambda item: _ranking_key(item, now), reverse=True)


def select_daily_brief_news(items, *, max_items=8, now=None) -> list[dict]:
    """Select a bounded, source-diverse set while preserving ranking priority."""
    try:
        limit = max(0, int(max_items))
    except (TypeError, ValueError):
        limit = 8
    ranked = rank_daily_brief_news(items, now=now)
    if not limit:
        return []
    selected = []
    selected_ids = set()
    seen_sources = set()
    for item in ranked:
        source = str(item.get("source") or item.get("provider") or "unknown").lower()
        if source in seen_sources:
            continue
        selected.append(item)
        selected_ids.add(id(item))
        seen_sources.add(source)
        if len(selected) >= limit:
            return selected
    for item in ranked:
        if id(item) not in selected_ids:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def daily_brief_fingerprint(items) -> str:
    """Build a stable fingerprint from only the selected news content."""
    payload = [
        {
            "title": item.get("title"), "summary": item.get("summary"),
            "url": item.get("url"), "source": item.get("source"),
            "published_at": item.get("published_at"),
            "ticker": item.get("ticker"), "related_tickers": item.get("related_tickers") or [],
        }
        for item in normalize_daily_brief_candidates(items)
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_daily_brief_prompt(items, *, language="zh") -> str:
    """Build a bounded prompt containing only necessary normalized fields."""
    language_key = str(language or "zh").lower()
    if language_key in ("中文", "zh", "chinese"):
        language_instruction = "使用简体中文，目标 180–260 个中文字符，最多约 320 个中文字符。"
    elif language_key in ("es", "español", "spanish"):
        language_instruction = "Escribe en español, aproximadamente 110–170 palabras."
    else:
        language_instruction = "Write in English, approximately 110–170 words."
    fields = (
        "title", "summary", "source", "publisher", "published_at", "ticker", "related_tickers",
    )
    payload = [{key: item.get(key) for key in fields} for item in normalize_daily_brief_candidates(items)]
    return (
        "Create exactly one combined Technology & Semiconductor Daily Brief using only the supplied news. "
        "Do not create market, provider, company, or ticker sections; specifically do not create separate "
        "Market, NVDA, MU, AMD, Yahoo, FMP, or TrendForce summaries. Use one paragraph or at most two short "
        "paragraphs, remove repetition, explain the most important industry drivers and one principal risk, "
        "and do not provide investment, trading, position, buy, or sell advice. Do not invent facts, forecasts, "
        "or price targets absent from the supplied news. If sources conflict, use cautious wording. "
        f"{language_instruction}\n\nNews JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def validate_daily_brief_text(text, *, language="zh") -> str:
    """Return cleaned model text or an empty value; reject ticker-section output."""
    cleaned = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if not cleaned:
        return ""
    prohibited_heading = re.compile(
        r"(?im)^\s*(market|nvda|mu|amd|yahoo|fmp|trendforce|市场摘要|市场|英伟达|美光)\s*[:：#-]"
    )
    if prohibited_heading.search(cleaned):
        raise ValueError("Daily brief must be one combined industry summary.")
    language_key = str(language or "zh").lower()
    if language_key in ("中文", "zh", "chinese") and len(cleaned) > 320:
        cleaned = cleaned[:320].rstrip("，,；;。 ") + "。"
    return cleaned


def _empty_result(status, *, error=None):
    return {
        "brief": None,
        "status": status,
        "articles_used": 0,
        "sources_used": [],
        "tickers_covered": [],
        "generated_at": None,
        "data_date": None,
        "candidate_titles": [],
        "error": error,
    }


def generate_daily_brief(items, *, language="zh", client_factory=None, model="gpt-4o-mini", now=None):
    """Generate one structured brief result through a supplied OpenAI client factory."""
    generated_at = _parse_datetime(now) or datetime.now(timezone.utc)
    selected = select_daily_brief_news(items, max_items=8, now=generated_at)
    if not selected:
        return _empty_result("empty")
    if client_factory is None:
        return _empty_result("missing_key")
    try:
        client = client_factory()
    except ValueError:
        return _empty_result("missing_key")
    except Exception:
        return _empty_result("error", error="Daily brief generation failed.")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_daily_brief_prompt(selected, language=language)}],
        )
        brief = validate_daily_brief_text(response.choices[0].message.content, language=language)
        if not brief:
            raise ValueError("empty response")
    except Exception:
        result = _empty_result("error", error="Daily brief generation failed.")
        result["candidate_titles"] = [item.get("title") for item in selected[:3]]
        return result
    sources = list(dict.fromkeys(str(item.get("source") or item.get("provider") or "unknown") for item in selected))
    tickers = list(dict.fromkeys(
        ticker
        for item in selected
        for ticker in ([item.get("ticker")] + list(item.get("related_tickers") or []))
        if ticker
    ))
    dates = [parsed for parsed in (_parse_datetime(item.get("published_at")) for item in selected) if parsed]
    return {
        "brief": brief,
        "status": "ok",
        "articles_used": len(selected),
        "sources_used": sources,
        "tickers_covered": tickers,
        "generated_at": generated_at.isoformat(),
        "data_date": max(dates).date().isoformat() if dates else None,
        "candidate_titles": [],
        "error": None,
    }
