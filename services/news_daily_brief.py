"""Deterministic event preparation and one-call AI generation for daily highlights."""

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
    "数据中心", "晶圆", "光刻", "刻蚀", "沉积", "检测", "先进封装", "存储",
)

EVENT_KEYWORDS = {
    "earnings": ("earnings", "revenue", "guidance", "财报", "营收", "指引"),
    "orders": ("order", "booking", "订单"),
    "capex": ("capex", "capital expenditure", "investment", "资本开支", "投资"),
    "demand": ("demand", "需求"),
    "supply": ("supply", "shortage", "inventory", "供给", "短缺", "库存"),
    "price": ("price", "pricing", "价格"),
    "capacity": ("capacity", "expansion", "fab", "产能", "扩产"),
    "regulation": ("regulation", "export restriction", "export control", "监管", "出口限制"),
    "launch": ("launch", "release", "product", "发布", "产品"),
    "deal": ("acquisition", "partnership", "merger", "收购", "合作", "并购"),
    "hbm": ("hbm",),
    "dram": ("dram",),
    "nand": ("nand",),
    "gpu": ("gpu",),
    "asic": ("asic",),
    "foundry": ("foundry", "晶圆代工"),
    "packaging": ("cowos", "advanced packaging", "先进封装"),
    "equipment": ("lithography", "etch", "deposition", "inspection", "光刻", "刻蚀", "沉积", "检测"),
}

TICKER_ENTITY_TERMS = {
    "NVDA": ("nvda", "nvidia", "英伟达"),
    "MU": ("micron", "美光"),
    "SNDK": ("sandisk", "闪迪"),
    "TSM": ("tsm", "tsmc", "taiwan semiconductor", "台积电"),
    "AMD": ("amd", "advanced micro devices", "超威"),
    "AVGO": ("avgo", "broadcom", "博通"),
    "INTC": ("intc", "intel", "英特尔"),
    "ASML": ("asml",),
    "AMAT": ("amat", "applied materials", "应用材料"),
    "LRCX": ("lrcx", "lam research", "泛林"),
    "KLAC": ("klac", "kla", "科磊"),
    "MRVL": ("mrvl", "marvell", "迈威尔"),
    "MSFT": ("msft", "microsoft", "微软"),
    "META": ("meta", "facebook", "脸书"),
    "GOOG": ("goog", "google", "alphabet", "谷歌"),
    "GOOGL": ("googl", "google", "alphabet", "谷歌"),
    "AMZN": ("amzn", "amazon", "aws", "亚马逊"),
    "AAPL": ("aapl", "apple", "苹果"),
    "SKHYV": ("skhyv", "sk hynix", "sk海力士", "海力士"),
}

LOW_INFORMATION_PHRASES = (
    "prediction:", "price target", "could reach", "can reach", "stock price",
    "stock could", "continue to soar", "better buy", "clear winner", "futures slump",
    "stocks slide", "shares slide", "shares surge", "buy this stock", "sell this stock",
    "stock to buy", "market is missing", "motley fool", "股价预测", "目标价",
)

FACTUAL_EVENT_TERMS = {"earnings", "orders", "capex", "capacity", "regulation", "launch", "deal"}

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
        parsed = None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
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


def _contains_term(text, term):
    if re.fullmatch(r"[a-z0-9.+-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _supported_tickers(item):
    text = " ".join(str(item.get(key) or "") for key in ("title", "summary")).lower()
    related = item.get("related_tickers")
    if isinstance(related, str):
        related_values = related.split(",")
    elif isinstance(related, (list, tuple, set)):
        related_values = related
    elif related is None:
        related_values = []
    else:
        related_values = [related]
    values = [item.get("ticker"), *related_values]
    supported = []
    for value in values:
        ticker = str(value or "").strip().upper()
        if not ticker or ticker in supported:
            continue
        terms = TICKER_ENTITY_TERMS.get(ticker, (ticker.lower(),))
        if any(_contains_term(text, term.lower()) for term in terms):
            supported.append(ticker)
    return supported


def normalize_daily_brief_candidates(items) -> list[dict]:
    """Return fresh unified candidates and retain only text-supported tickers."""
    if not isinstance(items, (list, tuple)):
        return []
    candidates = []
    for item in items:
        normalized = _normalized_view(item)
        if not normalized.get("title"):
            continue
        supported = _supported_tickers(normalized)
        primary = str(normalized.get("ticker") or "").strip().upper()
        normalized["ticker"] = primary if primary in supported else None
        normalized["related_tickers"] = supported
        candidates.append(normalized)
    return candidates


def _candidate_text(item):
    return " ".join(str(item.get(key) or "") for key in (
        "title", "summary", "category",
    )).lower()


def _is_low_information(item):
    text = " ".join(str(item.get(key) or "") for key in (
        "title", "summary", "publisher", "source",
    )).lower()
    return any(phrase in text for phrase in LOW_INFORMATION_PHRASES)


def _event_terms(item):
    text = _candidate_text(item)
    return {
        key for key, variants in EVENT_KEYWORDS.items()
        if any(_contains_term(text, variant) for variant in variants)
    }


def _entity_terms(item):
    text = _candidate_text(item)
    entities = set(item.get("related_tickers") or [])
    for ticker, terms in TICKER_ENTITY_TERMS.items():
        if any(_contains_term(text, term.lower()) for term in terms):
            entities.add(ticker)
    return entities


def filter_technology_semiconductor_news(items) -> list[dict]:
    """Keep explicit industry news and remove low-information ticker mismatches."""
    candidates = normalize_daily_brief_candidates(items)
    result = []
    for item in candidates:
        text = _candidate_text(item)
        relevance = sum(_contains_term(text, keyword) for keyword in TECHNOLOGY_KEYWORDS)
        low_information = _is_low_information(item)
        has_factual_event = bool(_event_terms(item) & FACTUAL_EVENT_TERMS)
        if relevance and not (low_information and not has_factual_event):
            result.append(item)
    return result


def _normalized_title(value):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(value or "").lower()).strip()


def _title_tokens(value):
    normalized = _normalized_title(value)
    if re.search(r"[\u4e00-\u9fff]", normalized):
        compact = normalized.replace(" ", "")
        if len(compact) >= 4:
            return {compact[index:index + 3] for index in range(len(compact) - 2)}
    tokens = {token for token in normalized.split() if len(token) > 2}
    if len(tokens) <= 1:
        compact = normalized.replace(" ", "")
        if len(compact) >= 4:
            return {compact[index:index + 3] for index in range(len(compact) - 2)}
    return tokens


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


def _article_score(item, now):
    text = _candidate_text(item)
    relevance = sum(_contains_term(text, keyword) for keyword in TECHNOLOGY_KEYWORDS)
    impact = len(_event_terms(item) & {
        "earnings", "orders", "capex", "demand", "supply", "price", "capacity",
        "regulation", "launch", "deal",
    })
    ticker_count = len(item.get("related_tickers") or [])
    published = _parse_datetime(item.get("published_at"))
    recency = 0
    timestamp = float("-inf")
    if published is not None:
        age_hours = max(0.0, (now - published).total_seconds() / 3600)
        recency = 5 if age_hours <= 24 else 3 if age_hours <= 48 else 1 if age_hours <= 96 else 0
        timestamp = published.timestamp()
    provider = str(item.get("provider") or "").lower()
    penalty = 8 if _is_low_information(item) else 0
    score = (
        recency + relevance * 2 + min(impact, 5) * 2 + min(ticker_count, 3)
        + PROVIDER_RELIABILITY.get(provider, 1) - penalty
    )
    return score, timestamp, _normalized_title(item.get("title"))


def rank_daily_brief_news(items, *, now=None) -> list[dict]:
    """Rank articles deterministically before event grouping."""
    now = _parse_datetime(now) or datetime.now(timezone.utc)
    candidates = deduplicate_daily_brief_news(filter_technology_semiconductor_news(items))
    return sorted(candidates, key=lambda item: _article_score(item, now), reverse=True)


def select_daily_brief_news(items, *, max_items=40, now=None) -> list[dict]:
    """Select at most 40 ranked articles while preserving initial source diversity."""
    try:
        limit = min(40, max(0, int(max_items)))
    except (TypeError, ValueError):
        limit = 40
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


def _titles_similar(left, right):
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= 0.5


def _within_event_window(left, right):
    left_date = _parse_datetime(left.get("published_at"))
    right_date = _parse_datetime(right.get("published_at"))
    if left_date is None or right_date is None:
        return True
    return abs((left_date - right_date).total_seconds()) <= 72 * 3600


def _same_event(left, right):
    if not _within_event_window(left, right):
        return False
    if _titles_similar(left.get("title"), right.get("title")):
        return True
    shared_events = _event_terms(left) & _event_terms(right)
    shared_entities = _entity_terms(left) & _entity_terms(right)
    if shared_entities and shared_events:
        return True
    strong_topics = {"hbm", "dram", "nand", "foundry", "packaging", "equipment", "regulation"}
    return bool(shared_events & strong_topics) and len(shared_events) >= 2


def group_daily_brief_events(items, *, max_events=18, max_articles=40, now=None) -> list[dict]:
    """Group ranked articles into deterministic event candidates."""
    now_value = _parse_datetime(now) or datetime.now(timezone.utc)
    articles = select_daily_brief_news(items, max_items=max_articles, now=now_value)
    groups = []
    for article_index, article in enumerate(articles):
        target = next(
            (group for group in groups if any(_same_event(article, member) for member in group["articles"])),
            None,
        )
        if target is None:
            target = {"articles": [], "source_article_indices": []}
            groups.append(target)
        target["articles"].append(article)
        target["source_article_indices"].append(article_index)
    prepared = []
    for group in groups:
        group_articles = group["articles"]
        sources = list(dict.fromkeys(
            str(article.get("source") or article.get("provider") or "unknown")
            for article in group_articles
        ))
        tickers = list(dict.fromkeys(
            ticker for article in group_articles for ticker in article.get("related_tickers") or []
        ))
        score = max(_article_score(article, now_value)[0] for article in group_articles)
        score += min(len(group_articles) - 1, 3) * 2 + min(len(sources) - 1, 2) * 3 + min(len(tickers), 3)
        prepared.append({
            "event_title": group_articles[0].get("title"),
            "articles": group_articles,
            "source_article_indices": group["source_article_indices"],
            "sources": sources,
            "related_tickers": tickers,
            "article_count": len(group_articles),
            "score": score,
        })
    prepared.sort(
        key=lambda group: (group["score"], group["article_count"], _normalized_title(group["event_title"])),
        reverse=True,
    )
    try:
        limit = min(18, max(0, int(max_events)))
    except (TypeError, ValueError):
        limit = 18
    return prepared[:limit]


def daily_brief_fingerprint(items) -> str:
    """Build a stable fingerprint from selected article content."""
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


def _prompt_event_payload(event_groups):
    fields = ("title", "summary", "source", "publisher", "published_at", "ticker", "related_tickers")
    payload = []
    for event_index, group in enumerate(event_groups):
        articles = []
        for source_index, article in zip(group["source_article_indices"], group["articles"]):
            row = {key: article.get(key) for key in fields}
            row["index"] = source_index
            row["summary"] = str(row.get("summary") or "")[:700]
            articles.append(row)
        payload.append({
            "event_candidate": event_index,
            "source_article_indices": group["source_article_indices"],
            "articles": articles,
        })
    return payload


def build_daily_brief_prompt(items, *, language="zh") -> str:
    """Request one JSON object containing dynamic, non-overlapping event highlights."""
    event_groups = items if items and isinstance(items[0], dict) and "articles" in items[0] else group_daily_brief_events(items)
    language_key = str(language or "zh").lower()
    if language_key in ("中文", "zh", "chinese"):
        language_instruction = "每条使用简体中文，目标 160–240 个中文字符，最多约 280 个中文字符。"
    elif language_key in ("es", "español", "spanish"):
        language_instruction = "Cada elemento debe estar en español y tener aproximadamente 90–150 palabras."
    else:
        language_instruction = "Each item must be in English and approximately 90–150 words."
    target = min(10, len(event_groups))
    return (
        "Return valid JSON only, with the shape {\"items\": [{\"title\": str, \"summary\": str, "
        "\"kind\": \"event\" or \"company\", \"primary_ticker\": str or null, "
        "\"related_tickers\": [str], \"source_article_indices\": [int], \"risk\": str}]}. "
        f"Create up to {target} distinct technology and semiconductor event or company highlights from the "
        "dynamic event candidates. When at least eight strong event candidates exist, return 8–10 items; "
        "when fewer exist, return only supported items and never invent content to reach a quota. Each item "
        "must cover a different real event. Merge duplicate reporting about the same event. Do not organize "
        "the output into fixed Market, AI, Memory, NVDA, MU, AMD, company, ticker, or provider categories. "
        "For every item explain what happened, why it matters to the industry, the supply-chain impact, and one "
        "risk or open question. Use only supplied facts and tickers. Do not copy article text, fabricate figures "
        "or price targets, or provide investment, position, buy, or sell advice. source_article_indices must refer "
        f"only to supplied article indices. {language_instruction}\n\nEvent candidates JSON:\n"
        f"{json.dumps(_prompt_event_payload(event_groups), ensure_ascii=False)}"
    )


def _strip_json_fence(text):
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _trim_summary(text, language):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    language_key = str(language or "zh").lower()
    if language_key in ("中文", "zh", "chinese") and len(cleaned) > 280:
        return cleaned[:280].rstrip("，,；;。 ") + "。"
    if language_key not in ("中文", "zh", "chinese"):
        words = cleaned.split()
        if len(words) > 150:
            return " ".join(words[:150]).rstrip(".,;: ") + "."
    return cleaned


def _text_similarity(left, right):
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def validate_daily_brief_response(text, candidates, *, language="zh") -> list[dict]:
    """Parse and validate model JSON against actual candidate article indices and tickers."""
    try:
        payload = json.loads(_strip_json_fence(text))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Daily brief response is not valid JSON.") from exc
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        raise ValueError("Daily brief response items must be a list.")
    candidate_list = normalize_daily_brief_candidates(candidates)
    validated = []
    seen_titles = []
    seen_summaries = []
    for raw in raw_items[:10]:
        if not isinstance(raw, dict):
            raise ValueError("Daily brief item must be an object.")
        title = str(raw.get("title") or "").strip()
        summary = _trim_summary(raw.get("summary"), language)
        if not title or not summary:
            raise ValueError("Daily brief item title and summary are required.")
        if any(_normalized_title(title) == _normalized_title(value) or _text_similarity(title, value) >= 0.8 for value in seen_titles):
            raise ValueError("Daily brief response contains duplicate items.")
        if any(_text_similarity(summary, value) >= 0.75 for value in seen_summaries):
            raise ValueError("Daily brief response contains duplicate items.")
        indices = raw.get("source_article_indices")
        if not isinstance(indices, list) or not indices:
            raise ValueError("Daily brief item must reference source articles.")
        unique_indices = []
        for value in indices:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(candidate_list):
                raise ValueError("Daily brief item references an invalid source article.")
            if value not in unique_indices:
                unique_indices.append(value)
        referenced = [candidate_list[index] for index in unique_indices]
        allowed_tickers = {
            ticker for article in referenced for ticker in article.get("related_tickers") or []
        }
        primary = raw.get("primary_ticker")
        primary = str(primary).strip().upper() if primary not in (None, "") else None
        related = []
        for value in raw.get("related_tickers") or []:
            ticker = str(value or "").strip().upper()
            if ticker and ticker not in related:
                related.append(ticker)
        if primary and primary not in allowed_tickers:
            raise ValueError("Daily brief item contains a ticker absent from its source articles.")
        if any(ticker not in allowed_tickers for ticker in related):
            raise ValueError("Daily brief item contains a ticker absent from its source articles.")
        if primary and primary not in related:
            related.insert(0, primary)
        sources = list(dict.fromkeys(
            str(article.get("source") or article.get("provider") or "unknown")
            for article in referenced
        ))
        validated.append({
            "title": title,
            "summary": summary,
            "kind": raw.get("kind") if raw.get("kind") in ("event", "company") else "event",
            "primary_ticker": primary,
            "related_tickers": related,
            "sources": sources,
            "article_count": len(unique_indices),
            "source_article_indices": unique_indices,
            "risk": str(raw.get("risk") or "").strip() or None,
        })
        seen_titles.append(title)
        seen_summaries.append(summary)
    if len(validated) < 3:
        raise ValueError("Daily brief response contains fewer than three valid events.")
    return validated


def validate_daily_brief_text(text, *, language="zh") -> str:
    """Retained compatibility helper for cleaning a single summary field."""
    return _trim_summary(text, language)


def _empty_result(status, *, error=None):
    return {
        "items": [],
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
    """Generate all event highlights with one structured OpenAI request."""
    generated_at = _parse_datetime(now) or datetime.now(timezone.utc)
    selected = select_daily_brief_news(items, max_items=40, now=generated_at)
    event_groups = group_daily_brief_events(selected, max_events=18, max_articles=40, now=generated_at)
    if len(event_groups) < 3:
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
            messages=[{"role": "user", "content": build_daily_brief_prompt(event_groups, language=language)}],
        )
        highlights = validate_daily_brief_response(
            response.choices[0].message.content,
            selected,
            language=language,
        )
    except Exception:
        result = _empty_result("error", error="Daily brief generation failed.")
        result["candidate_titles"] = [group.get("event_title") for group in event_groups[:5]]
        return result
    used_indices = list(dict.fromkeys(
        index for highlight in highlights for index in highlight["source_article_indices"]
    ))
    used_articles = [selected[index] for index in used_indices]
    sources = list(dict.fromkeys(
        source for highlight in highlights for source in highlight.get("sources") or []
    ))
    tickers = list(dict.fromkeys(
        ticker for highlight in highlights for ticker in highlight.get("related_tickers") or []
    ))
    dates = [parsed for parsed in (_parse_datetime(item.get("published_at")) for item in used_articles) if parsed]
    return {
        "items": highlights,
        "status": "ok",
        "articles_used": len(used_articles),
        "sources_used": sources,
        "tickers_covered": tickers,
        "generated_at": generated_at.isoformat(),
        "data_date": max(dates).date().isoformat() if dates else None,
        "candidate_titles": [],
        "error": None,
    }
