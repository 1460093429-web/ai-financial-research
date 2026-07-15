"""Pure presentation model for static Memory Cycle contract records."""

from datetime import date, datetime, timezone
from numbers import Real


_SECTION_ORDER = (
    "company_financials",
    "pricing_signals",
    "demand_signals",
    "supply_discipline",
    "inventory_health",
    "market_proxies",
    "unavailable_data",
)

_COMPANY_METRICS = {"company_revenue", "gross_margin", "operating_margin", "free_cash_flow_margin"}
_PRICING_METRICS = {
    "dram_price_direction",
    "nand_price_direction",
    "hbm_price_direction",
    "enterprise_ssd_price_direction",
    "client_ssd_price_direction",
    "wafer_component_price_direction",
}
_DEMAND_METRICS = {
    "ai_server_accelerator_demand",
    "hbm_demand",
    "data_center_server_demand",
    "enterprise_ssd_demand",
    "pc_smartphone_demand_direction",
    "cloud_capex_news",
    "cloud_capex_demand_proxy",
    "customer_inventory_restocking",
}
_SUPPLY_METRICS = {
    "dram_supply_direction",
    "nand_supply_direction",
    "hbm_capacity_direction",
    "advanced_packaging_capacity_direction",
    "manufacturer_expansion_plans",
    "production_cuts_or_supply_discipline",
    "node_transition_capacity_effect",
}
_INVENTORY_METRICS = {"channel_inventory", "customer_inventory"}

_TEXT = {
    "en": {
        "sections": {
            "company_financials": ("Company Financials", "Reviewed company-reported observations."),
            "pricing_signals": ("Pricing Signals", "Qualitative news signals, not direct memory price series."),
            "demand_signals": ("Demand Signals", "Qualitative demand evidence and clearly marked proxies."),
            "supply_discipline": ("Supply Discipline", "Qualitative supply and capacity evidence."),
            "inventory_health": ("Inventory Health", "Qualitative inventory evidence, not precise inventory levels."),
            "market_proxies": ("Market Proxies", "Market performance proxies; not memory fundamentals."),
            "unavailable_data": ("Unavailable Data", "Metrics without a currently verified source."),
        },
        "status": {"ok": "Available", "missing": "Missing", "stale": "Stale", "unavailable": "Unavailable"},
        "badges": {"proxy": "Proxy", "news_signal": "News signal", "fallback": "Fallback", "estimate": "Estimate", "stale": "Stale", "missing": "Missing", "unavailable": "Unavailable"},
        "values": {"improving": "Improving", "stable": "Stable", "weakening": "Weakening", "strong": "Strong", "mixed": "Mixed", "weak": "Weak", "disciplined": "Disciplined", "neutral": "Neutral", "aggressive": "Aggressive", "elevated": "Elevated", "deteriorating": "Deteriorating", "expanding": "Expanding", "contracting": "Contracting", "tightening": "Tightening", "easing": "Easing", "increasing": "Increasing", "decreasing": "Decreasing", "positive": "Positive", "negative": "Negative"},
        "warnings": {"unavailable": "{count} metrics are unavailable.", "missing": "{count} metrics are missing.", "stale": "{count} metrics are stale.", "pricing": "Pricing information is based on news signals, not direct price series.", "proxy": "Market performance metrics are proxies and do not represent memory fundamentals."},
    },
    "zh": {
        "sections": {
            "company_financials": ("公司财务", "经审阅的公司报告指标。"),
            "pricing_signals": ("价格信号", "定性新闻信号，并非内存产品直接价格序列。"),
            "demand_signals": ("需求信号", "定性需求证据及明确标注的代理指标。"),
            "supply_discipline": ("供给纪律", "定性供给与产能证据。"),
            "inventory_health": ("库存健康", "定性库存证据，并非精确库存水平。"),
            "market_proxies": ("市场代理", "市场表现代理指标，并非内存基本面。"),
            "unavailable_data": ("暂不可用数据", "当前没有可验证来源的指标。"),
        },
        "status": {"ok": "可用", "missing": "数据缺失", "stale": "已过期", "unavailable": "暂不可用"},
        "badges": {"proxy": "代理指标", "news_signal": "新闻信号", "fallback": "备用数据", "estimate": "估算", "stale": "已过期", "missing": "数据缺失", "unavailable": "暂不可用"},
        "values": {"improving": "改善", "stable": "稳定", "weakening": "走弱", "strong": "强劲", "mixed": "分化", "weak": "疲弱", "disciplined": "克制", "neutral": "中性", "aggressive": "激进", "elevated": "偏高", "deteriorating": "恶化", "expanding": "扩张", "contracting": "收缩", "tightening": "趋紧", "easing": "缓解", "increasing": "增加", "decreasing": "减少", "positive": "正面", "negative": "负面"},
        "warnings": {"unavailable": "{count} 个指标暂不可用。", "missing": "{count} 个指标数据缺失。", "stale": "{count} 个指标已过期。", "pricing": "价格信息来自新闻信号，并非直接价格序列。", "proxy": "市场表现指标属于代理指标，不代表内存基本面。"},
    },
    "es": {
        "sections": {
            "company_financials": ("Finanzas de empresas", "Observaciones empresariales revisadas."),
            "pricing_signals": ("Señales de precios", "Señales cualitativas de noticias, no series directas de precios de memoria."),
            "demand_signals": ("Señales de demanda", "Evidencia cualitativa y proxies claramente identificados."),
            "supply_discipline": ("Disciplina de oferta", "Evidencia cualitativa sobre oferta y capacidad."),
            "inventory_health": ("Salud del inventario", "Evidencia cualitativa, no niveles precisos de inventario."),
            "market_proxies": ("Proxies de mercado", "Proxies de rendimiento; no representan fundamentos de memoria."),
            "unavailable_data": ("Datos no disponibles", "Métricas sin una fuente verificada actualmente."),
        },
        "status": {"ok": "Disponible", "missing": "Faltante", "stale": "Desactualizado", "unavailable": "No disponible"},
        "badges": {"proxy": "Proxy", "news_signal": "Señal de noticias", "fallback": "Fuente alternativa", "estimate": "Estimación", "stale": "Desactualizado", "missing": "Faltante", "unavailable": "No disponible"},
        "values": {"improving": "Mejorando", "stable": "Estable", "weakening": "Debilitándose", "strong": "Fuerte", "mixed": "Mixto", "weak": "Débil", "disciplined": "Disciplinada", "neutral": "Neutral", "aggressive": "Agresiva", "elevated": "Elevado", "deteriorating": "Deteriorándose", "expanding": "Expandiéndose", "contracting": "Contrayéndose", "tightening": "Ajustándose", "easing": "Moderándose", "increasing": "Aumentando", "decreasing": "Disminuyendo", "positive": "Positivo", "negative": "Negativo"},
        "warnings": {"unavailable": "{count} métricas no están disponibles.", "missing": "Faltan {count} métricas.", "stale": "{count} métricas están desactualizadas.", "pricing": "La información de precios se basa en señales de noticias, no en series directas de precios.", "proxy": "Las métricas de rendimiento de mercado son proxies y no representan los fundamentos de memoria."},
    },
}


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed_date = date.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)


def _section_for(metric):
    if metric["status"] == "unavailable":
        return "unavailable_data"
    metric_id = metric["metric_id"]
    if metric_id in _COMPANY_METRICS:
        return "company_financials"
    if metric_id in _PRICING_METRICS:
        return "pricing_signals"
    if metric_id in _DEMAND_METRICS:
        return "demand_signals"
    if metric_id in _SUPPLY_METRICS:
        return "supply_discipline"
    if metric_id in _INVENTORY_METRICS:
        return "inventory_health"
    if metric["source_type"] == "proxy":
        return "market_proxies"
    return "unavailable_data"


def _number_text(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _metric_view(record, text):
    value = record.get("value")
    status = record.get("status") if record.get("status") in {"ok", "missing", "stale", "unavailable"} else "missing"
    if value is None and status not in {"missing", "unavailable"}:
        status = "missing"
    source_type = record.get("source_type") if record.get("source_type") in {"direct", "company_reported", "news_signal", "proxy"} else "direct"
    qualitative = isinstance(value, str) and value.casefold() in text["values"]
    if status in {"missing", "unavailable"}:
        display_value = text["status"][status]
    elif qualitative:
        display_value = text["values"][value.casefold()]
    else:
        display_value = _number_text(value)

    badge_keys = []
    if status in {"missing", "stale", "unavailable"}:
        badge_keys.append(status)
    if source_type in {"proxy", "news_signal"}:
        badge_keys.append(source_type)
    if record.get("is_fallback") is True:
        badge_keys.append("fallback")
    if record.get("is_estimate") is True:
        badge_keys.append("estimate")
    badges = [text["badges"][key] for key in badge_keys]
    source = record.get("source") if isinstance(record.get("source"), str) else ""
    notes = record.get("notes") if isinstance(record.get("notes"), str) else None
    evidence_available = (
        status in {"ok", "stale"}
        and bool(source.strip())
        and source.strip().casefold() not in {"unavailable", "unknown", "uncited"}
        and _parse_timestamp(record.get("as_of")) is not None
        and bool(notes and notes.strip())
    )
    return {
        "metric_id": record.get("metric_id") if isinstance(record.get("metric_id"), str) else "",
        "label": record.get("label") if isinstance(record.get("label"), str) else "",
        "display_value": display_value,
        "unit": record.get("unit") if isinstance(record.get("unit"), str) else None,
        "status": status,
        "status_label": text["status"][status],
        "confidence": record.get("confidence") if record.get("confidence") in {"high", "medium", "low"} else "low",
        "as_of": record.get("as_of") if isinstance(record.get("as_of"), str) else None,
        "source": source,
        "source_type": source_type,
        "is_fallback": record.get("is_fallback") is True,
        "is_estimate": record.get("is_estimate") is True,
        "staleness_days": record.get("staleness_days") if isinstance(record.get("staleness_days"), int) and not isinstance(record.get("staleness_days"), bool) else None,
        "notes": notes,
        "badge": " · ".join(badges),
        "badges": badges,
        "evidence_available": evidence_available,
    }


def build_memory_cycle_view_model(metrics, *, evaluated_at, language="zh") -> dict:
    """Build a deterministic, I/O-free view model without scoring or phase inference."""
    language = language if language in _TEXT else "en"
    text = _TEXT[language]
    source_records = metrics if isinstance(metrics, (list, tuple)) else ()
    metric_views = [_metric_view(dict(record), text) for record in source_records if isinstance(record, dict)]

    grouped = {section_id: [] for section_id in _SECTION_ORDER}
    for metric in metric_views:
        grouped[_section_for(metric)].append(metric)

    sections = []
    for section_id in _SECTION_ORDER:
        section_metrics = grouped[section_id]
        title, description = text["sections"][section_id]
        sections.append({
            "section_id": section_id,
            "title": title,
            "description": description,
            "metrics": section_metrics,
            "available_count": sum(metric["status"] == "ok" for metric in section_metrics),
            "missing_count": sum(metric["status"] == "missing" for metric in section_metrics),
            "stale_count": sum(metric["status"] == "stale" for metric in section_metrics),
            "unavailable_count": sum(metric["status"] == "unavailable" for metric in section_metrics),
        })

    status_counts = {status: sum(metric["status"] == status for metric in metric_views) for status in ("ok", "missing", "stale", "unavailable")}
    confidence_counts = {level: sum(metric["confidence"] == level for metric in metric_views) for level in ("high", "medium", "low")}
    proxy_count = sum(metric["source_type"] == "proxy" for metric in metric_views)
    news_count = sum(metric["source_type"] == "news_signal" for metric in metric_views)
    fallback_count = sum(metric["is_fallback"] for metric in metric_views)
    estimate_count = sum(metric["is_estimate"] for metric in metric_views)
    quality_summary = {
        "ok": status_counts["ok"],
        "missing": status_counts["missing"],
        "stale": status_counts["stale"],
        "unavailable": status_counts["unavailable"],
        "proxy": proxy_count,
        "news_signal": news_count,
        "fallback": fallback_count,
        "estimate": estimate_count,
        "high_confidence": confidence_counts["high"],
        "medium_confidence": confidence_counts["medium"],
        "low_confidence": confidence_counts["low"],
        "ok_count": status_counts["ok"],
        "missing_count": status_counts["missing"],
        "stale_count": status_counts["stale"],
        "unavailable_count": status_counts["unavailable"],
        "proxy_count": proxy_count,
        "news_signal_count": news_count,
        "fallback_count": fallback_count,
        "estimate_count": estimate_count,
        "high_confidence_count": confidence_counts["high"],
        "medium_confidence_count": confidence_counts["medium"],
        "low_confidence_count": confidence_counts["low"],
        "status_counts": status_counts,
        "confidence_counts": confidence_counts,
    }

    dated = [(parsed, metric["as_of"]) for metric in metric_views if (parsed := _parse_timestamp(metric["as_of"])) is not None]
    latest_as_of = max(dated, key=lambda item: item[0])[1] if dated else None
    warnings = []
    for key in ("unavailable", "missing", "stale"):
        count = status_counts[key]
        if count:
            warnings.append(text["warnings"][key].format(count=count))
    if any(metric["source_type"] == "news_signal" and metric["metric_id"] in _PRICING_METRICS for metric in metric_views):
        warnings.append(text["warnings"]["pricing"])
    if proxy_count:
        warnings.append(text["warnings"]["proxy"])

    return {
        "sections": sections,
        "quality_summary": quality_summary,
        "available_metric_count": status_counts["ok"],
        "missing_metric_count": status_counts["missing"],
        "stale_metric_count": status_counts["stale"],
        "unavailable_metric_count": status_counts["unavailable"],
        "proxy_metric_count": proxy_count,
        "news_signal_count": news_count,
        "latest_as_of": latest_as_of,
        "warnings": warnings,
        "language": language,
        "evaluated_at": evaluated_at,
    }
