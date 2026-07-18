"""Pure preparation and Streamlit rendering for the Memory Cycle MVP."""

from copy import deepcopy

import streamlit as st


_SECTION_TITLES = {
    "en": {
        "company_financials": "Company Financials",
        "pricing_signals": "Pricing Signals",
        "demand_signals": "Demand Signals",
        "supply_discipline": "Supply Discipline",
        "inventory_health": "Inventory Health",
        "market_proxies": "Market Proxies",
        "unavailable_data": "Unavailable Data",
    },
    "zh": {
        "company_financials": "公司财务",
        "pricing_signals": "价格信号",
        "demand_signals": "需求信号",
        "supply_discipline": "供给纪律",
        "inventory_health": "库存健康",
        "market_proxies": "市场代理",
        "unavailable_data": "暂不可用数据",
    },
    "es": {
        "company_financials": "Finanzas de empresas",
        "pricing_signals": "Señales de precios",
        "demand_signals": "Señales de demanda",
        "supply_discipline": "Disciplina de oferta",
        "inventory_health": "Salud del inventario",
        "market_proxies": "Proxies de mercado",
        "unavailable_data": "Datos no disponibles",
    },
}

_TEXT = {
    "en": {
        "title": "Memory Cycle Monitor",
        "empty": "No memory-cycle data is available.",
        "quality": "Data quality",
        "available": "Available metrics",
        "missing": "Missing metrics",
        "stale": "Stale metrics",
        "unavailable": "Unavailable metrics",
        "proxy_count": "Proxy metrics",
        "news_count": "News signals",
        "latest_as_of": "Data date",
        "status": "Status",
        "confidence": "Confidence",
        "source": "Source",
        "source_type": "Source type",
        "data_date": "Data date",
        "badge": "Badge",
        "notes": "Notes",
        "staleness_days": "Days stale",
        "no_evidence": "Complete evidence is missing",
        "proxy_note": "This is a market proxy, not direct memory-industry fundamental data.",
        "news_note": "This is a news signal, not a direct price series.",
        "not_available": "N/A",
        "statuses": {"ok": "Available", "missing": "Missing", "stale": "Stale", "unavailable": "Unavailable"},
        "badges": {"proxy": "Proxy", "news_signal": "News signal", "fallback": "Fallback", "estimate": "Estimate", "stale": "Stale", "missing": "Missing", "unavailable": "Unavailable"},
    },
    "zh": {
        "title": "存储周期监控",
        "empty": "暂无可展示的存储周期数据。",
        "quality": "数据质量",
        "available": "可用指标数量",
        "missing": "缺失指标数量",
        "stale": "过期指标数量",
        "unavailable": "暂不可用指标数量",
        "proxy_count": "代理指标数量",
        "news_count": "新闻信号数量",
        "latest_as_of": "数据日期",
        "status": "状态",
        "confidence": "可信度",
        "source": "来源",
        "source_type": "来源类型",
        "data_date": "数据日期",
        "badge": "标记",
        "notes": "备注",
        "staleness_days": "数据过期天数",
        "no_evidence": "缺少完整证据",
        "proxy_note": "这是市场代理指标，并非存储行业直接基本面数据。",
        "news_note": "这是新闻信号，并非直接价格序列。",
        "not_available": "N/A",
        "statuses": {"ok": "可用", "missing": "数据缺失", "stale": "数据过期", "unavailable": "暂不可用"},
        "badges": {"proxy": "代理指标", "news_signal": "新闻信号", "fallback": "备用数据", "estimate": "估算", "stale": "数据过期", "missing": "数据缺失", "unavailable": "暂不可用"},
    },
    "es": {
        "title": "Monitor del ciclo de memoria",
        "empty": "No hay datos disponibles del ciclo de memoria.",
        "quality": "Calidad de los datos",
        "available": "Métricas disponibles",
        "missing": "Métricas faltantes",
        "stale": "Métricas desactualizadas",
        "unavailable": "Métricas no disponibles",
        "proxy_count": "Métricas proxy",
        "news_count": "Señales de noticias",
        "latest_as_of": "Fecha de los datos",
        "status": "Estado",
        "confidence": "Confianza",
        "source": "Fuente",
        "source_type": "Tipo de fuente",
        "data_date": "Fecha de los datos",
        "badge": "Etiqueta",
        "notes": "Notas",
        "staleness_days": "Días de antigüedad",
        "no_evidence": "Falta evidencia completa",
        "proxy_note": "Este es un proxy de mercado, no un dato fundamental directo de la industria de memoria.",
        "news_note": "Esta es una señal de noticias, no una serie directa de precios.",
        "not_available": "N/D",
        "statuses": {"ok": "Disponible", "missing": "Faltante", "stale": "Desactualizado", "unavailable": "No disponible"},
        "badges": {"proxy": "Proxy", "news_signal": "Señal de noticias", "fallback": "Fuente alternativa", "estimate": "Estimación", "stale": "Desactualizado", "missing": "Faltante", "unavailable": "No disponible"},
    },
}


def _language_code(language):
    value = str(language or "").strip().casefold()
    aliases = {
        "zh": "zh",
        "zh-cn": "zh",
        "中文": "zh",
        "chinese": "zh",
        "en": "en",
        "english": "en",
        "es": "es",
        "español": "es",
        "spanish": "es",
    }
    return aliases.get(value, "en")


def build_memory_cycle_component_rows(view_model) -> dict:
    """Copy and safely shape a Phase 4.2 view model without deriving signals."""
    if not isinstance(view_model, dict):
        return {
            "sections": [],
            "quality_summary": {},
            "warnings": [],
            "latest_as_of": None,
        }

    sections = []
    source_sections = view_model.get("sections")
    if isinstance(source_sections, (list, tuple)):
        for source_section in source_sections:
            if not isinstance(source_section, dict):
                continue
            section = deepcopy(source_section)
            source_metrics = source_section.get("metrics")
            section["metrics"] = (
                [deepcopy(metric) for metric in source_metrics if isinstance(metric, dict)]
                if isinstance(source_metrics, (list, tuple))
                else []
            )
            sections.append(section)

    summary = view_model.get("quality_summary")
    warnings = view_model.get("warnings")
    rows = {
        "sections": sections,
        "quality_summary": deepcopy(summary) if isinstance(summary, dict) else {},
        "warnings": [str(item) for item in warnings if isinstance(item, str) and item.strip()]
        if isinstance(warnings, (list, tuple))
        else [],
        "latest_as_of": deepcopy(view_model.get("latest_as_of")),
    }
    for key in (
        "available_metric_count",
        "missing_metric_count",
        "stale_metric_count",
        "unavailable_metric_count",
        "proxy_metric_count",
        "news_signal_count",
    ):
        if key in view_model:
            rows[key] = deepcopy(view_model[key])
    return rows


def _summary_value(rows, summary_key, top_level_key, text):
    summary = rows.get("quality_summary", {})
    value = summary.get(summary_key)
    if not isinstance(value, int) or isinstance(value, bool):
        value = rows.get(top_level_key)
    return value if isinstance(value, int) and not isinstance(value, bool) else text["not_available"]


def _metric_display_value(metric, text, status):
    if status in {"missing", "unavailable"}:
        return text["statuses"][status]
    value = metric.get("display_value")
    if value is None:
        return text["statuses"]["missing"]
    unit = metric.get("unit")
    return f"{value} {unit}" if isinstance(unit, str) and unit.strip() else str(value)


def _metric_badges(metric, text):
    keys = []
    status = metric.get("status")
    if status in {"missing", "stale", "unavailable"}:
        keys.append(status)
    source_type = metric.get("source_type")
    if source_type in {"proxy", "news_signal"}:
        keys.append(source_type)
    if metric.get("is_fallback") is True:
        keys.append("fallback")
    if metric.get("is_estimate") is True:
        keys.append("estimate")
    if keys:
        return [text["badges"][key] for key in keys]
    badge = metric.get("badge")
    return [badge] if isinstance(badge, str) and badge.strip() else []


def render_memory_cycle_metric(metric, *, language="zh"):
    """Render one metric card without fetching or calculating data."""
    metric = metric if isinstance(metric, dict) else {}
    text = _TEXT[_language_code(language)]
    status = metric.get("status") if metric.get("status") in text["statuses"] else "missing"
    source = metric.get("source") if isinstance(metric.get("source"), str) and metric.get("source").strip() else text["not_available"]
    as_of = metric.get("as_of") if isinstance(metric.get("as_of"), str) and metric.get("as_of").strip() else text["not_available"]
    source_type = metric.get("source_type") if isinstance(metric.get("source_type"), str) and metric.get("source_type").strip() else text["not_available"]
    confidence = metric.get("confidence") if metric.get("confidence") in {"high", "medium", "low"} else text["not_available"]
    label = metric.get("label") if isinstance(metric.get("label"), str) and metric.get("label").strip() else text["not_available"]
    badges = _metric_badges(metric, text)

    with st.container(border=True):
        st.metric(label=label, value=_metric_display_value(metric, text, status))
        st.caption(f"{text['badge']}: {' · '.join(badges) if badges else text['not_available']}")
        st.caption(f"{text['status']}: {text['statuses'][status]} | {text['confidence']}: {confidence}")
        st.caption(f"{text['data_date']}: {as_of} | {text['source']}: {source}")
        st.caption(f"{text['source_type']}: {source_type}")
        if status == "stale" and isinstance(metric.get("staleness_days"), int) and not isinstance(metric.get("staleness_days"), bool):
            st.warning(f"{text['staleness_days']}: {metric['staleness_days']}")
        if source_type == "proxy":
            st.info(text["proxy_note"])
        elif source_type == "news_signal":
            st.info(text["news_note"])
        if metric.get("evidence_available") is False:
            st.warning(text["no_evidence"])
        notes = metric.get("notes") if isinstance(metric.get("notes"), str) and metric.get("notes").strip() else text["not_available"]
        with st.expander(text["notes"], expanded=False):
            st.caption(notes)


def render_memory_cycle_section(section, *, language="zh"):
    """Render one view-model section in its existing metric order."""
    section = section if isinstance(section, dict) else {}
    code = _language_code(language)
    section_id = section.get("section_id")
    title = section.get("title") if isinstance(section.get("title"), str) and section.get("title").strip() else _SECTION_TITLES[code].get(section_id, section_id or _TEXT[code]["not_available"])
    st.subheader(title)
    description = section.get("description")
    if isinstance(description, str) and description.strip():
        st.caption(description)
    metrics = section.get("metrics")
    for metric in metrics if isinstance(metrics, (list, tuple)) else ():
        render_memory_cycle_metric(metric, language=code)


def render_memory_cycle_dashboard(view_model, *, language="zh"):
    """Render the standalone Memory Cycle component from an existing view model."""
    code = _language_code(language)
    text = _TEXT[code]
    rows = build_memory_cycle_component_rows(view_model)
    st.title(text["title"])

    if not any(section.get("metrics") for section in rows["sections"]):
        st.info(text["empty"])
        return

    st.subheader(text["quality"])
    summary_items = (
        (text["available"], _summary_value(rows, "ok_count", "available_metric_count", text)),
        (text["missing"], _summary_value(rows, "missing_count", "missing_metric_count", text)),
        (text["stale"], _summary_value(rows, "stale_count", "stale_metric_count", text)),
        (text["unavailable"], _summary_value(rows, "unavailable_count", "unavailable_metric_count", text)),
        (text["proxy_count"], _summary_value(rows, "proxy_count", "proxy_metric_count", text)),
        (text["news_count"], _summary_value(rows, "news_signal_count", "news_signal_count", text)),
        (text["latest_as_of"], rows.get("latest_as_of") or text["not_available"]),
    )
    for start, size in ((0, 4), (4, 3)):
        columns = st.columns(size)
        for column, (label, value) in zip(columns, summary_items[start : start + size]):
            column.metric(label=label, value=value)
    for warning in rows["warnings"]:
        st.warning(warning)
    for section in rows["sections"]:
        render_memory_cycle_section(section, language=code)
