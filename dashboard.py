# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta
import hashlib
import html
import io
import json
import os
import re
from time import perf_counter
from urllib.parse import urljoin

import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from scipy.stats import norm
import streamlit as st
import yfinance as yf

from config import CACHE_DIR, get_fmp_api_key, get_openai_client
from financials import fetch_company_news, fetch_general_news, fetch_historical_prices, get_company_snapshot as get_fmp_company_snapshot
from macro_data import build_macro_snapshot, fetch_indicator, fetch_macro_calendar, fetch_market_series, fetch_treasury_rates


YFINANCE_CACHE_DIR = CACHE_DIR / "yfinance"
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
yf.cache.set_cache_location(YFINANCE_CACHE_DIR)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
CARD_FINANCIAL_TTL_SECONDS = 21600
DEFAULT_WATCHLIST = ["NVDA", "MU", "SNDK", "LITE", "RKLB"]
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
US_MARKET_VALUATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "us_market_valuation.csv")
US_MARKET_VALUATION_TTL_SECONDS = 7 * 24 * 60 * 60
NASDAQ100_FORWARD_PE_COLUMN = "Nasdaq-100 Forward P/E"
FORWARD_EARNINGS_YIELD_COLUMN = "Forward Earnings Yield %"
COMPANY_NAMES = {
    "NVDA": "NVIDIA",
    "MU": "Micron",
    "SNDK": "SanDisk",
    "LITE": "Lumentum",
    "RKLB": "Rocket Lab",
}
SUPPLY_CHAIN_ROLES = {
    "NVDA": "AI accelerators and compute platform",
    "MU": "HBM and memory",
    "SNDK": "Flash storage",
    "LITE": "Optical networking components",
    "RKLB": "Space systems and launch services",
}
EARNINGS_DATES = {
    "NVDA": "2026-08-26",
    "MU": "2026-07-01",
    "SNDK": "2026-08-13",
}


def _debug_state():
    if "_perf_debug" not in st.session_state:
        st.session_state["_perf_debug"] = {
            "api_calls": 0,
            "cacheable_calls": 0,
            "sections": {},
        }
    return st.session_state["_perf_debug"]


def reset_debug_state():
    st.session_state["_perf_debug"] = {
        "api_calls": 0,
        "cacheable_calls": 0,
        "sections": {},
    }


def track_cacheable_call():
    _debug_state()["cacheable_calls"] += 1


def track_api_call(name):
    debug = _debug_state()
    debug["api_calls"] += 1
    debug[name] = debug.get(name, 0) + 1


def track_section_time(name, elapsed):
    _debug_state()["sections"][name] = elapsed


def render_debug_panel():
    debug = _debug_state()
    with st.sidebar.expander("Performance debug", expanded=False):
        st.write(f"API calls made this run: {debug.get('api_calls', 0)}")
        st.write(f"Cacheable function calls: {debug.get('cacheable_calls', 0)}")
        st.caption("Streamlit cache hits do not execute cached function bodies; low API calls usually means cached data was used.")
        sections = debug.get("sections", {})
        if sections:
            st.write("Section load times:")
            for section, elapsed in sections.items():
                st.write(f"- {section}: {elapsed:.2f}s")


def normalize_ticker(ticker):
    return re.sub(r"\s+", "", str(ticker or "")).upper()


def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        save_watchlist(DEFAULT_WATCHLIST)
        return list(DEFAULT_WATCHLIST)
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("tickers"), list):
            raise ValueError("watchlist.json must contain a tickers list")
        tickers = data.get("tickers", [])
        normalized = []
        for ticker in tickers:
            symbol = normalize_ticker(ticker)
            if symbol and re.fullmatch(r"[A-Z0-9.-]+", symbol) and symbol not in normalized:
                normalized.append(symbol)
        return normalized
    except Exception:
        pass
    save_watchlist(DEFAULT_WATCHLIST)
    return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers):
    normalized = []
    for ticker in tickers or []:
        symbol = normalize_ticker(ticker)
        if symbol and re.fullmatch(r"[A-Z0-9.-]+", symbol) and symbol not in normalized:
            normalized.append(symbol)
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as handle:
        json.dump({"tickers": normalized}, handle, ensure_ascii=False, indent=2)
    return normalized


def add_ticker_to_watchlist(ticker):
    symbol = normalize_ticker(ticker)
    if not symbol:
        return False, "watchlist_invalid_ticker", ""
    if not re.fullmatch(r"[A-Z0-9.-]+", symbol):
        return False, "watchlist_invalid_ticker", symbol
    tickers = load_watchlist()
    if symbol in tickers:
        return False, "watchlist_ticker_exists", symbol
    tickers.append(symbol)
    save_watchlist(tickers)
    return True, "watchlist_added_success", symbol


def remove_ticker_from_watchlist(ticker):
    symbol = normalize_ticker(ticker)
    tickers = load_watchlist()
    if symbol not in tickers:
        return False, "watchlist_invalid_ticker", symbol
    save_watchlist([item for item in tickers if item != symbol])
    return True, "watchlist_removed_success", symbol


def company_name(ticker, snapshot=None):
    if snapshot and snapshot.get("name"):
        return snapshot["name"]
    return COMPANY_NAMES.get(ticker, ticker)


def supply_chain_role(ticker):
    return SUPPLY_CHAIN_ROLES.get(ticker, "Dynamic watchlist stock")
POSITIVE_NEWS_KEYWORDS = (
    "beat", "raise", "growth", "demand", "upgrade", "strong", "record",
    "expansion", "partnership",
)
NEGATIVE_NEWS_KEYWORDS = (
    "miss", "cut", "downgrade", "weak", "lawsuit", "decline", "guidance cut",
    "export restriction", "inventory", "margin pressure",
)
MARKET_NEWS_KEYWORDS = (
    "semiconductor", "ai", "memory", "dram", "nand", "data center", "nvidia", "micron",
)
TRANSLATIONS = {
    "English": {
        "language": "Language", "dashboard_title": "Equity Research Terminal",
        "dashboard_caption": "Cross-company dashboard | AI infrastructure and growth watchlist",
        "technical_analysis": "Technical Analysis", "options_gex": "Options & GEX",
        "value_investing": "Value Investing", "news_sentiment": "News & Sentiment",
        "multi_agent_research": "Multi-Agent Research", "macro": "Macro",
        "source": "Source", "price": "Price", "today": "today", "market_cap": "Market cap",
        "revenue": "Revenue", "net_margin": "Net margin", "technical_caption": "Six-month price trend, moving averages, RSI, and volume activity for the complete watchlist.",
        "rsi_signal": "RSI signal", "volume_vs_20d": "Volume vs 20D", "historical_price_source": "Historical price source",
        "technical_unavailable": "technical data unavailable", "overbought": "Overbought", "oversold": "Oversold", "neutral": "Neutral",
        "options_caption": "Gamma exposure and options positioning are calculated independently for every tracked stock.",
        "put_call_ratio": "Put/Call ratio", "max_pain": "Max pain", "net_gex": "Net GEX", "call_wall": "Call wall", "put_wall": "Put wall",
        "gamma_squeeze_risk": "Gamma squeeze risk", "nearest_expiration": "Nearest expiration", "high": "High", "medium": "Medium", "low": "Low",
        "gex_unavailable": "GEX regime unavailable.", "positive_gex": "Positive GEX: positioning may dampen moves.", "negative_gex": "Negative GEX: positioning may amplify moves.",
        "options_unavailable": "options data unavailable", "strike": "Strike", "open_interest": "Open interest", "gamma_exposure_by_strike": "Gamma Exposure by Strike",
        "gex_chart_unavailable": "GEX chart unavailable: no usable gamma exposure data returned.",
        "value_caption": "FMP-first ratios, key metrics, and growth comparison for every tracked company.", "valuation_unavailable": "Valuation data unavailable",
        "gross_margin": "Gross margin", "operating_margin": "Operating margin", "fcf_margin": "FCF margin", "current_ratio": "Current ratio",
        "quick_ratio": "Quick ratio", "debt_equity": "Debt / equity", "revenue_yoy": "Revenue YoY", "gross_profit_growth": "Gross profit growth",
        "operating_income_growth": "Operating income growth", "net_income_growth": "Net income growth", "eps_growth": "EPS growth",
        "current_price": "Current price", "consensus_target": "Consensus target", "high_target": "High target", "low_target": "Low target",
        "upside_downside": "Upside / downside", "analyst_rating": "Analyst rating", "all": "All", "ticker": "Ticker",
        "sentiment": "Sentiment", "number_news_items": "Number of news items", "positive": "Positive", "negative": "Negative",
        "select_ticker": "Ticker", "select_source": "Source", "select_sentiment": "Sentiment", "watchlist_stock_news": "Watchlist Stock News",
        "semiconductor_ai_news": "Semiconductor / AI Market News", "no_news_available": "No news available",
        "no_filtered_news": "No news matches the selected filters.", "fmp_news_fallback": "FMP news unavailable, using yfinance fallback",
        "stock_news_unavailable": "Stock news unavailable", "market_news_unavailable": "FMP general market news unavailable",
        "open_article": "Open article", "untitled_article": "Untitled article", "unknown_publisher": "Unknown publisher",
        "date_unavailable": "Date unavailable", "unknown_source": "Unknown source", "market": "Market",
        "daily_report_caption": "Build a complete daily research report for the watchlist in one pass.", "generate_daily_report": "Generate Complete Daily Report",
        "daily_watchlist_report": "Daily Watchlist Report", "technical_snapshot": "Technical Snapshot", "options_snapshot": "Options & GEX Snapshot",
        "value_snapshot": "Value Investing Snapshot", "earnings_catalysts": "Earnings Catalysts", "ai_summary": "AI Summary",
        "ai_summary_unavailable": "AI report summary unavailable", "company": "Company", "supply_chain_role": "Supply Chain Role",
        "trailing_pe": "Trailing P/E", "forward_pe": "Forward P/E", "price_book": "Price / Book", "analyst_target": "Analyst Target",
        "next_earnings_date": "Next Earnings Date", "estimated_eps": "Estimated EPS", "actual_eps": "Actual EPS", "eps_surprise": "EPS Surprise",
        "days_until_earnings": "Days Until Earnings", "multi_agent_caption": "Run the five-agent workflow for one selected ticker.",
        "run_multi_agent": "Run Multi-Agent Analysis", "running_agents": "Running research agents for", "final_verdict": "Final Verdict",
        "agent_detail": "Agent Detail", "fundamental_analysis": "Fundamental Analysis", "options_analysis": "Options Analysis",
        "data_unavailable": "data unavailable", "data_source": "Data Source", "revenue_growth_yoy": "Revenue Growth YoY",
        "last_updated": "Last Updated", "diagnostic_note": "Diagnostic Note", "macro_caption": "Dynamic FMP-first macro dashboard for the next 30 days. Market-series fallbacks use yfinance.",
        "refresh_macro": "Refresh Macro Data", "calendar_window": "Calendar window", "macro_risk_score": "Macro risk score", "treasury_source": "Treasury source",
        "dynamic_macro_calendar": "Dynamic 30-Day Macro Calendar", "show_all_macro_events": "Show all macro calendar events",
        "no_highlighted_macro_events": "No highlighted macro events in the next 30 days.", "economic_calendar_unavailable": "Economic calendar unavailable.",
        "historical_data_unavailable": "historical data unavailable", "cpi_index": "CPI index", "us_10y_treasury_yield": "US 10Y Treasury yield",
        "brent_crude_oil": "Brent crude oil", "unemployment": "Unemployment", "gdp_growth_yoy": "GDP growth YoY",
        "no_watchlist_news": "No news available", "no_market_news": "No news available",
        "market_news_caption": "FMP general news filtered for semiconductor, AI, memory, DRAM, NAND, data center, Nvidia, and Micron.",
        "fmp_news_tab": "FMP News", "yahoo_news_tab": "Yahoo News", "yahoo_news": "Yahoo News",
        "yahoo_news_caption": "Supplemental Yahoo/yfinance headlines for each tracked stock. Cached for 30 minutes.",
        "no_yahoo_news": "No Yahoo/yfinance news available", "yahoo_news_unavailable": "Yahoo/yfinance news unavailable",
        "related_news": "Related News", "related_ticker": "Related ticker",
    },
    "中文": {
        "language": "语言", "dashboard_title": "股票研究终端", "dashboard_caption": "跨公司仪表板 | AI 基础设施与成长股观察列表",
        "technical_analysis": "技术分析", "options_gex": "期权与 GEX", "value_investing": "价值投资", "news_sentiment": "新闻与情绪",
        "multi_agent_research": "多智能体研究", "macro": "宏观", "source": "来源", "price": "价格",
        "today": "今日", "market_cap": "市值", "revenue": "营收", "net_margin": "净利率", "technical_caption": "完整观察列表的六个月价格趋势、移动平均线、RSI 和成交量活动。",
        "rsi_signal": "RSI 信号", "volume_vs_20d": "成交量对比 20 日均值", "historical_price_source": "历史价格来源", "technical_unavailable": "技术数据不可用",
        "overbought": "超买", "oversold": "超卖", "neutral": "中性", "options_caption": "每只跟踪股票的伽马敞口和期权仓位均独立计算。",
        "put_call_ratio": "看跌/看涨比率", "max_pain": "最大痛点", "net_gex": "净 GEX", "call_wall": "看涨墙", "put_wall": "看跌墙",
        "gamma_squeeze_risk": "伽马挤压风险", "nearest_expiration": "最近到期日", "high": "高", "medium": "中", "low": "低",
        "gex_unavailable": "GEX 状态不可用。", "positive_gex": "正 GEX：仓位可能抑制波动。", "negative_gex": "负 GEX：仓位可能放大波动。",
        "options_unavailable": "期权数据不可用", "strike": "行权价", "open_interest": "未平仓量", "gamma_exposure_by_strike": "按行权价划分的伽马敞口",
        "gex_chart_unavailable": "GEX 图表不可用：未返回可用的伽马敞口数据。", "value_caption": "使用 FMP 优先数据，对每家跟踪公司进行比率、关键指标和增长比较。",
        "valuation_unavailable": "估值数据不可用", "gross_margin": "毛利率", "operating_margin": "营业利润率", "fcf_margin": "自由现金流利润率",
        "current_ratio": "流动比率", "quick_ratio": "速动比率", "debt_equity": "债务 / 权益", "revenue_yoy": "营收同比", "gross_profit_growth": "毛利润增长",
        "operating_income_growth": "营业利润增长", "net_income_growth": "净利润增长", "eps_growth": "EPS 增长", "current_price": "当前价格",
        "consensus_target": "一致目标价", "high_target": "最高目标价", "low_target": "最低目标价", "upside_downside": "上涨 / 下跌空间", "analyst_rating": "分析师评级",
        "all": "全部", "ticker": "股票代码", "sentiment": "情绪", "number_news_items": "新闻条数", "positive": "正面", "negative": "负面",
        "select_ticker": "股票代码", "select_source": "来源", "select_sentiment": "情绪", "watchlist_stock_news": "观察列表股票新闻",
        "semiconductor_ai_news": "半导体 / AI 市场新闻", "no_news_available": "暂无新闻", "no_filtered_news": "没有符合所选筛选条件的新闻。",
        "fmp_news_fallback": "FMP 新闻不可用，正在使用 yfinance 备用来源", "stock_news_unavailable": "股票新闻不可用", "market_news_unavailable": "FMP 综合市场新闻不可用",
        "open_article": "打开文章", "untitled_article": "无标题文章", "unknown_publisher": "未知发布者", "date_unavailable": "日期不可用", "unknown_source": "未知来源", "market": "市场",
        "daily_report_caption": "一次生成观察列表的完整每日研究报告。", "generate_daily_report": "生成完整每日报告", "daily_watchlist_report": "每日观察列表报告",
        "technical_snapshot": "技术快照", "options_snapshot": "期权与 GEX 快照", "value_snapshot": "价值投资快照", "earnings_catalysts": "财报催化剂", "ai_summary": "AI 摘要",
        "ai_summary_unavailable": "AI 报告摘要不可用", "company": "公司", "supply_chain_role": "供应链角色", "trailing_pe": "历史市盈率", "forward_pe": "预期市盈率",
        "price_book": "市净率", "analyst_target": "分析师目标价", "next_earnings_date": "下次财报日期", "estimated_eps": "预估 EPS", "actual_eps": "实际 EPS",
        "eps_surprise": "EPS 超预期幅度", "days_until_earnings": "距离财报天数", "multi_agent_caption": "为一个选定股票运行五智能体分析流程。",
        "run_multi_agent": "运行该股票多智能体分析", "running_agents": "正在运行研究智能体：", "final_verdict": "最终结论", "agent_detail": "智能体详情",
        "fundamental_analysis": "基本面分析", "options_analysis": "期权分析", "data_unavailable": "数据不可用", "data_source": "数据来源",
        "revenue_growth_yoy": "营收同比增长", "last_updated": "最后更新", "diagnostic_note": "诊断说明", "macro_caption": "未来 30 天的动态宏观仪表板，优先使用 FMP 数据。市场序列备用来源使用 yfinance。",
        "refresh_macro": "刷新宏观数据", "calendar_window": "日历区间", "macro_risk_score": "宏观风险评分", "treasury_source": "美债数据来源",
        "dynamic_macro_calendar": "动态 30 天宏观日历", "show_all_macro_events": "显示所有宏观日历事件", "no_highlighted_macro_events": "未来 30 天没有重点宏观事件。",
        "economic_calendar_unavailable": "经济日历不可用。", "historical_data_unavailable": "历史数据不可用", "cpi_index": "CPI 指数", "us_10y_treasury_yield": "美国 10 年期国债收益率",
        "brent_crude_oil": "布伦特原油", "unemployment": "失业率", "gdp_growth_yoy": "GDP 同比增长", "no_watchlist_news": "暂无新闻", "no_market_news": "暂无新闻",
        "market_news_caption": "筛选 FMP 综合新闻中的半导体、AI、内存、DRAM、NAND、数据中心、Nvidia 和 Micron 相关内容。",
        "fmp_news_tab": "FMP 新闻", "yahoo_news_tab": "Yahoo 新闻", "yahoo_news": "相关新闻",
        "yahoo_news_caption": "每只跟踪股票的 Yahoo/yfinance 补充新闻，缓存 30 分钟。",
        "no_yahoo_news": "暂无 Yahoo/yfinance 新闻", "yahoo_news_unavailable": "Yahoo/yfinance 新闻不可用",
        "related_news": "相关新闻", "related_ticker": "相关 ticker",
    },
    "Español": {
        "language": "Idioma", "dashboard_title": "Terminal de análisis bursátil", "dashboard_caption": "Panel comparativo | Infraestructura de IA y lista de seguimiento de crecimiento",
        "technical_analysis": "Análisis técnico", "options_gex": "Opciones y GEX", "value_investing": "Inversión en valor", "news_sentiment": "Noticias y sentimiento",
        "multi_agent_research": "Análisis multiagente", "macro": "Macro", "source": "Fuente", "price": "Precio",
        "today": "hoy", "market_cap": "Capitalización", "revenue": "Ingresos", "net_margin": "Margen neto", "technical_caption": "Tendencia de precios de seis meses, medias móviles, RSI y volumen para toda la lista.",
        "rsi_signal": "Señal RSI", "volume_vs_20d": "Volumen vs. 20 días", "historical_price_source": "Fuente de precios históricos", "technical_unavailable": "datos técnicos no disponibles",
        "overbought": "Sobrecompra", "oversold": "Sobreventa", "neutral": "Neutral", "options_caption": "La exposición gamma y el posicionamiento de opciones se calculan por separado para cada acción.",
        "put_call_ratio": "Ratio put/call", "max_pain": "Máximo dolor", "net_gex": "GEX neto", "call_wall": "Muro call", "put_wall": "Muro put",
        "gamma_squeeze_risk": "Riesgo de compresión gamma", "nearest_expiration": "Vencimiento más próximo", "high": "Alto", "medium": "Medio", "low": "Bajo",
        "gex_unavailable": "Régimen GEX no disponible.", "positive_gex": "GEX positivo: el posicionamiento puede moderar los movimientos.", "negative_gex": "GEX negativo: el posicionamiento puede amplificar los movimientos.",
        "options_unavailable": "datos de opciones no disponibles", "strike": "Precio de ejercicio", "open_interest": "Interés abierto", "gamma_exposure_by_strike": "Exposición gamma por precio de ejercicio",
        "gex_chart_unavailable": "Gráfico GEX no disponible: no se recibieron datos útiles.", "value_caption": "Ratios, métricas clave y crecimiento para cada empresa, con prioridad para FMP.",
        "valuation_unavailable": "Datos de valoración no disponibles", "gross_margin": "Margen bruto", "operating_margin": "Margen operativo", "fcf_margin": "Margen FCF",
        "current_ratio": "Ratio corriente", "quick_ratio": "Prueba ácida", "debt_equity": "Deuda / patrimonio", "revenue_yoy": "Ingresos interanuales", "gross_profit_growth": "Crecimiento del beneficio bruto",
        "operating_income_growth": "Crecimiento del beneficio operativo", "net_income_growth": "Crecimiento del beneficio neto", "eps_growth": "Crecimiento del BPA", "current_price": "Precio actual",
        "consensus_target": "Precio objetivo consensuado", "high_target": "Objetivo máximo", "low_target": "Objetivo mínimo", "upside_downside": "Potencial alcista / bajista", "analyst_rating": "Calificación de analistas",
        "all": "Todos", "ticker": "Ticker", "sentiment": "Sentimiento", "number_news_items": "Número de noticias", "positive": "Positivo", "negative": "Negativo",
        "select_ticker": "Ticker", "select_source": "Fuente", "select_sentiment": "Sentimiento", "watchlist_stock_news": "Noticias de la lista de seguimiento",
        "semiconductor_ai_news": "Noticias del mercado de semiconductores / IA", "no_news_available": "No hay noticias disponibles", "no_filtered_news": "No hay noticias que coincidan con los filtros.",
        "fmp_news_fallback": "Noticias FMP no disponibles; usando yfinance como respaldo", "stock_news_unavailable": "Noticias bursátiles no disponibles", "market_news_unavailable": "Noticias generales de FMP no disponibles",
        "open_article": "Abrir artículo", "untitled_article": "Artículo sin título", "unknown_publisher": "Editor desconocido", "date_unavailable": "Fecha no disponible", "unknown_source": "Fuente desconocida", "market": "Mercado",
        "daily_report_caption": "Genere un informe diario completo para la lista de seguimiento.", "generate_daily_report": "Generar informe diario completo", "daily_watchlist_report": "Informe diario de la lista",
        "technical_snapshot": "Resumen técnico", "options_snapshot": "Resumen de opciones y GEX", "value_snapshot": "Resumen de inversión en valor", "earnings_catalysts": "Catalizadores de resultados", "ai_summary": "Resumen de IA",
        "ai_summary_unavailable": "Resumen del informe de IA no disponible", "company": "Empresa", "supply_chain_role": "Función en la cadena de suministro", "trailing_pe": "P/E histórico", "forward_pe": "P/E futuro",
        "price_book": "Precio / valor contable", "analyst_target": "Objetivo de analistas", "next_earnings_date": "Próxima fecha de resultados", "estimated_eps": "BPA estimado", "actual_eps": "BPA real",
        "eps_surprise": "Sorpresa del BPA", "days_until_earnings": "Días hasta resultados", "multi_agent_caption": "Ejecute el flujo de cinco agentes para un ticker seleccionado.",
        "run_multi_agent": "Ejecutar análisis multiagente", "running_agents": "Ejecutando agentes de análisis para", "final_verdict": "Veredicto final", "agent_detail": "Detalle de agentes",
        "fundamental_analysis": "Análisis fundamental", "options_analysis": "Análisis de opciones", "data_unavailable": "datos no disponibles", "data_source": "Fuente de datos",
        "revenue_growth_yoy": "Crecimiento interanual de ingresos", "last_updated": "Última actualización", "diagnostic_note": "Nota de diagnóstico", "macro_caption": "Panel macro dinámico para los próximos 30 días, con prioridad para FMP. Los respaldos usan yfinance.",
        "refresh_macro": "Actualizar datos macro", "calendar_window": "Ventana del calendario", "macro_risk_score": "Puntuación de riesgo macro", "treasury_source": "Fuente de bonos del Tesoro",
        "dynamic_macro_calendar": "Calendario macro dinámico de 30 días", "show_all_macro_events": "Mostrar todos los eventos macro", "no_highlighted_macro_events": "No hay eventos macro destacados en los próximos 30 días.",
        "economic_calendar_unavailable": "Calendario económico no disponible.", "historical_data_unavailable": "datos históricos no disponibles", "cpi_index": "Índice IPC", "us_10y_treasury_yield": "Rendimiento del Tesoro de EE. UU. a 10 años",
        "brent_crude_oil": "Petróleo Brent", "unemployment": "Desempleo", "gdp_growth_yoy": "Crecimiento interanual del PIB", "no_watchlist_news": "No hay noticias disponibles", "no_market_news": "No hay noticias disponibles",
        "market_news_caption": "Noticias generales de FMP filtradas por semiconductores, IA, memoria, DRAM, NAND, centros de datos, Nvidia y Micron.",
        "fmp_news_tab": "Noticias FMP", "yahoo_news_tab": "Yahoo News", "yahoo_news": "Noticias relacionadas",
        "yahoo_news_caption": "Titulares complementarios de Yahoo/yfinance para cada acción seguida. Caché de 30 minutos.",
        "no_yahoo_news": "No hay noticias de Yahoo/yfinance disponibles", "yahoo_news_unavailable": "Noticias de Yahoo/yfinance no disponibles",
        "related_news": "Noticias relacionadas", "related_ticker": "Ticker relacionado",
    },
}


NEWS_UI_TRANSLATION_OVERRIDES = {
    "English": {
        "full_translation": "Full Translation",
        "chatgpt_detailed_summary": "ChatGPT Detailed Summary",
        "open_article": "Open article",
        "trendforce_news_tab": "TrendForce News",
        "trendforce_news": "TrendForce News",
        "trendforce_news_caption": "TrendForce semiconductor and memory industry news.",
        "no_trendforce_news": "TrendForce news has no data or is not configured yet.",
        "watchlist_manager": "Stock Watchlist",
        "watchlist_input": "Enter stock ticker",
        "watchlist_add": "Add stock",
        "watchlist_remove": "Remove stock",
        "watchlist_current": "Current watchlist",
        "watchlist_ticker_exists": "Stock already exists.",
        "watchlist_added_success": "Stock added successfully.",
        "watchlist_removed_success": "Stock removed successfully.",
        "watchlist_invalid_ticker": "Invalid stock ticker.",
        "option_expiry": "Option expiration",
        "current_expiry": "Current expiration",
        "option_expirations_not_found": "No available option expirations found",
        "option_open_interest_missing": "This expiration did not return open interest data",
        "option_gamma_missing": "The data source did not return gamma, so net GEX cannot be calculated",
        "option_call_put_empty": "Call/put data is empty for this expiration",
        "option_price_available_chain_unavailable": "Price is available, but the option chain is unavailable",
        "options_ai_summary": "Options AI Summary",
        "generate_options_ai_summary": "Generate Options AI Summary",
        "options_ai_summary_idle": "Generate this summary on demand to limit AI costs.",
        "options_ai_summary_disclaimer": "Risk disclaimer: this is not financial advice.",
    },
    "\u4e2d\u6587": {
        "full_translation": "\u5168\u6587\u7ffb\u8bd1",
        "chatgpt_detailed_summary": "ChatGPT \u8be6\u7ec6\u603b\u7ed3",
        "open_article": "\u6253\u5f00\u6587\u7ae0",
        "trendforce_news_tab": "TrendForce \u65b0\u95fb",
        "trendforce_news": "TrendForce \u65b0\u95fb",
        "trendforce_news_caption": "TrendForce \u534a\u5bfc\u4f53\u4e0e\u5b58\u50a8\u884c\u4e1a\u65b0\u95fb\u3002",
        "no_trendforce_news": "TrendForce \u65b0\u95fb\u6682\u65e0\u6570\u636e\u6216\u5c1a\u672a\u914d\u7f6e\u3002",
        "watchlist_manager": "\u80a1\u7968\u89c2\u5bdf\u5217\u8868",
        "watchlist_input": "\u8f93\u5165\u80a1\u7968\u4ee3\u7801",
        "watchlist_add": "\u6dfb\u52a0\u80a1\u7968",
        "watchlist_remove": "\u5220\u9664\u80a1\u7968",
        "watchlist_current": "\u5f53\u524d\u89c2\u5bdf\u5217\u8868",
        "watchlist_ticker_exists": "\u80a1\u7968\u5df2\u5b58\u5728\u3002",
        "watchlist_added_success": "\u80a1\u7968\u6dfb\u52a0\u6210\u529f\u3002",
        "watchlist_removed_success": "\u80a1\u7968\u5220\u9664\u6210\u529f\u3002",
        "watchlist_invalid_ticker": "\u80a1\u7968\u4ee3\u7801\u65e0\u6548\u3002",
        "option_expiry": "\u671f\u6743\u5230\u671f\u65e5",
        "current_expiry": "\u5f53\u524d\u5230\u671f\u65e5",
        "option_expirations_not_found": "\u672a\u627e\u5230\u53ef\u7528\u671f\u6743\u5230\u671f\u65e5",
        "option_open_interest_missing": "\u8be5\u5230\u671f\u65e5\u6ca1\u6709\u8fd4\u56de open interest \u6570\u636e",
        "option_gamma_missing": "\u8be5\u6570\u636e\u6e90\u672a\u8fd4\u56de gamma\uff0c\u51c0 GEX \u65e0\u6cd5\u8ba1\u7b97",
        "option_call_put_empty": "\u8be5\u5230\u671f\u65e5 call/put \u6570\u636e\u4e3a\u7a7a",
        "option_price_available_chain_unavailable": "\u4ef7\u683c\u53ef\u7528\uff0c\u4f46\u671f\u6743\u94fe\u4e0d\u53ef\u7528",
        "options_ai_summary": "\u671f\u6743 AI \u603b\u7ed3",
        "generate_options_ai_summary": "\u751f\u6210\u671f\u6743 AI \u603b\u7ed3",
        "options_ai_summary_idle": "\u6309\u9700\u751f\u6210\u6b64\u603b\u7ed3\uff0c\u4ee5\u51cf\u5c11 AI \u8c03\u7528\u6210\u672c\u3002",
        "options_ai_summary_disclaimer": "\u98ce\u9669\u63d0\u793a\uff1a\u8fd9\u4e0d\u662f\u6295\u8d44\u5efa\u8bae\u3002",
    },
    "Espa\u00f1ol": {
        "full_translation": "Traducci\u00f3n completa",
        "chatgpt_detailed_summary": "Resumen detallado de ChatGPT",
        "open_article": "Abrir art\u00edculo",
        "trendforce_news_tab": "Noticias de TrendForce",
        "trendforce_news": "Noticias de TrendForce",
        "trendforce_news_caption": "Noticias de TrendForce sobre semiconductores y memoria.",
        "no_trendforce_news": "Las noticias de TrendForce no tienen datos o a\u00fan no est\u00e1n configuradas.",
        "watchlist_manager": "Lista de seguimiento",
        "watchlist_input": "Introducir ticker",
        "watchlist_add": "A\u00f1adir acci\u00f3n",
        "watchlist_remove": "Eliminar acci\u00f3n",
        "watchlist_current": "Lista actual",
        "watchlist_ticker_exists": "La acci\u00f3n ya existe.",
        "watchlist_added_success": "Acci\u00f3n a\u00f1adida correctamente.",
        "watchlist_removed_success": "Acci\u00f3n eliminada correctamente.",
        "watchlist_invalid_ticker": "Ticker no v\u00e1lido.",
        "option_expiry": "Vencimiento de opciones",
        "current_expiry": "Vencimiento actual",
        "option_expirations_not_found": "No se encontraron vencimientos de opciones disponibles",
        "option_open_interest_missing": "Este vencimiento no devolvi\u00f3 datos de inter\u00e9s abierto",
        "option_gamma_missing": "La fuente de datos no devolvi\u00f3 gamma, por lo que no se puede calcular el GEX neto",
        "option_call_put_empty": "Los datos call/put est\u00e1n vac\u00edos para este vencimiento",
        "option_price_available_chain_unavailable": "El precio est\u00e1 disponible, pero la cadena de opciones no est\u00e1 disponible",
        "options_ai_summary": "Resumen IA de Opciones",
        "generate_options_ai_summary": "Generar Resumen IA de Opciones",
        "options_ai_summary_idle": "Genere este resumen bajo demanda para limitar los costos de IA.",
        "options_ai_summary_disclaimer": "Aviso de riesgo: esto no es asesoramiento financiero.",
    },
}


def _translation_language_key(language):
    if language in TRANSLATIONS:
        return language
    if language == "\u4e2d\u6587":
        return next((key for key in TRANSLATIONS if key not in ("English", "Espa\u00f1ol") and not str(key).startswith("Espa")), language)
    if language == "Espa\u00f1ol":
        return next((key for key in TRANSLATIONS if str(key).startswith("Espa")), language)
    return language


for _language, _labels in NEWS_UI_TRANSLATION_OVERRIDES.items():
    TRANSLATIONS.setdefault(_translation_language_key(_language), {}).update(_labels)


MACRO_TRANSLATION_OVERRIDES = {
    "English": {
        "macro_risk_score": "Macro risk score",
        "us_treasury_yields": "US Treasury yields",
        "fx_relative_performance": "FX relative performance",
        "inflation_and_economy": "Inflation and economy",
        "fed_indicator_explanation": "The Fed focuses most on PCE and Core PCE because they are closer to the official inflation framework behind the 2% target. CPI and Core CPI often move markets in the short term, but PCE carries more policy weight. Labor market data helps assess whether wage pressure and demand can keep inflation sticky.",
        "fed_ranking": "Fed indicator ranking",
        "why_it_matters": "Why it matters",
        "fed_rank_core_pce": "Best read on underlying inflation in the Fed's preferred PCE framework.",
        "fed_rank_pce": "Headline PCE is closest to the Fed's official 2% inflation target.",
        "fed_rank_labor": "Shows whether wages and demand can keep inflation sticky.",
        "fed_rank_core_cpi": "Market-moving inflation signal that strips out food and energy.",
        "fed_rank_cpi": "High-frequency household inflation gauge, but less policy-weighted than PCE.",
        "main_inflation_chart": "Main inflation chart",
        "labor_market_chart": "Labor market chart",
        "economy_chart": "Economy chart",
        "economy_chart_explanation": "The economy chart tracks the broad growth trend of the US economy. GDP YoY Growth measures how much GDP has grown compared with the same quarter one year earlier. GDP is quarterly data, so it is useful for macro direction rather than short-term trading.",
        "missing_macro_series": "Unavailable macro series: {series}",
        "core_pce_yoy": "Core PCE YoY",
        "pce_yoy": "PCE YoY",
        "core_cpi_yoy": "Core CPI YoY",
        "cpi_yoy": "CPI YoY",
        "unemployment_rate": "Unemployment rate",
        "wage_growth": "Wage growth",
        "nonfarm_payrolls": "Nonfarm payrolls",
        "job_openings": "Job openings",
        "gdp_yoy_growth": "GDP YoY Growth",
        "commodities_relative_performance": "Commodities relative performance",
        "latest_macro_data": "Latest macro data",
        "macro_series_unavailable": "Some macro series are unavailable.",
        "chart_period": "Period",
        "indicator": "Indicator",
        "latest": "Latest",
        "last_updated": "Last updated",
    },
    "\u4e2d\u6587": {
        "macro_risk_score": "\u5b8f\u89c2\u98ce\u9669\u8bc4\u5206",
        "us_treasury_yields": "\u7f8e\u503a\u6536\u76ca\u7387",
        "fx_relative_performance": "\u6c47\u7387\u76f8\u5bf9\u8868\u73b0",
        "inflation_and_economy": "\u901a\u80c0\u4e0e\u7ecf\u6d4e\u6570\u636e",
        "fed_indicator_explanation": "\u7f8e\u8054\u50a8\u6700\u5173\u6ce8\u7684\u662f PCE \u548c\u6838\u5fc3 PCE\uff0c\u56e0\u4e3a\u5b83\u4eec\u66f4\u63a5\u8fd1\u7f8e\u8054\u50a8 2% \u901a\u80c0\u76ee\u6807\u7684\u5b98\u65b9\u8861\u91cf\u53e3\u5f84\u3002CPI \u548c\u6838\u5fc3 CPI \u5bf9\u5e02\u573a\u77ed\u671f\u53cd\u5e94\u66f4\u654f\u611f\uff0c\u4f46\u653f\u7b56\u6743\u91cd\u901a\u5e38\u4f4e\u4e8e PCE\u3002\u5c31\u4e1a\u5e02\u573a\u6570\u636e\u7528\u4e8e\u5224\u65ad\u901a\u80c0\u662f\u5426\u4f1a\u901a\u8fc7\u5de5\u8d44\u548c\u9700\u6c42\u7ee7\u7eed\u4fdd\u6301\u7c98\u6027\u3002",
        "fed_ranking": "\u7f8e\u8054\u50a8\u6307\u6807\u6392\u540d",
        "why_it_matters": "\u91cd\u8981\u6027",
        "fed_rank_core_pce": "\u5728\u7f8e\u8054\u50a8\u504f\u597d\u7684 PCE \u6846\u67b6\u4e0b\u89c2\u5bdf\u5e95\u5c42\u901a\u80c0\u7684\u6700\u4f73\u6307\u6807\u3002",
        "fed_rank_pce": "\u6574\u4f53 PCE \u6700\u63a5\u8fd1\u7f8e\u8054\u50a8 2% \u901a\u80c0\u76ee\u6807\u7684\u5b98\u65b9\u53e3\u5f84\u3002",
        "fed_rank_labor": "\u663e\u793a\u5de5\u8d44\u548c\u9700\u6c42\u662f\u5426\u4f1a\u8ba9\u901a\u80c0\u7ee7\u7eed\u5177\u6709\u7c98\u6027\u3002",
        "fed_rank_core_cpi": "\u5254\u9664\u98df\u54c1\u548c\u80fd\u6e90\u540e\u7684\u5e02\u573a\u654f\u611f\u578b\u901a\u80c0\u4fe1\u53f7\u3002",
        "fed_rank_cpi": "\u9ad8\u9891\u5bb6\u5ead\u901a\u80c0\u6307\u6807\uff0c\u4f46\u653f\u7b56\u6743\u91cd\u4f4e\u4e8e PCE\u3002",
        "main_inflation_chart": "\u4e3b\u8981\u901a\u80c0\u56fe\u8868",
        "labor_market_chart": "\u52b3\u52a8\u529b\u5e02\u573a\u56fe\u8868",
        "economy_chart": "\u7ecf\u6d4e\u56fe\u8868",
        "economy_chart_explanation": "\u7ecf\u6d4e\u56fe\u8868\u4e3b\u8981\u7528\u4e8e\u89c2\u5bdf\u7f8e\u56fd\u7ecf\u6d4e\u589e\u957f\u8d8b\u52bf\u3002GDP \u540c\u6bd4\u589e\u957f\u8868\u793a\u5f53\u524d\u5b63\u5ea6 GDP \u76f8\u6bd4\u53bb\u5e74\u540c\u671f\u7684\u589e\u957f\u901f\u5ea6\u3002GDP \u662f\u5b63\u5ea6\u6570\u636e\uff0c\u9002\u5408\u5224\u65ad\u7ecf\u6d4e\u5927\u65b9\u5411\uff0c\u4e0d\u9002\u5408\u7528\u4e8e\u77ed\u7ebf\u4ea4\u6613\u3002\u5982\u679c GDP \u540c\u6bd4\u4e0a\u5347\uff0c\u8bf4\u660e\u7ecf\u6d4e\u589e\u957f\u8f83\u5f3a\uff1b\u5982\u679c\u6301\u7eed\u4e0b\u964d\uff0c\u8bf4\u660e\u7ecf\u6d4e\u653e\u7f13\u6216\u8870\u9000\u98ce\u9669\u4e0a\u5347\u3002",
        "missing_macro_series": "\u4e0d\u53ef\u7528\u7684\u5b8f\u89c2\u5e8f\u5217\uff1a{series}",
        "core_pce_yoy": "\u6838\u5fc3 PCE \u540c\u6bd4",
        "pce_yoy": "PCE \u540c\u6bd4",
        "core_cpi_yoy": "\u6838\u5fc3 CPI \u540c\u6bd4",
        "cpi_yoy": "CPI \u540c\u6bd4",
        "unemployment_rate": "\u5931\u4e1a\u7387",
        "wage_growth": "\u5de5\u8d44\u589e\u901f",
        "nonfarm_payrolls": "\u975e\u519c\u5c31\u4e1a",
        "job_openings": "\u804c\u4f4d\u7a7a\u7f3a",
        "gdp_yoy_growth": "GDP \u540c\u6bd4\u589e\u957f",
        "commodities_relative_performance": "\u5927\u5b97\u5546\u54c1\u76f8\u5bf9\u8868\u73b0",
        "latest_macro_data": "\u6700\u65b0\u5b8f\u89c2\u6570\u636e",
        "macro_series_unavailable": "\u90e8\u5206\u5b8f\u89c2\u6570\u636e\u6682\u4e0d\u53ef\u7528\u3002",
        "chart_period": "\u5468\u671f",
        "indicator": "\u6307\u6807",
        "latest": "\u6700\u65b0",
        "last_updated": "\u6700\u540e\u66f4\u65b0",
    },
    "Espa\u00f1ol": {
        "macro_risk_score": "Puntuaci\u00f3n de riesgo macro",
        "us_treasury_yields": "Rendimientos del Tesoro de EE. UU.",
        "fx_relative_performance": "Rendimiento relativo de divisas",
        "inflation_and_economy": "Inflaci\u00f3n y econom\u00eda",
        "fed_indicator_explanation": "La Fed se centra especialmente en el PCE y el PCE subyacente porque est\u00e1n m\u00e1s cerca del marco oficial de inflaci\u00f3n asociado al objetivo del 2%. El IPC y el IPC subyacente suelen mover el mercado a corto plazo, pero el PCE tiene m\u00e1s peso en pol\u00edtica monetaria. Los datos laborales ayudan a evaluar si los salarios y la demanda mantienen la inflaci\u00f3n persistente.",
        "fed_ranking": "Clasificaci\u00f3n de indicadores de la Fed",
        "why_it_matters": "Por qu\u00e9 importa",
        "fed_rank_core_pce": "Mejor lectura de la inflaci\u00f3n subyacente en el marco PCE preferido por la Fed.",
        "fed_rank_pce": "El PCE general es el m\u00e1s cercano al objetivo oficial de inflaci\u00f3n del 2% de la Fed.",
        "fed_rank_labor": "Muestra si salarios y demanda pueden mantener persistente la inflaci\u00f3n.",
        "fed_rank_core_cpi": "Se\u00f1al de inflaci\u00f3n que mueve el mercado y excluye alimentos y energ\u00eda.",
        "fed_rank_cpi": "Indicador frecuente de inflaci\u00f3n de los hogares, pero con menor peso pol\u00edtico que el PCE.",
        "main_inflation_chart": "Gr\u00e1fico principal de inflaci\u00f3n",
        "labor_market_chart": "Gr\u00e1fico del mercado laboral",
        "economy_chart": "Gr\u00e1fico de econom\u00eda",
        "economy_chart_explanation": "El gr\u00e1fico econ\u00f3mico sigue la tendencia general de crecimiento de la econom\u00eda estadounidense. El crecimiento interanual del PIB mide cu\u00e1nto ha crecido el PIB frente al mismo trimestre del a\u00f1o anterior. El PIB es un dato trimestral, por lo que sirve para analizar la direcci\u00f3n macro, no para trading de corto plazo.",
        "missing_macro_series": "Series macro no disponibles: {series}",
        "core_pce_yoy": "PCE subyacente interanual",
        "pce_yoy": "PCE interanual",
        "core_cpi_yoy": "IPC subyacente interanual",
        "cpi_yoy": "IPC interanual",
        "unemployment_rate": "Tasa de desempleo",
        "wage_growth": "Crecimiento salarial",
        "nonfarm_payrolls": "N\u00f3minas no agr\u00edcolas",
        "job_openings": "Vacantes laborales",
        "gdp_yoy_growth": "Crecimiento interanual del PIB",
        "commodities_relative_performance": "Rendimiento relativo de materias primas",
        "latest_macro_data": "\u00daltimos datos macro",
        "macro_series_unavailable": "Algunas series macro no est\u00e1n disponibles.",
        "chart_period": "Periodo",
        "indicator": "Indicador",
        "latest": "\u00daltimo",
        "last_updated": "\u00daltima actualizaci\u00f3n",
    },
}


for _language, _labels in MACRO_TRANSLATION_OVERRIDES.items():
    TRANSLATIONS.setdefault(_translation_language_key(_language), {}).update(_labels)


def t(key):
    language = st.session_state.get("language", "English")
    return TRANSLATIONS.get(language, TRANSLATIONS["English"]).get(key, TRANSLATIONS["English"].get(key, key))


def format_money(value, decimals=1):
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= divisor:
            return f"${value / divisor:,.{decimals}f}{suffix}"
    return f"${value:,.{decimals}f}"


def format_ratio(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):,.2f}"


def format_percent(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value) * 100:,.1f}%"


def _card_number(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def calculate_rsi(data, window=14):
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def black_scholes_gamma(spot, strike, time_to_expiry, rate, volatility):
    if time_to_expiry <= 0 or volatility <= 0:
        return 0
    d1 = (
        np.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry
    ) / (volatility * np.sqrt(time_to_expiry))
    return norm.pdf(d1) / (spot * volatility * np.sqrt(time_to_expiry))


@st.cache_data(ttl=300)
def get_yfinance_quote_snapshot(ticker):
    track_api_call("yfinance_quote")
    ticker = normalize_ticker(ticker)
    stock = yf.Ticker(ticker)
    fast_info = {}
    try:
        fast_info = dict(stock.fast_info or {})
    except Exception:
        fast_info = {}
    history = pd.DataFrame()
    try:
        history = stock.history(period="5d")
    except Exception:
        history = pd.DataFrame()
    price = fast_info.get("lastPrice") or fast_info.get("last_price")
    previous_close = fast_info.get("previousClose") or fast_info.get("previous_close")
    if price is None and not history.empty and "Close" in history:
        price = float(history["Close"].dropna().iloc[-1])
    if previous_close is None and not history.empty and "Close" in history and len(history["Close"].dropna()) >= 2:
        previous_close = float(history["Close"].dropna().iloc[-2])
    change_pct = None
    if price is not None and previous_close:
        change_pct = (float(price) - float(previous_close)) / float(previous_close) * 100
    return {
        "ticker": ticker,
        "name": COMPANY_NAMES.get(ticker, ticker),
        "price": None if price is None else float(price),
        "change_pct": change_pct,
        "market_cap": fast_info.get("marketCap") or fast_info.get("market_cap"),
        "revenue": None,
        "net_margin": None,
        "source": "yfinance",
        "role": supply_chain_role(ticker),
    }


def _empty_card_financial_fields(ticker, source="unavailable"):
    ticker = normalize_ticker(ticker)
    return {
        "ticker": ticker,
        "name": COMPANY_NAMES.get(ticker, ticker),
        "market_cap": None,
        "revenue": None,
        "net_margin": None,
        "financial_source": source,
    }


def _fmp_card_first(ticker, endpoint, api_key):
    track_api_call(f"fmp_card_{endpoint}")
    response = requests.get(
        f"{FMP_BASE_URL}/{endpoint}",
        params={"symbol": ticker, "limit": 1, "apikey": api_key},
        timeout=8,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return {}
    return data[0]


def _fmp_card_financial_fields(ticker):
    ticker = normalize_ticker(ticker)
    api_key = get_fmp_api_key()
    payloads = {}
    for endpoint in ("profile", "quote", "income-statement", "ratios"):
        try:
            payloads[endpoint] = _fmp_card_first(ticker, endpoint, api_key)
        except Exception:
            payloads[endpoint] = {}

    profile = payloads["profile"]
    quote = payloads["quote"]
    if ticker == "SNDK" and not any("sandisk" in (item.get("companyName") or item.get("name") or "").lower() for item in (profile, quote)):
        raise ValueError("FMP SNDK identity did not match SanDisk")

    income = payloads["income-statement"]
    ratios = payloads["ratios"]
    revenue = _card_number(income.get("revenue"))
    net_income = _card_number(income.get("netIncome"))
    net_margin = _card_number(ratios.get("netProfitMargin"))
    if net_margin is None and revenue:
        net_margin = None if net_income is None else net_income / revenue

    fields = {
        "ticker": ticker,
        "name": profile.get("companyName") or quote.get("name") or COMPANY_NAMES.get(ticker, ticker),
        "market_cap": (
            _card_number(quote.get("marketCap"))
            or _card_number(profile.get("marketCap"))
        ),
        "revenue": revenue,
        "net_margin": net_margin,
        "financial_source": "FMP",
    }
    if fields["market_cap"] is None and fields["revenue"] is None and fields["net_margin"] is None and fields["name"] == COMPANY_NAMES.get(ticker, ticker):
        raise ValueError("FMP returned no usable card financial fields")
    return fields


def _yfinance_card_financial_fields(ticker):
    ticker = normalize_ticker(ticker)
    track_api_call("yfinance_card_financial_fallback")
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or COMPANY_NAMES.get(ticker, ticker),
        "market_cap": _card_number(info.get("marketCap")),
        "revenue": _card_number(info.get("totalRevenue")),
        "net_margin": _card_number(info.get("profitMargins")),
        "financial_source": "yfinance fallback",
    }


@st.cache_data(ttl=CARD_FINANCIAL_TTL_SECONDS)
def get_card_financial_fields(ticker):
    track_cacheable_call()
    ticker = normalize_ticker(ticker)
    try:
        fields = _fmp_card_financial_fields(ticker)
        if any(fields.get(key) is None for key in ("market_cap", "revenue", "net_margin")):
            fallback = _yfinance_card_financial_fields(ticker)
            for key in ("market_cap", "revenue", "net_margin"):
                if fields.get(key) is None:
                    fields[key] = fallback.get(key)
            if not fields.get("name") or fields["name"] == COMPANY_NAMES.get(ticker, ticker):
                fields["name"] = fallback.get("name") or fields["name"]
        return fields
    except Exception:
        try:
            return _yfinance_card_financial_fields(ticker)
        except Exception:
            return _empty_card_financial_fields(ticker)


@st.cache_data(ttl=300)
def get_card_snapshot(ticker):
    track_cacheable_call()
    ticker = normalize_ticker(ticker)
    try:
        quote = get_yfinance_quote_snapshot(ticker)
    except Exception:
        quote = {
            "ticker": ticker,
            "name": COMPANY_NAMES.get(ticker, ticker),
            "price": None,
            "change_pct": None,
            "market_cap": None,
            "revenue": None,
            "net_margin": None,
            "source": "unavailable",
            "role": supply_chain_role(ticker),
        }
    financials = get_card_financial_fields(ticker)
    financial_source = financials.get("financial_source") or "unavailable"
    return {
        **quote,
        "name": financials.get("name") or quote.get("name"),
        "market_cap": financials.get("market_cap") if financials.get("market_cap") is not None else quote.get("market_cap"),
        "revenue": financials.get("revenue"),
        "net_margin": financials.get("net_margin"),
        "source": f"{financial_source} financials + yfinance quote" if financial_source != "unavailable" else quote.get("source", "unavailable"),
        "role": supply_chain_role(ticker),
    }


def _snapshot_from_yfinance_fallback(ticker):
    quote = get_yfinance_quote_snapshot(ticker)
    keys = (
        "sector", "industry", "trailing_pe", "forward_pe", "price_to_book", "price_to_sales",
        "ev_to_ebitda", "return_on_equity", "return_on_assets", "gross_margin",
        "operating_margin", "free_cash_flow_margin", "current_ratio", "quick_ratio",
        "debt_to_equity", "revenue_growth_yoy", "gross_profit_growth",
        "operating_income_growth", "net_income_growth", "eps_growth", "analyst_target",
        "analyst_target_high", "analyst_target_low", "analyst_upside_pct", "analyst_rating",
        "next_earnings_date", "estimated_eps", "actual_eps", "eps_surprise",
        "days_until_earnings",
    )
    return {**quote, **{key: None for key in keys}, "source": "yfinance fallback"}


@st.cache_data(ttl=21600)
def get_company_snapshot(ticker):
    track_cacheable_call()
    try:
        track_api_call("fmp_financial_snapshot")
        return {**get_fmp_company_snapshot(ticker), "role": supply_chain_role(ticker)}
    except Exception:
        return _snapshot_from_yfinance_fallback(ticker)


@st.cache_data(ttl=300)
def get_technical_data(ticker, period="6mo"):
    track_cacheable_call()
    track_api_call("price_history")
    days = {"3mo": 100, "6mo": 190, "1y": 370, "2y": 740}.get(period, 190)
    data, source = fetch_historical_prices(ticker, date.today() - timedelta(days=days), date.today())
    if data.empty:
        raise ValueError("No technical data returned.")
    data = data.copy()
    data["MA5"] = data["Close"].rolling(5).mean()
    data["MA20"] = data["Close"].rolling(20).mean()
    data["RSI"] = calculate_rsi(data)
    data["Vol_MA20"] = data["Volume"].rolling(20).mean()
    data["Vol_Ratio"] = data["Volume"] / data["Vol_MA20"]
    data.attrs["source"] = source
    return data


@st.cache_data(ttl=600)
def get_option_expirations(ticker):
    track_cacheable_call()
    track_api_call("yfinance_option_expirations")
    stock = yf.Ticker(ticker)
    expirations = list(stock.options or [])
    return sorted(str(expiration) for expiration in expirations if expiration)


@st.cache_data(ttl=600)
def get_option_open_interest_totals(ticker, expiry):
    track_cacheable_call()
    track_api_call("yfinance_option_chain")
    try:
        chain = yf.Ticker(ticker).option_chain(expiry)
    except Exception:
        return {"calls_rows": 0, "puts_rows": 0, "total_call_oi": 0.0, "total_put_oi": 0.0}
    calls = chain.calls.copy() if chain.calls is not None else pd.DataFrame()
    puts = chain.puts.copy() if chain.puts is not None else pd.DataFrame()
    return {
        "calls_rows": len(calls),
        "puts_rows": len(puts),
        "total_call_oi": float(_option_open_interest(calls).sum()),
        "total_put_oi": float(_option_open_interest(puts).sum()),
    }


def select_default_option_expiry(ticker, expirations):
    state_key = f"option_expiry_{ticker}"
    previous = st.session_state.get(state_key)
    if previous in expirations:
        return expirations.index(previous)
    today_text = date.today().isoformat()
    future_expirations = [(index, expiration) for index, expiration in enumerate(expirations) if expiration >= today_text]
    for index, expiration in future_expirations:
        totals = get_option_open_interest_totals(ticker, expiration)
        if totals["total_call_oi"] > 0 or totals["total_put_oi"] > 0:
            return index
    for index, _ in future_expirations:
        return index
    return 0


def _option_open_interest(frame):
    if frame is None or frame.empty or "openInterest" not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["openInterest"], errors="coerce").fillna(0)


def _normalize_option_chain_frame(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    for field in ("openInterest", "impliedVolatility", "strike", "volume", "lastPrice", "bid", "ask", "gamma"):
        if field in normalized.columns:
            normalized[field] = pd.to_numeric(normalized[field], errors="coerce")
    if "openInterest" in normalized.columns:
        normalized["openInterest"] = normalized["openInterest"].fillna(0)
    return normalized


def _option_missing_reasons(calls, puts, gex_by_strike, current_price_available=True, chain_available=True):
    reasons = []
    if current_price_available and not chain_available:
        reasons.append("option_price_available_chain_unavailable")
    if calls.empty or puts.empty:
        reasons.append("option_call_put_empty")
    call_oi = _option_open_interest(calls)
    put_oi = _option_open_interest(puts)
    if (call_oi.empty and put_oi.empty) or (call_oi.sum() == 0 and put_oi.sum() == 0):
        reasons.append("option_open_interest_missing")
    has_usable_gamma = any(
        "gamma" in frame.columns and (pd.to_numeric(frame["gamma"], errors="coerce").fillna(0) > 0).any()
        for frame in (calls, puts) if frame is not None and not frame.empty
    )
    has_usable_iv = any(
        "impliedVolatility" in frame.columns and (pd.to_numeric(frame["impliedVolatility"], errors="coerce").fillna(0) > 0).any()
        for frame in (calls, puts) if frame is not None and not frame.empty
    )
    if not gex_by_strike and not (has_usable_gamma or has_usable_iv):
        reasons.append("option_gamma_missing")
    return reasons


@st.cache_data(ttl=600)
def get_options_data(ticker, expiry=None):
    track_cacheable_call()
    track_api_call("yfinance_options_data")
    stock = yf.Ticker(ticker)
    history = stock.history(period="1d")
    expirations = get_option_expirations(ticker)
    if history.empty:
        raise ValueError("No price data returned.")
    if not expirations:
        raise ValueError("No options data returned.")
    current_price = float(history["Close"].iloc[-1])
    exp_date = expiry if expiry in expirations else expirations[0]
    try:
        chain = stock.option_chain(exp_date)
    except Exception:
        return {
            "current_price": current_price,
            "exp_date": exp_date,
            "expirations": expirations,
            "pc_ratio": None,
            "call_wall": None,
            "put_wall": None,
            "max_pain": None,
            "net_gex": None,
            "calls_near_gex": 0,
            "total_call_oi": 0,
            "total_put_oi": 0,
            "calls": pd.DataFrame(),
            "puts": pd.DataFrame(),
            "gex_by_strike": {},
            "missing_reasons": ["option_price_available_chain_unavailable"],
            "source": "yfinance",
        }
    calls = _normalize_option_chain_frame(chain.calls)
    puts = _normalize_option_chain_frame(chain.puts)
    total_call_oi = float(_option_open_interest(calls).sum())
    total_put_oi = float(_option_open_interest(puts).sum())
    calls_above = calls[(calls["strike"] > current_price) & (calls["openInterest"] > 0)] if {"strike", "openInterest"}.issubset(calls.columns) else pd.DataFrame()
    puts_below = puts[(puts["strike"] < current_price) & (puts["openInterest"] > 0)] if {"strike", "openInterest"}.issubset(puts.columns) else pd.DataFrame()
    call_wall = calls_above.loc[calls_above["openInterest"].idxmax(), "strike"] if not calls_above.empty else None
    put_wall = puts_below.loc[puts_below["openInterest"].idxmax(), "strike"] if not puts_below.empty else None
    call_strikes = calls["strike"].dropna().tolist() if "strike" in calls else []
    put_strikes = puts["strike"].dropna().tolist() if "strike" in puts else []
    strikes = sorted(set(call_strikes + put_strikes))
    pain = {}
    if total_call_oi > 0 or total_put_oi > 0:
        for strike in strikes:
            call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum() if {"strike", "openInterest"}.issubset(calls.columns) else 0
            put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum() if {"strike", "openInterest"}.issubset(puts.columns) else 0
            pain[strike] = call_loss + put_loss
    total_gex = {}
    time_to_expiry = max((datetime.strptime(exp_date, "%Y-%m-%d") - datetime.now()).days / 365, 0.001)
    for option_type, direction in ((calls, 1), (puts, -1)):
        for _, row in option_type.iterrows():
            strike = row.get("strike")
            oi = row.get("openInterest", 0)
            gamma = row.get("gamma")
            volatility = row.get("impliedVolatility")
            if pd.isna(strike) or pd.isna(oi) or oi <= 0:
                continue
            if (gamma is None or pd.isna(gamma) or gamma == 0) and not pd.isna(volatility) and volatility > 0:
                gamma = black_scholes_gamma(current_price, strike, time_to_expiry, 0.05, volatility)
            if gamma is not None and not pd.isna(gamma) and gamma > 0:
                total_gex[strike] = total_gex.get(strike, 0) + direction * gamma * oi * 100 * current_price
    missing_reasons = _option_missing_reasons(calls, puts, total_gex)
    return {
        "current_price": current_price,
        "exp_date": exp_date,
        "expirations": expirations,
        "pc_ratio": None if total_call_oi == 0 else total_put_oi / total_call_oi,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "max_pain": min(pain, key=pain.get) if pain else None,
        "net_gex": sum(total_gex.values()) if total_gex else None,
        "calls_near_gex": sum(value for strike, value in total_gex.items() if value > 0 and current_price < strike < current_price * 1.1),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "calls": calls,
        "puts": puts,
        "gex_by_strike": total_gex,
        "missing_reasons": missing_reasons,
        "source": "yfinance",
    }


def _options_ai_language(language):
    language_text = str(language or "")
    language_lower = language_text.lower()
    if language_text == "\u4e2d\u6587" or language_lower in ("zh", "chinese"):
        return "\u4e2d\u6587"
    if language_text == "Espa\u00f1ol" or language_lower in ("es", "spanish", "espa\u00f1ol") or language_text.startswith("Espa"):
        return "Espa\u00f1ol"
    if language_text != "English":
        return "\u4e2d\u6587"
    return "English"


def _options_metric_text(value, kind="number"):
    if value is None or pd.isna(value):
        return "unavailable"
    if kind == "money":
        return format_money(value, 2)
    if kind == "money0":
        return format_money(value, 0)
    if kind == "ratio":
        return format_ratio(value)
    if kind == "integer":
        return f"{float(value):,.0f}"
    return f"{float(value):,.2f}"


def _options_metric_payload(ticker, opt):
    return {
        "ticker": ticker,
        "current_price": opt.get("current_price"),
        "put_call_open_interest_ratio": opt.get("pc_ratio"),
        "call_open_interest": opt.get("total_call_oi"),
        "put_open_interest": opt.get("total_put_oi"),
        "max_pain": opt.get("max_pain"),
        "net_gex": opt.get("net_gex"),
        "call_wall": opt.get("call_wall"),
        "put_wall": opt.get("put_wall"),
        "current_expiry_date": opt.get("exp_date"),
    }


def _options_structure_view(metrics):
    pc_ratio = metrics.get("put_call_open_interest_ratio")
    net_gex = metrics.get("net_gex")
    if net_gex is not None and not pd.isna(net_gex) and net_gex < 0:
        return "volatile"
    if pc_ratio is not None and not pd.isna(pc_ratio):
        if pc_ratio >= 1.3:
            return "bearish"
        if pc_ratio <= 0.7:
            return "bullish"
    return "neutral"


def _price_distance_pct(price, level):
    if price is None or level is None or pd.isna(price) or pd.isna(level) or float(price) == 0:
        return None
    return abs(float(price) - float(level)) / abs(float(price))


def build_options_ai_prompt(ticker, metrics, language):
    language = _options_ai_language(language)
    if language == "\u4e2d\u6587":
        language_instruction = (
            "\u7528\u7b80\u6d01\u4f46\u5177\u4f53\u7684\u4e2d\u6587\u8f93\u51fa\u3002\u4e0d\u8981\u53ea\u8bf4\u770b\u6da8\u6216\u770b\u8dcc\uff0c"
            "\u5fc5\u987b\u89e3\u91ca\u539f\u56e0\u3001\u6307\u51fa\u5173\u952e\u4ef7\u4f4d\uff0c\u5e76\u8bf4\u660e\u8d1f GEX \u7684\u542b\u4e49\u3002"
        )
    elif language == "Espa\u00f1ol":
        language_instruction = "Write the entire summary in concise Spanish."
    else:
        language_instruction = "Write the entire summary in concise English."
    return f"""
You are an options market structure analyst. Use only the supplied metrics. Do not invent or infer missing values.
If a metric is missing, say it is unavailable. Do not provide financial advice.
{language_instruction}

Ticker: {ticker}
Options metrics:
{json.dumps(metrics, indent=2, default=str)}

Write one concise paragraph that covers:
1. Current price.
2. Put/Call open interest ratio.
3. Call open interest and put open interest.
4. Max pain.
5. Net GEX.
6. Call wall.
7. Put wall.
8. Current expiry date.
9. Whether the options structure looks bullish, bearish, neutral, or volatile.
10. Whether negative GEX may amplify volatility.
11. Whether the call wall may act as upside resistance.
12. Whether the put wall may act as downside support or downside magnet.
13. Whether price is close to max pain.
14. Key levels traders should watch.
End with a clear risk disclaimer that this is not financial advice.
"""


def build_options_rule_based_summary(ticker, metrics, language):
    language = _options_ai_language(language)
    price = metrics.get("current_price")
    pc_ratio = metrics.get("put_call_open_interest_ratio")
    call_oi = metrics.get("call_open_interest")
    put_oi = metrics.get("put_open_interest")
    max_pain = metrics.get("max_pain")
    net_gex = metrics.get("net_gex")
    call_wall = metrics.get("call_wall")
    put_wall = metrics.get("put_wall")
    expiry = metrics.get("current_expiry_date") or "unavailable"
    view = _options_structure_view(metrics)
    max_pain_distance = _price_distance_pct(price, max_pain)
    max_pain_close = max_pain_distance is not None and max_pain_distance <= 0.03
    key_levels = [
        _options_metric_text(price, "money"),
        _options_metric_text(max_pain, "money0"),
        _options_metric_text(call_wall, "money0"),
        _options_metric_text(put_wall, "money0"),
    ]
    key_levels = ", ".join(dict.fromkeys(level for level in key_levels if level != "unavailable")) or "unavailable"

    if language == "\u4e2d\u6587":
        view_text = {
            "bullish": "\u504f\u770b\u6da8",
            "bearish": "\u504f\u770b\u8dcc",
            "neutral": "\u504f\u4e2d\u6027",
            "volatile": "\u504f\u9ad8\u6ce2\u52a8",
        }[view]
        gex_text = (
            f"\u51c0 GEX \u4e3a {_options_metric_text(net_gex, 'money0')}\uff0c\u5c5e\u4e8e\u8d1f Gamma \u73af\u5883\uff0c\u505a\u5e02\u5546\u5bf9\u51b2\u53ef\u80fd\u653e\u5927\u4ef7\u683c\u6ce2\u52a8\u3002"
            if net_gex is not None and not pd.isna(net_gex) and net_gex < 0
            else f"\u51c0 GEX \u4e3a {_options_metric_text(net_gex, 'money0')}\uff0c\u8d1f GEX \u653e\u5927\u6ce2\u52a8\u7684\u4fe1\u53f7\u4e0d\u660e\u663e\u3002"
        )
        pain_text = "\u63a5\u8fd1" if max_pain_close else "\u4e0d\u63a5\u8fd1"
        return (
            f"\u5f53\u524d {ticker} \u5230\u671f\u65e5 {expiry} \u7684\u671f\u6743\u7ed3\u6784{view_text}\u3002"
            f"\u73b0\u4ef7\u4e3a {_options_metric_text(price, 'money')}\uff0cPut/Call OI \u6bd4\u7387\u4e3a {_options_metric_text(pc_ratio, 'ratio')}\uff0c"
            f"\u770b\u6da8\u672a\u5e73\u4ed3\u91cf\u4e3a {_options_metric_text(call_oi, 'integer')}\uff0c\u770b\u8dcc\u672a\u5e73\u4ed3\u91cf\u4e3a {_options_metric_text(put_oi, 'integer')}\u3002"
            f"{gex_text}\u6700\u5927\u75db\u70b9\u5728 {_options_metric_text(max_pain, 'money0')}\uff0c\u5f53\u524d\u4ef7\u683c{pain_text}\u6700\u5927\u75db\u70b9\u3002"
            f"Call wall \u5728 {_options_metric_text(call_wall, 'money0')}\uff0c\u53ef\u80fd\u662f\u4e0a\u65b9\u538b\u529b\u533a\uff1bPut wall \u5728 {_options_metric_text(put_wall, 'money0')}\uff0c\u53ef\u80fd\u662f\u4e0b\u65b9\u652f\u6491\u6216\u4e0b\u884c\u5438\u5f15\u533a\u3002"
            f"\u5173\u952e\u4ef7\u4f4d\u5173\u6ce8\uff1a{key_levels}\u3002\u98ce\u9669\u63d0\u793a\uff1a\u8fd9\u4e0d\u662f\u6295\u8d44\u5efa\u8bae\u3002"
        )

    if language == "Espa\u00f1ol":
        view_text = {"bullish": "alcista", "bearish": "bajista", "neutral": "neutral", "volatile": "vol\u00e1til"}[view]
        gex_text = (
            f"El GEX neto es {_options_metric_text(net_gex, 'money0')}, un entorno de gamma negativa que puede amplificar la volatilidad por coberturas de creadores de mercado."
            if net_gex is not None and not pd.isna(net_gex) and net_gex < 0
            else f"El GEX neto es {_options_metric_text(net_gex, 'money0')}; la se\u00f1al de gamma negativa que amplifica volatilidad no es clara."
        )
        pain_text = "cerca de" if max_pain_close else "lejos de"
        return (
            f"La estructura de opciones de {ticker} para el vencimiento {expiry} parece {view_text}. "
            f"El precio actual es {_options_metric_text(price, 'money')}, el ratio put/call de inter\u00e9s abierto es {_options_metric_text(pc_ratio, 'ratio')}, "
            f"con inter\u00e9s abierto call de {_options_metric_text(call_oi, 'integer')} y put de {_options_metric_text(put_oi, 'integer')}. "
            f"{gex_text} El m\u00e1ximo dolor est\u00e1 en {_options_metric_text(max_pain, 'money0')}, y el precio est\u00e1 {pain_text} ese nivel. "
            f"El call wall en {_options_metric_text(call_wall, 'money0')} puede actuar como resistencia al alza; el put wall en {_options_metric_text(put_wall, 'money0')} puede actuar como soporte o im\u00e1n bajista. "
            f"Niveles clave a vigilar: {key_levels}. Aviso de riesgo: esto no es asesoramiento financiero."
        )

    gex_text = (
        f"Net GEX is {_options_metric_text(net_gex, 'money0')}, a negative gamma setup where dealer hedging may amplify volatility."
        if net_gex is not None and not pd.isna(net_gex) and net_gex < 0
        else f"Net GEX is {_options_metric_text(net_gex, 'money0')}; the negative-GEX volatility amplification signal is not clear."
    )
    pain_text = "close to" if max_pain_close else "not close to"
    return (
        f"{ticker} options structure for expiry {expiry} looks {view}. "
        f"Current price is {_options_metric_text(price, 'money')}, the put/call open interest ratio is {_options_metric_text(pc_ratio, 'ratio')}, "
        f"with call open interest of {_options_metric_text(call_oi, 'integer')} and put open interest of {_options_metric_text(put_oi, 'integer')}. "
        f"{gex_text} Max pain is {_options_metric_text(max_pain, 'money0')}, and price is {pain_text} max pain. "
        f"The call wall at {_options_metric_text(call_wall, 'money0')} may act as upside resistance; the put wall at {_options_metric_text(put_wall, 'money0')} may act as downside support or a downside magnet. "
        f"Key levels to watch: {key_levels}. Risk disclaimer: this is not financial advice."
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def generate_options_ai_summary(ticker, expiry, metrics, language, summary_version="options_ai_summary_v1"):
    fallback = build_options_rule_based_summary(ticker, metrics, language)
    try:
        client = get_openai_client()
    except Exception:
        return fallback
    try:
        prompt = build_options_ai_prompt(ticker, metrics, language)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        summary = (response.choices[0].message.content or "").strip()
        return summary or fallback
    except Exception:
        return fallback


def render_snapshot_card(container, snapshot):
    change = snapshot["change_pct"] or 0
    delta_color = "#22c55e" if change >= 0 else "#ef4444"
    container.markdown(
        f"""
        <div class="stock-card">
          <div class="ticker">{snapshot["ticker"]}</div>
          <div class="company">{snapshot["name"]}</div>
          <div class="source">{t("source")}: {snapshot["source"]}</div>
          <div class="price">{format_money(snapshot["price"], 2)}</div>
          <div class="change" style="color:{delta_color}">{change:+.2f}% {t("today")}</div>
          <div class="card-grid">
            <span>{t("market_cap")}<b>{format_money(snapshot["market_cap"])}</b></span>
            <span>{t("revenue")}<b>{format_money(snapshot["revenue"])}</b></span>
            <span>{t("net_margin")}<b>{"N/A" if snapshot["net_margin"] is None else f'{snapshot["net_margin"] * 100:.1f}%'}</b></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_row(metrics):
    columns = st.columns(len(metrics))
    for column, (label, value, *delta) in zip(columns, metrics):
        column.metric(label, value, delta[0] if delta else None)


def filter_options_near_price(options, current_price, price_range=0.2):
    if options is None or options.empty or "strike" not in options or "openInterest" not in options:
        return pd.DataFrame()
    filtered = options[
        (options["strike"] >= current_price * (1 - price_range))
        & (options["strike"] <= current_price * (1 + price_range))
    ]
    return filtered if not filtered.empty else options


def render_option_chain_chart(ticker, option_type, options, current_price, exp_date, color):
    filtered = filter_options_near_price(options, current_price)
    if filtered.empty:
        st.warning(t("option_call_put_empty"))
        return
    fig = go.Figure(go.Bar(
        x=filtered["strike"],
        y=filtered["openInterest"],
        marker_color=color,
        name=f"{option_type} {t('open_interest')}",
    ))
    fig.add_vline(x=current_price, line_dash="dash", line_color="yellow")
    fig.update_layout(
        template="plotly_dark",
        height=300,
        title=f"{ticker} {option_type} | {t('open_interest')} | {exp_date}",
        xaxis_title=t("strike"),
        yaxis_title=t("open_interest"),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_{exp_date}_{option_type.lower()}_options")


def render_gex_chart(ticker, gex_by_strike, current_price, exp_date):
    if not gex_by_strike:
        st.warning(f"{ticker} {t('gex_chart_unavailable')}")
        return
    strikes, values = zip(*sorted(gex_by_strike.items()))
    colors = ["#22c55e" if value >= 0 else "#ef4444" for value in values]
    fig = go.Figure(go.Bar(x=strikes, y=values, marker_color=colors, name="Net GEX"))
    fig.add_vline(x=current_price, line_dash="dash", line_color="yellow")
    fig.update_layout(
        template="plotly_dark",
        height=320,
        title=f"{ticker} {t('gamma_exposure_by_strike')}",
        xaxis_title=t("strike"),
        yaxis_title=t("net_gex"),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_{exp_date}_gex")


def render_technical_section():
    st.caption(t("technical_caption"))
    for ticker in load_watchlist():
        with st.expander(f"{ticker} | {company_name(ticker)}", expanded=ticker == "NVDA"):
            try:
                data = get_technical_data(ticker)
                rsi = float(data["RSI"].iloc[-1])
                signal = t("overbought") if rsi > 70 else t("oversold") if rsi < 30 else t("neutral")
                render_metric_row([
                    (t("price"), format_money(data["Close"].iloc[-1], 2)),
                    ("RSI (14)", f"{rsi:.1f}"),
                    (t("rsi_signal"), signal),
                    (t("volume_vs_20d"), f"{data['Vol_Ratio'].iloc[-1]:.2f}x"),
                ])
                st.line_chart(data[["Close", "MA5", "MA20"]], height=260)
                st.caption(f"{t('historical_price_source')}: {data.attrs.get('source', 'N/A')}")
            except Exception as exc:
                st.warning(f"{ticker} {t('technical_unavailable')}: {exc}")


def render_options_section():
    st.caption(t("options_caption"))
    watchlist = load_watchlist()
    if not watchlist:
        st.warning(t("options_unavailable"))
        return
    ticker = st.selectbox(t("select_ticker"), watchlist, key="options_selected_ticker")
    with st.spinner("Loading options data..."):
        try:
            expirations = get_option_expirations(ticker)
            if not expirations:
                st.warning(t("option_expirations_not_found"))
                return
            previous = st.session_state.get(f"option_expiry_{ticker}")
            today_text = date.today().isoformat()
            default_expiry = previous if previous in expirations else next(
                (expiration for expiration in expirations if expiration >= today_text),
                expirations[0],
            )
            selected_expiry = st.selectbox(
                t("option_expiry"),
                expirations,
                index=expirations.index(default_expiry),
                key=f"option_expiry_{ticker}",
            )
            st.caption(f"{t('current_expiry')}: {selected_expiry}")
            opt = get_options_data(ticker, selected_expiry)
        except Exception as exc:
            st.warning(f"{ticker} {t('options_unavailable')}: {exc}")
            return
    try:
                st.caption(
                    f"calls rows: {len(opt['calls'])} | puts rows: {len(opt['puts'])} | "
                    f"call OI: {opt['total_call_oi']:,.0f} | put OI: {opt['total_put_oi']:,.0f} | "
                    f"expiry: {opt['exp_date']} | source: {opt.get('source', 'N/A')}"
                )
                render_metric_row([
                    (t("price"), format_money(opt["current_price"], 2)),
                    (t("put_call_ratio"), format_ratio(opt["pc_ratio"])),
                    (t("max_pain"), format_money(opt["max_pain"], 0)),
                    (t("net_gex"), format_money(opt["net_gex"], 0)),
                    (t("call_wall"), format_money(opt["call_wall"], 0)),
                    (t("put_wall"), format_money(opt["put_wall"], 0)),
                ])
                squeeze = t("high") if opt["calls_near_gex"] > 1_000_000 else t("medium") if opt["calls_near_gex"] > 500_000 else t("low")
                if opt["net_gex"] is None:
                    regime = t("gex_unavailable")
                elif opt["net_gex"] >= 0:
                    regime = t("positive_gex")
                else:
                    regime = t("negative_gex")
                st.info(f"{t('gamma_squeeze_risk')}: {squeeze}. {regime} {t('current_expiry')}: {opt['exp_date']}.")
                if "option_open_interest_missing" in opt.get("missing_reasons", []):
                    st.warning(f"{t('option_open_interest_missing')}. {t('option_expiry')}: {selected_expiry}.")
                for reason in opt.get("missing_reasons", []):
                    if reason == "option_open_interest_missing":
                        continue
                    st.warning(t(reason))
                st.markdown(f"#### {t('options_ai_summary')}")
                st.caption(t("options_ai_summary_disclaimer"))
                summary_language = st.session_state.get("language", "English")
                summary_metrics = _options_metric_payload(ticker, opt)
                summary_cache_key = hashlib.sha256(json.dumps(
                    {
                        "ticker": ticker,
                        "expiry": opt["exp_date"],
                        "language": summary_language,
                        "metrics": summary_metrics,
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")).hexdigest()
                summary_state_key = f"options_ai_summary_{summary_cache_key}"
                if st.button(t("generate_options_ai_summary"), key=f"generate_options_ai_summary_{ticker}_{opt['exp_date']}"):
                    st.session_state[summary_state_key] = generate_options_ai_summary(
                        ticker,
                        opt["exp_date"],
                        summary_metrics,
                        summary_language,
                    )
                if st.session_state.get(summary_state_key):
                    st.info(st.session_state[summary_state_key])
                else:
                    st.caption(t("options_ai_summary_idle"))
                chart_columns = st.columns(2)
                with chart_columns[0]:
                    render_option_chain_chart(ticker, "Call", opt["calls"], opt["current_price"], opt["exp_date"], "#22c55e")
                with chart_columns[1]:
                    render_option_chain_chart(ticker, "Put", opt["puts"], opt["current_price"], opt["exp_date"], "#ef4444")
                render_gex_chart(ticker, opt["gex_by_strike"], opt["current_price"], opt["exp_date"])
    except Exception as exc:
        st.warning(f"{ticker} {t('options_unavailable')}: {exc}")


def render_value_section(snapshots=None):
    st.caption(t("value_caption"))
    for ticker in load_watchlist():
        snapshot = None
        try:
            snapshot = get_company_snapshot(ticker)
        except Exception:
            snapshot = (snapshots or {}).get(ticker)
        with st.expander(f"{ticker} | {company_name(ticker, snapshot)}", expanded=ticker == "NVDA"):
            st.markdown(f"**{ticker} | {company_name(ticker, snapshot)}**")
            st.caption(supply_chain_role(ticker))
            if not snapshot:
                st.write(t("valuation_unavailable"))
                continue
            st.caption(f"{t('source')}: {snapshot['source']} | {snapshot.get('sector') or 'N/A'} | {snapshot.get('industry') or 'N/A'}")
            render_metric_row([
                ("P/E", format_ratio(snapshot["trailing_pe"])),
                ("P/B", format_ratio(snapshot["price_to_book"])),
                ("P/S", format_ratio(snapshot["price_to_sales"])),
                ("EV/EBITDA", format_ratio(snapshot["ev_to_ebitda"])),
                ("ROE", format_percent(snapshot["return_on_equity"])),
                ("ROA", format_percent(snapshot["return_on_assets"])),
            ])
            render_metric_row([
                (t("gross_margin"), format_percent(snapshot["gross_margin"])),
                (t("operating_margin"), format_percent(snapshot["operating_margin"])),
                (t("net_margin"), format_percent(snapshot["net_margin"])),
                (t("fcf_margin"), format_percent(snapshot["free_cash_flow_margin"])),
                (t("current_ratio"), format_ratio(snapshot["current_ratio"])),
                (t("quick_ratio"), format_ratio(snapshot["quick_ratio"])),
                (t("debt_equity"), format_ratio(snapshot["debt_to_equity"])),
            ])
            render_metric_row([
                (t("revenue_yoy"), format_percent(snapshot["revenue_growth_yoy"])),
                (t("gross_profit_growth"), format_percent(snapshot["gross_profit_growth"])),
                (t("operating_income_growth"), format_percent(snapshot["operating_income_growth"])),
                (t("net_income_growth"), format_percent(snapshot["net_income_growth"])),
                (t("eps_growth"), format_percent(snapshot["eps_growth"])),
            ])
            render_metric_row([
                (t("current_price"), format_money(snapshot["price"], 2)),
                (t("consensus_target"), format_money(snapshot["analyst_target"], 2)),
                (t("high_target"), format_money(snapshot["analyst_target_high"], 2)),
                (t("low_target"), format_money(snapshot["analyst_target_low"], 2)),
                (t("upside_downside"), "N/A" if snapshot["analyst_upside_pct"] is None else f"{snapshot['analyst_upside_pct']:+.1f}%"),
                (t("analyst_rating"), snapshot.get("analyst_rating") or "N/A"),
            ])


def _quarter_label_from_date(value):
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return f"{timestamp.year}Q{timestamp.quarter}"


def _normalize_quarter_label(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper().replace(" ", "")
    match = re.fullmatch(r"(\d{4})Q([1-4])", text)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    return _quarter_label_from_date(value)


def _quarter_sort_key(quarter):
    match = re.fullmatch(r"(\d{4})Q([1-4])", str(quarter or ""))
    if not match:
        return pd.NA
    return int(match.group(1)) * 4 + int(match.group(2))


def _current_quarter_label():
    today = pd.Timestamp.today()
    return f"{today.year}Q{today.quarter}"


def _quarter_range(start_quarter="2008Q1", end_quarter=None):
    end_quarter = end_quarter or _current_quarter_label()
    start_key = _quarter_sort_key(start_quarter)
    end_key = _quarter_sort_key(end_quarter)
    if pd.isna(start_key) or pd.isna(end_key) or end_key < start_key:
        return []
    labels = []
    for key in range(int(start_key), int(end_key) + 1):
        year = (key - 1) // 4
        quarter = key - year * 4
        labels.append(f"{year}Q{quarter}")
    return labels


def _first_existing_column(frame, candidates):
    normalized_columns = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in candidates:
        column = normalized_columns.get(candidate.lower())
        if column is not None:
            return column
    return None


def _load_existing_nasdaq100_valuation_history():
    if not os.path.exists(US_MARKET_VALUATION_FILE):
        return pd.DataFrame(columns=["Quarter", NASDAQ100_FORWARD_PE_COLUMN])
    try:
        raw = pd.read_csv(US_MARKET_VALUATION_FILE)
    except Exception:
        return pd.DataFrame(columns=["Quarter", NASDAQ100_FORWARD_PE_COLUMN])

    quarter_col = _first_existing_column(raw, ["Quarter", "Date", "Period"])
    pe_col = _first_existing_column(raw, [
        NASDAQ100_FORWARD_PE_COLUMN,
        "Nasdaq 100 Forward P/E",
        "Nasdaq-100 Forward PE",
        "Nasdaq 100 Forward PE",
        "Forward P/E",
        "Forward PE",
        "Nasdaq-100 P/E",
        "Nasdaq 100 P/E",
        "NDX P/E",
        "P/E",
        "PE",
        "pe",
    ])
    if quarter_col is None:
        return pd.DataFrame(columns=["Quarter", NASDAQ100_FORWARD_PE_COLUMN])

    frame = pd.DataFrame({"Quarter": raw[quarter_col].map(_normalize_quarter_label)})
    frame[NASDAQ100_FORWARD_PE_COLUMN] = pd.to_numeric(raw[pe_col], errors="coerce") if pe_col is not None else np.nan
    frame = frame.dropna(subset=["Quarter"]).drop_duplicates(subset=["Quarter"], keep="last")
    frame["_sort"] = frame["Quarter"].map(_quarter_sort_key)
    return frame.sort_values("_sort").drop(columns="_sort")


def _quarterly_ndx_metrics():
    track_api_call("yfinance_ndx_market_score")
    ndx = yf.download("^NDX", start="2007-12-01", progress=False, auto_adjust=False)
    if ndx is None or ndx.empty:
        raise ValueError("No ^NDX price data returned.")
    close = ndx["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        raise ValueError("No usable ^NDX close prices returned.")
    moving_average_200d = close.rolling(200, min_periods=120).mean()
    try:
        quarterly_close = close.resample("Q").last()
        quarterly_ma_200d = moving_average_200d.resample("Q").last()
    except ValueError as exc:
        if "Q" not in str(exc):
            raise
        quarterly_close = close.resample("QE").last()
        quarterly_ma_200d = moving_average_200d.resample("QE").last()
    frame = pd.DataFrame({
        "Date": quarterly_close.index,
        "Nasdaq-100 Close": quarterly_close.values,
        "Nasdaq-100 200D MA": quarterly_ma_200d.reindex(quarterly_close.index).values,
    })
    frame["Quarter"] = frame["Date"].map(_quarter_label_from_date)
    frame["Nasdaq-100 Quarterly Return %"] = frame["Nasdaq-100 Close"].pct_change() * 100
    frame["Nasdaq-100 6M Return %"] = frame["Nasdaq-100 Close"].pct_change(2) * 100
    frame["Nasdaq-100 12M Return %"] = frame["Nasdaq-100 Close"].pct_change(4) * 100
    frame["Nasdaq-100 vs 200D MA %"] = (
        frame["Nasdaq-100 Close"] / frame["Nasdaq-100 200D MA"] - 1
    ) * 100
    frame["Nasdaq-100 Drawdown %"] = (
        frame["Nasdaq-100 Close"] / frame["Nasdaq-100 Close"].cummax() - 1
    ) * 100
    return frame[[
        "Quarter",
        "Nasdaq-100 Quarterly Return %",
        "Nasdaq-100 6M Return %",
        "Nasdaq-100 12M Return %",
        "Nasdaq-100 vs 200D MA %",
        "Nasdaq-100 Drawdown %",
    ]]


def _quarterly_yfinance_yield_series(symbol, column_name):
    track_api_call(f"yfinance_{symbol}_market_score")
    data = yf.download(symbol, start="2007-12-01", progress=False, auto_adjust=False)
    if data is None or data.empty:
        raise ValueError(f"No {symbol} yield data returned.")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        raise ValueError(f"No usable {symbol} yield data returned.")
    try:
        quarterly = close.resample("Q").last()
    except ValueError as exc:
        if "Q" not in str(exc):
            raise
        quarterly = close.resample("QE").last()
    frame = quarterly.dropna().reset_index()
    frame.columns = ["Date", column_name]
    frame["Quarter"] = frame["Date"].map(_quarter_label_from_date)
    frame[column_name] = pd.to_numeric(frame[column_name], errors="coerce")
    if frame[column_name].dropna().median() > 15:
        frame[column_name] = frame[column_name] / 10.0
    return frame[["Quarter", column_name]]


def _quarterly_yfinance_relative_strength(primary_symbol, secondary_symbol, column_name):
    track_api_call(f"yfinance_{primary_symbol}_{secondary_symbol}_market_score")
    data = yf.download([primary_symbol, secondary_symbol], start="2007-12-01", progress=False, auto_adjust=True)
    if data is None or data.empty:
        raise ValueError(f"No {primary_symbol}/{secondary_symbol} price data returned.")
    close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
    if primary_symbol not in close or secondary_symbol not in close:
        raise ValueError(f"No usable {primary_symbol}/{secondary_symbol} close prices returned.")
    primary = pd.to_numeric(close[primary_symbol], errors="coerce")
    secondary = pd.to_numeric(close[secondary_symbol], errors="coerce")
    relative = (primary / secondary).replace([np.inf, -np.inf], np.nan).dropna()
    if relative.empty:
        raise ValueError(f"No usable {primary_symbol}/{secondary_symbol} relative strength data returned.")
    try:
        quarterly = relative.resample("Q").last()
    except ValueError as exc:
        if "Q" not in str(exc):
            raise
        quarterly = relative.resample("QE").last()
    frame = quarterly.dropna().reset_index()
    frame.columns = ["Date", "HYG/LQD Ratio"]
    frame["Quarter"] = frame["Date"].map(_quarter_label_from_date)
    frame[column_name] = frame["HYG/LQD Ratio"].pct_change(2) * 100
    return frame[["Quarter", column_name]]


def _quarterly_vix_metrics():
    track_api_call("yfinance_vix_market_score")
    vix = yf.download("^VIX", start="2007-12-01", progress=False, auto_adjust=False)
    if vix is None or vix.empty:
        raise ValueError("No ^VIX data returned.")
    close = vix["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if close.empty:
        raise ValueError("No usable ^VIX close prices returned.")
    try:
        quarterly = close.resample("Q").mean()
    except ValueError as exc:
        if "Q" not in str(exc):
            raise
        quarterly = close.resample("QE").mean()
    frame = quarterly.dropna().reset_index()
    frame.columns = ["Date", "VIX"]
    frame["Quarter"] = frame["Date"].map(_quarter_label_from_date)
    return frame[["Quarter", "VIX"]]


def _score_lower_better(value, best, worst):
    if value is None or pd.isna(value):
        return np.nan
    if best == worst:
        return 50.0
    score = (worst - float(value)) / (worst - best) * 100
    return float(np.clip(score, 0, 100))


def _score_higher_better(value, worst, best):
    if value is None or pd.isna(value):
        return np.nan
    if best == worst:
        return 50.0
    score = (float(value) - worst) / (best - worst) * 100
    return float(np.clip(score, 0, 100))


def _fear_greed_label(value):
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    if value <= 24:
        return "Extreme Fear"
    if value <= 44:
        return "Fear"
    if value <= 55:
        return "Neutral"
    if value <= 75:
        return "Greed"
    return "Extreme Greed"


def _mean_score_with_fallback(scores):
    values = [50.0 if score is None or pd.isna(score) else float(score) for score in scores]
    used_fallback = any(score is None or pd.isna(score) for score in scores)
    return float(np.clip(np.mean(values), 0, 100)), used_fallback


def _valuation_forward_return_score(pe, earnings_yield):
    pe_score = np.nan
    ey_score = np.nan
    if pe is not None and pd.notna(pe):
        pe_value = float(pe)
        pe_score = np.interp(
            pe_value,
            [18.0, 20.0, 23.0, 25.0, 30.0, 35.0],
            [95.0, 80.0, 65.0, 55.0, 35.0, 18.0],
            left=95.0,
            right=10.0,
        )
    if earnings_yield is not None and pd.notna(earnings_yield):
        ey_score = _score_higher_better(earnings_yield, 2.0, 5.0)
        if pd.notna(ey_score):
            ey_score = float(np.clip(ey_score, 10.0, 95.0))

    scores = []
    if pd.notna(pe_score):
        scores.append((float(pe_score), 0.85))
    if pd.notna(ey_score):
        scores.append((float(ey_score), 0.15))
    if not scores:
        return 50.0, True
    total_weight = sum(weight for _, weight in scores)
    score = sum(score * weight for score, weight in scores) / total_weight
    used_fallback = len(scores) < 2
    return float(np.clip(score, 10.0, 95.0)), used_fallback


def _market_score_components(row):
    curve_score = _score_higher_better(row.get("10Y-Short Treasury Spread %"), -1.5, 2.0)
    yield_curve_score, yield_curve_fallback = _mean_score_with_fallback([curve_score])

    trend_position_score = _score_higher_better(row.get("Nasdaq-100 vs 200D MA %"), -20.0, 20.0)
    yield_score = _score_lower_better(row.get("10Y Treasury Yield %"), 2.0, 6.0)
    vix_score = _score_lower_better(row.get("VIX"), 15.0, 35.0)
    credit_risk_appetite_score = _score_higher_better(row.get("HYG/LQD 6M Relative Strength %"), -8.0, 8.0)
    liquidity_score, liquidity_fallback = _mean_score_with_fallback([
        yield_score,
        vix_score,
        credit_risk_appetite_score,
    ])

    six_month_score = _score_higher_better(row.get("Nasdaq-100 6M Return %"), -20.0, 25.0)
    twelve_month_score = _score_higher_better(row.get("Nasdaq-100 12M Return %"), -35.0, 45.0)
    sentiment_score, sentiment_fallback = _mean_score_with_fallback([
        six_month_score,
        twelve_month_score,
        trend_position_score,
    ])

    valuation_score, valuation_fallback = _valuation_forward_return_score(
        row.get(NASDAQ100_FORWARD_PE_COLUMN),
        row.get(FORWARD_EARNINGS_YIELD_COLUMN),
    )

    crowding_base = 50.0
    twelve_month_return = row.get("Nasdaq-100 12M Return %")
    pe = row.get(NASDAQ100_FORWARD_PE_COLUMN)
    if pd.notna(twelve_month_return) and pd.notna(pe):
        crowding_base += np.clip((25.0 - float(twelve_month_return)) * 1.2, -30, 20)
        crowding_base += np.clip((28.0 - float(pe)) * 1.6, -30, 20)
        if float(twelve_month_return) < 0 and float(pe) < 28.0:
            crowding_base += min(20.0, abs(float(twelve_month_return)) * 0.8 + (28.0 - float(pe)) * 1.2)
    crowding_price_score = float(np.clip(crowding_base, 0, 100))
    crowding_score, crowding_fallback = _mean_score_with_fallback([crowding_price_score, vix_score])

    final_score = (
        yield_curve_score * 0.20
        + liquidity_score * 0.25
        + sentiment_score * 0.20
        + valuation_score * 0.20
        + crowding_score * 0.15
    )
    return pd.Series({
        "Yield Curve Score": yield_curve_score,
        "Liquidity / Credit Score": liquidity_score,
        "Investor Sentiment / Trend Score": sentiment_score,
        "Valuation / Forward Return Score": valuation_score,
        "Crowding / Risk Discipline Score": crowding_score,
        "Final Market Score": float(np.clip(final_score, 0, 100)),
        "Yield Curve Status": "Fallback neutral" if yield_curve_fallback else "Live data: yfinance",
        "Liquidity / Credit Status": "Fallback neutral" if liquidity_fallback else "Live data: yfinance",
        "Investor Sentiment / Trend Status": "Fallback neutral" if sentiment_fallback else "Live data: yfinance",
        "Valuation / Forward Return Status": "Fallback neutral" if valuation_fallback else "Live data: yfinance",
        "Crowding / Risk Discipline Status": "Fallback neutral" if crowding_fallback else "Live data: yfinance",
        "Uses Fallback Score": any([
            yield_curve_fallback,
            liquidity_fallback,
            sentiment_fallback,
            valuation_fallback,
            crowding_fallback,
        ]),
    })


def _us_market_score_component_rows(latest_score_row):
    score_columns = [
        ("Yield Curve Score", 20, "Yield Curve Status"),
        ("Liquidity / Credit Score", 25, "Liquidity / Credit Status"),
        ("Investor Sentiment / Trend Score", 20, "Investor Sentiment / Trend Status"),
        ("Valuation / Forward Return Score", 20, "Valuation / Forward Return Status"),
        ("Crowding / Risk Discipline Score", 15, "Crowding / Risk Discipline Status"),
    ]
    return [
        {
            "Component": label,
            "Weight": f"{weight}%",
            "Score": None if pd.isna(latest_score_row.get(label)) else round(float(latest_score_row.get(label)), 1),
            "Status / Data Source": latest_score_row.get(status_column) or "Live data: yfinance",
        }
        for label, weight, status_column in score_columns
    ]


def _as_numeric_score(value):
    if isinstance(value, str):
        value = value.replace("%", "").strip()
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return np.nan
    return float(np.clip(float(numeric_value), 0, 100))


def _cnn_timestamp_to_date(value):
    if value is None or pd.isna(value):
        return pd.NaT
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return pd.to_datetime(value, errors="coerce").date()
    unit = "ms" if numeric_value > 10_000_000_000 else "s"
    return pd.to_datetime(numeric_value, unit=unit, errors="coerce").date()


def _score_at_or_before(history, target_date):
    if history is None or history.empty:
        return None
    frame = history.dropna(subset=["Date", "Fear & Greed"]).copy()
    if frame.empty:
        return None
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).sort_values("Date")
    target = pd.Timestamp(target_date)
    values = frame[frame["Date"] <= target]
    if values.empty:
        return None
    return float(values.iloc[-1]["Fear & Greed"])


def _cnn_fear_greed_from_payload(payload, source_url=None):
    current = payload.get("fear_and_greed") or payload.get("fearAndGreed") or {}
    current_value = _as_numeric_score(
        current.get("score")
        or current.get("value")
        or payload.get("score")
        or payload.get("value")
    )

    historical = (
        payload.get("fear_and_greed_historical")
        or payload.get("fearAndGreedHistorical")
        or payload.get("historical")
        or {}
    )
    raw_points = historical.get("data") if isinstance(historical, dict) else historical
    history_rows = []
    if isinstance(raw_points, list):
        for point in raw_points:
            if not isinstance(point, dict):
                continue
            point_date = _cnn_timestamp_to_date(
                point.get("x") or point.get("timestamp") or point.get("date")
            )
            point_value = _as_numeric_score(point.get("y") or point.get("score") or point.get("value"))
            if pd.notna(point_date) and pd.notna(point_value):
                history_rows.append({"Date": point_date, "Fear & Greed": point_value})
    history = pd.DataFrame(history_rows)
    used_historical_current = False
    if not history.empty:
        history = history.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
        if pd.isna(current_value):
            current_value = float(history.iloc[-1]["Fear & Greed"])
            used_historical_current = True

    if pd.isna(current_value):
        raise ValueError("CNN payload did not include a usable Fear & Greed score.")

    today = date.today()
    return {
        "current": float(current_value),
        "label": _fear_greed_label(current_value),
        "one_week_ago": _score_at_or_before(history, today - timedelta(days=7)),
        "one_month_ago": _score_at_or_before(history, today - timedelta(days=30)),
        "one_year_ago": _score_at_or_before(history, today - timedelta(days=365)),
        "history": history,
        "status": "Live data: CNN Fear & Greed",
        "source": "CNN",
        "source_caption": "Source: CNN",
        "source_url": source_url,
        "source_priority": "CNN historical" if used_historical_current else "CNN current",
        "historical_available": not history.empty,
        "debug": {
            "cnn_source_url": source_url,
            "cnn_used_historical_current": used_historical_current,
        },
    }


@st.cache_data(ttl=60 * 60)
def _fetch_cnn_fear_greed_index():
    track_cacheable_call()
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cnn.com/markets/fear-and-greed",
    }
    start_date = (date.today() - timedelta(days=400)).isoformat()
    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start_date}",
    ]
    errors = []
    session = requests.Session()
    session.trust_env = False
    for url in urls:
        try:
            track_api_call("cnn_fear_greed")
            response = session.get(url, headers=headers, timeout=8)
            response.raise_for_status()
            return _cnn_fear_greed_from_payload(response.json(), source_url=url)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise ValueError("CNN Fear & Greed unavailable: " + " | ".join(errors))


def _safe_close_series(data, symbol=None):
    if data is None or data.empty:
        return pd.Series(dtype=float)
    close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data.get("Close", data)
    if isinstance(close, pd.DataFrame):
        if symbol is not None and symbol in close:
            close = close[symbol]
        else:
            close = close.iloc[:, 0]
    return pd.to_numeric(close, errors="coerce").dropna()


def _fear_greed_proxy_history():
    track_api_call("yfinance_fear_greed_proxy")
    symbols = ["^VIX", "^NDX", "HYG", "LQD", "QQQ", "TLT", "IEF"]
    data = yf.download(symbols, period="2y", progress=False, auto_adjust=True, group_by="column")
    series = {symbol: _safe_close_series(data, symbol) for symbol in symbols}
    if series["TLT"].empty:
        series["TLT"] = series["IEF"]

    frame = pd.DataFrame({
        "VIX": series["^VIX"],
        "NDX": series["^NDX"],
        "HYG": series["HYG"],
        "LQD": series["LQD"],
        "QQQ": series["QQQ"],
        "TLT": series["TLT"],
    }).dropna(how="all")
    if frame.empty:
        raise ValueError("No yfinance data returned for Fear & Greed proxy.")

    vix_score = frame["VIX"].map(lambda value: _score_lower_better(value, 12.0, 35.0))
    momentum_score = (frame["NDX"].pct_change(63) * 100).map(lambda value: _score_higher_better(value, -15.0, 20.0))
    credit_ratio = frame["HYG"] / frame["LQD"]
    credit_score = (credit_ratio.pct_change(63) * 100).map(lambda value: _score_higher_better(value, -5.0, 5.0))
    qqq_ma50 = frame["QQQ"].rolling(50, min_periods=30).mean()
    qqq_ma200 = frame["QQQ"].rolling(200, min_periods=120).mean()
    breadth_proxy = ((((frame["QQQ"] / qqq_ma50) - 1) + ((frame["QQQ"] / qqq_ma200) - 1)) / 2 * 100)
    breadth_score = breadth_proxy.map(lambda value: _score_higher_better(value, -10.0, 10.0))
    safe_haven_ratio = frame["QQQ"] / frame["TLT"]
    safe_haven_score = (safe_haven_ratio.pct_change(63) * 100).map(lambda value: _score_higher_better(value, -15.0, 20.0))

    proxy = (
        vix_score * 0.30
        + momentum_score * 0.25
        + credit_score * 0.20
        + breadth_score * 0.15
        + safe_haven_score * 0.10
    )
    history = pd.DataFrame({
        "Date": pd.to_datetime(proxy.index).date,
        "Fear & Greed": proxy.clip(0, 100),
    }).dropna()
    if history.empty:
        raise ValueError("Fear & Greed proxy could not be calculated.")
    return history


@st.cache_data(ttl=6 * 60 * 60)
def _fallback_fear_greed_index():
    track_cacheable_call()
    history = _fear_greed_proxy_history()
    current = float(history.iloc[-1]["Fear & Greed"])
    latest_date = pd.to_datetime(history.iloc[-1]["Date"]).date()
    return {
        "current": current,
        "label": _fear_greed_label(current),
        "one_week_ago": _score_at_or_before(history, latest_date - timedelta(days=7)),
        "one_month_ago": _score_at_or_before(history, latest_date - timedelta(days=30)),
        "one_year_ago": _score_at_or_before(history, latest_date - timedelta(days=365)),
        "history": history,
        "status": "Fallback proxy: yfinance",
        "source": "yfinance proxy",
        "source_caption": "Source: yfinance proxy",
        "source_priority": "yfinance fallback proxy",
        "historical_available": not history.empty,
    }


def get_fear_greed_index():
    try:
        return _fetch_cnn_fear_greed_index()
    except Exception as cnn_error:
        try:
            fallback = _fallback_fear_greed_index()
            fallback["warning"] = "CNN unavailable; using yfinance proxy."
            fallback["debug"] = {
                **fallback.get("debug", {}),
                "cnn_error": str(cnn_error),
            }
            return fallback
        except Exception as fallback_error:
            return {
                "current": None,
                "label": "N/A",
                "one_week_ago": None,
                "one_month_ago": None,
                "one_year_ago": None,
                "history": pd.DataFrame(columns=["Date", "Fear & Greed"]),
                "status": "Unavailable",
                "source": "unavailable",
                "source_caption": "Source: unavailable",
                "historical_available": False,
                "warning": "Fear & Greed unavailable.",
                "debug": {
                    "cnn_error": str(cnn_error),
                    "fallback_error": str(fallback_error),
                },
            }


@st.cache_data(ttl=7 * 24 * 60 * 60)
def get_us_market_valuation_dashboard_data():
    track_cacheable_call()
    valuation = _load_existing_nasdaq100_valuation_history()
    market_proxy_errors = []
    try:
        market_metrics = _quarterly_ndx_metrics()
    except Exception as exc:
        market_proxy_errors.append(f"^NDX: {exc}")
        market_metrics = pd.DataFrame(columns=[
            "Quarter",
            "Nasdaq-100 Quarterly Return %",
            "Nasdaq-100 6M Return %",
            "Nasdaq-100 12M Return %",
            "Nasdaq-100 vs 200D MA %",
            "Nasdaq-100 Drawdown %",
        ])

    try:
        vix_metrics = _quarterly_vix_metrics()
    except Exception as exc:
        market_proxy_errors.append(f"^VIX: {exc}")
        vix_metrics = pd.DataFrame(columns=["Quarter", "VIX"])

    market_proxy_series = []
    for symbol, column_name in (
        ("^TNX", "10Y Treasury Yield %"),
        ("^IRX", "13W Treasury Yield %"),
        ("^FVX", "5Y Treasury Yield %"),
    ):
        try:
            market_proxy_series.append(_quarterly_yfinance_yield_series(symbol, column_name))
        except Exception as exc:
            market_proxy_errors.append(f"{symbol}: {exc}")
            market_proxy_series.append(pd.DataFrame(columns=["Quarter", column_name]))

    try:
        market_proxy_series.append(_quarterly_yfinance_relative_strength("HYG", "LQD", "HYG/LQD 6M Relative Strength %"))
    except Exception as exc:
        market_proxy_errors.append(f"HYG/LQD: {exc}")
        market_proxy_series.append(pd.DataFrame(columns=["Quarter", "HYG/LQD 6M Relative Strength %"]))

    latest_quarter = _current_quarter_label()
    if not valuation.empty:
        latest_quarter = max(latest_quarter, valuation["Quarter"].max(), key=_quarter_sort_key)
    if not market_metrics.empty:
        latest_quarter = max(latest_quarter, market_metrics["Quarter"].max(), key=_quarter_sort_key)

    quarters = pd.DataFrame({"Quarter": _quarter_range("2008Q1", latest_quarter)})
    frame = quarters.merge(valuation, on="Quarter", how="left").merge(market_metrics, on="Quarter", how="left")
    for series_frame in market_proxy_series:
        frame = frame.merge(series_frame, on="Quarter", how="left")
    frame = frame.merge(vix_metrics, on="Quarter", how="left")
    frame["_sort"] = frame["Quarter"].map(_quarter_sort_key)
    frame = frame.sort_values("_sort").drop(columns="_sort")
    frame[FORWARD_EARNINGS_YIELD_COLUMN] = np.where(
        frame[NASDAQ100_FORWARD_PE_COLUMN] > 0,
        100 / frame[NASDAQ100_FORWARD_PE_COLUMN],
        np.nan,
    )
    short_rate = frame["13W Treasury Yield %"].combine_first(frame["5Y Treasury Yield %"])
    frame["10Y-Short Treasury Spread %"] = frame["10Y Treasury Yield %"] - short_rate
    component_frame = frame.apply(_market_score_components, axis=1)
    frame = pd.concat([frame, component_frame], axis=1)
    latest_score_rows = frame.dropna(subset=["Final Market Score"], how="all")
    latest_uses_fallback = (
        bool(latest_score_rows.iloc[-1].get("Uses Fallback Score"))
        if not latest_score_rows.empty
        else False
    )
    score_components = (
        pd.DataFrame(_us_market_score_component_rows(latest_score_rows.iloc[-1]))
        if not latest_score_rows.empty
        else pd.DataFrame(columns=["Component", "Weight", "Score", "Status / Data Source"])
    )
    warnings = []
    if market_proxy_errors:
        warnings.append("Some market proxy data unavailable. Using neutral fallback values.")
    return {
        "data": frame,
        "last_updated": date.today().isoformat(),
        "market_proxy_errors": market_proxy_errors,
        "warnings": warnings,
        "score_components": score_components,
        "uses_fallback_score": latest_uses_fallback,
        "valuation_source": US_MARKET_VALUATION_FILE if os.path.exists(US_MARKET_VALUATION_FILE) else None,
    }


def _latest_numeric(frame, column):
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return None if values.empty else float(values.iloc[-1])


def _format_signed_percent_value(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):+.1f}%"


def _format_fear_greed_value(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.0f}"


def _us_market_summary_language(language):
    language_text = str(language or "")
    if language_text == "中文" or language_text.lower() in ("zh", "chinese"):
        return "中文"
    if language_text == "Español" or language_text.lower() in ("es", "spanish", "español") or language_text.startswith("Espa"):
        return "Español"
    return "English"


def _market_score_band(score, language):
    if score is None or pd.isna(score):
        messages = {
            "中文": ("数据不足", "当前 Final Market Score 暂不可用，无法判断市场区间。"),
            "Español": ("Datos insuficientes", "El Final Market Score actual no esta disponible, por lo que no se puede clasificar el entorno de mercado."),
            "English": ("Insufficient data", "The current Final Market Score is unavailable, so the market regime cannot be classified."),
        }
        return messages[_us_market_summary_language(language)]

    score = float(score)
    language = _us_market_summary_language(language)
    if score <= 30:
        return {
            "中文": ("市场环境很差", "市场环境很差，风险较高，适合防守。"),
            "Español": ("Entorno muy debil", "El entorno de mercado es muy debil, con riesgo elevado; favorece una postura defensiva."),
            "English": ("Very weak environment", "The market environment is very weak, risk is elevated, and a defensive stance is more appropriate."),
        }[language]
    if score <= 50:
        return {
            "中文": ("市场偏弱", "市场偏弱，适合谨慎参与，控制仓位。"),
            "Español": ("Mercado debil", "El mercado esta debil; conviene participar con cautela y controlar la exposicion."),
            "English": ("Weak market", "The market is weak; cautious participation and position control are appropriate."),
        }[language]
    if score <= 70:
        return {
            "中文": ("中性偏乐观", "市场中性偏好，风险资产环境相对友好，但仍需要注意估值和回撤风险。"),
            "Español": ("Neutral a favorable", "El mercado es neutral a favorable para activos de riesgo, aunque siguen importando la valoracion y el riesgo de caidas."),
            "English": ("Neutral to constructive", "The market is neutral to constructive for risk assets, while valuation and drawdown risk still matter."),
        }[language]
    if score <= 85:
        return {
            "中文": ("市场较强", "市场较强，趋势和风险偏好较好，但需要开始注意拥挤和追高风险。"),
            "Español": ("Mercado fuerte", "El mercado esta fuerte, con mejor tendencia y apetito por riesgo, pero aumenta el riesgo de congestion y perseguir precios."),
            "English": ("Strong market", "The market is strong, with better trend and risk appetite, but crowding and chasing risk are becoming more important."),
        }[language]
    return {
        "中文": ("市场非常强", "市场非常强，但可能过热、贪婪、交易拥挤，不适合盲目追高。"),
        "Español": ("Mercado muy fuerte", "El mercado esta muy fuerte, pero puede estar sobrecalentado, codicioso y congestionado; no favorece perseguir precios sin disciplina."),
        "English": ("Very strong market", "The market is very strong, but may be overheated, greedy, and crowded; blind chasing is not appropriate."),
    }[language]


def _fear_greed_bilingual_label(value, language):
    label = _fear_greed_label(value)
    language = _us_market_summary_language(language)
    translations = {
        "中文": {
            "Extreme Fear": "Extreme Fear，极度恐惧",
            "Fear": "Fear，恐惧",
            "Neutral": "Neutral，中性",
            "Greed": "Greed，贪婪",
            "Extreme Greed": "Extreme Greed，极度贪婪",
            "N/A": "N/A",
        },
        "Español": {
            "Extreme Fear": "Extreme Fear, miedo extremo",
            "Fear": "Fear, miedo",
            "Neutral": "Neutral, neutral",
            "Greed": "Greed, codicia",
            "Extreme Greed": "Extreme Greed, codicia extrema",
            "N/A": "N/A",
        },
        "English": {
            "Extreme Fear": "Extreme Fear",
            "Fear": "Fear",
            "Neutral": "Neutral",
            "Greed": "Greed",
            "Extreme Greed": "Extreme Greed",
            "N/A": "N/A",
        },
    }
    return translations[language].get(label, label)


def _score_tone(score, language):
    if score is None or pd.isna(score):
        return {"中文": "暂无可用分数", "Español": "sin puntuacion disponible", "English": "no score available"}[_us_market_summary_language(language)]
    score = float(score)
    language = _us_market_summary_language(language)
    if score >= 70:
        return {"中文": "当前偏强", "Español": "actualmente fuerte", "English": "currently strong"}[language]
    if score >= 50:
        return {"中文": "当前中性偏好", "Español": "actualmente neutral a favorable", "English": "currently neutral to constructive"}[language]
    if score >= 30:
        return {"中文": "当前偏弱", "Español": "actualmente debil", "English": "currently weak"}[language]
    return {"中文": "当前很弱", "Español": "actualmente muy debil", "English": "currently very weak"}[language]


def _render_market_score_summary(latest_score_row, fear_greed, language):
    language = _us_market_summary_language(language)
    score = None if latest_score_row is None else latest_score_row.get("Final Market Score")
    pe = None if latest_score_row is None else latest_score_row.get(NASDAQ100_FORWARD_PE_COLUMN)
    earnings_yield = None if latest_score_row is None else latest_score_row.get(FORWARD_EARNINGS_YIELD_COLUMN)
    score_value = None if score is None or pd.isna(score) else float(score)
    pe_text = "N/A" if pe is None or pd.isna(pe) else f"{float(pe):.1f}x"
    earnings_yield_text = "N/A" if earnings_yield is None or pd.isna(earnings_yield) else f"{float(earnings_yield):.2f}%"
    band_label, band_description = _market_score_band(score_value, language)
    fear_greed_current = fear_greed.get("current")
    fear_greed_text = "N/A" if fear_greed_current is None or pd.isna(fear_greed_current) else f"{float(fear_greed_current):.0f}"
    fear_greed_label = _fear_greed_bilingual_label(fear_greed_current, language)
    source_is_cnn = fear_greed.get("source") == "CNN"

    component_explanations = [
        ("Yield Curve Score", {
            "中文": "收益率曲线分数。越高代表利率结构更正常，对经济和市场更友好；越低代表倒挂或利率压力更明显。",
            "Español": "Puntuacion de la curva de rendimientos. Una lectura mas alta indica una estructura de tasas mas normal y favorable; una mas baja senala inversion o presion de tasas.",
            "English": "Yield curve score. Higher means the rate structure is more normal and supportive; lower points to inversion or rate pressure.",
        }),
        ("Liquidity / Credit Score", {
            "中文": "流动性和信用环境分数。越高说明融资环境和信用风险偏好较好；越低说明市场融资条件偏紧，信用压力较大。",
            "Español": "Puntuacion de liquidez y credito. Mas alta sugiere mejores condiciones de financiacion y apetito por riesgo crediticio; mas baja indica condiciones mas estrictas.",
            "English": "Liquidity and credit score. Higher suggests better financing conditions and credit risk appetite; lower indicates tighter funding and more credit stress.",
        }),
        ("Investor Sentiment / Trend Score", {
            "中文": "投资者情绪和趋势分数。越高说明市场趋势更强，投资者更愿意买入；越低说明趋势走弱，风险偏好下降。",
            "Español": "Puntuacion de sentimiento y tendencia. Mas alta indica una tendencia mas fuerte y mas disposicion a comprar; mas baja senala debilidad y menor apetito por riesgo.",
            "English": "Investor sentiment and trend score. Higher indicates stronger trend and willingness to buy; lower signals weaker trend and falling risk appetite.",
        }),
        ("Valuation / Forward Return Score", {
            "中文": "估值和未来收益分数。越高说明 Forward P/E 较合理，未来预期收益更有吸引力；越低说明估值偏贵，未来回报空间被压缩。",
            "Español": "Puntuacion de valoracion y retorno esperado. Mas alta implica un Forward P/E mas razonable y retornos esperados mas atractivos; mas baja indica valoracion exigente.",
            "English": "Valuation and forward return score. Higher means Forward P/E is more reasonable and expected returns are more attractive; lower means valuation is expensive.",
        }),
        ("Crowding / Risk Discipline Score", {
            "中文": "拥挤度和风险纪律分数。越高说明市场尚未极端拥挤，风险相对可控；越低说明涨幅过大、估值过高或情绪过热，容易出现回撤。",
            "Español": "Puntuacion de congestion y disciplina de riesgo. Mas alta indica que el mercado no esta extremadamente congestionado; mas baja senala subidas excesivas, valoracion alta o euforia.",
            "English": "Crowding and risk discipline score. Higher means the market is not extremely crowded; lower points to stretched gains, valuation, or overheated sentiment.",
        }),
    ]

    with st.container():
        st.markdown("#### Market Score Summary")
        if language == "中文":
            st.write(
                f"当前 Final Market Score 为 {'N/A' if score_value is None else f'{score_value:.1f}'}，"
                f"属于“{band_label}”区间。{band_description} 这说明当前市场环境整体支持风险资产的程度需要结合估值、情绪和回撤风险一起判断，并不代表无风险买入信号。"
            )
            st.markdown("**子分数解读**")
            for component, texts in component_explanations:
                value = None if latest_score_row is None else latest_score_row.get(component)
                score_text = "N/A" if value is None or pd.isna(value) else f"{float(value):.1f}"
                st.markdown(f"- **{component}：{score_text}**，{_score_tone(value, language)}。{texts[language]}")
            source_text = (
                "当前 Fear & Greed 来自 CNN 官方数据。该指标反映市场短期恐惧或贪婪程度，只作为参考，不参与 Final Market Score。"
                if source_is_cnn
                else "当前 Fear & Greed 使用 yfinance proxy，因为 CNN 官方数据不可用。该指标只作为市场情绪参考，不参与 Final Market Score。"
            )
            st.write(f"{source_text} 当前数值为 {fear_greed_text}，属于 {fear_greed_label}。")
            st.write(
                f"Forward P/E 当前为 {pe_text}，表示 Nasdaq-100 基于未来预期盈利的市盈率。数值越高，代表市场对未来盈利的定价越贵。"
            )
            st.write(
                f"Forward Earnings Yield 当前为 {earnings_yield_text}，公式为 Forward Earnings Yield = 100 / Forward P/E。"
                "它表示按照未来预期盈利计算，每 100 美元指数价格对应多少美元预期盈利；越高估值越便宜，越低估值越贵。"
            )
            sentiment_hot = fear_greed_current is not None and pd.notna(fear_greed_current) and float(fear_greed_current) > 75
            if score_value is not None and score_value >= 70 and sentiment_hot:
                conclusion = "综合来看，当前市场趋势和风险偏好较强，但 Fear & Greed 已经偏高，说明短期情绪较热。当前环境适合继续观察和持有强趋势资产，但不适合盲目追高或大幅加杠杆。"
            elif score_value is not None and score_value >= 50:
                conclusion = "综合来看，当前市场环境对风险资产相对友好，但仍需要关注估值、情绪升温和潜在回撤风险。更适合有纪律地持有或分批参与，而不是盲目追高。"
            else:
                conclusion = "综合来看，当前市场环境偏弱或数据不足，风险资产的胜率不够明确。更适合控制仓位、等待趋势和流动性信号改善。"
            st.markdown(f"**最终结论：**{conclusion}")
        elif language == "Español":
            st.write(f"El Final Market Score actual es {'N/A' if score_value is None else f'{score_value:.1f}'}, en la zona de \"{band_label}\". {band_description}")
            st.markdown("**Lectura de componentes**")
            for component, texts in component_explanations:
                value = None if latest_score_row is None else latest_score_row.get(component)
                score_text = "N/A" if value is None or pd.isna(value) else f"{float(value):.1f}"
                st.markdown(f"- **{component}: {score_text}**, {_score_tone(value, language)}. {texts[language]}")
            source_text = "Fear & Greed viene de datos oficiales de CNN." if source_is_cnn else "Fear & Greed usa un proxy de yfinance porque los datos oficiales de CNN no estan disponibles."
            st.write(f"{source_text} Es solo una referencia de sentimiento y no participa en el Final Market Score. Valor actual: {fear_greed_text}, {fear_greed_label}.")
            st.write(f"Forward P/E: {pe_text}. Mide el P/E del Nasdaq-100 basado en beneficios esperados; cuanto mas alto, mas cara es la valoracion.")
            st.write(f"Forward Earnings Yield: {earnings_yield_text}. Formula: Forward Earnings Yield = 100 / Forward P/E. Cuanto mas alto, mas barata es la valoracion; cuanto mas bajo, mas cara.")
            st.markdown("**Conclusion:** El entorno debe leerse junto con tendencia, sentimiento, valoracion y disciplina de riesgo; no es una senal para perseguir precios sin control.")
        else:
            st.write(f"The current Final Market Score is {'N/A' if score_value is None else f'{score_value:.1f}'}, in the \"{band_label}\" zone. {band_description}")
            st.markdown("**Component Read-Through**")
            for component, texts in component_explanations:
                value = None if latest_score_row is None else latest_score_row.get(component)
                score_text = "N/A" if value is None or pd.isna(value) else f"{float(value):.1f}"
                st.markdown(f"- **{component}: {score_text}**, {_score_tone(value, language)}. {texts[language]}")
            source_text = "Fear & Greed comes from official CNN data." if source_is_cnn else "Fear & Greed uses a yfinance proxy because official CNN data is unavailable."
            st.write(f"{source_text} It is a sentiment reference only and does not feed into the Final Market Score. Current value: {fear_greed_text}, {fear_greed_label}.")
            st.write(f"Forward P/E is {pe_text}. It is the Nasdaq-100 P/E based on expected future earnings; higher means the market is pricing those earnings more expensively.")
            st.write(f"Forward Earnings Yield is {earnings_yield_text}. Formula: Forward Earnings Yield = 100 / Forward P/E. Higher means cheaper valuation; lower means more expensive valuation.")
            st.markdown("**Conclusion:** Read the setup through trend, sentiment, valuation, and risk discipline; it is not a signal to chase prices without controls.")


def _render_us_market_value_card(label, value, color):
    st.markdown(
        f"""
        <div style="background:#050608;border:1px solid #1f2937;border-radius:8px;padding:12px 14px;">
            <div style="font-size:0.76rem;color:#9ca3af;">{html.escape(label)}</div>
            <div style="font-size:1.35rem;font-weight:700;color:{color};">{html.escape(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _filter_us_market_chart_frame(frame, view):
    quarter_counts = {
        "3Y": 12,
        "5Y": 20,
        "10Y": 40,
    }
    count = quarter_counts.get(view)
    if count is None:
        return frame.copy()
    return frame.tail(count).copy()


def _us_market_valuation_chart(frame):
    plot_frame = frame.copy()
    plot_frame["x"] = plot_frame["Quarter"]
    fig = make_subplots(
        specs=[[{"secondary_y": True}]],
    )
    fig.add_trace(
        go.Scatter(
            x=plot_frame["x"],
            y=plot_frame[NASDAQ100_FORWARD_PE_COLUMN],
            name=NASDAQ100_FORWARD_PE_COLUMN,
            mode="lines",
            line=dict(color="#2dd4bf", width=2.6),
            connectgaps=True,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_frame["x"],
            y=plot_frame["Final Market Score"],
            name="Final Market Score",
            mode="lines",
            line=dict(color="#f59e0b", width=2.2, dash="dash"),
            connectgaps=True,
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_frame["x"],
            y=plot_frame["Nasdaq-100 Quarterly Return %"],
            name="Nasdaq-100 Quarterly Return",
            mode="lines",
            line=dict(color="#38bdf8", width=2),
            connectgaps=False,
        ),
        secondary_y=True,
    )
    latest_pe = _latest_numeric(plot_frame, NASDAQ100_FORWARD_PE_COLUMN)
    latest_score = _latest_numeric(plot_frame, "Final Market Score")
    latest_return = _latest_numeric(plot_frame, "Nasdaq-100 Quarterly Return %")
    annotations = []
    if latest_pe is not None:
        annotations.append(dict(x=1.01, y=latest_pe, xref="paper", yref="y", text=f"Forward P/E: {latest_pe:.1f}x", showarrow=False, font=dict(color="#2dd4bf", size=12), xanchor="left"))
    if latest_score is not None:
        annotations.append(dict(x=1.01, y=latest_score, xref="paper", yref="y2", text=f"Score: {latest_score:.1f}", showarrow=False, font=dict(color="#f59e0b", size=12), xanchor="left"))
    if latest_return is not None:
        annotations.append(dict(x=1.01, y=latest_return, xref="paper", yref="y2", text=f"Quarterly Return: {latest_return:+.1f}%", showarrow=False, font=dict(color="#38bdf8", size=12), xanchor="left"))
    fig.update_layout(
        height=680,
        paper_bgcolor="#050608",
        plot_bgcolor="#050608",
        font=dict(color="#d1d5db"),
        margin=dict(l=60, r=180, t=50, b=55),
        title=dict(text="US Market Valuation Dashboard", font=dict(size=22, color="#f9fafb")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        annotations=annotations,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, tickangle=0, nticks=18, color="#9ca3af")
    fig.update_yaxes(title_text="Forward P/E", gridcolor="rgba(148,163,184,0.14)", zeroline=False, color="#9ca3af", secondary_y=False)
    fig.update_yaxes(title_text="Score / Quarterly Return %", gridcolor="rgba(148,163,184,0.08)", zeroline=True, zerolinecolor="rgba(255,255,255,0.25)", color="#9ca3af", secondary_y=True)
    return fig


def _render_fear_greed_expander(fear_greed):
    with st.expander("Fear & Greed Index", expanded=False):
        current = fear_greed.get("current")
        label = fear_greed.get("label") or _fear_greed_label(current)
        status = fear_greed.get("status") or "Unavailable"
        source_caption = fear_greed.get("source_caption") or "Source: unavailable"
        is_cnn = fear_greed.get("source") == "CNN"
        source_label = "CNN" if is_cnn else "Proxy"
        if current is None or pd.isna(current):
            st.markdown("**Current:** N/A")
            st.caption(f"Status: {status}")
            st.caption(source_caption)
            if fear_greed.get("warning"):
                st.info(str(fear_greed["warning"]))
            return

        st.markdown(f"**{source_label} Current:** {_format_fear_greed_value(current)} · {label}")
        st.caption(f"Status: {status}")
        st.caption(source_caption)
        if fear_greed.get("warning"):
            st.info(str(fear_greed["warning"]))

        history_values = [
            ("1 week ago", fear_greed.get("one_week_ago")),
            ("1 month ago", fear_greed.get("one_month_ago")),
            ("1 year ago", fear_greed.get("one_year_ago")),
        ]
        available_history = [(period, value) for period, value in history_values if value is not None and pd.notna(value)]
        if available_history:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Period": period,
                        "Value": _format_fear_greed_value(value),
                        "Status": _fear_greed_label(value),
                        "Source": "CNN historical" if is_cnn else "Proxy historical",
                    }
                    for period, value in history_values
                ]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("historical values unavailable")

        history = fear_greed.get("history")
        if isinstance(history, pd.DataFrame) and not history.empty:
            fg_fig = go.Figure()
            fg_fig.add_trace(go.Scatter(
                x=history["Date"],
                y=history["Fear & Greed"],
                name="CNN Fear & Greed Index" if is_cnn else "Fear & Greed Index (yfinance proxy)",
                mode="lines",
                line=dict(color="#c084fc", width=2),
            ))
            fg_fig.update_layout(
                height=300,
                paper_bgcolor="#050608",
                plot_bgcolor="#050608",
                font=dict(color="#d1d5db"),
                margin=dict(l=50, r=30, t=30, b=45),
                yaxis_title="0-100",
                hovermode="x unified",
            )
            fg_fig.update_xaxes(showgrid=False, color="#9ca3af", nticks=12)
            fg_fig.update_yaxes(range=[0, 100], gridcolor="rgba(148,163,184,0.14)", color="#9ca3af")
            st.plotly_chart(fg_fig, use_container_width=True)

def render_us_market_valuation_dashboard():
    st.markdown("### US Market Valuation Dashboard")
    chart_view = st.radio(
        "Time range",
        ["3Y", "5Y", "10Y", "All"],
        index=1,
        horizontal=True,
        label_visibility="collapsed",
        key="us_market_valuation_chart_view",
    )
    st.caption(f"Quarterly · {chart_view} view · 2008Q1-latest available quarter")
    dashboard = get_us_market_valuation_dashboard_data()
    fear_greed = get_fear_greed_index()
    frame = dashboard["data"]
    chart_frame = _filter_us_market_chart_frame(frame, chart_view)
    st.caption(f"Last updated: {dashboard['last_updated']}")
    for warning in dashboard.get("warnings", []):
        st.warning(warning)
    if not dashboard["valuation_source"]:
        st.warning("Nasdaq-100 Forward P/E history not found. Add data/us_market_valuation.csv with Quarter and Nasdaq-100 Forward P/E columns to populate the valuation series.")
    if frame.empty or frame[[NASDAQ100_FORWARD_PE_COLUMN, "Final Market Score", "Nasdaq-100 Quarterly Return %"]].dropna(how="all").empty:
        st.info("No US market valuation data available yet.")
        return

    pe = _latest_numeric(frame, NASDAQ100_FORWARD_PE_COLUMN)
    score = _latest_numeric(frame, "Final Market Score")
    quarterly_return = _latest_numeric(frame, "Nasdaq-100 Quarterly Return %")
    fear_greed_current = fear_greed.get("current")
    fear_greed_label = fear_greed.get("label") or _fear_greed_label(fear_greed_current)
    card_cols = st.columns(4)
    with card_cols[0]:
        _render_us_market_value_card("Forward P/E", "N/A" if pe is None else f"{pe:.1f}x", "#2dd4bf")
    with card_cols[1]:
        _render_us_market_value_card("Final Market Score", "N/A" if score is None else f"{score:.1f}", "#f59e0b")
    with card_cols[2]:
        _render_us_market_value_card("Quarterly Return", _format_signed_percent_value(quarterly_return), "#38bdf8")
    with card_cols[3]:
        fear_greed_card_value = "N/A" if fear_greed_current is None or pd.isna(fear_greed_current) else f"{float(fear_greed_current):.0f} · {fear_greed_label}"
        _render_us_market_value_card("Fear & Greed", fear_greed_card_value, "#c084fc")
        st.caption(fear_greed.get("source_caption") or "Source: unavailable")
        if fear_greed.get("warning"):
            st.info(str(fear_greed["warning"]))
    st.plotly_chart(_us_market_valuation_chart(chart_frame), use_container_width=True)

    latest_score_rows = frame.dropna(subset=["Final Market Score"], how="all")
    latest_score_row = latest_score_rows.iloc[-1] if not latest_score_rows.empty else None
    _render_market_score_summary(latest_score_row, fear_greed, st.session_state.get("language", "English"))

    score_components = dashboard.get("score_components")
    if score_components is not None and not score_components.empty:
        fear_greed_is_cnn = fear_greed.get("source") == "CNN"
        fear_greed_reference_component = (
            "CNN Fear & Greed Index"
            if fear_greed_is_cnn
            else "Fear & Greed Index (yfinance proxy)"
        )
        fear_greed_reference_status = "Live data: CNN" if fear_greed_is_cnn else "Fallback proxy: yfinance"
        reference_row = pd.DataFrame([{
            "Component": fear_greed_reference_component,
            "Weight": "Reference only",
            "Score": None if fear_greed_current is None or pd.isna(fear_greed_current) else round(float(fear_greed_current), 1),
            "Status / Data Source": fear_greed_reference_status,
        }])
        score_components = pd.concat([score_components, reference_row], ignore_index=True)
        st.markdown("#### Latest Quarterly Score Components")
        st.dataframe(score_components, use_container_width=True, hide_index=True)

    _render_fear_greed_expander(fear_greed)

    with st.expander("Forward Earnings Yield", expanded=False):
        earnings_yield_frame = chart_frame[["Quarter", FORWARD_EARNINGS_YIELD_COLUMN]].dropna()
        if earnings_yield_frame.empty:
            st.info("Forward Earnings Yield is unavailable until Nasdaq-100 Forward P/E history is available.")
        else:
            ey_fig = go.Figure()
            ey_fig.add_trace(go.Scatter(
                x=earnings_yield_frame["Quarter"],
                y=earnings_yield_frame[FORWARD_EARNINGS_YIELD_COLUMN],
                name="Forward Earnings Yield",
                mode="lines",
                line=dict(color="#a7f3d0", width=2),
            ))
            ey_fig.update_layout(
                height=300,
                paper_bgcolor="#050608",
                plot_bgcolor="#050608",
                font=dict(color="#d1d5db"),
                margin=dict(l=50, r=30, t=30, b=45),
                yaxis_title="%",
                hovermode="x unified",
            )
            ey_fig.update_xaxes(showgrid=False, color="#9ca3af", nticks=16)
            ey_fig.update_yaxes(gridcolor="rgba(148,163,184,0.14)", color="#9ca3af")
            st.plotly_chart(ey_fig, use_container_width=True)


@st.cache_data(ttl=1800)
def get_cached_company_news(ticker, limit=5):
    track_cacheable_call()
    track_api_call("fmp_company_news")
    try:
        return fetch_company_news(ticker, limit)
    except Exception:
        return []


@st.cache_data(ttl=1800)
def get_cached_watchlist_news(tickers, limit_per_ticker=20):
    track_cacheable_call()
    results = []
    for ticker in tickers:
        try:
            results.extend(get_cached_company_news(ticker, limit_per_ticker))
        except Exception:
            continue
    return results


@st.cache_data(ttl=1800)
def get_cached_market_news(limit=150):
    track_cacheable_call()
    track_api_call("fmp_market_news")
    try:
        return fetch_general_news(limit)
    except Exception:
        return []


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


@st.cache_data(ttl=1800)
def get_cached_yahoo_news(ticker, limit=10):
    track_cacheable_call()
    track_api_call("yfinance_news")
    ticker = ticker.upper()
    stock = yf.Ticker(ticker)
    raw_news = []
    try:
        raw_news = stock.get_news(count=limit) or []
    except TypeError:
        raw_news = stock.get_news() or []
    except Exception:
        raw_news = stock.news or []
    if not raw_news:
        try:
            raw_news = stock.news or []
        except Exception:
            raw_news = []
    normalized = []
    for item in raw_news:
        normalized_item = _normalize_yfinance_news_item(item, ticker)
        if normalized_item:
            normalized.append(normalized_item)
        if len(normalized) >= limit:
            break
    return normalized


@st.cache_data(ttl=1800)
def get_cached_watchlist_yahoo_news(tickers, limit_per_ticker=10):
    track_cacheable_call()
    news = {}
    for ticker in tickers:
        try:
            news[ticker] = get_cached_yahoo_news(ticker, limit_per_ticker)
        except Exception:
            news[ticker] = []
    return news


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


def get_trendforce_news(limit=20):
    track_api_call("trendforce_news")
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


@st.cache_data(ttl=1800)
def get_cached_trendforce_news(limit=20):
    track_cacheable_call()
    return get_trendforce_news(limit)


def classify_news_sentiment(item):
    text = f"{item.get('title') or ''} {item.get('text') or ''}".lower()
    positive_score = sum(_contains_news_keyword(text, keyword) for keyword in POSITIVE_NEWS_KEYWORDS)
    negative_score = sum(_contains_news_keyword(text, keyword) for keyword in NEGATIVE_NEWS_KEYWORDS)
    if positive_score > negative_score:
        return "Positive"
    if negative_score > positive_score:
        return "Negative"
    return "Neutral"


def _contains_news_keyword(text, keyword):
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, re.IGNORECASE) is not None


def _news_sort_key(item):
    return item.get("published_date") or item.get("publishedDate") or ""


def news_sentiment_label(sentiment):
    return t(sentiment.lower()) if sentiment in ("Positive", "Neutral", "Negative") else sentiment


NEWS_SUMMARY_LABELS = {
    "English": "AI Summary",
    "\u4e2d\u6587": "AI \u603b\u7ed3",
    "Espa\u00f1ol": "Resumen de IA",
}
AI_SUMMARY_VERSION = "v3"
AI_TRANSLATION_VERSION = "v1"
AI_SENTIMENT_VERSION = "v1"
AI_DETAILED_SUMMARY_VERSION = "v2"
NEWS_TRANSLATION_LABELS = {
    "English": "Full Translation",
    "\u4e2d\u6587": "\u5168\u6587\u7ffb\u8bd1",
    "Espa\u00f1ol": "Traducci\u00f3n completa",
}
NEWS_TRANSLATION_UI = {
    "English": ("Generate translation", "Regenerate translation", "Generate this translation on demand to limit AI calls."),
    "\u4e2d\u6587": ("\u751f\u6210\u7ffb\u8bd1", "\u91cd\u65b0\u751f\u6210\u7ffb\u8bd1", "\u6309\u9700\u751f\u6210\u6b64\u7ffb\u8bd1\uff0c\u4ee5\u51cf\u5c11 AI \u8c03\u7528\u3002"),
    "Espa\u00f1ol": ("Generar traducci\u00f3n", "Regenerar traducci\u00f3n", "Genere esta traducci\u00f3n bajo demanda para limitar las llamadas de IA."),
}
NEWS_DETAILED_SUMMARY_LABELS = {
    "English": "ChatGPT Detailed Summary",
    "\u4e2d\u6587": "ChatGPT \u8be6\u7ec6\u603b\u7ed3",
    "Espa\u00f1ol": "Resumen detallado de ChatGPT",
}
NEWS_DETAILED_SUMMARY_UI = {
    "English": ("Generate detailed summary", "Regenerate detailed summary", "Generate this detailed summary on demand to limit AI calls."),
    "\u4e2d\u6587": ("\u751f\u6210\u8be6\u7ec6\u603b\u7ed3", "\u91cd\u65b0\u751f\u6210\u8be6\u7ec6\u603b\u7ed3", "\u6309\u9700\u751f\u6210\u6b64\u8be6\u7ec6\u603b\u7ed3\uff0c\u4ee5\u51cf\u5c11 AI \u8c03\u7528\u3002"),
    "Espa\u00f1ol": ("Generar resumen detallado", "Regenerar resumen detallado", "Genere este resumen detallado bajo demanda para limitar las llamadas de IA."),
}
NEWS_DETAILED_SUMMARY_UNAVAILABLE = {
    "English": "Detailed summary is temporarily unavailable.",
    "\u4e2d\u6587": "\u6682\u65f6\u65e0\u6cd5\u751f\u6210\u8be6\u7ec6\u603b\u7ed3\u3002",
    "Espa\u00f1ol": "El resumen detallado no est\u00e1 disponible temporalmente.",
}
NEWS_SCORE_LABELS = {
    "English": {
        "credibility": "Credibility",
        "sentiment": "Sentiment",
        "credibility_bands": ((80, "High"), (60, "Medium-High"), (40, "Medium"), (0, "Low")),
        "sentiment_bands": (
            (0.35, "Bullish"),
            (0.10, "Slightly Bullish"),
            (-0.10, "Neutral"),
            (-0.35, "Slightly Bearish"),
            (-1.01, "Bearish"),
        ),
    },
    "\u4e2d\u6587": {
        "credibility": "\u53ef\u4fe1\u5ea6",
        "sentiment": "\u60c5\u7eea",
        "credibility_bands": ((80, "\u9ad8"), (60, "\u4e2d\u9ad8"), (40, "\u4e2d"), (0, "\u4f4e")),
        "sentiment_bands": (
            (0.35, "\u504f\u591a"),
            (0.10, "\u8f7b\u5fae\u504f\u591a"),
            (-0.10, "\u4e2d\u6027"),
            (-0.35, "\u8f7b\u5fae\u504f\u7a7a"),
            (-1.01, "\u504f\u7a7a"),
        ),
    },
    "Espa\u00f1ol": {
        "credibility": "Credibilidad",
        "sentiment": "Sentimiento",
        "credibility_bands": ((80, "Alta"), (60, "Media-alta"), (40, "Media"), (0, "Baja")),
        "sentiment_bands": (
            (0.35, "Alcista"),
            (0.10, "Ligeramente alcista"),
            (-0.10, "Neutral"),
            (-0.35, "Ligeramente bajista"),
            (-1.01, "Bajista"),
        ),
    },
}
NEWS_SUMMARY_LANGUAGE_NAMES = {
    "English": "English",
    "\u4e2d\u6587": "Chinese",
    "Espa\u00f1ol": "Spanish",
}
NEWS_SUMMARY_LANGUAGE_ALIASES = {
    "en": "English",
    "english": "English",
    "zh": "\u4e2d\u6587",
    "chinese": "\u4e2d\u6587",
    "\u4e2d\u6587": "\u4e2d\u6587",
    "es": "Espa\u00f1ol",
    "spanish": "Espa\u00f1ol",
    "espa\u00f1ol": "Espa\u00f1ol",
}
NEWS_SUMMARY_FIELD_LABELS = {
    "English": {
        "news_overview": "News Overview", "why_it_matters": "Why It Matters",
        "potential_stock_impact": "Potential Stock Impact", "positive_factors": "Positive Factors",
        "risk_factors": "Risk Factors", "what_to_watch_next": "What to Watch Next",
        "ai_view": "AI View", "confidence": "Confidence",
    },
    "\u4e2d\u6587": {
        "news_overview": "\u65b0\u95fb\u6982\u8ff0", "why_it_matters": "\u4e3a\u4f55\u91cd\u8981",
        "potential_stock_impact": "\u6f5c\u5728\u80a1\u4ef7\u5f71\u54cd", "positive_factors": "\u79ef\u6781\u56e0\u7d20",
        "risk_factors": "\u98ce\u9669\u56e0\u7d20", "what_to_watch_next": "\u540e\u7eed\u5173\u6ce8",
        "ai_view": "AI \u89c2\u70b9", "confidence": "\u7f6e\u4fe1\u5ea6",
    },
    "Espa\u00f1ol": {
        "news_overview": "Resumen de la noticia", "why_it_matters": "Por qu\u00e9 importa",
        "potential_stock_impact": "Impacto potencial en la acci\u00f3n", "positive_factors": "Factores positivos",
        "risk_factors": "Factores de riesgo", "what_to_watch_next": "Qu\u00e9 vigilar",
        "ai_view": "Visi\u00f3n de IA", "confidence": "Confianza",
    },
}
NEWS_SUMMARY_UI = {
    "English": ("Generate summary", "Regenerate summary", "Generate this summary on demand to limit AI calls."),
    "\u4e2d\u6587": ("\u751f\u6210\u603b\u7ed3", "\u91cd\u65b0\u751f\u6210\u603b\u7ed3", "\u6309\u9700\u751f\u6210\u6b64\u603b\u7ed3\uff0c\u4ee5\u51cf\u5c11 AI \u8c03\u7528\u3002"),
    "Espa\u00f1ol": ("Generar resumen", "Regenerar resumen", "Genere este resumen bajo demanda para limitar las llamadas de IA."),
}
NEWS_DRIVER_KEYWORDS = (
    ("earnings", ("earnings", "revenue", "profit", "eps", "guidance", "margin")),
    ("demand", ("demand", "sales", "orders", "bookings")),
    ("valuation", ("valuation", "price target", "overvalued", "undervalued")),
    ("macro", ("inflation", "interest rate", "fed", "economy", "macro")),
    ("regulation", ("regulation", "regulatory", "lawsuit", "export restriction", "antitrust")),
    ("product", ("product", "launch", "chip", "platform")),
    ("analyst rating", ("upgrade", "downgrade", "analyst", "rating")),
    ("supply chain", ("supply chain", "inventory", "supplier", "shipment")),
)


def _news_summary_language(language):
    if language in NEWS_SUMMARY_LABELS:
        return language
    return NEWS_SUMMARY_LANGUAGE_ALIASES.get(str(language or "").strip().lower(), "English")


def _news_summary_language_instruction(language):
    language = _news_summary_language(language)
    if language == "\u4e2d\u6587":
        return (
            "\u8bf7\u5b8c\u5168\u4f7f\u7528\u5f53\u524d\u9009\u62e9\u7684\u8bed\u8a00\u8f93\u51fa\uff0c\u4e0d\u8981\u6df7\u7528\u82f1\u6587\u3002"
            "\u5373\u4f7f\u65b0\u95fb\u539f\u6587\u662f\u82f1\u6587\uff0c\u4e5f\u8981\u7ffb\u8bd1\u5e76\u603b\u7ed3\u4e3a\u5f53\u524d\u8bed\u8a00\u3002"
            "\u9664\u65b0\u95fb\u6807\u9898\u3001\u516c\u53f8\u540d\u79f0\u3001ticker\u3001\u6765\u6e90\u548c URL \u5916\uff0cJSON \u6240\u6709\u5b57\u6bb5\u503c\u5fc5\u987b\u662f\u4e2d\u6587\uff1b"
            "\u79ef\u6781\u56e0\u7d20\u3001\u98ce\u9669\u56e0\u7d20\u3001\u540e\u7eed\u5173\u6ce8\u7684 bullet point \u4e5f\u5fc5\u987b\u662f\u4e2d\u6587\u3002"
            "\u4f7f\u7528\u4e2d\u6587\u8868\u8fbe AI \u89c2\u70b9\u548c\u7f6e\u4fe1\u5ea6\uff0c\u4f8b\u5982\u770b\u6da8\u3001\u4e2d\u6027\u3001\u770b\u8dcc\u3001\u4f4e\u3001\u4e2d\u3001\u9ad8\u3002"
        )
    if language == "Espa\u00f1ol":
        return (
            "Use only Spanish for every JSON field value. Do not mix in English sentences. "
            "Even if the source news is in English, translate and summarize it in Spanish. "
            "Article titles, company names, tickers, sources, and URLs may remain as supplied. "
            "Use Spanish labels for ai_view and confidence, such as Alcista, Neutral, Bajista, Baja, Media, Alta."
        )
    return (
        "Use only English for every JSON field value. Article titles, company names, tickers, "
        "sources, and URLs may remain as supplied. Use English labels for ai_view and confidence."
    )


def _news_summary_label_text(labels, field, language):
    separator = "\uff1a" if _news_summary_language(language) == "\u4e2d\u6587" else ":"
    return f"{labels[field]}{separator}"


def _clean_extracted_article_text(text, max_chars=9000):
    text = html.unescape(str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    blocked_phrases = (
        "subscribe to continue", "sign in to continue", "already a subscriber",
        "enable javascript", "cookie policy", "advertisement",
    )
    if not text or any(phrase in text.lower() for phrase in blocked_phrases):
        return ""
    return text[:max_chars]


def _extract_article_text_from_html(page_html):
    if not page_html:
        return ""
    page_html = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?</\1>", " ", page_html)
    candidates = []
    for tag in ("article", "main"):
        for match in re.finditer(rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>", page_html):
            candidates.append(match.group(1))
    paragraphs = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", "\n".join(candidates) or page_html)
    if paragraphs:
        text = "\n\n".join(re.sub(r"(?is)<[^>]+>", " ", paragraph) for paragraph in paragraphs)
    else:
        text = re.sub(r"(?is)<[^>]+>", " ", "\n".join(candidates) or page_html)
    return _clean_extracted_article_text(text)


@st.cache_data(ttl=1800)
def get_cached_yahoo_article_text(url):
    track_cacheable_call()
    if not url:
        return ""
    try:
        track_api_call("news_article_text")
        response = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                )
            },
        )
        if response.status_code >= 400:
            return ""
        return _extract_article_text_from_html(response.text)
    except Exception:
        return ""


@st.cache_data(ttl=1800)
def get_cached_news_article_text(source, url):
    track_cacheable_call()
    if not url:
        return ""
    return get_cached_yahoo_article_text(url)


def _news_item_source_name(item):
    return item.get("source") or item.get("source_type") or item.get("site") or t("unknown_source")


def _news_item_publisher(item):
    return item.get("publisher") or item.get("site") or item.get("source_name") or t("unknown_publisher")


def _news_item_summary_text(item):
    return item.get("summary") or item.get("text") or item.get("description") or ""


def _standard_news_source_text(item):
    source = _news_item_source_name(item)
    article_text = get_cached_news_article_text(source, item.get("url"))
    parts = [
        item.get("title") or "",
        item.get("summary") or "",
        item.get("text") or "",
    ]
    fallback_text = "\n\n".join(dict.fromkeys(value for value in parts if value))
    return article_text or fallback_text


def _yahoo_news_source_text(item):
    return _standard_news_source_text(item)


def _parse_news_datetime(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def _credibility_label(score, language):
    labels = NEWS_SCORE_LABELS[_news_summary_language(language)]["credibility_bands"]
    for threshold, label in labels:
        if score >= threshold:
            return label
    return labels[-1][1]


def _sentiment_label(score, language):
    labels = NEWS_SCORE_LABELS[_news_summary_language(language)]["sentiment_bands"]
    for threshold, label in labels:
        if score >= threshold:
            return label
    return labels[-1][1]


def _format_yahoo_scores(credibility_score, sentiment_score, language):
    language = _news_summary_language(language)
    labels = NEWS_SCORE_LABELS[language]
    separator = "\uff1a" if language == "\u4e2d\u6587" else ":"
    sentiment_score = max(-1.0, min(1.0, float(sentiment_score or 0)))
    credibility_score = max(0, min(100, int(round(credibility_score or 0))))
    return (
        f"{labels['credibility']}{separator} {credibility_score}/100 {_credibility_label(credibility_score, language)}",
        f"{labels['sentiment']}{separator} {sentiment_score:+.2f} {_sentiment_label(sentiment_score, language)}",
    )


def _rule_based_yahoo_credibility_score(ticker, title, url, summary, publisher, published_date, article_text):
    score = 30
    if publisher:
        score += 15
    if url:
        score += 10
    if summary:
        score += 10
    if article_text:
        score += 20
    if ticker and title:
        score += 5
    published_at = _parse_news_datetime(published_date)
    if published_at:
        age_days = max(0, (datetime.utcnow() - published_at).days)
        if age_days <= 2:
            score += 10
        elif age_days <= 14:
            score += 6
        elif age_days <= 45:
            score += 3
    else:
        score -= 5
    return max(0, min(100, score))


def _rule_based_yahoo_sentiment_score(text):
    text = str(text or "").lower()
    positive_score = sum(_contains_news_keyword(text, keyword) for keyword in POSITIVE_NEWS_KEYWORDS)
    negative_score = sum(_contains_news_keyword(text, keyword) for keyword in NEGATIVE_NEWS_KEYWORDS)
    raw_score = (positive_score - negative_score) * 0.18
    return max(-0.55, min(0.55, raw_score))


@st.cache_data(ttl=7 * 24 * 60 * 60)
def get_cached_yahoo_news_scores(ticker, title, url, summary, language, sentiment_version, publisher, published_date, article_text):
    track_cacheable_call()
    article_text = _clean_extracted_article_text(article_text, max_chars=9000)
    credibility_score = _rule_based_yahoo_credibility_score(
        ticker, title, url, summary, publisher, published_date, article_text
    )
    fallback = {
        "credibility_score": credibility_score,
        "sentiment_score": _rule_based_yahoo_sentiment_score(
            "\n\n".join(value for value in (title or "", summary or "", article_text or "") if value)
        ),
    }
    return fallback


@st.cache_data(ttl=7 * 24 * 60 * 60)
def get_cached_ai_news_translation(ticker, title, url, source, language, translation_version, source_text, refresh_nonce=0):
    source_text = _clean_extracted_article_text(source_text, max_chars=12000)
    if not source_text:
        return "", None
    language = _news_summary_language(language)
    if language == "English":
        return source_text, None
    try:
        client = get_openai_client()
    except Exception as exc:
        return source_text, f"AI translation unavailable; showing source text: {exc}"
    target_language = NEWS_SUMMARY_LANGUAGE_NAMES[language]
    prompt = (
        f"Translate the supplied {source or 'news'} content into {target_language}. "
        "Do not summarize, analyze, add investment opinions, classify sentiment, or use bullish/bearish/neutral labels. "
        "Keep company names, tickers, source names, URLs, and article titles as supplied when appropriate. "
        "Return only the translated article text in plain paragraphs. "
        "If the input contains only a title and source summary, translate that title and summary fully.\n\n"
        f"Source: {source or ''}\nTicker: {ticker or ''}\nTitle: {title or ''}\nURL: {url or ''}\n"
        f"Translation cache version: {translation_version}\n\nSource content:\n{source_text}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        translated = (response.choices[0].message.content or "").strip()
        if not translated:
            raise ValueError("AI translation response was empty")
        return translated, None
    except Exception as exc:
        return source_text, f"AI translation unavailable; showing source text: {exc}"


def _news_item_ai_cache_key(item, language, version, purpose):
    return hashlib.sha256(json.dumps(
        [
            purpose,
            _news_item_source_name(item),
            item.get("ticker") or "",
            item.get("title") or "",
            item.get("url") or "",
            language,
            version,
        ],
        ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def render_news_translation(item):
    language = _news_summary_language(st.session_state.get("language", "English"))
    with st.expander(NEWS_TRANSLATION_LABELS[language], expanded=False):
        try:
            translation_key = _news_item_ai_cache_key(item, language, AI_TRANSLATION_VERSION, "translation")
            requested_key = f"news_translation_requested_{translation_key}"
            button_label, refresh_label, idle_caption = NEWS_TRANSLATION_UI[language]
            if st.button(button_label, key=f"generate_news_translation_{translation_key}"):
                st.session_state[requested_key] = True
            if not st.session_state.get(requested_key):
                st.caption(idle_caption)
                return
            translation, warning = get_cached_ai_news_translation(
                item.get("ticker") or "",
                item.get("title") or "",
                item.get("url") or "",
                _news_item_source_name(item),
                language,
                AI_TRANSLATION_VERSION,
                _standard_news_source_text(item),
                st.session_state.get(f"news_translation_refresh_{translation_key}", 0),
            )
            if warning:
                st.warning(warning)
            if translation:
                st.write(translation)
            else:
                st.info(item.get("text") or item.get("title") or t("no_yahoo_news"))
            if st.button(refresh_label, key=f"refresh_news_translation_{translation_key}"):
                refresh_key = f"news_translation_refresh_{translation_key}"
                st.session_state[refresh_key] = st.session_state.get(refresh_key, 0) + 1
                st.rerun()
        except Exception as exc:
            st.warning(f"AI translation unavailable: {exc}")


def render_yahoo_news_translation(item):
    render_news_translation(item)


def _yahoo_translation_key(item, language):
    return _news_item_ai_cache_key(item, language, AI_TRANSLATION_VERSION, "translation")


def _detailed_summary_language_instruction(language):
    language = _news_summary_language(language)
    if language == "\u4e2d\u6587":
        return (
            "\u4f60\u5fc5\u987b\u5b8c\u6574\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u8f93\u51fa\uff0c\u4e0d\u8981\u5728\u603b\u7ed3\u6b63\u6587\u4e2d\u6df7\u7528\u82f1\u6587\u3002"
            "\u65b0\u95fb\u6807\u9898\u3001\u516c\u53f8\u540d\u79f0\u3001ticker\u3001\u6765\u6e90\u548c URL \u53ef\u4ee5\u4fdd\u7559\u82f1\u6587\u3002"
            "\u6309\u4ee5\u4e0b\u7ed3\u6784\u8f93\u51fa\uff0c\u4fdd\u7559\u8fd9\u4e9b\u4e2d\u6587\u6807\u9898\uff1a\n"
            "\u8fd9\u7bc7\u6587\u7ae0\u7684\u6838\u5fc3\u610f\u601d\u662f\uff1a\n\n"
            "[\u7528 2-4 \u53e5\u8bdd\u89e3\u91ca\u6587\u7ae0\u4e3b\u65e8]\n\n"
            "\u6587\u7ae0\u4e3b\u8981\u5206\u6210\u51e0\u4e2a\u903b\u8f91\uff1a\n\n"
            "1. [\u7b2c\u4e00\u90e8\u5206\u6807\u9898]\n[\u8be6\u7ec6\u89e3\u91ca]\n\n"
            "2. [\u7b2c\u4e8c\u90e8\u5206\u6807\u9898]\n[\u8be6\u7ec6\u89e3\u91ca]\n\n"
            "3. [\u7b2c\u4e09\u90e8\u5206\u6807\u9898]\n[\u8be6\u7ec6\u89e3\u91ca]\n\n"
            "4. [\u7b2c\u56db\u90e8\u5206\u6807\u9898]\n[\u8be6\u7ec6\u89e3\u91ca]\n\n"
            "\u6295\u8d44\u8005\u9700\u8981\u6ce8\u610f\u7684\u662f\uff1a\n[\u89e3\u91ca\u8fd9\u7bc7\u6587\u7ae0\u5bf9\u80a1\u7968/\u884c\u4e1a/\u4f30\u503c/\u98ce\u9669\u7684\u542b\u4e49]\n\n"
            "\u4e00\u53e5\u8bdd\u603b\u7ed3\uff1a\n[\u7528\u4e00\u53e5\u8bdd\u603b\u7ed3\u6587\u7ae0\u7ed3\u8bba]"
        )
    if language == "Espa\u00f1ol":
        return (
            "Write the full detailed summary in Spanish. Article titles, company names, tickers, sources, and URLs may remain as supplied. "
            "Use this translated structure: 'La idea central de este art\u00edculo es:', 'El art\u00edculo se divide principalmente en varios razonamientos:', "
            "four numbered logic sections, 'Lo que los inversores deben tener en cuenta:', and 'Resumen en una frase:'."
        )
    return (
        "Write the full detailed summary in English. Article titles, company names, tickers, sources, and URLs may remain as supplied. "
        "Use this structure: 'The core idea of this article is:', 'The article mainly breaks into several logical parts:', "
        "four numbered logic sections, 'What investors need to pay attention to:', and 'One-sentence summary:'."
    )


@st.cache_data(ttl=7 * 24 * 60 * 60)
def get_cached_ai_news_detailed_summary(
    ticker, title, url, source, summary, language, detailed_summary_version, source_text, refresh_nonce=0
):
    source_text = _clean_extracted_article_text(source_text, max_chars=16000)
    if not source_text:
        return "", None
    language = _news_summary_language(language)
    try:
        client = get_openai_client()
    except Exception as exc:
        return "", str(exc)
    prompt = (
        f"Create a natural-language ChatGPT-style detailed explanation of the supplied {source or 'news'} item. "
        "Do not use the old fixed investment AI Summary template and do not output sections named News Overview, "
        "Why It Matters, Potential Stock Impact, Positive Factors, Risk Factors, AI View, or Confidence. "
        "Explain the article's logic clearly, not just a short overview. Use only the supplied text; do not fetch the URL. "
        "The detailed summary must be more specific than the source summary. If it is investment-related, explicitly cover: "
        "1) the core news event, 2) the direct impact on related companies, 3) the possible impact on revenue, profit, "
        "valuation, or stock-price sentiment, 4) key risks, and 5) follow-up signals investors should monitor. If it is not "
        "investment-related, summarize it as ordinary news and do not force an investment conclusion. "
        f"{_detailed_summary_language_instruction(language)}\n\n"
        f"Source: {source or ''}\nTicker: {ticker or ''}\nTitle: {title or ''}\nURL: {url or ''}\n"
        f"Source summary: {summary or ''}\nLanguage: {NEWS_SUMMARY_LANGUAGE_NAMES[language]}\n"
        f"Detailed summary cache version: {detailed_summary_version}\n\n"
        f"News content:\n{source_text}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        detailed_summary = (response.choices[0].message.content or "").strip()
        if not detailed_summary:
            raise ValueError("AI detailed summary response was empty")
        return detailed_summary, None
    except Exception as exc:
        return "", str(exc)


def get_cached_ai_yahoo_detailed_summary(
    ticker, title, url, summary, language, detailed_summary_version, source_text, refresh_nonce=0
):
    return get_cached_ai_news_detailed_summary(
        ticker, title, url, "Yahoo/yfinance", summary, language, detailed_summary_version, source_text, refresh_nonce
    )


def render_news_detailed_summary(item):
    language = _news_summary_language(st.session_state.get("language", "English"))
    with st.expander(NEWS_DETAILED_SUMMARY_LABELS[language], expanded=False):
        try:
            detailed_summary_key = _news_item_ai_cache_key(item, language, AI_DETAILED_SUMMARY_VERSION, "detailed_summary")
            requested_key = f"news_detailed_summary_requested_{detailed_summary_key}"
            button_label, refresh_label, idle_caption = NEWS_DETAILED_SUMMARY_UI[language]
            if st.button(button_label, key=f"generate_news_detailed_summary_{detailed_summary_key}"):
                st.session_state[requested_key] = True
            if not st.session_state.get(requested_key):
                st.caption(idle_caption)
                return
            source_text = _standard_news_source_text(item)
            translation_key = _news_item_ai_cache_key(item, language, AI_TRANSLATION_VERSION, "translation")
            if st.session_state.get(f"news_translation_requested_{translation_key}"):
                translated_text, _ = get_cached_ai_news_translation(
                    item.get("ticker") or "",
                    item.get("title") or "",
                    item.get("url") or "",
                    _news_item_source_name(item),
                    language,
                    AI_TRANSLATION_VERSION,
                    source_text,
                    st.session_state.get(f"news_translation_refresh_{translation_key}", 0),
                )
                if translated_text:
                    source_text = translated_text
            detailed_summary, warning = get_cached_ai_news_detailed_summary(
                item.get("ticker") or "",
                item.get("title") or "",
                item.get("url") or "",
                _news_item_source_name(item),
                _news_item_summary_text(item),
                language,
                AI_DETAILED_SUMMARY_VERSION,
                source_text,
                st.session_state.get(f"news_detailed_summary_refresh_{detailed_summary_key}", 0),
            )
            if detailed_summary:
                st.markdown(detailed_summary)
            else:
                st.warning(NEWS_DETAILED_SUMMARY_UNAVAILABLE[language])
            if warning and not detailed_summary:
                st.caption(warning)
            if st.button(refresh_label, key=f"refresh_news_detailed_summary_{detailed_summary_key}"):
                refresh_key = f"news_detailed_summary_refresh_{detailed_summary_key}"
                st.session_state[refresh_key] = st.session_state.get(refresh_key, 0) + 1
                st.rerun()
        except Exception:
            st.warning(NEWS_DETAILED_SUMMARY_UNAVAILABLE[language])


def render_yahoo_news_detailed_summary(item):
    render_news_detailed_summary(item)


def _rule_based_news_summary(title, text, ticker, sentiment, language):
    language = _news_summary_language(language)
    article_text = f"{title or ''} {text or ''}".lower()
    driver = next(
        (name for name, keywords in NEWS_DRIVER_KEYWORDS if any(keyword in article_text for keyword in keywords)),
        "other",
    )
    canonical_impact = {"Positive": "Bullish", "Negative": "Bearish"}.get(sentiment, "Neutral")
    confidence = "Medium" if text else "Low"
    title = title or "No article title was provided."
    ticker = ticker or "the related stock"
    if language == "\u4e2d\u6587":
        impact = {"Bullish": "\u770b\u6da8", "Bearish": "\u770b\u8dcc", "Neutral": "\u4e2d\u6027"}[canonical_impact]
        reason = {
            "Positive": "\u73b0\u6709\u4fe1\u606f\u5305\u542b\u6b63\u9762\u4fe1\u53f7\uff0c\u53ef\u80fd\u6539\u5584\u5e02\u573a\u9884\u671f\u3002",
            "Negative": "\u73b0\u6709\u4fe1\u606f\u5305\u542b\u8d1f\u9762\u4fe1\u53f7\uff0c\u53ef\u80fd\u538b\u4f4e\u5e02\u573a\u9884\u671f\u3002",
            "Neutral": "\u73b0\u6709\u4fe1\u606f\u5c1a\u4e0d\u8db3\u4ee5\u5f62\u6210\u660e\u786e\u65b9\u5411\u3002",
        }.get(sentiment, "\u73b0\u6709\u4fe1\u606f\u5c1a\u4e0d\u8db3\u4ee5\u5f62\u6210\u660e\u786e\u65b9\u5411\u3002")
        confidence = {"Medium": "\u4e2d", "Low": "\u4f4e"}[confidence]
        return {
            "news_overview": f"\u6587\u7ae0\u300a{title}\u300b\u805a\u7126 {ticker} \u76f8\u5173\u52a8\u6001\u3002\u672c\u6458\u8981\u4ec5\u4f9d\u636e\u6807\u9898\u548c\u6570\u636e\u6e90\u63d0\u4f9b\u7684\u6587\u672c\uff0c\u6838\u5fc3\u9a71\u52a8\u56e0\u7d20\u4e3a {driver}\u3002",
            "why_it_matters": f"\u6295\u8d44\u8005\u9700\u8bc4\u4f30\u8be5\u4e8b\u4ef6\u662f\u5426\u4f1a\u5f71\u54cd {ticker} \u7684\u9700\u6c42\u3001\u76c8\u5229\u7387\u3001\u6307\u5f15\u6216\u4f30\u503c\u3002",
            "potential_stock_impact": f"{impact}\uff1a{reason}",
            "positive_factors": ["\u53ef\u80fd\u6539\u5584\u6295\u8d44\u8005\u5bf9\u4e1a\u52a1\u52a8\u80fd\u7684\u9884\u671f\u3002", "\u82e5\u540e\u7eed\u6570\u636e\u8bc1\u5b9e\uff0c\u53ef\u80fd\u652f\u6301\u66f4\u9ad8\u4f30\u503c\u3002"],
            "risk_factors": ["\u4ec5\u4f9d\u636e\u6807\u9898\u548c\u6765\u6e90\u6458\u8981\uff0c\u80cc\u666f\u6709\u9650\u3002", "\u5e02\u573a\u53ef\u80fd\u5df2\u7ecf\u63d0\u524d\u53cd\u6620\u76f8\u5173\u9884\u671f\u3002"],
            "what_to_watch_next": ["\u7ba1\u7406\u5c42\u6307\u5f15\u4e0e\u4e0b\u6b21\u8d22\u62a5\u3002", "\u9700\u6c42\u3001\u5229\u6da6\u7387\u4e0e\u5206\u6790\u5e08\u9884\u6d4b\u8c03\u6574\u3002"],
            "ai_view": impact, "confidence": confidence,
        }
    elif language == "Espa\u00f1ol":
        impact = {"Bullish": "Alcista", "Bearish": "Bajista", "Neutral": "Neutral"}[canonical_impact]
        reason = {
            "Positive": "La informaci\u00f3n disponible contiene se\u00f1ales positivas que podr\u00edan mejorar las expectativas.",
            "Negative": "La informaci\u00f3n disponible contiene se\u00f1ales negativas que podr\u00edan reducir las expectativas.",
            "Neutral": "La informaci\u00f3n disponible no establece una direcci\u00f3n clara.",
        }.get(sentiment, "La informaci\u00f3n disponible no establece una direcci\u00f3n clara.")
        confidence = {"Medium": "Media", "Low": "Baja"}[confidence]
        return {
            "news_overview": f"El art\u00edculo '{title}' trata un desarrollo relacionado con {ticker}. Este resumen usa solo el titular y el texto aportado por la fuente; el principal factor identificado es {driver}.",
            "why_it_matters": f"Los inversores deben valorar si el desarrollo afecta la demanda, los m\u00e1rgenes, las previsiones o la valoraci\u00f3n de {ticker}.",
            "potential_stock_impact": f"{impact}: {reason}",
            "positive_factors": ["Podr\u00eda reforzar las expectativas sobre el impulso del negocio.", "Una confirmaci\u00f3n posterior podr\u00eda respaldar una valoraci\u00f3n mayor."],
            "risk_factors": ["El contexto est\u00e1 limitado al titular y al resumen de la fuente.", "El mercado puede haber descontado ya parte de las expectativas."],
            "what_to_watch_next": ["Pr\u00f3ximos resultados y previsiones de la direcci\u00f3n.", "Tendencias de demanda, m\u00e1rgenes y revisiones de analistas."],
            "ai_view": impact, "confidence": confidence,
        }
    reason = {
        "Positive": "The available information contains positive signals that could improve investor expectations.",
        "Negative": "The available information contains negative signals that could reduce investor expectations.",
        "Neutral": "The available information does not establish a clear directional effect.",
    }.get(sentiment, "The available information does not establish a clear directional effect.")
    return {
        "news_overview": f"The article '{title}' covers a development related to {ticker}. This summary uses only the headline and source-provided text; the main identified driver is {driver}.",
        "why_it_matters": f"Investors should assess whether the development changes demand, margins, guidance, or valuation expectations for {ticker}.",
        "potential_stock_impact": f"{canonical_impact}: {reason}",
        "positive_factors": ["The development could improve expectations for business momentum.", "Follow-through evidence could support a stronger valuation case."],
        "risk_factors": ["Context is limited to the headline and source-provided summary.", "The market may already have priced in some of the expected effect."],
        "what_to_watch_next": ["Upcoming earnings and management guidance.", "Demand trends, margins, and analyst estimate revisions."],
        "ai_view": canonical_impact,
        "confidence": confidence,
    }


@st.cache_data(ttl=12 * 60 * 60)
def get_cached_ai_news_summary(title, ticker, source, published_date, sentiment, language, summary_version, article_text="", refresh_nonce=0):
    fallback = _rule_based_news_summary(title, article_text, ticker, sentiment, language)
    try:
        client = get_openai_client()
    except Exception:
        return fallback, None
    language = _news_summary_language(language)
    language_instruction = _news_summary_language_instruction(language)
    prompt = (
        "Create a concise but detailed investment-focused article summary using only the supplied news metadata. "
        "Do not fetch or infer content from the article URL. Preserve company names, tickers, source names, "
        f"and other proper nouns exactly as supplied. Write the values in {NEWS_SUMMARY_LANGUAGE_NAMES[language]}. "
        f"{language_instruction} "
        "Return JSON only with keys news_overview, why_it_matters, potential_stock_impact, positive_factors, "
        "risk_factors, what_to_watch_next, ai_view, confidence. news_overview must be 2-3 sentences. "
        "positive_factors, risk_factors, and what_to_watch_next must each be arrays with 2-3 concise items. "
        "potential_stock_impact must state whether the article is bullish, neutral, or bearish for the related stock and explain why, using the requested language. "
        "ai_view and confidence must use the requested language, not fixed English labels. "
        "Keep the full response around 120-180 English words, 180-260 Chinese characters, or 130-190 Spanish words. "
        "Translate the section values naturally for the requested language, including every bullet point, the view, and confidence labels, "
        "but do not translate the supplied article title, company name, ticker, source, or URL.\n\n"
        f"Title: {title or ''}\nTicker: {ticker or ''}\nSource: {source or ''}\n"
        f"Published date: {published_date or ''}\nExisting sentiment: {sentiment or ''}\n"
        f"Source-provided summary/text: {article_text or ''}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        summary = json.loads(response.choices[0].message.content)
        required_fields = (
            "news_overview", "why_it_matters", "potential_stock_impact", "positive_factors",
            "risk_factors", "what_to_watch_next", "ai_view", "confidence",
        )
        if not all(summary.get(field) for field in required_fields):
            raise ValueError("AI summary response omitted required fields")
        for field in ("positive_factors", "risk_factors", "what_to_watch_next"):
            if not isinstance(summary[field], list) or not 2 <= len(summary[field]) <= 3:
                raise ValueError(f"AI summary field {field} must contain 2-3 items")
        return {field: summary[field] if isinstance(summary[field], list) else str(summary[field]) for field in required_fields}, None
    except Exception as exc:
        return fallback, f"AI summary unavailable; showing rule-based fallback: {exc}"


def render_ai_news_summary(item):
    language = _news_summary_language(st.session_state.get("language", "English"))
    with st.expander(NEWS_SUMMARY_LABELS[language], expanded=False):
        try:
            summary_key = hashlib.sha256(json.dumps(
                [
                    item.get("title") or "",
                    item.get("ticker") or "",
                    item.get("source") or "",
                    item.get("published_date") or "",
                    item.get("sentiment") or "",
                    language,
                    AI_SUMMARY_VERSION,
                    item.get("text") or "",
                ],
                ensure_ascii=True,
            ).encode("utf-8")).hexdigest()
            requested_key = f"news_summary_requested_{summary_key}"
            button_label, refresh_label, idle_caption = NEWS_SUMMARY_UI[language]
            if st.button(button_label, key=f"generate_news_summary_{summary_key}"):
                st.session_state[requested_key] = True
            if not st.session_state.get(requested_key):
                st.caption(idle_caption)
                return
            summary, warning = get_cached_ai_news_summary(
                item.get("title") or "",
                item.get("ticker") or "",
                item.get("source") or "",
                item.get("published_date") or "",
                item.get("sentiment") or "",
                language,
                AI_SUMMARY_VERSION,
                item.get("text") or "",
                st.session_state.get(f"news_summary_refresh_{summary_key}", 0),
            )
            if warning:
                st.warning(warning)
            labels = NEWS_SUMMARY_FIELD_LABELS[language]
            for field in ("news_overview", "why_it_matters", "potential_stock_impact"):
                st.markdown(f"**{_news_summary_label_text(labels, field, language)}** {summary[field]}")
            for field in ("positive_factors", "risk_factors", "what_to_watch_next"):
                st.markdown(f"**{_news_summary_label_text(labels, field, language)}**")
                for value in summary[field]:
                    st.markdown(f"- {value}")
            for field in ("ai_view", "confidence"):
                st.markdown(f"**{_news_summary_label_text(labels, field, language)}** {summary[field]}")
            if st.button(refresh_label, key=f"refresh_news_summary_{summary_key}"):
                refresh_key = f"news_summary_refresh_{summary_key}"
                st.session_state[refresh_key] = st.session_state.get(refresh_key, 0) + 1
                st.rerun()
        except Exception as exc:
            st.warning(f"AI summary unavailable: {exc}")


@st.cache_data(ttl=12 * 60 * 60)
def get_cached_ai_ticker_news_summary(ticker, news_digest, language, summary_version, refresh_nonce=0):
    language = _news_summary_language(language)
    news_items = json.loads(news_digest or "[]")
    joined_text = "\n".join(
        f"- {item.get('title') or ''} | {item.get('publisher') or ''} | {item.get('published_date') or ''} | {item.get('text') or ''}"
        for item in news_items[:10]
    )
    fallback = _rule_based_news_summary(
        f"{ticker} recent Yahoo news",
        joined_text,
        ticker,
        "Neutral",
        language,
    )
    try:
        client = get_openai_client()
    except Exception:
        return fallback, None
    language_instruction = _news_summary_language_instruction(language)
    prompt = (
        "Create a concise investment-focused summary for the supplied Yahoo/yfinance news list. "
        "Use only the supplied headlines, publishers, dates, and summaries. "
        f"Write the values in {NEWS_SUMMARY_LANGUAGE_NAMES[language]}. "
        f"{language_instruction} "
        "Return JSON only with keys news_overview, why_it_matters, potential_stock_impact, positive_factors, "
        "risk_factors, what_to_watch_next, ai_view, confidence. "
        "potential_stock_impact and ai_view must explicitly describe a bullish, bearish, or neutral view using the requested language. "
        "positive_factors, risk_factors, and what_to_watch_next must each be arrays with 2-3 concise items. "
        "Translate every bullet point naturally into the requested language. Keep the full response concise.\n\n"
        f"Ticker: {ticker}\nNews list:\n{joined_text}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        summary = json.loads(response.choices[0].message.content)
        required_fields = (
            "news_overview", "why_it_matters", "potential_stock_impact", "positive_factors",
            "risk_factors", "what_to_watch_next", "ai_view", "confidence",
        )
        if not all(summary.get(field) for field in required_fields):
            raise ValueError("AI summary response omitted required fields")
        for field in ("positive_factors", "risk_factors", "what_to_watch_next"):
            if not isinstance(summary[field], list) or not 2 <= len(summary[field]) <= 3:
                raise ValueError(f"AI summary field {field} must contain 2-3 items")
        return {field: summary[field] if isinstance(summary[field], list) else str(summary[field]) for field in required_fields}, None
    except Exception as exc:
        return fallback, f"AI summary unavailable; showing rule-based fallback: {exc}"


def render_ticker_news_summary(ticker, news_items):
    language = _news_summary_language(st.session_state.get("language", "English"))
    digest = json.dumps(
        [
            {
                "title": item.get("title"),
                "publisher": item.get("publisher"),
                "published_date": item.get("published_date"),
                "text": item.get("text"),
            }
            for item in news_items[:10]
        ],
        ensure_ascii=True,
        sort_keys=True,
    )
    summary_key = hashlib.sha256(f"{ticker}:{language}:{AI_SUMMARY_VERSION}:{digest}".encode("utf-8")).hexdigest()
    requested_key = f"ticker_news_summary_requested_{summary_key}"
    button_label, refresh_label, idle_caption = NEWS_SUMMARY_UI[language]
    with st.expander(NEWS_SUMMARY_LABELS[language], expanded=False):
        if st.button(button_label, key=f"generate_ticker_news_summary_{summary_key}"):
            st.session_state[requested_key] = True
        if not st.session_state.get(requested_key):
            st.caption(idle_caption)
            return
        summary, warning = get_cached_ai_ticker_news_summary(
            ticker,
            digest,
            language,
            AI_SUMMARY_VERSION,
            st.session_state.get(f"ticker_news_summary_refresh_{summary_key}", 0),
        )
        if warning:
            st.warning(warning)
        labels = NEWS_SUMMARY_FIELD_LABELS[language]
        for field in ("news_overview", "why_it_matters", "potential_stock_impact"):
            st.markdown(f"**{_news_summary_label_text(labels, field, language)}** {summary[field]}")
        for field in ("positive_factors", "risk_factors", "what_to_watch_next"):
            st.markdown(f"**{_news_summary_label_text(labels, field, language)}**")
            for value in summary[field]:
                st.markdown(f"- {value}")
        for field in ("ai_view", "confidence"):
            st.markdown(f"**{_news_summary_label_text(labels, field, language)}** {summary[field]}")
        if st.button(refresh_label, key=f"refresh_ticker_news_summary_{summary_key}"):
            refresh_key = f"ticker_news_summary_refresh_{summary_key}"
            st.session_state[refresh_key] = st.session_state.get(refresh_key, 0) + 1
            st.rerun()


def yahoo_news_score_caption_parts(item):
    language = _news_summary_language(st.session_state.get("language", "English"))
    article_text = ""
    try:
        scores = get_cached_yahoo_news_scores(
            item.get("ticker") or "",
            item.get("title") or "",
            item.get("url") or "",
            item.get("text") or "",
            language,
            AI_SENTIMENT_VERSION,
            item.get("publisher") or "",
            item.get("published_date") or "",
            article_text or "",
        )
    except Exception:
        scores = {
            "credibility_score": _rule_based_yahoo_credibility_score(
                item.get("ticker") or "",
                item.get("title") or "",
                item.get("url") or "",
                item.get("text") or "",
                item.get("publisher") or "",
                item.get("published_date") or "",
                article_text or "",
            ),
            "sentiment_score": 0.0,
        }
    return _format_yahoo_scores(
        scores.get("credibility_score", 0),
        scores.get("sentiment_score", 0.0),
        language,
    )


def render_standard_news_card(item):
    title = item.get("title") or t("untitled_article")
    url = item.get("url")
    st.markdown("#### " + title)
    publisher = _news_item_publisher(item)
    related_ticker = item.get("related_tickers") or item.get("ticker") or t("market")
    caption_parts = [
        item.get("published_date") or item.get("publishedDate") or t("date_unavailable"),
        publisher,
        f"{t('related_ticker')}: {related_ticker}",
        _news_item_source_name(item),
    ]
    if item.get("source") == "Yahoo/yfinance":
        caption_parts.extend(yahoo_news_score_caption_parts(item))
    elif item.get("sentiment"):
        caption_parts.append(news_sentiment_label(item["sentiment"]))
    st.caption(" | ".join(caption_parts))
    summary_text = _news_item_summary_text(item)
    if summary_text:
        st.write(summary_text)
    render_news_translation(item)
    render_news_detailed_summary(item)
    if url:
        st.link_button(t("open_article"), url)
    st.divider()


def render_news_item(item):
    render_standard_news_card(item)


def render_fmp_news_section():
    st.caption(t("fmp_news_fallback"))
    watchlist = load_watchlist()
    try:
        stock_news = get_cached_watchlist_news(tuple(watchlist))
    except Exception as exc:
        st.warning(f"{t('stock_news_unavailable')}: {exc}")
        stock_news = []
    if not stock_news:
        try:
            yahoo_fallback = get_cached_watchlist_yahoo_news(tuple(watchlist), 10)
            stock_news = [
                item
                for ticker in watchlist
                for item in yahoo_fallback.get(ticker, [])
            ]
        except Exception as exc:
            st.warning(f"{t('fmp_news_fallback')}: {exc}")

    prepared_news = [
        {**item, "sentiment": classify_news_sentiment(item)}
        for item in stock_news
        if item.get("title")
    ]
    filter_columns = st.columns(4)
    ticker_filter_label = filter_columns[0].selectbox(t("select_ticker"), [t("all"), *watchlist], key="news_ticker")
    ticker_filter = "All" if ticker_filter_label == t("all") else ticker_filter_label
    available_sources = sorted({item["source"] for item in prepared_news if item.get("source")})
    source_filter_label = filter_columns[1].selectbox(t("select_source"), [t("all"), *available_sources], key="news_source")
    source_filter = "All" if source_filter_label == t("all") else source_filter_label
    sentiment_labels = {t("all"): "All", t("positive"): "Positive", t("neutral"): "Neutral", t("negative"): "Negative"}
    sentiment_filter = sentiment_labels[filter_columns[2].selectbox(t("select_sentiment"), list(sentiment_labels), key="news_sentiment")]
    item_limit = filter_columns[3].selectbox(t("number_news_items"), [5, 10, 20, 50, 100], index=1, key="news_limit")

    visible_news = sorted(prepared_news, key=_news_sort_key, reverse=True)
    if ticker_filter != "All":
        visible_news = [item for item in visible_news if item.get("ticker") == ticker_filter]
    if source_filter != "All":
        visible_news = [item for item in visible_news if item.get("source") == source_filter]
    if sentiment_filter != "All":
        visible_news = [item for item in visible_news if item["sentiment"] == sentiment_filter]

    st.subheader(t("watchlist_stock_news"))
    if not stock_news:
        st.warning(t("no_watchlist_news"))
    elif not visible_news:
        st.info(t("no_filtered_news"))
    else:
        for item in visible_news[:item_limit]:
            render_news_item(item)

    st.subheader(t("semiconductor_ai_news"))
    st.caption(t("market_news_caption"))
    try:
        general_news = get_cached_market_news()
        market_news = [
            {**item, "sentiment": classify_news_sentiment(item)}
            for item in general_news
            if any(
                _contains_news_keyword(f"{item.get('title') or ''} {item.get('text') or ''}", keyword)
                for keyword in MARKET_NEWS_KEYWORDS
            )
        ]
    except Exception as exc:
        st.warning(f"{t('market_news_unavailable')}: {exc}")
        market_news = []
    if not market_news:
        st.info(t("no_market_news"))
    else:
        for item in sorted(market_news, key=_news_sort_key, reverse=True)[:item_limit]:
            render_news_item(item)


def render_yahoo_news_section():
    st.subheader(t("yahoo_news"))
    st.caption(t("yahoo_news_caption"))
    watchlist = load_watchlist()
    try:
        yahoo_news_by_ticker = get_cached_watchlist_yahoo_news(tuple(watchlist), 10)
    except Exception as exc:
        st.warning(f"{t('yahoo_news_unavailable')}: {exc}")
        yahoo_news_by_ticker = {}

    for ticker in watchlist:
        news_items = [
            {**item, "sentiment": classify_news_sentiment(item)}
            for item in yahoo_news_by_ticker.get(ticker, [])
            if item.get("title")
        ]
        with st.expander(f"{ticker} | {company_name(ticker)} | {t('related_news')}", expanded=ticker == "NVDA"):
            if not news_items:
                st.info(t("no_yahoo_news"))
                continue
            render_ticker_news_summary(ticker, news_items)
            for item in sorted(news_items, key=_news_sort_key, reverse=True)[:10]:
                render_news_item(item)


def render_trendforce_news_section():
    st.subheader(t("trendforce_news"))
    st.caption(t("trendforce_news_caption"))
    try:
        trendforce_news = [
            {**item, "source": item.get("source") or "TrendForce", "sentiment": item.get("sentiment") or classify_news_sentiment(item)}
            for item in get_cached_trendforce_news(20)
            if item.get("title")
        ]
    except Exception as exc:
        st.warning(f"{t('no_trendforce_news')}: {exc}")
        trendforce_news = []
    if not trendforce_news:
        st.info(t("no_trendforce_news"))
        return
    for item in sorted(trendforce_news, key=_news_sort_key, reverse=True)[:20]:
        render_news_item(item)


def render_news_section():
    news_sections = [t("fmp_news_tab"), t("yahoo_news_tab"), t("trendforce_news_tab")]
    selected_news_section = st.radio(
        t("select_source"),
        news_sections,
        horizontal=True,
        key="news_section_selector",
    )
    with st.spinner("Loading news..."):
        if selected_news_section == t("fmp_news_tab"):
            render_fmp_news_section()
        elif selected_news_section == t("yahoo_news_tab"):
            render_yahoo_news_section()
        else:
            render_trendforce_news_section()


def get_cached_yahoo_rss_headlines(ticker, limit=5):
    track_cacheable_call()
    track_api_call("yahoo_rss_headlines")
    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    return [entry.title for entry in feed.entries[:limit]]


get_cached_yahoo_rss_headlines = st.cache_data(ttl=1800)(get_cached_yahoo_rss_headlines)


def fetch_news_headlines(ticker, limit=5):
    fmp_news = get_cached_company_news(ticker, limit)
    if fmp_news:
        return [item["title"] for item in fmp_news if item.get("title")]
    try:
        return get_cached_yahoo_rss_headlines(ticker, limit)
    except Exception:
        return []


def fetch_news_sentiment(ticker, client):
    headlines = fetch_news_headlines(ticker)
    if not headlines:
        return {"sentiment": "N/A", "score": 0, "summary": "No recent headlines returned."}
    prompt = (
        f"Analyze sentiment of these {ticker} headlines: {headlines}. Reply with JSON only: "
        '{"sentiment": "BULLISH/BEARISH/NEUTRAL", "score": 0, "summary": "one line"}'
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def get_technical_summary(ticker):
    data = get_technical_data(ticker)
    latest = data.iloc[-1]
    closes = data["Close"].dropna()
    price = float(latest["Close"])
    previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
    daily_change_pct = None if previous_close in (None, 0) else (price - previous_close) / previous_close * 100
    ma5 = None if pd.isna(latest["MA5"]) else float(latest["MA5"])
    ma20 = None if pd.isna(latest["MA20"]) else float(latest["MA20"])
    if ma5 is None or ma20 is None:
        trend = "unavailable"
    elif price > ma20 and ma5 > ma20:
        trend = "bullish"
    elif price < ma20 and ma5 < ma20:
        trend = "bearish"
    else:
        trend = "neutral"
    return {
        "price": price,
        "daily_change_pct": daily_change_pct,
        "trend": trend,
        "rsi_14": None if pd.isna(latest["RSI"]) else round(float(latest["RSI"]), 2),
        "ma_5": ma5,
        "ma_20": ma20,
        "volume_vs_20d": None if pd.isna(latest["Vol_Ratio"]) else round(float(latest["Vol_Ratio"]), 2),
    }


def get_options_summary(ticker):
    opt = get_options_data(ticker)
    return {
        "nearest_expiration": opt["exp_date"],
        "put_call_ratio": opt["pc_ratio"],
        "total_call_oi": opt.get("total_call_oi"),
        "total_put_oi": opt.get("total_put_oi"),
        "max_pain": opt["max_pain"],
        "net_gex": opt["net_gex"],
        "call_wall": opt["call_wall"],
        "put_wall": opt["put_wall"],
        "missing_reasons": opt.get("missing_reasons", []),
        "source": opt.get("source"),
    }


def build_ai_summary_payload(snapshots, macro_snapshot=None):
    stocks = []
    for ticker in load_watchlist():
        snapshot = snapshots.get(ticker) or {}
        stock_data = {
            "ticker": ticker,
            "company_name": company_name(ticker, snapshot),
            "supply_chain_role": supply_chain_role(ticker),
            "current_price": snapshot.get("price"),
            "daily_change_pct": snapshot.get("change_pct"),
            "revenue": snapshot.get("revenue"),
            "net_margin": snapshot.get("net_margin"),
            "trailing_pe": snapshot.get("trailing_pe"),
            "forward_pe": snapshot.get("forward_pe"),
            "price_to_book": snapshot.get("price_to_book"),
            "price_to_sales": snapshot.get("price_to_sales"),
            "ev_to_ebitda": snapshot.get("ev_to_ebitda"),
            "revenue_growth_yoy": snapshot.get("revenue_growth_yoy"),
            "gross_profit_growth": snapshot.get("gross_profit_growth"),
            "operating_income_growth": snapshot.get("operating_income_growth"),
            "net_income_growth": snapshot.get("net_income_growth"),
            "eps_growth": snapshot.get("eps_growth"),
            "analyst_consensus_target": snapshot.get("analyst_target"),
            "analyst_high_target": snapshot.get("analyst_target_high"),
            "analyst_low_target": snapshot.get("analyst_target_low"),
            "analyst_upside_downside_pct": snapshot.get("analyst_upside_pct"),
            "next_earnings_date": snapshot.get("next_earnings_date"),
            "estimated_eps": snapshot.get("estimated_eps"),
            "actual_eps": snapshot.get("actual_eps"),
            "eps_surprise": snapshot.get("eps_surprise"),
            "days_until_earnings": snapshot.get("days_until_earnings"),
            "analyst_rating": snapshot.get("analyst_rating"),
            "data_source": snapshot.get("source"),
        }
        try:
            news = get_cached_company_news(ticker, 5)
            stock_data["latest_news"] = news or [{"title": title, "source": "Yahoo RSS fallback"} for title in fetch_news_headlines(ticker)]
        except Exception as exc:
            stock_data["latest_news_headlines"] = []
            stock_data["news_error"] = str(exc)
        try:
            stock_data["technical"] = get_technical_summary(ticker)
        except Exception as exc:
            stock_data["technical"] = {"status": "unavailable", "error": str(exc)}
        try:
            stock_data["options_gex"] = get_options_summary(ticker)
        except Exception as exc:
            stock_data["options_gex"] = {"status": "unavailable", "error": str(exc)}
        stocks.append(stock_data)
    return {"report_date": datetime.now().strftime("%Y-%m-%d"), "macro": macro_snapshot or {}, "stocks": stocks}


def build_ai_summary_prompt(payload):
    tracked_tickers = ", ".join(stock.get("ticker", "") for stock in payload.get("stocks", []) if stock.get("ticker"))
    return f"""
You are a professional US equity analyst. Write a concise daily watchlist summary dated {payload["report_date"]}.
Use only the supplied structured data. Do not invent missing values, do not use placeholder dates,
and never ask the user to provide data. State that a metric is unavailable when needed.

Structured watchlist data:
{json.dumps(payload, indent=2, default=str)}

Use this exact report structure:
1. Market Summary
2. Macro Backdrop
- Explain whether the US 10Y yield is rising, falling, or stable.
- Explain whether the yield curve is inverted or normal.
- Assess USD strength, inflation pressure, oil risk, and important 30-day events.
- State the Macro Risk Score from 0 to 10.
- State whether macro is favorable, neutral, or unfavorable for growth stocks, AI stocks, semiconductors, and high-duration stocks.
3. Stock-by-stock analysis
4. Bull Case
5. Bear Case
6. Catalysts
7. Risks
8. Options / GEX interpretation
9. Investment View
10. Portfolio Conclusion
- Compare all tracked stocks
- Identify strongest setup
- Identify highest risk name
- State whether the group is bullish, neutral, or bearish overall
- Explain how macro affects the current tracked tickers ({tracked_tickers}) based on their supplied roles and metrics.
- Do not assume every ticker is a semiconductor or AI stock; use each company's supplied data and mark unknown exposures as unavailable when needed.
"""


def render_daily_report(snapshots):
    st.caption(t("daily_report_caption"))
    if st.button(t("generate_daily_report"), key="daily_report"):
        watchlist = load_watchlist()
        st.subheader(f"{t('daily_watchlist_report')} | {datetime.now():%Y-%m-%d}")
        render_overview_cards(snapshots)
        st.markdown(f"#### {t('technical_snapshot')}")
        rows = []
        for ticker in watchlist:
            try:
                data = get_technical_data(ticker)
                rows.append({
                    t("ticker"): ticker,
                    t("price"): format_money(data["Close"].iloc[-1], 2),
                    "RSI (14)": f"{data['RSI'].iloc[-1]:.1f}",
                    t("volume_vs_20d"): f"{data['Vol_Ratio'].iloc[-1]:.2f}x",
                })
            except Exception:
                rows.append({t("ticker"): ticker, t("price"): "N/A", "RSI (14)": "N/A", t("volume_vs_20d"): "N/A"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown(f"#### {t('options_snapshot')}")
        options_rows = []
        for ticker in watchlist:
            try:
                opt = get_options_data(ticker)
                options_rows.append({
                    t("ticker"): ticker,
                    t("put_call_ratio"): format_ratio(opt["pc_ratio"]),
                    t("max_pain"): format_money(opt["max_pain"], 0),
                    t("net_gex"): format_money(opt["net_gex"], 0),
                    t("call_wall"): format_money(opt["call_wall"], 0),
                    t("put_wall"): format_money(opt["put_wall"], 0),
                })
            except Exception:
                options_rows.append({
                    t("ticker"): ticker, t("put_call_ratio"): "N/A", t("max_pain"): "N/A",
                    t("net_gex"): "N/A", t("call_wall"): "N/A", t("put_wall"): "N/A",
                })
        st.dataframe(pd.DataFrame(options_rows), use_container_width=True, hide_index=True)
        st.markdown(f"#### {t('value_snapshot')}")
        valuation_rows = []
        for ticker in watchlist:
            snapshot = snapshots.get(ticker)
            valuation_rows.append({
                t("ticker"): ticker, t("company"): company_name(ticker, snapshot), t("supply_chain_role"): supply_chain_role(ticker),
                t("trailing_pe"): "N/A" if not snapshot else format_ratio(snapshot["trailing_pe"]),
                t("forward_pe"): "N/A" if not snapshot else format_ratio(snapshot["forward_pe"]),
                t("price_book"): "N/A" if not snapshot else format_ratio(snapshot["price_to_book"]),
                t("revenue_yoy"): "N/A" if not snapshot else format_percent(snapshot["revenue_growth_yoy"]),
                t("analyst_target"): "N/A" if not snapshot else format_money(snapshot["analyst_target"], 2),
                t("upside_downside"): "N/A" if not snapshot else format_percent(snapshot["analyst_upside_pct"] / 100 if snapshot["analyst_upside_pct"] is not None else None),
            })
        st.dataframe(pd.DataFrame(valuation_rows), use_container_width=True, hide_index=True)
        st.markdown(f"#### {t('earnings_catalysts')}")
        catalyst_rows = []
        for ticker in watchlist:
            snapshot = snapshots.get(ticker) or {}
            catalyst_rows.append({
                t("ticker"): ticker, t("next_earnings_date"): snapshot.get("next_earnings_date") or "N/A",
                t("estimated_eps"): format_ratio(snapshot.get("estimated_eps")), t("actual_eps"): format_ratio(snapshot.get("actual_eps")),
                t("eps_surprise"): format_percent(snapshot.get("eps_surprise")),
                t("days_until_earnings"): snapshot.get("days_until_earnings") if snapshot.get("days_until_earnings") is not None else "N/A",
            })
        st.dataframe(pd.DataFrame(catalyst_rows), use_container_width=True, hide_index=True)
        st.markdown(f"#### {t('news_sentiment')}")
        try:
            client = get_openai_client()
            sentiment_rows = []
            for ticker in watchlist:
                try:
                    sentiment_rows.append({t("ticker"): ticker, **fetch_news_sentiment(ticker, client)})
                except Exception as exc:
                    sentiment_rows.append({t("ticker"): ticker, "sentiment": "N/A", "score": 0, "summary": str(exc)})
            st.dataframe(pd.DataFrame(sentiment_rows), use_container_width=True, hide_index=True)
            summary_payload = build_ai_summary_payload(snapshots, summarize_macro_snapshot(get_cached_macro_snapshot()))
            prompt = build_ai_summary_prompt(summary_payload)
            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
            st.markdown(f"#### {t('ai_summary')}")
            st.write(response.choices[0].message.content)
        except Exception as exc:
            st.warning(f"{t('ai_summary_unavailable')}: {exc}")


MULTI_AGENT_TEXTS = {
    "English": {
        "caption": "Run the five-agent workflow for one selected ticker.",
        "select_ticker": "Select ticker for multi-agent analysis",
        "run_button": "Run Multi-Agent Analysis",
        "running": "Running research agents for",
        "no_analysis": "No multi-agent analysis available for this ticker yet.",
        "final_conclusion": "Final Summary",
        "final_summary": "Final Summary",
        "overall_rating": "Overall Rating",
        "key_risk": "Key Risk",
        "key_opportunity": "Key Opportunity",
        "suggested_action": "Suggested Action",
        "key_levels": "Key Levels",
        "risk_management": "Risk Management",
        "agent_details": "Agent Details",
        "technical_analysis": "Technical Analysis",
        "options_analysis": "Options Analysis",
        "sentiment_analysis": "Sentiment Analysis",
        "fundamental_analysis": "Fundamental Analysis",
        "missing_data": "Missing Data",
        "fallback_validation_note": "OpenAI returned a result, but it did not pass quality checks. A rule-based fallback summary is shown.",
        "fallback_error_note": "OpenAI failed. A rule-based fallback summary is shown.",
        "neutral_rating": "NEUTRAL",
        "unavailable": "Unavailable",
        "hold": "Wait for clearer data before taking action.",
        "mixed_setup": "The setup is mixed based on currently available data.",
    },
    "中文": {
        "caption": "为一个选定股票运行五智能体分析流程。",
        "select_ticker": "选择要进行多智能体分析的股票",
        "run_button": "运行该股票多智能体分析",
        "running": "正在运行研究智能体：",
        "no_analysis": "当前股票暂无多智能体分析结果。",
        "final_conclusion": "最终总结",
        "final_summary": "最终总结",
        "overall_rating": "综合评级",
        "key_risk": "主要风险",
        "key_opportunity": "主要机会",
        "suggested_action": "建议操作",
        "key_levels": "关键价位",
        "risk_management": "风险管理",
        "agent_details": "智能体详情",
        "technical_analysis": "技术分析",
        "options_analysis": "期权分析",
        "sentiment_analysis": "情绪分析",
        "fundamental_analysis": "基本面分析",
        "missing_data": "缺失数据",
        "fallback_validation_note": "OpenAI 已返回结果，但未通过质量检查，已显示基于规则的备用摘要。",
        "fallback_error_note": "OpenAI 调用失败，已显示基于规则的备用摘要。",
        "neutral_rating": "中性",
        "unavailable": "不可用",
        "hold": "等待更清晰的数据后再采取行动。",
        "mixed_setup": "根据当前可用数据，整体形势较为混合。",
    },
    "Español": {
        "caption": "Ejecute el flujo de cinco agentes para un ticker seleccionado.",
        "select_ticker": "Seleccionar ticker para análisis multiagente",
        "run_button": "Ejecutar análisis multiagente",
        "running": "Ejecutando agentes de análisis para",
        "no_analysis": "No hay análisis multiagente disponible para este ticker.",
        "final_conclusion": "Resumen final",
        "final_summary": "Resumen final",
        "overall_rating": "Calificación general",
        "key_risk": "Riesgo principal",
        "key_opportunity": "Oportunidad principal",
        "suggested_action": "Acción sugerida",
        "key_levels": "Niveles clave",
        "risk_management": "Gestión del riesgo",
        "agent_details": "Detalles de los agentes",
        "technical_analysis": "Análisis técnico",
        "options_analysis": "Análisis de opciones",
        "sentiment_analysis": "Análisis de sentimiento",
        "fundamental_analysis": "Análisis fundamental",
        "missing_data": "Datos faltantes",
        "fallback_validation_note": "OpenAI devolvió un resultado, pero no superó los controles de calidad. Se muestra un resumen basado en reglas.",
        "fallback_error_note": "OpenAI falló. Se muestra un resumen basado en reglas.",
        "neutral_rating": "NEUTRAL",
        "unavailable": "No disponible",
        "hold": "Esperar datos más claros antes de actuar.",
        "mixed_setup": "La configuración es mixta según los datos disponibles.",
    },
}


def _multi_agent_language(language):
    language_text = str(language or "")
    if language_text == "中文" or language_text.lower() in ("zh", "chinese"):
        return "中文"
    if language_text == "Español" or language_text.lower() in ("es", "spanish", "español") or language_text.startswith("Espa"):
        return "Español"
    return "English"


def multi_agent_text(key, language=None):
    language = _multi_agent_language(language or st.session_state.get("language", "English"))
    return MULTI_AGENT_TEXTS.get(language, MULTI_AGENT_TEXTS["English"]).get(key, MULTI_AGENT_TEXTS["English"].get(key, key))


def build_multi_agent_language_instruction(language):
    language = _multi_agent_language(language)
    if language == "中文":
        return "Write the entire report in Simplified Chinese. Only ticker symbols and standard financial terms such as RSI, GEX, P/E, EBITDA may remain in English. Translate news titles by meaning instead of leaving English headlines."
    if language == "Español":
        return "Write the entire report in Spanish. Only ticker symbols and standard financial terms such as RSI, GEX, P/E, EBITDA may remain in English. Translate news titles by meaning instead of leaving English headlines."
    return "Please write the entire analysis in English."


def _multi_agent_is_unavailable(value):
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_multi_agent_is_unavailable(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value
    return str(value).strip().lower() in ("", "n/a", "none", "nan", "unavailable")


def _multi_agent_has_value(container, keys):
    container = container or {}
    return any(not _multi_agent_is_unavailable(container.get(key)) for key in keys)


def _multi_agent_news_sentiment(headlines):
    text = " ".join(str(headline or "") for headline in headlines).lower()
    positive = sum(_contains_news_keyword(text, keyword) for keyword in POSITIVE_NEWS_KEYWORDS)
    negative = sum(_contains_news_keyword(text, keyword) for keyword in NEGATIVE_NEWS_KEYWORDS)
    score = positive - negative
    if score > 0:
        return "Positive", score
    if score < 0:
        return "Negative", score
    return "Neutral", 0


def _multi_agent_loaded_flags(inputs):
    technical = inputs.get("technical") or {}
    fundamental = inputs.get("fundamental") or {}
    options = inputs.get("options") or {}
    sentiment = inputs.get("sentiment") or {}
    return {
        "technical_data_loaded": _multi_agent_has_value(technical, ("price", "daily_change_pct", "rsi_14", "ma_5", "ma_20", "volume_vs_20d")),
        "options_data_loaded": _multi_agent_has_value(options, ("put_call_ratio", "net_gex", "max_pain", "total_call_oi", "total_put_oi", "call_wall", "put_wall")),
        "news_data_loaded": _multi_agent_has_value(sentiment, ("latest_headlines", "latest_sentiment", "sentiment_score")),
        "financial_data_loaded": _multi_agent_has_value(fundamental, ("current_price", "daily_change_pct", "revenue", "market_cap", "net_margin", "trailing_pe", "forward_pe")),
    }


def _multi_agent_inputs_have_data(inputs):
    technical = inputs.get("technical") or {}
    fundamental = inputs.get("fundamental") or {}
    options = inputs.get("options") or {}
    sentiment = inputs.get("sentiment") or {}
    return any(
        not _multi_agent_is_unavailable(value)
        for value in (
            technical.get("trend"),
            technical.get("price"),
            technical.get("daily_change_pct"),
            technical.get("rsi_14"),
            technical.get("ma_5"),
            technical.get("ma_20"),
            technical.get("volume_vs_20d"),
            fundamental.get("current_price"),
            fundamental.get("daily_change_pct"),
            fundamental.get("revenue"),
            fundamental.get("market_cap"),
            fundamental.get("net_margin"),
            fundamental.get("trailing_pe"),
            fundamental.get("forward_pe"),
            fundamental.get("revenue_growth_yoy"),
            fundamental.get("analyst_target"),
            options.get("put_call_ratio"),
            options.get("max_pain"),
            options.get("net_gex"),
            options.get("call_wall"),
            options.get("put_wall"),
            sentiment.get("latest_headlines"),
            sentiment.get("latest_sentiment"),
        )
    )


def collect_multi_agent_inputs(ticker):
    inputs = {"ticker": ticker, "company_name": company_name(ticker), "report_date": datetime.now().strftime("%Y-%m-%d")}
    errors = {}
    try:
        inputs["technical"] = get_technical_summary(ticker)
    except Exception as exc:
        inputs["technical"] = {"status": "unavailable"}
        errors["technical"] = str(exc)
    try:
        snapshot = get_company_snapshot(ticker)
        inputs["fundamental"] = {
            "company_name": company_name(ticker, snapshot),
            "current_price": snapshot.get("price") if snapshot else None,
            "daily_change_pct": snapshot.get("change_pct") if snapshot else None,
            "revenue": snapshot.get("revenue") if snapshot else None,
            "market_cap": snapshot.get("market_cap") if snapshot else None,
            "net_margin": snapshot.get("net_margin") if snapshot else None,
            "trailing_pe": snapshot.get("trailing_pe") if snapshot else None,
            "forward_pe": snapshot.get("forward_pe") if snapshot else None,
            "price_to_book": snapshot.get("price_to_book") if snapshot else None,
            "revenue_growth_yoy": snapshot.get("revenue_growth_yoy") if snapshot else None,
            "analyst_target": snapshot.get("analyst_target") if snapshot else None,
            "analyst_rating": snapshot.get("analyst_rating") if snapshot else None,
            "data_source": snapshot.get("source") if snapshot else None,
        }
    except Exception as exc:
        inputs["fundamental"] = {"status": "unavailable"}
        errors["fundamental"] = str(exc)
    try:
        inputs["options"] = get_options_summary(ticker)
    except Exception as exc:
        inputs["options"] = {"status": "unavailable"}
        errors["options"] = str(exc)
    try:
        headlines = fetch_news_headlines(ticker, 6)
        sentiment_label, sentiment_score = _multi_agent_news_sentiment(headlines)
        inputs["sentiment"] = {
            "latest_headlines": headlines,
            "latest_sentiment": sentiment_label if headlines else None,
            "sentiment_score": sentiment_score if headlines else None,
        }
    except Exception as exc:
        inputs["sentiment"] = {"latest_headlines": []}
        errors["sentiment"] = str(exc)
    inputs["errors"] = errors
    inputs["no_data"] = not _multi_agent_inputs_have_data(inputs)
    inputs["loaded_flags"] = _multi_agent_loaded_flags(inputs)
    return inputs


def build_multi_agent_prompt(ticker, inputs, language):
    return f"""
You are a five-agent equity research team analyzing only this selected ticker: {ticker}.
{build_multi_agent_language_instruction(language)}

Use only the supplied structured data. Do not invent missing values. If a metric is unavailable, explain exactly which metric is missing in missing_data.
Return a complete structured report in the selected language.

Strict JSON contract:
Return valid JSON only with exactly these keys:
{{
  "overall_rating": "...",
  "key_risk": "...",
  "key_opportunity": "...",
  "suggested_action": "...",
  "final_summary": "...",
  "technical_analysis": "...",
  "options_analysis": "...",
  "sentiment_analysis": "...",
  "fundamental_analysis": "...",
  "risk_management": "...",
  "key_levels": ["...", "...", "..."],
  "missing_data": ["..."]
}}

Quality rules:
- Do not return N/A if data is available.
- Do not write "missing data: none" or any equivalent sentence.
- If no data is missing, set "missing_data": [].
- Use the actual metrics provided below and cite the numbers in the analysis text.
- Explain why the overall rating is bullish, neutral, or bearish.
- Mention uncertainty and risk clearly.
- Avoid generic text; every section must connect to the supplied metrics.
- Each analysis section should be specific and at least 2-4 sentences when data is available.
- For Chinese ratings use 看涨 / 看跌 / 中性. For Spanish ratings use Alcista / Bajista / Neutral. For English use Bullish / Bearish / Neutral.

Technical analysis must include:
- current price, daily change, RSI, MA5, MA20
- whether price is above or below MA5 and MA20
- momentum interpretation
- support/resistance if available, otherwise infer cautiously from MA5/MA20 and options walls

Options analysis must include:
- expiry date, Put/Call OI ratio, call OI, put OI, net GEX, max pain, call wall, put wall
- whether negative GEX may amplify volatility
- whether call wall may act as resistance
- whether put wall may act as support or a downside magnet
- whether current price is far from max pain

Sentiment analysis must include:
- latest news titles translated/localized into the selected language when the selected language is not English
- localized summary of what the news means
- sentiment as positive / neutral / negative in the selected language
- why the sentiment matters for the stock

Fundamental analysis must include:
- revenue, market cap, net margin
- valuation quality if trailing P/E, forward P/E, price/book, or analyst target is available
- profitability quality
- whether the company looks like high growth, cyclical, margin risk, or a quality compounder
- if data is insufficient, explain exactly what is missing

Risk management must include:
- whether the stock appears high beta or volatile based on daily move, RSI, options GEX, and option walls
- whether current options structure increases volatility risk
- what an investor using leverage should watch
- key levels where risk may increase
- do not give direct financial advice

Structured data:
{json.dumps(inputs, indent=2, ensure_ascii=False, default=str)}
"""


def _multi_agent_metric(value, kind="number"):
    if _multi_agent_is_unavailable(value):
        return None
    if kind == "money":
        return format_money(value, 2)
    if kind == "money0":
        return format_money(value, 0)
    if kind == "percent_points":
        return f"{float(value):+.2f}%"
    if kind == "percent":
        return format_percent(value)
    if kind == "ratio":
        return format_ratio(value)
    return f"{float(value):,.2f}" if isinstance(value, (int, float, np.integer, np.floating)) else str(value)


def _multi_agent_first_available(*values):
    for value in values:
        if not _multi_agent_is_unavailable(value):
            return value
    return None


def _multi_agent_missing_labels(inputs, language="English"):
    language = _multi_agent_language(language)
    technical = inputs.get("technical") or {}
    fundamental = inputs.get("fundamental") or {}
    options = inputs.get("options") or {}
    sentiment = inputs.get("sentiment") or {}
    labels = {
        "English": {
            "price": "price",
            "daily_change": "daily change",
            "rsi": "RSI",
            "ma5": "MA5",
            "ma20": "MA20",
            "put_call": "options Put/Call ratio",
            "net_gex": "net GEX",
            "max_pain": "max pain",
            "sentiment": "latest news sentiment",
            "revenue": "revenue",
            "market_cap": "market cap",
            "net_margin": "net margin",
        },
        "中文": {
            "price": "现价",
            "daily_change": "日涨跌幅",
            "rsi": "RSI",
            "ma5": "MA5",
            "ma20": "MA20",
            "put_call": "期权 Put/Call 比率",
            "net_gex": "净 GEX",
            "max_pain": "最大痛点",
            "sentiment": "最新新闻情绪",
            "revenue": "收入",
            "market_cap": "市值",
            "net_margin": "净利率",
        },
        "Español": {
            "price": "precio",
            "daily_change": "cambio diario",
            "rsi": "RSI",
            "ma5": "MA5",
            "ma20": "MA20",
            "put_call": "ratio Put/Call de opciones",
            "net_gex": "GEX neto",
            "max_pain": "max pain",
            "sentiment": "sentimiento de noticias más reciente",
            "revenue": "ingresos",
            "market_cap": "capitalización bursátil",
            "net_margin": "margen neto",
        },
    }.get(language, {})
    checks = (
        (labels["price"], _multi_agent_first_available(technical.get("price"), fundamental.get("current_price"))),
        (labels["daily_change"], _multi_agent_first_available(technical.get("daily_change_pct"), fundamental.get("daily_change_pct"))),
        (labels["rsi"], technical.get("rsi_14")),
        (labels["ma5"], technical.get("ma_5")),
        (labels["ma20"], technical.get("ma_20")),
        (labels["put_call"], options.get("put_call_ratio")),
        (labels["net_gex"], options.get("net_gex")),
        (labels["max_pain"], options.get("max_pain")),
        (labels["sentiment"], sentiment.get("latest_sentiment")),
        (labels["revenue"], fundamental.get("revenue")),
        (labels["market_cap"], fundamental.get("market_cap")),
        (labels["net_margin"], fundamental.get("net_margin")),
    )
    return [label for label, value in checks if _multi_agent_is_unavailable(value)]


def _multi_agent_rating(technical, options, sentiment, fundamental):
    score = 0
    trend = str(technical.get("trend") or "").lower()
    rsi = technical.get("rsi_14")
    pc_ratio = options.get("put_call_ratio")
    net_gex = options.get("net_gex")
    net_margin = fundamental.get("net_margin")
    revenue_growth = fundamental.get("revenue_growth_yoy")
    sentiment_label = sentiment.get("latest_sentiment")
    if trend == "bullish":
        score += 1
    elif trend == "bearish":
        score -= 1
    if rsi is not None and not pd.isna(rsi):
        if rsi < 35:
            score += 1
        elif rsi > 70:
            score -= 1
    if pc_ratio is not None and not pd.isna(pc_ratio):
        if pc_ratio < 0.8:
            score += 1
        elif pc_ratio > 1.2:
            score -= 1
    if net_gex is not None and not pd.isna(net_gex) and net_gex < 0:
        score -= 1
    if sentiment_label == "Positive":
        score += 1
    elif sentiment_label == "Negative":
        score -= 1
    if net_margin is not None and not pd.isna(net_margin) and net_margin > 0:
        score += 1
    if revenue_growth is not None and not pd.isna(revenue_growth) and revenue_growth > 0:
        score += 1
    if score >= 2:
        return "BULLISH"
    if score <= -2:
        return "BEARISH"
    return "NEUTRAL"


def _localized_rating(rating, language):
    language = _multi_agent_language(language)
    mapping = {
        "中文": {"BULLISH": "看涨", "BEARISH": "看跌", "NEUTRAL": "中性", "Bullish": "看涨", "Bearish": "看跌", "Neutral": "中性"},
        "Español": {"BULLISH": "alcista", "BEARISH": "bajista", "NEUTRAL": "neutral", "Bullish": "alcista", "Bearish": "bajista", "Neutral": "neutral"},
        "English": {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral", "Bullish": "bullish", "Bearish": "bearish", "Neutral": "neutral"},
    }
    return mapping.get(language, mapping["English"]).get(str(rating), str(rating or mapping.get(language, mapping["English"])["NEUTRAL"]))


def _multi_agent_chinese_money(value):
    text = _multi_agent_metric(value, "money")
    return text.replace("$", "") + " 美元" if text and text.startswith("$") else text


def _multi_agent_position_text(price, level, language, label):
    if _multi_agent_is_unavailable(price) or _multi_agent_is_unavailable(level):
        return None
    relation = "above" if float(price) > float(level) else "below" if float(price) < float(level) else "at"
    distance = (float(price) - float(level)) / float(level) * 100 if float(level) else 0
    if _multi_agent_language(language) == "中文":
        relation_text = {"above": "高于", "below": "低于", "at": "位于"}[relation]
        return f"价格{relation_text} {label}（{_multi_agent_chinese_money(level)}），偏离约 {distance:+.2f}%"
    if _multi_agent_language(language) == "Español":
        relation_text = {"above": "por encima", "below": "por debajo", "at": "en"}[relation]
        article = "la " if label in ("MA5", "MA20") else ""
        return f"El precio está {relation_text} de {article}{label} ({_multi_agent_metric(level, 'money')}), con una distancia aproximada de {distance:+.2f}%"
    return f"Price is {relation} {label} ({_multi_agent_metric(level, 'money')}), about {distance:+.2f}% away"


def _multi_agent_key_levels(technical, options, fundamental, language):
    price = _multi_agent_first_available(technical.get("price"), fundamental.get("current_price"))
    language = _multi_agent_language(language)
    if language == "中文":
        labels = {
            "ma5": "MA5",
            "ma20": "MA20",
            "call_wall": "Call wall",
            "put_wall": "Put wall",
            "max_pain": "最大痛点",
            "analyst_target": "分析师目标价",
        }
    elif language == "Español":
        labels = {
            "ma5": "MA5",
            "ma20": "MA20",
            "call_wall": "Call wall",
            "put_wall": "Put wall",
            "max_pain": "max pain",
            "analyst_target": "precio objetivo de analistas",
        }
    else:
        labels = {
            "ma5": "MA5",
            "ma20": "MA20",
            "call_wall": "call wall",
            "put_wall": "put wall",
            "max_pain": "max pain",
            "analyst_target": "analyst target",
        }
    candidates = [
        (labels["ma5"], technical.get("ma_5")),
        (labels["ma20"], technical.get("ma_20")),
        (labels["call_wall"], options.get("call_wall")),
        (labels["put_wall"], options.get("put_wall")),
        (labels["max_pain"], options.get("max_pain")),
        (labels["analyst_target"], fundamental.get("analyst_target")),
    ]
    levels = []
    for label, value in candidates:
        if _multi_agent_is_unavailable(value):
            continue
        text = _multi_agent_position_text(price, value, language, label)
        fallback_value = _multi_agent_chinese_money(value) if language == "中文" else _multi_agent_metric(value, "money")
        levels.append(text or f"{label}: {fallback_value}")
    return levels[:6]


def _multi_agent_localized_sentiment(sentiment_label, language):
    label = str(sentiment_label or "Neutral")
    if _multi_agent_language(language) == "中文":
        return {"Positive": "正面", "Negative": "负面", "Neutral": "中性", "positive": "正面", "negative": "负面", "neutral": "中性"}.get(label, "中性")
    if _multi_agent_language(language) == "Español":
        return {"Positive": "positivo", "Negative": "negativo", "Neutral": "neutral", "positive": "positivo", "negative": "negativo", "neutral": "neutral"}.get(label, "neutral")
    return {"Positive": "positive", "Negative": "negative", "Neutral": "neutral"}.get(label, label.lower())


def _multi_agent_localized_headline_notes(headlines, ticker, language):
    notes = []
    for index, headline in enumerate((headlines or [])[:4], start=1):
        text = str(headline or "").lower()
        if any(word in text for word in POSITIVE_NEWS_KEYWORDS):
            tone = "positive"
        elif any(word in text for word in NEGATIVE_NEWS_KEYWORDS):
            tone = "negative"
        else:
            tone = "neutral"
        if _multi_agent_language(language) == "中文":
            tone_text = {"positive": "偏正面", "negative": "偏负面", "neutral": "偏中性"}[tone]
            notes.append(f"第{index}条新闻与 {ticker} 相关，关键词显示情绪{tone_text}。")
        elif _multi_agent_language(language) == "Español":
            tone_text = {"positive": "positivo", "negative": "negativo", "neutral": "neutral"}[tone]
            notes.append(f"Titular {index} relacionado con {ticker}; las palabras clave sugieren un tono {tone_text}.")
        else:
            notes.append(f"Headline {index}: {headline}")
    if notes:
        return notes
    if _multi_agent_language(language) == "中文":
        return ["暂无可用的最新新闻标题。"]
    if _multi_agent_language(language) == "Español":
        return ["No hay titulares recientes disponibles."]
    return ["No recent headlines are available."]


def _multi_agent_localized_missing_item(item, language):
    language = _multi_agent_language(language)
    normalized = str(item or "").strip()
    if not normalized:
        return normalized
    mapping = {
        "price": {"中文": "现价", "Español": "precio"},
        "daily change": {"中文": "日涨跌幅", "Español": "cambio diario"},
        "RSI": {"中文": "RSI", "Español": "RSI"},
        "MA5": {"中文": "MA5", "Español": "MA5"},
        "MA20": {"中文": "MA20", "Español": "MA20"},
        "options put/call ratio": {"中文": "期权 Put/Call 比率", "Español": "ratio Put/Call de opciones"},
        "options Put/Call ratio": {"中文": "期权 Put/Call 比率", "Español": "ratio Put/Call de opciones"},
        "net GEX": {"中文": "净 GEX", "Español": "GEX neto"},
        "max pain": {"中文": "最大痛点", "Español": "max pain"},
        "latest news sentiment": {"中文": "最新新闻情绪", "Español": "sentimiento de noticias más reciente"},
        "revenue": {"中文": "收入", "Español": "ingresos"},
        "market cap": {"中文": "市值", "Español": "capitalización bursátil"},
        "net margin": {"中文": "净利率", "Español": "margen neto"},
    }
    return mapping.get(normalized, {}).get(language, normalized)


def _multi_agent_report_incomplete_reason(result):
    if not isinstance(result, dict):
        return "OpenAI result is not a JSON object."
    required = (
        "overall_rating", "key_risk", "key_opportunity", "suggested_action", "final_summary",
        "technical_analysis", "options_analysis", "sentiment_analysis", "fundamental_analysis",
        "risk_management", "key_levels", "missing_data",
    )
    missing_keys = [key for key in required if key not in result]
    if missing_keys:
        return f"OpenAI result is missing required fields: {', '.join(missing_keys)}."
    text_keys = [key for key in required if key not in ("key_levels", "missing_data")]
    for key in text_keys:
        value = result.get(key)
        if _multi_agent_is_unavailable(value) or len(str(value).strip()) < 35:
            return f"OpenAI field '{key}' is empty or too short."
    if not isinstance(result.get("key_levels"), list):
        return "OpenAI field 'key_levels' is not a list."
    if not isinstance(result.get("missing_data"), list):
        return "OpenAI field 'missing_data' is not a list."
    joined = " ".join(str(result.get(key, "")) for key in text_keys).lower()
    if "missing data: none" in joined or "missing_data: none" in joined:
        return "OpenAI text contains a literal missing-data placeholder."
    return None


def _multi_agent_float(value):
    if _multi_agent_is_unavailable(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _multi_agent_contains_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def _multi_agent_report_validation_failure(result, inputs, language=None):
    incomplete_reason = _multi_agent_report_incomplete_reason(result)
    if incomplete_reason:
        return incomplete_reason

    technical = (inputs or {}).get("technical") or {}
    fundamental = (inputs or {}).get("fundamental") or {}
    options = (inputs or {}).get("options") or {}
    price = _multi_agent_float(_multi_agent_first_available(technical.get("price"), fundamental.get("current_price")))
    ma5 = _multi_agent_float(technical.get("ma_5"))
    ma20 = _multi_agent_float(technical.get("ma_20"))
    net_gex = _multi_agent_float(options.get("net_gex"))
    put_call_ratio = _multi_agent_float(options.get("put_call_ratio"))

    text_fields = (
        "final_summary", "key_risk", "key_opportunity", "suggested_action",
        "technical_analysis", "options_analysis", "sentiment_analysis",
        "fundamental_analysis", "risk_management",
    )
    joined = " ".join(str(result.get(key, "")) for key in text_fields).lower()
    if _multi_agent_language(language) == "中文":
        english_phrases = (
            "current price", "primary risk", "opportunity improves",
            "this is not direct financial advice", "risk management",
            "fundamental data includes",
        )
        if _multi_agent_contains_any(joined, english_phrases):
            return "Language contradiction: Chinese mode result contains obvious English fallback phrases."
    technical_text = str(result.get("technical_analysis", "")).lower()
    options_text = str(result.get("options_analysis", "")).lower()
    risk_text = str(result.get("risk_management", "")).lower()
    options_and_risk = f"{options_text} {risk_text}"

    above_terms = ("above ma5", "above the ma5", "over ma5", "over the ma5", "higher than ma5", "higher than the ma5", "高于ma5", "位于ma5上方", "ma5上方", "por encima de ma5", "por encima del ma5", "superior a ma5")
    below_terms = ("below ma20", "below the ma20", "under ma20", "under the ma20", "lower than ma20", "lower than the ma20", "低于ma20", "位于ma20下方", "ma20下方", "por debajo de ma20", "por debajo del ma20", "inferior a ma20")
    if price is not None and ma5 is not None and price < ma5 and _multi_agent_contains_any(technical_text, above_terms):
        return "Metric contradiction: price is below MA5, but OpenAI says price is above MA5."
    if price is not None and ma20 is not None and price > ma20 and _multi_agent_contains_any(technical_text, below_terms):
        return "Metric contradiction: price is above MA20, but OpenAI says price is below MA20."

    negative_gex_terms = ("negative gex", "negative gamma", "gex negativo", "gamma negativa", "负gex", "负 gamma", "负gamma", "负伽马")
    volatility_terms = ("volatility", "volatile", "amplif", "magnif", "波动", "放大", "加剧", "volatilidad", "volátil")
    if net_gex is not None and net_gex < 0:
        describes_negative_gex = _multi_agent_contains_any(options_and_risk, negative_gex_terms)
        describes_volatility = _multi_agent_contains_any(options_and_risk, volatility_terms)
        if not (describes_negative_gex and describes_volatility):
            return "Metric contradiction: net GEX is negative, but OpenAI did not describe negative GEX as volatility-amplifying."

    call_dominated_terms = ("call-dominated", "call dominated", "calls dominate", "call-heavy", "call heavy", "dominated by calls", "call主导", "看涨期权主导", "看涨主导", "dominado por calls", "dominado por call", "predominio de calls")
    if put_call_ratio is not None and put_call_ratio > 1.5 and _multi_agent_contains_any(joined, call_dominated_terms):
        return "Metric contradiction: put/call ratio is above 1.5, but OpenAI describes options positioning as call-dominated."
    return None


def _multi_agent_report_is_incomplete(result):
    return _multi_agent_report_incomplete_reason(result) is not None



def _localized_multi_agent_fallback(ticker, inputs, language, error=None):
    language = _multi_agent_language(language)
    technical = inputs.get("technical") or {}
    fundamental = inputs.get("fundamental") or {}
    options = inputs.get("options") or {}
    sentiment = inputs.get("sentiment") or {}
    headlines = sentiment.get("latest_headlines") or []
    missing = _multi_agent_missing_labels(inputs, language)
    price = _multi_agent_first_available(technical.get("price"), fundamental.get("current_price"))
    daily_change = _multi_agent_first_available(technical.get("daily_change_pct"), fundamental.get("daily_change_pct"))
    rating = _multi_agent_rating(technical, options, sentiment, fundamental)
    rating_text = _localized_rating(rating, language)
    trend = technical.get("trend") or None
    localized_trend = _localized_rating(str(trend or "NEUTRAL").upper(), language) if trend else multi_agent_text("unavailable", language)
    rsi = _multi_agent_metric(technical.get("rsi_14"))
    ma5 = _multi_agent_metric(technical.get("ma_5"), "money")
    ma20 = _multi_agent_metric(technical.get("ma_20"), "money")
    call_oi = _multi_agent_metric(options.get("total_call_oi"))
    put_oi = _multi_agent_metric(options.get("total_put_oi"))
    pc_ratio = _multi_agent_metric(options.get("put_call_ratio"), "ratio")
    net_gex = _multi_agent_metric(options.get("net_gex"), "money0")
    max_pain = _multi_agent_metric(options.get("max_pain"), "money0")
    call_wall = _multi_agent_metric(options.get("call_wall"), "money0")
    put_wall = _multi_agent_metric(options.get("put_wall"), "money0")
    expiry = options.get("nearest_expiration") or multi_agent_text("unavailable", language)
    revenue = _multi_agent_metric(fundamental.get("revenue"), "money")
    market_cap = _multi_agent_metric(fundamental.get("market_cap"), "money")
    net_margin = _multi_agent_metric(fundamental.get("net_margin"), "percent")
    trailing_pe = _multi_agent_metric(fundamental.get("trailing_pe"), "ratio")
    forward_pe = _multi_agent_metric(fundamental.get("forward_pe"), "ratio")
    price_to_book = _multi_agent_metric(fundamental.get("price_to_book"), "ratio")
    revenue_growth = _multi_agent_metric(fundamental.get("revenue_growth_yoy"), "percent")
    analyst_target = _multi_agent_metric(fundamental.get("analyst_target"), "money")
    sentiment_label = _multi_agent_localized_sentiment(sentiment.get("latest_sentiment"), language)
    price_text = _multi_agent_metric(price, "money") or multi_agent_text("unavailable", language)
    change_text = _multi_agent_metric(daily_change, "percent_points") or multi_agent_text("unavailable", language)
    ma5_relation = _multi_agent_position_text(price, technical.get("ma_5"), language, "MA5")
    ma20_relation = _multi_agent_position_text(price, technical.get("ma_20"), language, "MA20")
    max_pain_label = "最大痛点" if language == "中文" else "max pain"
    max_pain_relation = _multi_agent_position_text(price, options.get("max_pain"), language, max_pain_label)
    headline_notes = _multi_agent_localized_headline_notes(headlines, ticker, language)
    key_levels = _multi_agent_key_levels(technical, options, fundamental, language)
    negative_gex = not _multi_agent_is_unavailable(options.get("net_gex")) and float(options.get("net_gex")) < 0
    high_daily_move = not _multi_agent_is_unavailable(daily_change) and abs(float(daily_change)) >= 3
    rsi_value = technical.get("rsi_14")
    rsi_extreme = not _multi_agent_is_unavailable(rsi_value) and (float(rsi_value) >= 70 or float(rsi_value) <= 30)

    unavailable = multi_agent_text("unavailable", language)
    if language == "中文":
        result = {
            "ticker": ticker, "source": "fallback", "error": error, "no_data": inputs.get("no_data", False),
            "final_summary": f"{ticker} 当前规则版综合判断为{rating_text}。现价为 {price_text}，日涨跌幅为 {change_text}，技术趋势为{localized_trend}；期权端 Put/Call OI 比率为 {pc_ratio or unavailable}，净 GEX 为 {net_gex or unavailable}。该评级综合了技术面、期权结构、新闻情绪和基本面数据，同时需要注意市场波动和数据口径不确定性。",
            "overall_rating": rating_text,
            "key_risk": "主要风险来自估值波动和期权结构。当前净 GEX 为负，可能放大价格波动；如果价格跌破关键支撑位，短线风险可能上升。" if negative_gex else f"主要风险来自估值波动和期权结构。当前净 GEX 为 {net_gex or unavailable}，暂未显示明显的负 GEX 放大效应；如果价格跌破关键支撑位，短线风险可能上升。",
            "key_opportunity": "主要机会来自技术趋势改善、新闻情绪回暖以及盈利能力保持稳定。如果价格重新站上关键均线并突破 Call wall，走势会更清晰。",
            "suggested_action": "这不是投资建议。可以等待价格行为、期权墙和基本面数据进一步确认；使用杠杆的投资者应提前设定失效价位和仓位上限。",
            "technical_analysis": f"技术面方面，现价为 {price_text}，日涨跌幅为 {change_text}，RSI 为 {rsi or unavailable}，MA5 为 {ma5 or unavailable}，MA20 为 {ma20 or unavailable}。{ma5_relation or '价格与 MA5 的关系暂不可用'}；{ma20_relation or '价格与 MA20 的关系暂不可用'}。当前技术趋势为{localized_trend}；RSI 极端区间可能增加反转风险。关键观察位置包括 MA20、Call wall {call_wall or unavailable}、Put wall {put_wall or unavailable} 和最大痛点 {max_pain or unavailable}。",
            "options_analysis": f"最近到期日为 {expiry}。Put/Call OI 比率为 {pc_ratio or unavailable}，Call OI 为 {call_oi or unavailable}，Put OI 为 {put_oi or unavailable}。净 GEX 为 {net_gex or unavailable}，如果为负，说明做市商对冲可能放大价格波动。Call wall 位于 {call_wall or unavailable}，可能形成上方压力；Put wall 位于 {put_wall or unavailable}，可能形成下方支撑或下行磁吸。最大痛点为 {max_pain or unavailable}。{max_pain_relation or '当前无法可靠计算价格与最大痛点的距离。'}",
            "sentiment_analysis": f"最新新闻情绪为{sentiment_label}。{' '.join(headline_notes)} 新闻情绪会影响市场对增长、利润率和行业需求的预期，也可能与拥挤的期权仓位相互放大。",
            "fundamental_analysis": f"基本面方面，公司收入为 {revenue or unavailable}，市值为 {market_cap or unavailable}，净利率为 {net_margin or unavailable}。估值指标包括 P/E {trailing_pe or unavailable}、Forward P/E {forward_pe or unavailable}、P/B {price_to_book or unavailable}，分析师目标价为 {analyst_target or unavailable}。收入同比增长为 {revenue_growth or unavailable}。这些数据说明公司具备成长和盈利能力，但仍需要结合行业周期、库存、毛利率和现金流进一步判断。",
            "risk_management": "风险管理方面，当前个股波动较高，负 GEX 可能增加短线波动。使用融资或杠杆时，需要重点关注 MA5、MA20、Call wall、Put wall 和最大痛点附近的价格反应。" if negative_gex or high_daily_move else "风险管理方面，当前日内波动暂未显示极端状态，但仍需要关注期权墙和关键均线附近的价格反应。使用融资或杠杆时，需要重点关注 MA5、MA20、Call wall、Put wall 和最大痛点附近的价格反应。",
            "key_levels": key_levels, "missing_data": missing,
        }
        failed_phrases = (
            "Current price", "Primary risk", "Opportunity improves",
            "This is not direct financial advice", "Risk management",
            "Fundamental data includes",
        )
        joined = " ".join(str(result.get(key, "")) for key in (
            "final_summary", "key_risk", "key_opportunity", "suggested_action",
            "technical_analysis", "options_analysis", "sentiment_analysis",
            "fundamental_analysis", "risk_management",
        ))
        if any(phrase in joined for phrase in failed_phrases):
            result.update({
                "final_summary": f"{ticker} 当前规则版综合判断为{rating_text}。现价为 {price_text}，日涨跌幅为 {change_text}，技术趋势为{localized_trend}；期权端 Put/Call OI 比率为 {pc_ratio or unavailable}，净 GEX 为 {net_gex or unavailable}。",
                "key_risk": "主要风险来自估值波动、期权结构和关键支撑位失守。",
                "key_opportunity": "主要机会来自技术趋势改善、新闻情绪回暖以及盈利能力保持稳定。",
                "suggested_action": "这不是投资建议。应等待价格、期权墙和基本面数据进一步确认。",
                "fundamental_analysis": f"基本面方面，公司收入为 {revenue or unavailable}，市值为 {market_cap or unavailable}，净利率为 {net_margin or unavailable}。",
                "risk_management": "风险管理方面，需要关注 MA5、MA20、Call wall、Put wall 和最大痛点附近的价格反应。",
            })
        return result
    if language == "Español":
        return {
            "ticker": ticker, "source": "fallback", "error": error, "no_data": inputs.get("no_data", False),
            "final_summary": f"La lectura integral basada en reglas para {ticker} es {rating_text}. El precio actual es {price_text}, el cambio diario es {change_text} y la tendencia técnica es {localized_trend}; en opciones, el ratio Put/Call OI es {pc_ratio or unavailable} y el GEX neto es {net_gex or unavailable}. La calificación combina análisis técnico, estructura de opciones, sentimiento de noticias y datos fundamentales, con atención a la volatilidad y a la incertidumbre de los datos.",
            "overall_rating": rating_text,
            "key_risk": f"El riesgo principal proviene de la volatilidad de valoración y de la estructura de opciones. El GEX neto es {net_gex or unavailable}; {'si es negativo, puede ampliar los movimientos de precio' if negative_gex else 'por ahora no muestra una señal clara de amplificación por GEX negativo'}. Si el precio pierde soportes clave, el riesgo de corto plazo puede aumentar.",
            "key_opportunity": "La oportunidad principal proviene de una mejora de la tendencia técnica, una recuperación del sentimiento de noticias y una rentabilidad estable. Si el precio recupera medias clave y supera el Call wall, la lectura será más clara.",
            "suggested_action": "Esto no es asesoramiento financiero. Conviene esperar más confirmación de la acción del precio, los muros de opciones y los datos fundamentales; los inversores con apalancamiento deberían definir de antemano niveles de invalidación y límites de posición.",
            "technical_analysis": f"En análisis técnico, el precio actual es {price_text}, el cambio diario es {change_text}, el RSI es {rsi or unavailable}, la MA5 es {ma5 or unavailable} y la MA20 es {ma20 or unavailable}. {ma5_relation or 'La relación del precio con la MA5 no está disponible'}; {ma20_relation or 'la relación del precio con la MA20 no está disponible'}. La tendencia técnica es {localized_trend}; los extremos del RSI pueden elevar el riesgo de reversión. Los niveles relevantes incluyen la MA20, el Call wall {call_wall or unavailable}, el Put wall {put_wall or unavailable} y el max pain {max_pain or unavailable}.",
            "options_analysis": f"El vencimiento más cercano es {expiry}. El ratio Put/Call OI es {pc_ratio or unavailable}, el Call OI es {call_oi or unavailable} y el Put OI es {put_oi or unavailable}. El GEX neto es {net_gex or unavailable}; si es negativo, la cobertura de los creadores de mercado puede amplificar la volatilidad. El Call wall está en {call_wall or unavailable} y puede actuar como resistencia; el Put wall está en {put_wall or unavailable} y puede actuar como soporte o atracción bajista. El max pain es {max_pain or unavailable}. {max_pain_relation or 'No se puede calcular de forma fiable la distancia frente al max pain.'}",
            "sentiment_analysis": f"El sentimiento de noticias más reciente es {sentiment_label}. {' '.join(headline_notes)} El sentimiento importa porque puede cambiar las expectativas sobre crecimiento, márgenes y demanda sectorial.",
            "fundamental_analysis": f"En fundamentales, los ingresos son {revenue or unavailable}, la capitalización bursátil es {market_cap or unavailable} y el margen neto es {net_margin or unavailable}. Las métricas de valoración incluyen P/E {trailing_pe or unavailable}, Forward P/E {forward_pe or unavailable} y P/B {price_to_book or unavailable}. El crecimiento interanual de ingresos es {revenue_growth or unavailable}. Estos datos ayudan a evaluar crecimiento y rentabilidad, pero deben combinarse con ciclo sectorial, inventarios, margen bruto y flujo de caja.",
            "risk_management": f"En gestión del riesgo, {'el movimiento diario elevado indica volatilidad alta' if high_daily_move else 'el movimiento diario no indica volatilidad extrema por sí solo'}, y {'el GEX negativo puede aumentar la volatilidad de corto plazo' if negative_gex else 'la estructura de opciones no muestra una amplificación clara por GEX negativo'}. Con margen o apalancamiento, conviene vigilar la MA5, la MA20, el Call wall, el Put wall y las reacciones cerca del max pain.",
            "key_levels": key_levels, "missing_data": missing,
        }
    return {
        "ticker": ticker, "source": "fallback", "error": error, "no_data": inputs.get("no_data", False),
        "final_summary": f"{ticker} has a {rating_text} rule-based read. Current price is {price_text}, daily change is {change_text}, technical trend is {localized_trend}; options show Put/Call {pc_ratio or 'unavailable'} and net GEX {net_gex or 'unavailable'}. The rating reflects the combined technical, options, sentiment, and fundamental evidence, with uncertainty from any missing fields and market volatility.",
        "overall_rating": rating_text,
        "key_risk": f"Primary risk is valuation and volatility. Net GEX is {net_gex or 'unavailable'}; {'negative GEX may amplify price moves' if negative_gex else 'current GEX does not show a clear negative-gamma amplifier'}. Risk can rise if price loses {put_wall or ma20 or 'a key technical level'}.",
        "key_opportunity": f"Opportunity improves if price reclaims key averages, news sentiment improves, and profitability remains durable. A move through {call_wall or analyst_target or 'upper resistance'} with confirmation would make the setup clearer.",
        "suggested_action": "This is not direct financial advice. Wait for confirmation from price action, options walls, and fundamental data; leveraged investors should predefine invalidation levels and position sensitivity.",
        "technical_analysis": f"Current price is {price_text}, daily change is {change_text}, RSI is {rsi or 'unavailable'}, MA5 is {ma5 or 'unavailable'}, and MA20 is {ma20 or 'unavailable'}. {ma5_relation or 'Price versus MA5 is unavailable'}; {ma20_relation or 'price versus MA20 is unavailable'}. Momentum is {localized_trend}; RSI extremes can increase reversal risk. Key support/resistance includes MA20, call wall {call_wall or 'unavailable'}, put wall {put_wall or 'unavailable'}, and max pain {max_pain or 'unavailable'}.",
        "options_analysis": f"Nearest expiry is {expiry}, Put/Call OI ratio is {pc_ratio or 'unavailable'}, call OI is {call_oi or 'unavailable'}, and put OI is {put_oi or 'unavailable'}. Net GEX is {net_gex or 'unavailable'}, max pain is {max_pain or 'unavailable'}, call wall is {call_wall or 'unavailable'}, and put wall is {put_wall or 'unavailable'}. {'Negative GEX may cause hedging flows to amplify volatility. ' if negative_gex else 'Net GEX does not show a clear negative-gamma volatility amplifier. '}The call wall may act as resistance; the put wall may act as support or a downside magnet if price approaches it. {max_pain_relation or 'Distance from max pain cannot be reliably calculated'}.",
        "sentiment_analysis": f"Latest sentiment is {sentiment_label}. {' '.join(headline_notes)} Sentiment matters because news can change expectations for growth, margins, regulation, or sector demand, and can interact with crowded options positioning.",
        "fundamental_analysis": f"Fundamental data includes revenue {revenue or 'unavailable'}, market cap {market_cap or 'unavailable'}, and net margin {net_margin or 'unavailable'}. Valuation markers are P/E {trailing_pe or 'unavailable'}, Forward P/E {forward_pe or 'unavailable'}, P/B {price_to_book or 'unavailable'}, and analyst target {analyst_target or 'unavailable'}. Profitability quality depends on whether margin and growth hold; revenue growth is {revenue_growth or 'unavailable'}, so the company profile should be viewed through high-growth, cyclical, margin-risk, or quality-compounder lenses based on the available fields.",
        "risk_management": f"Risk management: {'the daily move suggests elevated short-term volatility; ' if high_daily_move else 'the daily move alone does not show extreme volatility; '}{'RSI is in an extreme zone, increasing reversal risk; ' if rsi_extreme else 'RSI is not in an obvious extreme zone; '}{'negative GEX can increase volatility risk.' if negative_gex else 'options structure does not show a clear negative-GEX amplifier.'} Leveraged investors should watch {', '.join(key_levels[:3]) if key_levels else 'MA20, options walls, and max pain'}, where risk may increase.",
        "key_levels": key_levels, "missing_data": missing,
    }

def run_multi_agent_analysis(ticker, language):
    ticker = normalize_ticker(ticker)
    inputs = collect_multi_agent_inputs(ticker)
    debug = {
        "selected_ticker": ticker,
        **inputs.get("loaded_flags", _multi_agent_loaded_flags(inputs)),
        "openai_called": False,
        "openai_error": None,
        "openai_json_received": False,
        "openai_validation_passed": False,
        "fallback_used": False,
        "fallback_reason": None,
        "raw_openai_json": None,
    }
    if inputs.get("no_data"):
        debug["fallback_used"] = True
        debug["fallback_reason"] = "No input data available for multi-agent analysis."
        result = _localized_multi_agent_fallback(ticker, inputs, language)
        result.update({"inputs": inputs, "debug": debug})
        return result
    try:
        client = get_openai_client()
        if not client:
            raise RuntimeError("OpenAI client unavailable.")
        debug["openai_called"] = True
        prompt = build_multi_agent_prompt(ticker, inputs, language)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw_openai_json = response.choices[0].message.content
        debug["raw_openai_json"] = raw_openai_json
        debug["openai_json_received"] = bool(raw_openai_json)
        result = json.loads(raw_openai_json)
        fallback = _localized_multi_agent_fallback(ticker, inputs, language)
        if "final_summary" not in result and "final_conclusion" in result:
            result["final_summary"] = result.get("final_conclusion")
        for key in (
            "final_summary", "overall_rating", "key_risk", "key_opportunity", "suggested_action",
            "technical_analysis", "options_analysis", "sentiment_analysis", "fundamental_analysis",
            "risk_management",
        ):
            if _multi_agent_is_unavailable(result.get(key)):
                result[key] = fallback.get(key)
        if not isinstance(result.get("key_levels"), list) or not result.get("key_levels"):
            result["key_levels"] = fallback.get("key_levels", [])
        if not isinstance(result.get("missing_data"), list):
            result["missing_data"] = fallback.get("missing_data", [])
        source = "openai"
        validation_failure = _multi_agent_report_validation_failure(result, inputs, language)
        debug["openai_validation_passed"] = validation_failure is None
        if validation_failure:
            result = fallback
            source = "fallback"
            result["openai_incomplete"] = True
            debug["fallback_used"] = True
            debug["fallback_reason"] = validation_failure
        result.update({"ticker": ticker, "source": source, "no_data": False})
        result.update({"inputs": inputs, "debug": debug})
        return result
    except Exception as exc:
        debug["openai_error"] = str(exc)
        debug["fallback_used"] = True
        debug["fallback_reason"] = str(exc)
        result = _localized_multi_agent_fallback(ticker, inputs, language, str(exc))
        result.update({"inputs": inputs, "debug": debug})
        return result


def _multi_agent_result_state_key(ticker, language):
    return f"multi_agent_result_{normalize_ticker(ticker)}_{_multi_agent_language(language)}"


def render_multi_agent_debug(selected_ticker, analysis=None):
    debug = (analysis or {}).get("debug") or {
        "selected_ticker": normalize_ticker(selected_ticker),
        "technical_data_loaded": False,
        "options_data_loaded": False,
        "news_data_loaded": False,
        "financial_data_loaded": False,
        "openai_called": False,
        "openai_error": None,
        "openai_json_received": False,
        "openai_validation_passed": False,
        "fallback_used": False,
        "fallback_reason": None,
    }
    with st.expander("Multi-Agent Debug", expanded=False):
        st.write(f"selected ticker: {debug.get('selected_ticker') or normalize_ticker(selected_ticker)}")
        st.write(f"technical data loaded: {bool(debug.get('technical_data_loaded'))}")
        st.write(f"options data loaded: {bool(debug.get('options_data_loaded'))}")
        st.write(f"news data loaded: {bool(debug.get('news_data_loaded'))}")
        st.write(f"financial data loaded: {bool(debug.get('financial_data_loaded'))}")
        st.write(f"OpenAI called: {bool(debug.get('openai_called'))}")
        st.write(f"OpenAI error: {debug.get('openai_error') or 'None'}")
        st.write(f"OpenAI JSON received: {bool(debug.get('openai_json_received'))}")
        st.write(f"OpenAI validation passed: {bool(debug.get('openai_validation_passed'))}")
        st.write(f"Fallback used: {bool(debug.get('fallback_used'))}")
        st.write(f"Fallback reason: {debug.get('fallback_reason') or 'None'}")
        if analysis:
            st.markdown("**Raw collected input data**")
            st.json(analysis.get("inputs") or {})
            raw_openai_json = debug.get("raw_openai_json")
            if raw_openai_json:
                st.markdown("**Raw OpenAI JSON**")
                try:
                    st.json(json.loads(raw_openai_json))
                except Exception:
                    st.code(raw_openai_json, language="json")


def render_multi_agent_result(analysis, language):
    if not analysis:
        return
    if analysis.get("no_data"):
        st.warning(multi_agent_text("no_analysis", language))
    if analysis.get("source") == "fallback" and not analysis.get("no_data"):
        debug = analysis.get("debug") or {}
        note_key = "fallback_validation_note" if debug.get("openai_json_received") and not debug.get("openai_validation_passed") else "fallback_error_note"
        st.caption(multi_agent_text(note_key, language))

    final_summary = analysis.get("final_summary") or analysis.get("final_conclusion") or multi_agent_text("no_analysis", language)
    st.markdown(f"##### {multi_agent_text('final_summary', language)}")
    st.info(final_summary)
    st.markdown(f"**{multi_agent_text('overall_rating', language)}:** {analysis.get('overall_rating') or multi_agent_text('unavailable', language)}")
    st.markdown(f"**{multi_agent_text('key_risk', language)}:** {analysis.get('key_risk') or multi_agent_text('unavailable', language)}")
    st.markdown(f"**{multi_agent_text('key_opportunity', language)}:** {analysis.get('key_opportunity') or multi_agent_text('unavailable', language)}")
    st.markdown(f"**{multi_agent_text('suggested_action', language)}:** {analysis.get('suggested_action') or multi_agent_text('unavailable', language)}")
    key_levels = analysis.get("key_levels") if isinstance(analysis.get("key_levels"), list) else []
    if key_levels:
        st.markdown(f"**{multi_agent_text('key_levels', language)}:**")
        for level in key_levels:
            st.markdown(f"- {level}")
    st.markdown(f"**{multi_agent_text('risk_management', language)}:**")
    st.write(analysis.get("risk_management") or multi_agent_text("unavailable", language))

    with st.expander(multi_agent_text("agent_details", language), expanded=True):
        st.markdown(f"**{multi_agent_text('technical_analysis', language)}**")
        st.write(analysis.get("technical_analysis") or multi_agent_text("no_analysis", language))
        st.markdown(f"**{multi_agent_text('options_analysis', language)}**")
        st.write(analysis.get("options_analysis") or multi_agent_text("no_analysis", language))
        st.markdown(f"**{multi_agent_text('sentiment_analysis', language)}**")
        st.write(analysis.get("sentiment_analysis") or multi_agent_text("no_analysis", language))
        st.markdown(f"**{multi_agent_text('fundamental_analysis', language)}**")
        st.write(analysis.get("fundamental_analysis") or multi_agent_text("no_analysis", language))
    missing_data = analysis.get("missing_data") if isinstance(analysis.get("missing_data"), list) else []
    if missing_data:
        st.markdown(f"**{multi_agent_text('missing_data', language)}:**")
        for item in missing_data:
            st.markdown(f"- {_multi_agent_localized_missing_item(item, language)}")


def render_multi_agent_section(language=None, watchlist=None):
    language = _multi_agent_language(language or st.session_state.get("language", "English"))
    watchlist = load_watchlist() if watchlist is None else list(watchlist)
    st.caption(multi_agent_text("caption", language))
    if not watchlist:
        st.warning(multi_agent_text("no_analysis", language))
        return

    selected_ticker = st.selectbox(
        multi_agent_text("select_ticker", language),
        watchlist,
        key="multi_agent_selected_ticker",
    )
    result_key = _multi_agent_result_state_key(selected_ticker, language)
    if st.button(multi_agent_text("run_button", language), key="multi_agent"):
        with st.spinner(f"{multi_agent_text('running', language)} {selected_ticker}..."):
            st.session_state[result_key] = run_multi_agent_analysis(selected_ticker, language)
    analysis = st.session_state.get(result_key)
    render_multi_agent_debug(selected_ticker, analysis)
    render_multi_agent_result(analysis, language)


def render_overview_cards(snapshots):
    watchlist = load_watchlist()
    columns = st.columns(max(len(watchlist), 1))
    for column, ticker in zip(columns, watchlist):
        snapshot = snapshots.get(ticker)
        if snapshot:
            render_snapshot_card(column, snapshot)
        else:
            column.warning(f"{ticker} {t('data_unavailable')}")


def get_macro_trend(history):
    if history is None or history.empty or len(history) < 2:
        return "N/A"
    first = float(history["value"].iloc[0])
    last = float(history["value"].iloc[-1])
    if not first:
        return "N/A"
    change = (last - first) / abs(first)
    return "rising" if change > 0.01 else "falling" if change < -0.01 else "stable"


def summarize_macro_snapshot(macro):
    rates = macro["rates"]
    markets = macro["markets"]
    calendar = macro["calendar"]
    important_events = [item for item in calendar["events"] if item["Important"]][:20]
    return {
        "last_updated": macro["last_updated"],
        "macro_risk_score_0_to_10": macro["macro_risk_score"],
        "us_10y_yield": rates["year10"],
        "us_10y_trend": get_macro_trend(rates["history"].rename(columns={"year10": "value"})[["date", "value"]].dropna()) if "year10" in rates["history"] else "N/A",
        "us_10y_minus_2y_spread": rates["spread_10y_2y"],
        "yield_curve": "inverted" if rates["spread_10y_2y"] is not None and rates["spread_10y_2y"] < 0 else "normal" if rates["spread_10y_2y"] is not None else "N/A",
        "eur_usd": markets["EUR/USD"]["value"],
        "usd_cny": markets["USD/CNY"]["value"],
        "usd_jpy": markets["USD/JPY"]["value"],
        "dxy": markets["DXY"]["value"],
        "cpi_yoy_pct": macro["cpi_yoy"],
        "unemployment_rate_pct": macro["indicators"]["unemploymentRate"]["value"],
        "gdp_growth_yoy_pct": macro["gdp_growth_yoy"],
        "brent_crude": markets["Brent crude oil"]["value"],
        "wti_crude": markets["WTI crude oil"]["value"],
        "important_events_next_30_days": important_events,
    }


@st.cache_data(ttl=3600)
def get_cached_macro_snapshot():
    track_cacheable_call()
    track_api_call("macro_snapshot")
    return build_macro_snapshot()


FRED_SERIES_CODES = {
    "cpi_yoy": "CPIAUCSL",
    "core_cpi_yoy": "CPILFESL",
    "pce_yoy": "PCEPI",
    "core_pce_yoy": "PCEPILFE",
    "unemployment_rate": "UNRATE",
    "nonfarm_payrolls": "PAYEMS",
    "wage_growth": "CES0500000003",
    "job_openings": "JTSJOL",
    "gdp": "GDPC1",
}


def _fred_api_key():
    try:
        secret_value = st.secrets.get("FRED_API_KEY")
        if secret_value:
            return str(secret_value)
    except Exception:
        pass
    env_value = os.environ.get("FRED_API_KEY")
    if env_value:
        return env_value
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() == "FRED_API_KEY":
                        return value.strip().strip('"').strip("'")
        except Exception:
            return None
    return None


@st.cache_data(ttl=3600)
def fetch_fred_series_history(series_id, observation_start="1990-01-01"):
    track_cacheable_call()
    track_api_call("fred_series")
    api_key = _fred_api_key()
    try:
        if api_key:
            response = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "observation_start": observation_start,
                },
                timeout=15,
            )
            response.raise_for_status()
            observations = response.json().get("observations", [])
            frame = pd.DataFrame(observations)
            source = "FRED API"
        else:
            response = requests.get(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
                timeout=15,
            )
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
            source = "FRED CSV"
    except Exception:
        return {"name": series_id, "value": None, "source": "FRED unavailable", "history": pd.DataFrame()}

    if frame.empty:
        return {"name": series_id, "value": None, "source": source, "history": pd.DataFrame()}
    date_column = "date" if "date" in frame.columns else "observation_date" if "observation_date" in frame.columns else None
    value_column = "value" if "value" in frame.columns else series_id if series_id in frame.columns else None
    if not date_column or not value_column:
        return {"name": series_id, "value": None, "source": source, "history": pd.DataFrame()}
    history = frame[[date_column, value_column]].rename(columns={date_column: "date", value_column: "value"}).copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history["value"] = pd.to_numeric(history["value"].replace(".", np.nan), errors="coerce")
    history = history.dropna().sort_values("date")
    latest = None if history.empty else float(history["value"].iloc[-1])
    return {"name": series_id, "value": latest, "source": source, "history": history}


def _fred_indicator(key):
    series_id = FRED_SERIES_CODES[key]
    indicator = fetch_fred_series_history(series_id)
    return {
        "name": series_id,
        "value": indicator.get("value"),
        "source": indicator.get("source", "FRED"),
        "history": indicator.get("history", pd.DataFrame()),
    }


def _macro_chart_key(title):
    return "macro_" + hashlib.md5(str(title).encode("utf-8")).hexdigest()[:12]


def _macro_history_frame(history, value_column="value", label=None):
    if history is None or history.empty or "date" not in history or value_column not in history:
        return pd.DataFrame()
    frame = history[["date", value_column]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame[value_column], errors="coerce")
    frame = frame[["date", "value"]].dropna().sort_values("date")
    if label:
        frame = frame.rename(columns={"value": label})
    return frame


def _macro_cutoff(frame, days):
    if frame.empty:
        return frame
    cutoff = frame["date"].max() - pd.Timedelta(days=days)
    return frame[frame["date"] >= cutoff]


def _normalize_macro_frame(frame, columns):
    normalized = frame.copy()
    for column in columns:
        series = pd.to_numeric(normalized[column], errors="coerce").dropna()
        if series.empty or float(series.iloc[0]) == 0:
            normalized[column] = np.nan
            continue
        normalized[column] = normalized[column] / float(series.iloc[0]) - 1
    return normalized


def _render_macro_line_chart(title, frame, columns, normalize=False, y_tickformat=None, height=300):
    available = [column for column in columns if column in frame and pd.to_numeric(frame[column], errors="coerce").notna().any()]
    if frame.empty or not available:
        st.info(f"{title}: {t('historical_data_unavailable')}")
        return False
    chart = frame[["date", *available]].copy().sort_values("date")
    if normalize:
        chart = _normalize_macro_frame(chart, available)
        y_tickformat = y_tickformat or ".1%"
    figure = go.Figure()
    for column in available:
        series_frame = chart[["date", column]].copy()
        series_frame[column] = pd.to_numeric(series_frame[column], errors="coerce")
        series_frame = series_frame.dropna()
        figure.add_trace(go.Scatter(x=series_frame["date"], y=series_frame[column], mode="lines", name=column))
    figure.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        height=height,
        margin={"l": 8, "r": 8, "t": 48, "b": 8},
        template="plotly_dark",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    if y_tickformat:
        figure.update_yaxes(tickformat=y_tickformat)
    st.plotly_chart(figure, use_container_width=True, key=_macro_chart_key(title))
    return True


def _macro_indicator_label(key):
    labels = {
        "core_pce_yoy": t("core_pce_yoy"),
        "pce_yoy": t("pce_yoy"),
        "core_cpi_yoy": t("core_cpi_yoy"),
        "cpi_yoy": t("cpi_yoy"),
        "unemployment_rate": t("unemployment_rate"),
        "wage_growth": t("wage_growth"),
        "nonfarm_payrolls": t("nonfarm_payrolls"),
        "job_openings": t("job_openings"),
        "gdp_yoy_growth": t("gdp_yoy_growth"),
    }
    return labels.get(key, key)


def _empty_macro_indicator(name, source="unavailable"):
    return {"name": name, "value": None, "source": source, "history": pd.DataFrame()}


def _macro_snapshot_indicator(macro, names):
    normalized_names = {str(name).lower().replace(" ", "_") for name in names}
    indicators = macro.get("indicators", {}) if isinstance(macro, dict) else {}
    for key, indicator in indicators.items():
        key_norm = str(key).lower().replace(" ", "_")
        item_name = str((indicator or {}).get("name", "")).lower().replace(" ", "_") if isinstance(indicator, dict) else ""
        if key_norm in normalized_names or item_name in normalized_names:
            return indicator
    for name in names:
        for container in (macro, indicators):
            if isinstance(container, dict) and name in container:
                value = container[name]
                if isinstance(value, dict):
                    return value
                return {"name": name, "value": value, "source": "macro snapshot", "history": pd.DataFrame()}
    return None


def _first_available_indicator(macro, candidates):
    for names, fetch_name in candidates:
        snapshot_indicator = _macro_snapshot_indicator(macro, names)
        if isinstance(snapshot_indicator, dict):
            return snapshot_indicator, "macro snapshot"
        if fetch_name:
            indicator = fetch_indicator(fetch_name)
            history = indicator.get("history") if isinstance(indicator, dict) else pd.DataFrame()
            if isinstance(indicator, dict) and (indicator.get("value") is not None or (history is not None and not history.empty)):
                return indicator, "fetch_indicator"
    fetch_name = candidates[0][1] if candidates else "unknown"
    return _empty_macro_indicator(fetch_name), "unavailable"


def _indicator_history_yoy(indicator):
    frame = _macro_history_frame((indicator or {}).get("history"))
    if frame.empty:
        return pd.DataFrame()
    name = str((indicator or {}).get("name", "")).lower()
    if "yoy" in name or "rate" in name or "growth" in name:
        return frame
    if len(frame) < 13:
        return pd.DataFrame()
    frame["value"] = (frame["value"] / frame["value"].shift(12) - 1) * 100
    return frame.dropna()


def _macro_indicator_latest(indicator, history=None):
    if history is not None and not history.empty and "value" in history:
        series = pd.to_numeric(history["value"], errors="coerce").dropna()
        if not series.empty:
            return float(series.iloc[-1])
    value = (indicator or {}).get("value")
    return None if value is None or pd.isna(value) else float(value)


def _add_macro_row(rows, key, indicator, latest=None, history=None, percent=False):
    latest_value = _macro_indicator_latest(indicator, history) if latest is None else latest
    rows.append({
        "Indicator": _macro_indicator_label(key),
        "Latest": "N/A" if latest_value is None else f"{latest_value:.2f}%" if percent else f"{latest_value:,.2f}",
        "Source": (indicator or {}).get("source", "unavailable"),
        "Last updated": _latest_history_date(history if history is not None else (indicator or {}).get("history")),
    })


def _resolve_fed_macro_indicators(macro):
    resolved = {}
    for key in FRED_SERIES_CODES:
        indicator = _fred_indicator(key)
        history = indicator.get("history")
        if history is not None and not history.empty:
            resolved[key] = indicator
        else:
            resolved[key] = _empty_macro_indicator(FRED_SERIES_CODES[key], "FRED unavailable")
    return resolved


def _fed_indicator_ranking_rows():
    return [
        {"Rank": 1, "Indicator": "Core PCE", t("indicator"): t("core_pce_yoy"), t("why_it_matters"): t("fed_rank_core_pce")},
        {"Rank": 2, "Indicator": "PCE", t("indicator"): t("pce_yoy"), t("why_it_matters"): t("fed_rank_pce")},
        {"Rank": 3, "Indicator": "Labor market data", t("indicator"): f"{t('unemployment_rate')} / {t('wage_growth')} / {t('nonfarm_payrolls')} / {t('job_openings')}", t("why_it_matters"): t("fed_rank_labor")},
        {"Rank": 4, "Indicator": "Core CPI", t("indicator"): t("core_cpi_yoy"), t("why_it_matters"): t("fed_rank_core_cpi")},
        {"Rank": 5, "Indicator": "CPI", t("indicator"): t("cpi_yoy"), t("why_it_matters"): t("fed_rank_cpi")},
    ]


def _latest_history_date(history):
    if history is None or history.empty or "date" not in history:
        return ""
    dates = pd.to_datetime(history["date"], errors="coerce").dropna()
    return "" if dates.empty else dates.max().strftime("%Y-%m-%d")


def _macro_latest_rows(macro, fed_indicators=None):
    rates = macro["rates"]
    markets = macro["markets"]
    indicators = macro["indicators"]
    last_updated = macro["last_updated"]
    fed_indicators = fed_indicators or _resolve_fed_macro_indicators(macro)
    core_pce_history = _indicator_history_yoy(fed_indicators["core_pce_yoy"])
    pce_history = _indicator_history_yoy(fed_indicators["pce_yoy"])
    core_cpi_history = _indicator_history_yoy(fed_indicators["core_cpi_yoy"])
    wage_history = _indicator_history_yoy(fed_indicators["wage_growth"])
    gdp_yoy_history = _gdp_yoy_history(fed_indicators["gdp"]["history"])
    rows = [
        {"Indicator": "US 10Y", "Latest": "N/A" if rates["year10"] is None else f"{rates['year10']:.2f}%", "Source": rates["source"], "Last updated": _latest_history_date(rates["history"]) or last_updated},
        {"Indicator": "US 30Y", "Latest": "N/A" if rates["year30"] is None else f"{rates['year30']:.2f}%", "Source": rates["source"], "Last updated": _latest_history_date(rates["history"]) or last_updated},
    ]
    for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY"):
        rows.append({"Indicator": label, "Latest": format_ratio(markets[label]["value"]), "Source": markets[label]["source"], "Last updated": _latest_history_date(markets[label]["history"]) or last_updated})
    _add_macro_row(rows, "core_pce_yoy", fed_indicators["core_pce_yoy"], history=core_pce_history, percent=True)
    _add_macro_row(rows, "pce_yoy", fed_indicators["pce_yoy"], history=pce_history, percent=True)
    _add_macro_row(rows, "core_cpi_yoy", fed_indicators["core_cpi_yoy"], history=core_cpi_history, percent=True)
    _add_macro_row(rows, "cpi_yoy", fed_indicators["cpi_yoy"], history=_indicator_history_yoy(fed_indicators["cpi_yoy"]), percent=True)
    _add_macro_row(rows, "unemployment_rate", fed_indicators["unemployment_rate"], percent=True)
    _add_macro_row(rows, "wage_growth", fed_indicators["wage_growth"], history=wage_history, percent=True)
    _add_macro_row(rows, "nonfarm_payrolls", fed_indicators["nonfarm_payrolls"], percent=False)
    _add_macro_row(rows, "job_openings", fed_indicators["job_openings"], percent=False)
    _add_macro_row(rows, "gdp_yoy_growth", fed_indicators["gdp"], history=gdp_yoy_history, percent=True)
    for label in ("Brent crude oil", "WTI crude oil", "Gold", "Copper"):
        rows.append({"Indicator": label, "Latest": format_money(markets[label]["value"], 2), "Source": markets[label]["source"], "Last updated": _latest_history_date(markets[label]["history"]) or last_updated})
    return rows


def _render_macro_latest_table(rows):
    table = pd.DataFrame(rows)
    table = table.rename(columns={
        "Indicator": t("indicator"),
        "Latest": t("latest"),
        "Source": t("source"),
        "Last updated": t("last_updated"),
    })
    st.markdown(f"#### {t('latest_macro_data')}")
    st.dataframe(table.fillna("N/A"), use_container_width=True, hide_index=True)


def _combine_macro_histories(series_map):
    combined = None
    for label, history in series_map.items():
        frame = _macro_history_frame(history, label=label)
        if frame.empty:
            continue
        combined = frame if combined is None else combined.merge(frame, on="date", how="outer")
    return pd.DataFrame() if combined is None else combined.sort_values("date")


def _gdp_yoy_history(history):
    frame = _macro_history_frame(history)
    if len(frame) < 5:
        return pd.DataFrame()
    frame["GDP YoY Growth"] = (frame["value"] / frame["value"].shift(4) - 1) * 100
    return frame[["date", "GDP YoY Growth"]].dropna()


def render_macro_section():
    st.caption(t("macro_caption"))
    if st.button(t("refresh_macro"), key="refresh_macro"):
        fetch_treasury_rates.clear()
        fetch_market_series.clear()
        fetch_indicator.clear()
        fetch_macro_calendar.clear()
        get_cached_macro_snapshot.clear()
        fetch_fred_series_history.clear()
        st.rerun()
    with st.spinner("Using cached data when available..."):
        macro = get_cached_macro_snapshot()
    rates = macro["rates"]
    markets = macro["markets"]
    indicators = macro["indicators"]
    fed_indicators = _resolve_fed_macro_indicators(macro)
    st.caption(f"{t('last_updated')}: {macro['last_updated']} | {t('calendar_window')}: {macro['calendar']['start_date']} to {macro['calendar']['end_date']}")
    st.markdown(
        f"""
        <div style="display:inline-flex;align-items:baseline;gap:0.5rem;border:1px solid rgba(250,250,250,0.16);border-radius:8px;padding:0.45rem 0.7rem;margin:0.25rem 0 0.75rem 0;">
            <span style="font-size:0.86rem;color:rgba(250,250,250,0.72);">{html.escape(t("macro_risk_score"))}</span>
            <span style="font-size:1.18rem;font-weight:700;">{macro['macro_risk_score']}/10</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    period_options = {"30D": 30, "3M": 90, "6M": 180, "1Y": 365}
    selected_period = st.segmented_control(t("chart_period"), list(period_options), default="30D", key="macro_chart_period")
    chart_days = period_options.get(selected_period, 30)

    treasury_history = rates["history"]
    if treasury_history is not None and not treasury_history.empty:
        treasury_frame = treasury_history[["date"]].copy() if "date" in treasury_history else pd.DataFrame()
        if not treasury_frame.empty:
            treasury_frame["date"] = pd.to_datetime(treasury_frame["date"], errors="coerce")
            if "year10" in treasury_history:
                treasury_frame["US 10Y"] = pd.to_numeric(treasury_history["year10"], errors="coerce")
            elif "value" in treasury_history:
                treasury_frame["US 10Y"] = pd.to_numeric(treasury_history["value"], errors="coerce")
            if "year30" in treasury_history:
                treasury_frame["US 30Y"] = pd.to_numeric(treasury_history["year30"], errors="coerce")
            treasury_frame = _macro_cutoff(treasury_frame.dropna(subset=["date"]), chart_days)
    else:
        treasury_frame = pd.DataFrame()
    _render_macro_line_chart(t("us_treasury_yields"), treasury_frame, ["US 10Y", "US 30Y"], y_tickformat=".2f")
    st.caption(f"{t('treasury_source')}: {rates['source']}")

    fx_frame = _combine_macro_histories({label: markets[label]["history"] for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY")})
    fx_frame = _macro_cutoff(fx_frame, chart_days)
    _render_macro_line_chart(t("fx_relative_performance"), fx_frame, ["EUR/USD", "USD/CNY", "USD/JPY", "DXY"], normalize=True)

    st.info(t("fed_indicator_explanation"))
    st.markdown(f"#### {t('fed_ranking')}")
    st.dataframe(pd.DataFrame(_fed_indicator_ranking_rows()), use_container_width=True, hide_index=True)

    inflation_histories = {
        "core_pce_yoy": _indicator_history_yoy(fed_indicators["core_pce_yoy"]),
        "pce_yoy": _indicator_history_yoy(fed_indicators["pce_yoy"]),
        "core_cpi_yoy": _indicator_history_yoy(fed_indicators["core_cpi_yoy"]),
        "cpi_yoy": _indicator_history_yoy(fed_indicators["cpi_yoy"]),
    }
    labor_histories = {
        "unemployment_rate": _macro_history_frame(fed_indicators["unemployment_rate"]["history"]),
        "wage_growth": _indicator_history_yoy(fed_indicators["wage_growth"]),
        "nonfarm_payrolls": _macro_history_frame(fed_indicators["nonfarm_payrolls"]["history"]),
        "job_openings": _macro_history_frame(fed_indicators["job_openings"]["history"]),
    }
    gdp_yoy = _gdp_yoy_history(fed_indicators["gdp"]["history"]).rename(columns={"GDP YoY Growth": _macro_indicator_label("gdp_yoy_growth")})
    missing_series = [
        _macro_indicator_label(key)
        for key, history in {**inflation_histories, **labor_histories, "gdp_yoy_growth": gdp_yoy}.items()
        if history.empty
    ]
    if missing_series:
        st.warning(t("missing_macro_series").format(series=", ".join(missing_series)))

    inflation_frame = _combine_macro_histories({
        _macro_indicator_label("core_pce_yoy"): inflation_histories["core_pce_yoy"],
        _macro_indicator_label("pce_yoy"): inflation_histories["pce_yoy"],
        _macro_indicator_label("core_cpi_yoy"): inflation_histories["core_cpi_yoy"],
        _macro_indicator_label("cpi_yoy"): inflation_histories["cpi_yoy"],
    })
    official_monthly_days = max(chart_days, 365)
    official_quarterly_days = max(chart_days, 730)
    inflation_frame = _macro_cutoff(inflation_frame, official_monthly_days)
    _render_macro_line_chart(
        t("main_inflation_chart"),
        inflation_frame,
        [_macro_indicator_label("core_pce_yoy"), _macro_indicator_label("pce_yoy"), _macro_indicator_label("core_cpi_yoy"), _macro_indicator_label("cpi_yoy")],
        y_tickformat=".2f",
    )

    labor_frame = _combine_macro_histories({
        _macro_indicator_label("unemployment_rate"): labor_histories["unemployment_rate"],
        _macro_indicator_label("wage_growth"): labor_histories["wage_growth"],
        _macro_indicator_label("nonfarm_payrolls"): labor_histories["nonfarm_payrolls"],
        _macro_indicator_label("job_openings"): labor_histories["job_openings"],
    })
    labor_frame = _macro_cutoff(labor_frame, official_monthly_days)
    _render_macro_line_chart(
        t("labor_market_chart"),
        labor_frame,
        [_macro_indicator_label("unemployment_rate"), _macro_indicator_label("wage_growth"), _macro_indicator_label("nonfarm_payrolls"), _macro_indicator_label("job_openings")],
        normalize=True,
    )

    economy_frame = _macro_cutoff(gdp_yoy, official_quarterly_days)
    _render_macro_line_chart(t("economy_chart"), economy_frame, [_macro_indicator_label("gdp_yoy_growth")], y_tickformat=".2f")
    st.caption(t("economy_chart_explanation"))

    st.markdown(f"#### {t('dynamic_macro_calendar')}")
    events = macro["calendar"]["events"]
    if events:
        show_all_events = st.checkbox(t("show_all_macro_events"), value=False, key="show_all_macro_events")
        visible_events = events if show_all_events else [item for item in events if item["Important"]]
        if visible_events:
            table = pd.DataFrame(visible_events).drop(columns=["Important"])
            table = table.fillna("N/A")
            for column in ("Actual", "Estimate", "Previous"):
                table[column] = table[column].map(lambda value: "N/A" if value == "N/A" else str(value))
            st.dataframe(table, use_container_width=True, hide_index=True)
        else:
            st.info(t("no_highlighted_macro_events"))
    else:
        st.info(t("economic_calendar_unavailable"))
    _render_macro_latest_table(_macro_latest_rows(macro, fed_indicators))
    return macro


UBS_BASELINE = {
    "FQ3_2026": {"revenue_b": 36.026, "gross_margin": 0.831, "operating_margin": 0.792, "eps": 20.96, "fcf_b": 11.861},
    "FY2026": {"revenue_b": 116.596, "eps": 63.74, "fcf_b": 49.191},
    "FY2027": {"revenue_b": 230.707, "eps": 142.23, "fcf_b": 121.128},
    "FY2028": {"revenue_b": 274.110, "eps": 169.64, "fcf_b": 143.135},
    "C2029": {"eps": 117.48, "base_pe": 15.0, "coe": 0.12, "discount_years": 1.0},
}

MU_TEXT = {
    "English": {
        "tab": "MU Valuation Model", "title": "MU Memory Re-rating Valuation Model",
        "overview": "Model Overview", "intro": "This model compares Micron's latest reported earnings with UBS-style baseline forecasts, adjusts future EPS and FCF assumptions based on the surprise, applies a Nomura-style memory industry overlay, and calculates updated Bear/Base/Bull target prices.",
        "disclaimer": "This is a personal research model, not investment advice.",
        "baseline": "UBS Baseline Forecasts", "baseline_note": "Stored UBS-style assumptions are editable below. Enter updated assumptions manually after a forecast change.",
        "quarterly": "Quarterly UBS-style baseline: MU FQ3 2026", "annual": "Annual UBS-style baseline", "valuation": "C2029E valuation assumptions",
        "actual": "Actual Earnings Input", "actual_note": "Enter the latest MU results manually. Current price can use the dashboard quote when available.",
        "use_quote": "Use automatically fetched MU share price when available", "price_warning": "Current MU price could not be fetched. Enter a manual price.",
        "actual_revenue": "Actual Revenue, billion USD", "actual_gm": "Actual Gross Margin, %", "actual_om": "Actual Operating Margin, %",
        "actual_eps": "Actual EPS", "actual_fcf": "Actual Free Cash Flow, billion USD", "actual_capex": "Actual Capex, billion USD",
        "actual_cash": "Actual Cash, billion USD", "actual_debt": "Actual Debt, billion USD", "shares": "Actual Diluted Shares, billion", "share_price": "Current MU share price",
        "surprise": "Surprise Analysis", "weighted": "Weighted Surprise Score", "overall": "Overall result", "metric": "Metric",
        "forecast": "UBS Forecast", "actual_col": "Actual", "surprise_col": "Surprise", "interpretation": "Interpretation",
        "revenue_surprise": "Revenue Surprise", "eps_surprise": "EPS Surprise", "fcf_surprise": "FCF Surprise",
        "gm_surprise": "Gross Margin Surprise", "om_surprise": "Operating Margin Surprise",
        "revision": "Forecast Revision", "advanced": "Advanced settings", "pass_through": "Surprise pass-through assumptions",
        "forecast_item": "Forecast Item", "updated_estimate": "Updated Model Estimate", "change": "Change %",
        "next_q": "Next quarter", "industry": "Nomura Industry Overlay", "industry_note": "This editable scoring panel uses a Nomura-style memory-cycle framework. It does not display or retrieve proprietary report text.",
        "industry_score": "Industry Score", "target_pe": "Target P/E", "regime": "Industry regime", "score_help": "-2 = Very negative, -1 = Negative, 0 = Neutral, +1 = Positive, +2 = Very positive",
        "output": "Target Price Output", "bear": "Bear Target Price", "base": "Base Target Price", "bull": "Bull Target Price",
        "upside": "Upside / downside vs current price", "market_cap": "Implied market cap", "net_cash": "Net cash",
        "apply_net_cash": "Add net cash per share to P/E target prices", "explanation": "Target Price Change Explanation",
        "dcf": "DCF Cross-Check", "dcf_note": "DCF is highly sensitive to WACC and terminal growth.", "wacc": "WACC", "terminal_growth": "Terminal growth",
        "dcf_value": "DCF fair value per share", "dcf_diff": "Difference vs P/E base target", "sensitivity": "Sensitivity Analysis",
        "dcf_error": "WACC must be greater than terminal growth. DCF cannot be calculated.", "summary": "Assumption Summary",
        "method": "All calculations use editable stored assumptions and manually entered values. No proprietary research text is retrieved or displayed.",
        "increased": "Target price increased because actual results improved the UBS-style baseline comparison and the Nomura-style industry overlay is {regime}.",
        "decreased": "Target price decreased because actual results weakened the UBS-style baseline comparison or the Nomura-style industry overlay is {regime}.",
        "analyst_tracker": "Analyst Target Price Tracker", "analyst_tracker_note": "Enter analyst targets manually. This tracker does not scrape or retrieve analyst reports, including paywalled reports.",
        "institution": "Institution", "old_target": "Old Target", "new_target": "New Target", "rating": "Rating", "credibility_weight": "Credibility Weight", "date": "Date", "notes": "Notes",
        "analyst_no_targets": "Enter at least one positive analyst target price to calculate tracker outputs.", "analyst_weight_warning": "Credibility weights total {total:.1f}%. Calculations automatically normalize the entered weights to 100%.",
        "analyst_weight_error": "Enter at least one positive credibility weight to calculate the weighted target.", "simple_average_target": "Simple Average Target", "weighted_target": "Weighted Target", "conservative_target": "Conservative Target",
        "median_target": "Median Target", "highest_target": "Highest Target", "lowest_target": "Lowest Target", "bullish_target": "Bullish Average", "target_range": "Target Price Range",
        "analyst_upside": "Upside/Downside vs Current Price", "target_comparison": "Target Price Comparison", "model_base_target": "Model-implied Base Target Price", "analyst_weighted_target": "Analyst Weighted Target Price",
        "analyst_conservative_target": "Analyst Conservative Target Price", "blended_target": "Final Blended Target", "blend_weights": "Editable blended-target weights",
        "model_weight": "MU Model Base Target Weight", "analyst_weighted_weight": "Analyst Weighted Target Weight", "analyst_conservative_weight": "Analyst Conservative Target Weight",
        "blend_weight_warning": "Blended-target weights total {total:.1f}%. Calculations automatically normalize the entered weights to 100%.",
        "blend_weight_error": "Enter at least one positive blended-target weight to calculate the final blended target.",
        "model_more_bullish": "The internal model is more bullish than analyst consensus.", "model_more_conservative": "The internal model is more conservative than analyst consensus.", "model_aligned": "The internal model is broadly aligned with analyst consensus.",
    },
    "\u4e2d\u6587": {
        "tab": "\u7f8e\u5149\u4f30\u503c\u6a21\u578b", "title": "MU Memory Re-rating Valuation Model", "overview": "\u6a21\u578b\u6982\u89c8",
        "intro": "\u8be5\u6a21\u578b\u5c06\u7f8e\u5149\u6700\u65b0\u8d22\u62a5\u5b9e\u9645\u6570\u636e\u4e0e UBS \u98ce\u683c\u57fa\u51c6\u9884\u6d4b\u8fdb\u884c\u5bf9\u6bd4\uff0c\u6839\u636e\u8d85\u9884\u671f\u6216\u4f4e\u4e8e\u9884\u671f\u7684\u7a0b\u5ea6\u4fee\u6b63\u672a\u6765 EPS \u548c FCF\uff0c\u5e76\u7ed3\u5408\u91ce\u6751\u98ce\u683c\u7684\u5185\u5b58\u884c\u4e1a\u666f\u6c14\u5ea6 overlay\uff0c\u81ea\u52a8\u8ba1\u7b97 Bear/Base/Bull \u4e09\u79cd\u76ee\u6807\u4ef7\u3002",
        "disclaimer": "\u8fd9\u662f\u4e2a\u4eba\u7814\u7a76\u6a21\u578b\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002", "baseline": "UBS \u57fa\u51c6\u9884\u6d4b", "baseline_note": "\u4ee5\u4e0b UBS \u98ce\u683c\u5047\u8bbe\u53ef\u7f16\u8f91\u3002\u9884\u6d4b\u53d8\u5316\u540e\u8bf7\u624b\u52a8\u66f4\u65b0\u3002",
        "quarterly": "\u5b63\u5ea6 UBS \u98ce\u683c\u57fa\u51c6\uff1aMU FQ3 2026", "annual": "\u5e74\u5ea6 UBS \u98ce\u683c\u57fa\u51c6", "valuation": "C2029E \u4f30\u503c\u5047\u8bbe",
        "actual": "\u5b9e\u9645\u8d22\u62a5\u8f93\u5165", "actual_note": "\u624b\u52a8\u8f93\u5165 MU \u6700\u65b0\u4e1a\u7ee9\u3002\u5982\u679c\u53ef\u7528\uff0c\u5f53\u524d\u4ef7\u683c\u53ef\u4f7f\u7528\u4eea\u8868\u677f\u62a5\u4ef7\u3002",
        "use_quote": "\u5982\u679c\u53ef\u7528\uff0c\u4f7f\u7528\u81ea\u52a8\u83b7\u53d6\u7684 MU \u80a1\u4ef7", "price_warning": "\u65e0\u6cd5\u83b7\u53d6\u5f53\u524d MU \u80a1\u4ef7\u3002\u8bf7\u624b\u52a8\u8f93\u5165\u3002",
        "actual_revenue": "\u5b9e\u9645\u6536\u5165\uff0c\u5341\u4ebf\u7f8e\u5143", "actual_gm": "\u5b9e\u9645\u6bdb\u5229\u7387\uff0c%", "actual_om": "\u5b9e\u9645\u8425\u4e1a\u5229\u6da6\u7387\uff0c%", "actual_eps": "\u5b9e\u9645 EPS", "actual_fcf": "\u5b9e\u9645\u81ea\u7531\u73b0\u91d1\u6d41\uff0c\u5341\u4ebf\u7f8e\u5143", "actual_capex": "\u5b9e\u9645\u8d44\u672c\u5f00\u652f\uff0c\u5341\u4ebf\u7f8e\u5143", "actual_cash": "\u5b9e\u9645\u73b0\u91d1\uff0c\u5341\u4ebf\u7f8e\u5143", "actual_debt": "\u5b9e\u9645\u503a\u52a1\uff0c\u5341\u4ebf\u7f8e\u5143", "shares": "\u5b9e\u9645\u7a00\u91ca\u80a1\u6570\uff0c\u5341\u4ebf", "share_price": "\u5f53\u524d MU \u80a1\u4ef7",
        "surprise": "\u8d85\u9884\u671f\u5206\u6790", "weighted": "\u52a0\u6743\u8d85\u9884\u671f\u5206\u6570", "overall": "\u6574\u4f53\u7ed3\u679c", "metric": "\u6307\u6807", "forecast": "UBS \u9884\u6d4b", "actual_col": "\u5b9e\u9645", "surprise_col": "\u5dee\u8ddd", "interpretation": "\u89e3\u8bfb", "revenue_surprise": "\u6536\u5165\u5dee\u8ddd", "eps_surprise": "EPS \u5dee\u8ddd", "fcf_surprise": "\u81ea\u7531\u73b0\u91d1\u6d41\u5dee\u8ddd", "gm_surprise": "\u6bdb\u5229\u7387\u5dee\u8ddd", "om_surprise": "\u8425\u4e1a\u5229\u6da6\u7387\u5dee\u8ddd",
        "revision": "\u9884\u6d4b\u4fee\u6b63", "advanced": "\u9ad8\u7ea7\u8bbe\u7f6e", "pass_through": "\u8d85\u9884\u671f\u4f20\u5bfc\u5047\u8bbe", "forecast_item": "\u9884\u6d4b\u9879\u76ee", "updated_estimate": "\u66f4\u65b0\u540e\u6a21\u578b\u4f30\u7b97", "change": "\u53d8\u5316 %", "next_q": "\u4e0b\u4e00\u5b63\u5ea6",
        "industry": "\u91ce\u6751\u884c\u4e1a\u666f\u6c14\u5ea6 Overlay", "industry_note": "\u8be5\u53ef\u7f16\u8f91\u8bc4\u5206\u9762\u677f\u4f7f\u7528\u91ce\u6751\u98ce\u683c\u7684\u5185\u5b58\u5468\u671f\u6846\u67b6\uff0c\u4e0d\u663e\u793a\u6216\u83b7\u53d6\u4efb\u4f55\u4e13\u6709\u62a5\u544a\u6587\u672c\u3002", "industry_score": "\u884c\u4e1a\u5206\u6570", "target_pe": "\u76ee\u6807\u5e02\u76c8\u7387", "regime": "\u884c\u4e1a\u72b6\u6001", "score_help": "-2 = \u975e\u5e38\u8d1f\u9762\uff0c-1 = \u8d1f\u9762\uff0c0 = \u4e2d\u6027\uff0c+1 = \u6b63\u9762\uff0c+2 = \u975e\u5e38\u6b63\u9762",
        "output": "\u76ee\u6807\u4ef7\u8f93\u51fa", "bear": "\u60b2\u89c2\u76ee\u6807\u4ef7", "base": "\u57fa\u51c6\u76ee\u6807\u4ef7", "bull": "\u4e50\u89c2\u76ee\u6807\u4ef7", "upside": "\u76f8\u5bf9\u5f53\u524d\u4ef7\u683c\u7684\u4e0a\u6da8 / \u4e0b\u8dcc\u7a7a\u95f4", "market_cap": "\u9690\u542b\u5e02\u503c", "net_cash": "\u51c0\u73b0\u91d1", "apply_net_cash": "\u5c06\u6bcf\u80a1\u51c0\u73b0\u91d1\u52a0\u5165 P/E \u76ee\u6807\u4ef7", "explanation": "\u76ee\u6807\u4ef7\u53d8\u5316\u8bf4\u660e",
        "dcf": "DCF \u4ea4\u53c9\u9a8c\u8bc1", "dcf_note": "DCF \u5bf9 WACC \u548c\u7ec8\u503c\u589e\u957f\u7387\u9ad8\u5ea6\u654f\u611f\u3002", "wacc": "WACC", "terminal_growth": "\u7ec8\u503c\u589e\u957f\u7387", "dcf_value": "DCF \u6bcf\u80a1\u516c\u5141\u4ef7\u503c", "dcf_diff": "\u4e0e P/E \u57fa\u51c6\u76ee\u6807\u4ef7\u7684\u5dee\u5f02", "sensitivity": "\u654f\u611f\u6027\u5206\u6790", "dcf_error": "WACC \u5fc5\u987b\u9ad8\u4e8e\u7ec8\u503c\u589e\u957f\u7387\u3002\u65e0\u6cd5\u8ba1\u7b97 DCF\u3002", "summary": "\u5047\u8bbe\u6c47\u603b", "method": "\u6240\u6709\u8ba1\u7b97\u4ec5\u4f7f\u7528\u53ef\u7f16\u8f91\u7684\u5df2\u5b58\u5047\u8bbe\u548c\u624b\u52a8\u8f93\u5165\u503c\u3002\u4e0d\u83b7\u53d6\u6216\u663e\u793a\u4e13\u6709\u7814\u7a76\u6587\u672c\u3002",
        "increased": "\u76ee\u6807\u4ef7\u4e0a\u5347\uff0c\u56e0\u4e3a\u5b9e\u9645\u7ed3\u679c\u6539\u5584\u4e86 UBS \u98ce\u683c\u57fa\u51c6\u5bf9\u6bd4\uff0c\u4e14\u91ce\u6751\u98ce\u683c\u884c\u4e1a overlay \u5904\u4e8e {regime} \u72b6\u6001\u3002", "decreased": "\u76ee\u6807\u4ef7\u4e0b\u964d\uff0c\u56e0\u4e3a\u5b9e\u9645\u7ed3\u679c\u524a\u5f31\u4e86 UBS \u98ce\u683c\u57fa\u51c6\u5bf9\u6bd4\uff0c\u6216\u91ce\u6751\u98ce\u683c\u884c\u4e1a overlay \u5904\u4e8e {regime} \u72b6\u6001\u3002",
        "analyst_tracker": "\u673a\u6784\u76ee\u6807\u4ef7\u8ffd\u8e2a", "analyst_tracker_note": "\u8bf7\u624b\u52a8\u8f93\u5165\u673a\u6784\u76ee\u6807\u4ef7\u3002\u672c\u8ffd\u8e2a\u5668\u4e0d\u6293\u53d6\u6216\u83b7\u53d6\u4efb\u4f55\u5206\u6790\u5e08\u62a5\u544a\uff0c\u5305\u62ec\u4ed8\u8d39\u62a5\u544a\u3002",
        "institution": "\u673a\u6784", "old_target": "\u65e7\u76ee\u6807\u4ef7", "new_target": "\u65b0\u76ee\u6807\u4ef7", "rating": "\u8bc4\u7ea7", "credibility_weight": "\u53ef\u4fe1\u5ea6\u6743\u91cd", "date": "\u65e5\u671f", "notes": "\u5907\u6ce8",
        "analyst_no_targets": "\u8bf7\u81f3\u5c11\u8f93\u5165\u4e00\u4e2a\u6b63\u6570\u673a\u6784\u76ee\u6807\u4ef7\u4ee5\u8ba1\u7b97\u8ffd\u8e2a\u7ed3\u679c\u3002", "analyst_weight_warning": "\u53ef\u4fe1\u5ea6\u6743\u91cd\u5408\u8ba1\u4e3a {total:.1f}%\u3002\u8ba1\u7b97\u65f6\u5df2\u81ea\u52a8\u5f52\u4e00\u5316\u4e3a 100%\u3002",
        "analyst_weight_error": "\u8bf7\u81f3\u5c11\u8f93\u5165\u4e00\u4e2a\u6b63\u6570\u53ef\u4fe1\u5ea6\u6743\u91cd\u4ee5\u8ba1\u7b97\u52a0\u6743\u76ee\u6807\u4ef7\u3002", "simple_average_target": "\u7b80\u5355\u5e73\u5747\u76ee\u6807\u4ef7", "weighted_target": "\u52a0\u6743\u76ee\u6807\u4ef7", "conservative_target": "\u4fdd\u5b88\u76ee\u6807\u4ef7",
        "median_target": "\u4e2d\u4f4d\u6570\u76ee\u6807\u4ef7", "highest_target": "\u6700\u9ad8\u76ee\u6807\u4ef7", "lowest_target": "\u6700\u4f4e\u76ee\u6807\u4ef7", "bullish_target": "\u4e50\u89c2\u5e73\u5747\u76ee\u6807\u4ef7", "target_range": "\u76ee\u6807\u4ef7\u533a\u95f4",
        "analyst_upside": "\u76f8\u5bf9\u5f53\u524d\u4ef7\u683c\u7684\u4e0a\u6da8/\u4e0b\u8dcc\u7a7a\u95f4", "target_comparison": "\u76ee\u6807\u4ef7\u5bf9\u6bd4", "model_base_target": "\u6a21\u578b\u9690\u542b\u57fa\u51c6\u76ee\u6807\u4ef7", "analyst_weighted_target": "\u673a\u6784\u52a0\u6743\u76ee\u6807\u4ef7",
        "analyst_conservative_target": "\u673a\u6784\u4fdd\u5b88\u76ee\u6807\u4ef7", "blended_target": "\u6700\u7ec8\u6df7\u5408\u76ee\u6807\u4ef7", "blend_weights": "\u53ef\u7f16\u8f91\u7684\u6df7\u5408\u76ee\u6807\u4ef7\u6743\u91cd",
        "model_weight": "MU \u6a21\u578b\u57fa\u51c6\u76ee\u6807\u4ef7\u6743\u91cd", "analyst_weighted_weight": "\u673a\u6784\u52a0\u6743\u76ee\u6807\u4ef7\u6743\u91cd", "analyst_conservative_weight": "\u673a\u6784\u4fdd\u5b88\u76ee\u6807\u4ef7\u6743\u91cd",
        "blend_weight_warning": "\u6df7\u5408\u76ee\u6807\u4ef7\u6743\u91cd\u5408\u8ba1\u4e3a {total:.1f}%\u3002\u8ba1\u7b97\u65f6\u5df2\u81ea\u52a8\u5f52\u4e00\u5316\u4e3a 100%\u3002",
        "blend_weight_error": "\u8bf7\u81f3\u5c11\u8f93\u5165\u4e00\u4e2a\u6b63\u6570\u6df7\u5408\u76ee\u6807\u4ef7\u6743\u91cd\u4ee5\u8ba1\u7b97\u6700\u7ec8\u6df7\u5408\u76ee\u6807\u4ef7\u3002",
        "model_more_bullish": "\u5185\u90e8\u6a21\u578b\u6bd4\u673a\u6784\u5171\u8bc6\u66f4\u4e50\u89c2\u3002", "model_more_conservative": "\u5185\u90e8\u6a21\u578b\u6bd4\u673a\u6784\u5171\u8bc6\u66f4\u4fdd\u5b88\u3002", "model_aligned": "\u5185\u90e8\u6a21\u578b\u4e0e\u673a\u6784\u5171\u8bc6\u57fa\u672c\u4e00\u81f4\u3002",
    },
    "Espa\u00f1ol": {
        "tab": "Modelo de valoraci\u00f3n de MU", "title": "MU Memory Re-rating Valuation Model", "overview": "Resumen del modelo",
        "intro": "Este modelo compara los \u00faltimos resultados reportados de Micron con previsiones base estilo UBS, ajusta las hip\u00f3tesis futuras de EPS y FCF seg\u00fan la sorpresa, aplica una capa sectorial de memoria estilo Nomura y calcula precios objetivo Bear/Base/Bull.",
        "disclaimer": "Este es un modelo personal de investigaci\u00f3n, no asesoramiento de inversi\u00f3n.", "baseline": "Previsiones base estilo UBS", "baseline_note": "Las hip\u00f3tesis almacenadas estilo UBS se pueden editar. Actual\u00edcelas manualmente cuando cambien las previsiones.",
        "quarterly": "Base trimestral estilo UBS: MU FQ3 2026", "annual": "Base anual estilo UBS", "valuation": "Hip\u00f3tesis de valoraci\u00f3n C2029E", "actual": "Entrada de resultados reales", "actual_note": "Introduzca manualmente los \u00faltimos resultados de MU. El precio actual puede usar la cotizaci\u00f3n del panel si est\u00e1 disponible.", "use_quote": "Usar el precio de MU obtenido autom\u00e1ticamente si est\u00e1 disponible", "price_warning": "No se pudo obtener el precio actual de MU. Introduzca un precio manual.",
        "actual_revenue": "Ingresos reales, miles de millones USD", "actual_gm": "Margen bruto real, %", "actual_om": "Margen operativo real, %", "actual_eps": "EPS real", "actual_fcf": "Flujo de caja libre real, miles de millones USD", "actual_capex": "Capex real, miles de millones USD", "actual_cash": "Efectivo real, miles de millones USD", "actual_debt": "Deuda real, miles de millones USD", "shares": "Acciones diluidas reales, miles de millones", "share_price": "Precio actual de MU",
        "surprise": "An\u00e1lisis de sorpresa", "weighted": "Puntuaci\u00f3n ponderada de sorpresa", "overall": "Resultado general", "metric": "M\u00e9trica", "forecast": "Previsi\u00f3n UBS", "actual_col": "Real", "surprise_col": "Sorpresa", "interpretation": "Interpretaci\u00f3n", "revenue_surprise": "Sorpresa de ingresos", "eps_surprise": "Sorpresa de EPS", "fcf_surprise": "Sorpresa de flujo de caja libre", "gm_surprise": "Sorpresa de margen bruto", "om_surprise": "Sorpresa de margen operativo",
        "revision": "Revisi\u00f3n de previsiones", "advanced": "Configuraci\u00f3n avanzada", "pass_through": "Hip\u00f3tesis de transmisi\u00f3n de sorpresa", "forecast_item": "Partida prevista", "updated_estimate": "Estimaci\u00f3n actualizada", "change": "Cambio %", "next_q": "Pr\u00f3ximo trimestre",
        "industry": "Capa sectorial estilo Nomura", "industry_note": "Este panel editable usa un marco de ciclo de memoria estilo Nomura. No muestra ni recupera texto de informes propietarios.", "industry_score": "Puntuaci\u00f3n sectorial", "target_pe": "P/E objetivo", "regime": "R\u00e9gimen sectorial", "score_help": "-2 = Muy negativo, -1 = Negativo, 0 = Neutral, +1 = Positivo, +2 = Muy positivo",
        "output": "Resultado de precios objetivo", "bear": "Precio objetivo bajista", "base": "Precio objetivo base", "bull": "Precio objetivo alcista", "upside": "Potencial vs precio actual", "market_cap": "Capitalizaci\u00f3n impl\u00edcita", "net_cash": "Efectivo neto", "apply_net_cash": "A\u00f1adir efectivo neto por acci\u00f3n a los objetivos P/E", "explanation": "Explicaci\u00f3n del cambio del precio objetivo",
        "dcf": "Verificaci\u00f3n DCF", "dcf_note": "El DCF es muy sensible al WACC y al crecimiento terminal.", "wacc": "WACC", "terminal_growth": "Crecimiento terminal", "dcf_value": "Valor razonable DCF por acci\u00f3n", "dcf_diff": "Diferencia vs objetivo base P/E", "sensitivity": "An\u00e1lisis de sensibilidad", "dcf_error": "El WACC debe superar el crecimiento terminal. No se puede calcular el DCF.", "summary": "Resumen de hip\u00f3tesis", "method": "Todos los c\u00e1lculos usan hip\u00f3tesis almacenadas editables y valores introducidos manualmente. No se recupera ni muestra texto de investigaci\u00f3n propietario.",
        "increased": "El precio objetivo aument\u00f3 porque los resultados reales mejoraron la comparaci\u00f3n con la base estilo UBS y la capa sectorial estilo Nomura es {regime}.", "decreased": "El precio objetivo disminuy\u00f3 porque los resultados reales debilitaron la comparaci\u00f3n con la base estilo UBS o la capa sectorial estilo Nomura es {regime}.",
        "analyst_tracker": "Seguimiento de precios objetivo", "analyst_tracker_note": "Introduzca manualmente los precios objetivo. Este seguimiento no extrae ni recupera informes de analistas, incluidos los informes de pago.",
        "institution": "Instituci\u00f3n", "old_target": "Objetivo anterior", "new_target": "Objetivo nuevo", "rating": "Recomendaci\u00f3n", "credibility_weight": "Peso de credibilidad", "date": "Fecha", "notes": "Notas",
        "analyst_no_targets": "Introduzca al menos un precio objetivo positivo para calcular los resultados.", "analyst_weight_warning": "Los pesos de credibilidad suman {total:.1f}%. Los c\u00e1lculos normalizan autom\u00e1ticamente los pesos al 100%.",
        "analyst_weight_error": "Introduzca al menos un peso de credibilidad positivo para calcular el objetivo ponderado.", "simple_average_target": "Objetivo medio simple", "weighted_target": "Objetivo ponderado", "conservative_target": "Objetivo conservador",
        "median_target": "Objetivo mediano", "highest_target": "Objetivo m\u00e1ximo", "lowest_target": "Objetivo m\u00ednimo", "bullish_target": "Promedio alcista", "target_range": "Rango de objetivos",
        "analyst_upside": "Potencial vs precio actual", "target_comparison": "Comparaci\u00f3n de precios objetivo", "model_base_target": "Objetivo base impl\u00edcito del modelo", "analyst_weighted_target": "Objetivo ponderado de analistas",
        "analyst_conservative_target": "Objetivo conservador de analistas", "blended_target": "Objetivo final combinado", "blend_weights": "Pesos editables del objetivo combinado",
        "model_weight": "Peso del objetivo base del modelo MU", "analyst_weighted_weight": "Peso del objetivo ponderado de analistas", "analyst_conservative_weight": "Peso del objetivo conservador de analistas",
        "blend_weight_warning": "Los pesos del objetivo combinado suman {total:.1f}%. Los c\u00e1lculos normalizan autom\u00e1ticamente los pesos al 100%.",
        "blend_weight_error": "Introduzca al menos un peso positivo para calcular el objetivo final combinado.",
        "model_more_bullish": "El modelo interno es m\u00e1s alcista que el consenso de analistas.", "model_more_conservative": "El modelo interno es m\u00e1s conservador que el consenso de analistas.", "model_aligned": "El modelo interno est\u00e1 ampliamente alineado con el consenso de analistas.",
    },
}

MU_FACTOR_TEXT = {
    "English": ["DRAM ASP strength", "HBM ASP strength", "NAND ASP strength", "LTA confidence", "AI inference / agentic AI demand strength", "Memory supply constraint", "AI capex slowdown risk", "Data center construction delay risk", "Power bottleneck risk", "Higher-rate financing risk", "Export controls / geopolitical risk", "Memory ASP correction risk"],
    "\u4e2d\u6587": ["DRAM ASP \u5f3a\u5ea6", "HBM ASP \u5f3a\u5ea6", "NAND ASP \u5f3a\u5ea6", "LTA \u4fe1\u5fc3", "AI \u63a8\u7406 / agentic AI \u9700\u6c42\u5f3a\u5ea6", "\u5185\u5b58\u4f9b\u5e94\u7d27\u5f20", "AI \u8d44\u672c\u5f00\u652f\u653e\u7f13\u98ce\u9669", "\u6570\u636e\u4e2d\u5fc3\u5efa\u8bbe\u5ef6\u8fdf\u98ce\u9669", "\u7535\u529b\u74f6\u9888\u98ce\u9669", "\u9ad8\u5229\u7387\u878d\u8d44\u98ce\u9669", "\u51fa\u53e3\u7ba1\u5236 / \u5730\u7f18\u653f\u6cbb\u98ce\u9669", "\u5185\u5b58 ASP \u56de\u8c03\u98ce\u9669"],
    "Espa\u00f1ol": ["Fortaleza del ASP de DRAM", "Fortaleza del ASP de HBM", "Fortaleza del ASP de NAND", "Confianza en LTA", "Fortaleza de demanda de inferencia / IA ag\u00e9ntica", "Restricci\u00f3n de oferta de memoria", "Riesgo de desaceleraci\u00f3n del capex de IA", "Riesgo de retrasos en centros de datos", "Riesgo de cuello de botella energ\u00e9tico", "Riesgo de financiaci\u00f3n a tipos altos", "Riesgo de controles de exportaci\u00f3n / geopol\u00edtico", "Riesgo de correcci\u00f3n del ASP de memoria"],
}
MU_FACTOR_DEFAULTS = [1, 2, 1, 1, 2, 1, 0, -1, -1, 0, -1, -1]
MU_ANALYST_TARGETS = [
    {"Institution": "Susquehanna", "Old Target": 600.0, "New Target": 1750.0, "Rating": "Buy", "Credibility Weight": 14.0, "Date": "manual", "Notes": "Highest target, reduce overweight risk"},
    {"Institution": "D.A. Davidson", "Old Target": 1000.0, "New Target": 1500.0, "Rating": "Buy", "Credibility Weight": 15.0, "Date": "manual", "Notes": "Bullish target"},
    {"Institution": "DBS", "Old Target": 900.0, "New Target": 1200.0, "Rating": "Buy", "Credibility Weight": 10.0, "Date": "manual", "Notes": "Asia perspective"},
    {"Institution": "Mizuho Securities", "Old Target": 800.0, "New Target": 1150.0, "Rating": "Buy", "Credibility Weight": 18.0, "Date": "manual", "Notes": "Semiconductor coverage"},
    {"Institution": "Barclays", "Old Target": 675.0, "New Target": 1175.0, "Rating": "Buy", "Credibility Weight": 18.0, "Date": "manual", "Notes": "Global investment bank"},
    {"Institution": "UBS", "Old Target": 535.0, "New Target": 1625.0, "Rating": "Buy", "Credibility Weight": 25.0, "Date": "manual", "Notes": "Detailed MU LTA/EPS framework"},
]
MU_TERM_TEXT = {
    "English": {
        "revenue_usd": "Revenue (USD bn)", "gross_margin": "Gross margin", "operating_margin": "Operating margin", "non_gaap_eps": "Non-GAAP EPS", "fcf_usd": "FCF (USD bn)", "base_pe": "Base P/E", "coe": "COE / discount rate, %", "discount_years": "Discount years", "updated_c2029_eps": "Updated C2029E EPS", "assumption": "Assumption", "value": "Value", "current_mu_price": "Current MU price", "actual_capex_usd": "Actual capex (USD bn)", "net_cash_usd": "Net cash (USD bn)", "diluted_shares_b": "Diluted shares (bn)",
        "financial_note": "Reference formulas: gross margin = gross profit / revenue; operating margin = operating income / revenue; FCF = operating cash flow - capex.",
    },
    "\u4e2d\u6587": {
        "revenue_usd": "\u6536\u5165\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "gross_margin": "\u6bdb\u5229\u7387", "operating_margin": "\u8425\u4e1a\u5229\u6da6\u7387", "non_gaap_eps": "\u975e GAAP EPS", "fcf_usd": "FCF\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "base_pe": "\u57fa\u51c6 P/E", "coe": "COE / \u6298\u73b0\u7387\uff0c%", "discount_years": "\u6298\u73b0\u5e74\u6570", "updated_c2029_eps": "\u66f4\u65b0\u540e C2029E EPS", "assumption": "\u5047\u8bbe", "value": "\u6570\u503c", "current_mu_price": "\u5f53\u524d MU \u80a1\u4ef7", "actual_capex_usd": "\u5b9e\u9645\u8d44\u672c\u5f00\u652f\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "net_cash_usd": "\u51c0\u73b0\u91d1\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "diluted_shares_b": "\u7a00\u91ca\u80a1\u6570\uff08\u5341\u4ebf\uff09",
        "financial_note": "\u53c2\u8003\u516c\u5f0f\uff1a\u6bdb\u5229\u7387 = \u6bdb\u5229 / \u6536\u5165\uff1b\u8425\u4e1a\u5229\u6da6\u7387 = \u8425\u4e1a\u5229\u6da6 / \u6536\u5165\uff1bFCF = \u7ecf\u8425\u73b0\u91d1\u6d41 - \u8d44\u672c\u5f00\u652f\u3002",
    },
    "Espa\u00f1ol": {
        "revenue_usd": "Ingresos (miles de millones USD)", "gross_margin": "Margen bruto", "operating_margin": "Margen operativo", "non_gaap_eps": "EPS no GAAP", "fcf_usd": "FCF (miles de millones USD)", "base_pe": "P/E base", "coe": "COE / tasa de descuento, %", "discount_years": "A\u00f1os de descuento", "updated_c2029_eps": "EPS C2029E actualizado", "assumption": "Hip\u00f3tesis", "value": "Valor", "current_mu_price": "Precio actual de MU", "actual_capex_usd": "Capex real (miles de millones USD)", "net_cash_usd": "Efectivo neto (miles de millones USD)", "diluted_shares_b": "Acciones diluidas (miles de millones)",
        "financial_note": "F\u00f3rmulas de referencia: margen bruto = beneficio bruto / ingresos; margen operativo = beneficio operativo / ingresos; FCF = flujo de caja operativo - capex.",
    },
}
MU_RESULT_TEXT = {
    "English": {"Strong beat": "Strong beat", "Beat": "Beat", "In line": "In line", "Miss": "Miss", "Large miss": "Large miss", "Strong Beat": "Strong Beat", "In Line": "In Line", "Large Miss": "Large Miss", "Very negative": "Very negative", "Negative": "Negative", "Neutral/Base": "Neutral/Base", "Positive": "Positive", "Very positive": "Very positive"},
    "\u4e2d\u6587": {"Strong beat": "\u5927\u5e45\u8d85\u9884\u671f", "Beat": "\u8d85\u9884\u671f", "In line": "\u7b26\u5408\u9884\u671f", "Miss": "\u4f4e\u4e8e\u9884\u671f", "Large miss": "\u5927\u5e45\u4f4e\u4e8e\u9884\u671f", "Strong Beat": "\u5927\u5e45\u8d85\u9884\u671f", "In Line": "\u7b26\u5408\u9884\u671f", "Large Miss": "\u5927\u5e45\u4f4e\u4e8e\u9884\u671f", "Very negative": "\u975e\u5e38\u8d1f\u9762", "Negative": "\u8d1f\u9762", "Neutral/Base": "\u4e2d\u6027 / \u57fa\u51c6", "Positive": "\u6b63\u9762", "Very positive": "\u975e\u5e38\u6b63\u9762"},
    "Espa\u00f1ol": {"Strong beat": "Supera ampliamente", "Beat": "Supera", "In line": "En l\u00ednea", "Miss": "Por debajo", "Large miss": "Muy por debajo", "Strong Beat": "Supera ampliamente", "In Line": "En l\u00ednea", "Large Miss": "Muy por debajo", "Very negative": "Muy negativo", "Negative": "Negativo", "Neutral/Base": "Neutral/Base", "Positive": "Positivo", "Very positive": "Muy positivo"},
}

IB_TEXT = {
    "English": {
        "title": "Investment Bank Overlay", "note": "Manual, user-editable assumptions only. This overlay does not scrape, retrieve, or display proprietary or paywalled research content.",
        "ubs_overlay": "UBS Company Overlay", "nomura_overlay": "Nomura Industry Regime Overlay", "goldman_overlay": "Goldman Memory Cycle Overlay",
        "ubs_score": "UBS Company Score", "nomura_score": "Nomura Industry Score", "goldman_score": "Goldman Cycle Score", "combined_score": "Combined IB Score",
        "cycle_status": "Cycle status", "pe_adjustment": "P/E Adjustment", "original_pe": "Original Model Target P/E", "adjusted_pe": "IB Adjusted Target P/E",
        "original_base": "Original Base Target Price", "adjusted_target": "IB Adjusted Target Price", "difference": "Difference", "upside": "Upside / downside vs current MU price",
        "ib_weights": "Editable investment-bank weights", "ubs_weight": "UBS weight", "nomura_weight": "Nomura weight", "goldman_weight": "Goldman weight",
        "weight_warning": "Investment-bank weights total {total:.1f}%. Calculations automatically normalize the entered weights to 100%.",
        "weight_error": "Enter at least one positive investment-bank weight to calculate the overlay.",
        "assumptions": "Editable Goldman-style assumptions", "supply_demand": "Supply / demand balance", "hbm_outlook": "HBM market assumptions", "year": "Year",
        "dram": "DRAM supply / demand", "nand": "NAND supply / demand", "hbm": "HBM supply / demand", "hbm_tam": "HBM TAM (USD bn)", "mu_hbm_revenue": "Micron HBM Revenue (USD bn)", "mu_hbm_share": "Micron HBM Market Share",
        "enhanced": "IB-Enhanced Final Target", "enhanced_weights": "Editable IB-enhanced target weights", "existing_blended": "Existing Final Blended Target", "existing_weight": "Existing final blended target weight", "adjusted_weight": "IB adjusted target price weight",
        "enhanced_warning": "IB-enhanced target weights total {total:.1f}%. Calculations automatically normalize the entered weights to 100%.",
        "enhanced_error": "The existing final blended target is unavailable. Enter valid analyst tracker targets and weights to calculate the IB-enhanced final target.",
        "strong": "Strong re-rating support", "positive": "Positive re-rating support", "neutral": "Neutral / mixed", "weakening": "Cycle weakening", "damaged": "Thesis damaged",
        "explanation_strong": "UBS, Nomura, and Goldman-style assumptions collectively support a higher-for-longer memory cycle, stronger earnings durability, and potential P/E multiple expansion.",
        "explanation_positive": "Investment bank assumptions remain supportive, but not aggressive.",
        "explanation_neutral": "Investment bank assumptions are mixed and do not justify a major multiple change.",
        "explanation_weak": "Investment bank assumptions are weakening and suggest reducing valuation multiple support.",
        "score_help": "Score interpretation: 80-100 strongly supports memory re-rating; 60-80 supports memory re-rating; 40-60 neutral / mixed; 20-40 cycle weakening; 0-20 thesis damaged.",
        "risk_help": "Risk factors are reverse scored: higher raw risk reduces the Nomura score.",
    },
    "\u4e2d\u6587": {
        "title": "\u6295\u884c\u89c2\u70b9 Overlay", "note": "\u4ec5\u4f7f\u7528\u624b\u52a8\u5b58\u50a8\u3001\u7528\u6237\u53ef\u7f16\u8f91\u7684\u5047\u8bbe\u3002\u672c Overlay \u4e0d\u6293\u53d6\u3001\u83b7\u53d6\u6216\u663e\u793a\u4efb\u4f55\u4e13\u6709\u6216\u4ed8\u8d39\u7814\u7a76\u5185\u5bb9\u3002",
        "ubs_overlay": "UBS \u516c\u53f8\u5c42\u9762 Overlay", "nomura_overlay": "\u91ce\u6751\u884c\u4e1a\u5468\u671f Overlay", "goldman_overlay": "\u9ad8\u76db\u5185\u5b58\u5468\u671f Overlay",
        "ubs_score": "UBS \u516c\u53f8\u5206\u6570", "nomura_score": "\u91ce\u6751\u884c\u4e1a\u5206\u6570", "goldman_score": "\u9ad8\u76db\u5468\u671f\u5206\u6570", "combined_score": "\u7efc\u5408\u6295\u884c\u5206\u6570",
        "cycle_status": "\u5468\u671f\u72b6\u6001", "pe_adjustment": "P/E \u8c03\u6574", "original_pe": "\u539f\u6a21\u578b\u76ee\u6807 P/E", "adjusted_pe": "\u6295\u884c\u8c03\u6574\u540e\u76ee\u6807 P/E",
        "original_base": "\u539f\u57fa\u51c6\u76ee\u6807\u4ef7", "adjusted_target": "\u6295\u884c\u8c03\u6574\u540e\u76ee\u6807\u4ef7", "difference": "\u5dee\u989d", "upside": "\u76f8\u5bf9\u5f53\u524d MU \u80a1\u4ef7\u7684\u4e0a\u6da8 / \u4e0b\u8dcc\u7a7a\u95f4",
        "ib_weights": "\u53ef\u7f16\u8f91\u7684\u6295\u884c\u6743\u91cd", "ubs_weight": "UBS \u6743\u91cd", "nomura_weight": "\u91ce\u6751\u6743\u91cd", "goldman_weight": "\u9ad8\u76db\u6743\u91cd",
        "weight_warning": "\u6295\u884c\u6743\u91cd\u5408\u8ba1\u4e3a {total:.1f}%\u3002\u8ba1\u7b97\u65f6\u5df2\u81ea\u52a8\u5f52\u4e00\u5316\u4e3a 100%\u3002", "weight_error": "\u8bf7\u81f3\u5c11\u8f93\u5165\u4e00\u4e2a\u6b63\u6570\u6295\u884c\u6743\u91cd\u3002",
        "assumptions": "\u53ef\u7f16\u8f91\u7684\u9ad8\u76db\u98ce\u683c\u5047\u8bbe", "supply_demand": "\u4f9b\u9700\u5e73\u8861", "hbm_outlook": "HBM \u5e02\u573a\u5047\u8bbe", "year": "\u5e74\u4efd",
        "dram": "DRAM \u4f9b\u9700", "nand": "NAND \u4f9b\u9700", "hbm": "HBM \u4f9b\u9700", "hbm_tam": "HBM TAM\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "mu_hbm_revenue": "\u7f8e\u5149 HBM \u6536\u5165\uff08\u5341\u4ebf\u7f8e\u5143\uff09", "mu_hbm_share": "\u7f8e\u5149 HBM \u5e02\u573a\u4efd\u989d",
        "enhanced": "\u6295\u884c\u589e\u5f3a\u7efc\u5408\u76ee\u6807\u4ef7", "enhanced_weights": "\u53ef\u7f16\u8f91\u7684\u6295\u884c\u589e\u5f3a\u76ee\u6807\u6743\u91cd", "existing_blended": "\u73b0\u6709\u6700\u7ec8\u6df7\u5408\u76ee\u6807\u4ef7", "existing_weight": "\u73b0\u6709\u6700\u7ec8\u6df7\u5408\u76ee\u6807\u4ef7\u6743\u91cd", "adjusted_weight": "\u6295\u884c\u8c03\u6574\u540e\u76ee\u6807\u4ef7\u6743\u91cd",
        "enhanced_warning": "\u6295\u884c\u589e\u5f3a\u76ee\u6807\u6743\u91cd\u5408\u8ba1\u4e3a {total:.1f}%\u3002\u8ba1\u7b97\u65f6\u5df2\u81ea\u52a8\u5f52\u4e00\u5316\u4e3a 100%\u3002", "enhanced_error": "\u73b0\u6709\u6700\u7ec8\u6df7\u5408\u76ee\u6807\u4ef7\u4e0d\u53ef\u7528\u3002\u8bf7\u5728\u673a\u6784\u76ee\u6807\u4ef7\u8ffd\u8e2a\u5668\u4e2d\u8f93\u5165\u6709\u6548\u7684\u76ee\u6807\u4ef7\u548c\u6743\u91cd\u3002",
        "strong": "\u5f3a\u529b\u652f\u6301\u91cd\u4f30", "positive": "\u6b63\u9762\u652f\u6301\u91cd\u4f30", "neutral": "\u4e2d\u6027 / \u6df7\u5408", "weakening": "\u5468\u671f\u8d70\u5f31", "damaged": "\u903b\u8f91\u53d7\u635f",
        "explanation_strong": "UBS\u3001\u91ce\u6751\u548c\u9ad8\u76db\u98ce\u683c\u5047\u8bbe\u5171\u540c\u652f\u6301\u5185\u5b58\u5468\u671f\u66f4\u957f\u3001\u76c8\u5229\u6301\u7eed\u6027\u66f4\u5f3a\uff0c\u4ee5\u53ca\u6f5c\u5728 P/E \u500d\u6570\u6269\u5f20\u3002",
        "explanation_positive": "\u6295\u884c\u5047\u8bbe\u4ecd\u7136\u63d0\u4f9b\u652f\u6301\uff0c\u4f46\u5e76\u4e0d\u6fc0\u8fdb\u3002", "explanation_neutral": "\u6295\u884c\u5047\u8bbe\u8868\u73b0\u6df7\u5408\uff0c\u4e0d\u8db3\u4ee5\u652f\u6301\u5927\u5e45\u8c03\u6574\u4f30\u503c\u500d\u6570\u3002", "explanation_weak": "\u6295\u884c\u5047\u8bbe\u8d70\u5f31\uff0c\u5efa\u8bae\u964d\u4f4e\u4f30\u503c\u500d\u6570\u652f\u6301\u3002",
        "score_help": "\u5206\u6570\u89e3\u8bfb\uff1a80-100 \u5f3a\u529b\u652f\u6301\u5185\u5b58\u91cd\u4f30\uff1b60-80 \u652f\u6301\u5185\u5b58\u91cd\u4f30\uff1b40-60 \u4e2d\u6027 / \u6df7\u5408\uff1b20-40 \u5468\u671f\u8d70\u5f31\uff1b0-20 \u903b\u8f91\u53d7\u635f\u3002", "risk_help": "\u98ce\u9669\u56e0\u5b50\u53cd\u5411\u8ba1\u5206\uff1a\u539f\u59cb\u98ce\u9669\u8d8a\u9ad8\uff0c\u91ce\u6751\u5206\u6570\u8d8a\u4f4e\u3002",
    },
    "Espa\u00f1ol": {
        "title": "Overlay de bancos de inversi\u00f3n", "note": "Solo se usan hip\u00f3tesis manuales y editables. Este overlay no extrae, recupera ni muestra contenido propietario o de pago.",
        "ubs_overlay": "Overlay corporativo UBS", "nomura_overlay": "Overlay de r\u00e9gimen sectorial Nomura", "goldman_overlay": "Overlay del ciclo de memoria Goldman",
        "ubs_score": "Puntuaci\u00f3n corporativa UBS", "nomura_score": "Puntuaci\u00f3n sectorial Nomura", "goldman_score": "Puntuaci\u00f3n de ciclo Goldman", "combined_score": "Puntuaci\u00f3n IB combinada",
        "cycle_status": "Estado del ciclo", "pe_adjustment": "Ajuste P/E", "original_pe": "P/E objetivo original del modelo", "adjusted_pe": "P/E objetivo ajustado por IB",
        "original_base": "Precio objetivo base original", "adjusted_target": "Precio objetivo ajustado por IB", "difference": "Diferencia", "upside": "Potencial vs precio actual de MU",
        "ib_weights": "Pesos editables de bancos de inversi\u00f3n", "ubs_weight": "Peso UBS", "nomura_weight": "Peso Nomura", "goldman_weight": "Peso Goldman",
        "weight_warning": "Los pesos de bancos de inversi\u00f3n suman {total:.1f}%. Los c\u00e1lculos los normalizan autom\u00e1ticamente al 100%.", "weight_error": "Introduzca al menos un peso positivo para calcular el overlay.",
        "assumptions": "Hip\u00f3tesis editables estilo Goldman", "supply_demand": "Balance oferta / demanda", "hbm_outlook": "Hip\u00f3tesis de mercado HBM", "year": "A\u00f1o",
        "dram": "Oferta / demanda DRAM", "nand": "Oferta / demanda NAND", "hbm": "Oferta / demanda HBM", "hbm_tam": "TAM HBM (miles de millones USD)", "mu_hbm_revenue": "Ingresos HBM de Micron (miles de millones USD)", "mu_hbm_share": "Cuota HBM de Micron",
        "enhanced": "Precio objetivo final mejorado por bancos", "enhanced_weights": "Pesos editables del objetivo mejorado por IB", "existing_blended": "Objetivo final combinado existente", "existing_weight": "Peso del objetivo combinado existente", "adjusted_weight": "Peso del objetivo ajustado por IB",
        "enhanced_warning": "Los pesos del objetivo mejorado suman {total:.1f}%. Los c\u00e1lculos los normalizan autom\u00e1ticamente al 100%.", "enhanced_error": "El objetivo final combinado existente no est\u00e1 disponible. Introduzca objetivos y pesos v\u00e1lidos en el seguimiento de analistas.",
        "strong": "Fuerte apoyo a la revalorizaci\u00f3n", "positive": "Apoyo positivo a la revalorizaci\u00f3n", "neutral": "Neutral / mixto", "weakening": "Debilitamiento del ciclo", "damaged": "Tesis da\u00f1ada",
        "explanation_strong": "Las hip\u00f3tesis estilo UBS, Nomura y Goldman respaldan en conjunto un ciclo de memoria m\u00e1s largo, mayor durabilidad de beneficios y posible expansi\u00f3n del m\u00faltiplo P/E.",
        "explanation_positive": "Las hip\u00f3tesis de bancos de inversi\u00f3n siguen siendo favorables, pero no agresivas.", "explanation_neutral": "Las hip\u00f3tesis de bancos de inversi\u00f3n son mixtas y no justifican un cambio importante del m\u00faltiplo.", "explanation_weak": "Las hip\u00f3tesis de bancos de inversi\u00f3n se debilitan y sugieren reducir el apoyo al m\u00faltiplo de valoraci\u00f3n.",
        "score_help": "Interpretaci\u00f3n: 80-100 apoya firmemente la revalorizaci\u00f3n; 60-80 la apoya; 40-60 neutral / mixto; 20-40 debilitamiento del ciclo; 0-20 tesis da\u00f1ada.", "risk_help": "Los factores de riesgo se punt\u00faan a la inversa: un riesgo bruto mayor reduce la puntuaci\u00f3n Nomura.",
    },
}

IB_FACTOR_TEXT = {
    "English": {
        "ubs": ["MU EPS durability", "MU FCF durability", "LTA visibility", "HBM revenue contribution", "Margin strength", "Through-cycle earnings power"],
        "nomura": ["AI / agentic AI demand strength", "Token usage growth", "Memory supply constraint", "Risk premium reduction", "Data center capex durability", "LTA support across memory industry", "Power / data center construction risk", "Higher-rate financing risk"],
        "goldman": ["DRAM tightness", "NAND tightness", "HBM tightness", "HBM ASP catch-up", "HBM TAM expansion", "Micron HBM revenue growth", "LTA binding strength", "Supply discipline / limited capacity additions"],
    },
    "\u4e2d\u6587": {
        "ubs": ["MU EPS \u6301\u7eed\u6027", "MU FCF \u6301\u7eed\u6027", "LTA \u53ef\u89c1\u5ea6", "HBM \u6536\u5165\u8d21\u732e", "\u5229\u6da6\u7387\u5f3a\u5ea6", "\u8de8\u5468\u671f\u76c8\u5229\u80fd\u529b"],
        "nomura": ["AI / agentic AI \u9700\u6c42\u5f3a\u5ea6", "Token \u4f7f\u7528\u91cf\u589e\u957f", "\u5185\u5b58\u4f9b\u5e94\u7ea6\u675f", "\u98ce\u9669\u6ea2\u4ef7\u4e0b\u964d", "\u6570\u636e\u4e2d\u5fc3\u8d44\u672c\u5f00\u652f\u6301\u7eed\u6027", "\u5185\u5b58\u884c\u4e1a LTA \u652f\u6301", "\u7535\u529b / \u6570\u636e\u4e2d\u5fc3\u5efa\u8bbe\u98ce\u9669", "\u9ad8\u5229\u7387\u878d\u8d44\u98ce\u9669"],
        "goldman": ["DRAM \u7d27\u5f20\u5ea6", "NAND \u7d27\u5f20\u5ea6", "HBM \u7d27\u5f20\u5ea6", "HBM ASP \u8ffd\u8d76", "HBM TAM \u6269\u5f20", "\u7f8e\u5149 HBM \u6536\u5165\u589e\u957f", "LTA \u7ea6\u675f\u5f3a\u5ea6", "\u4f9b\u5e94\u7eaa\u5f8b / \u4ea7\u80fd\u589e\u52a0\u6709\u9650"],
    },
    "Espa\u00f1ol": {
        "ubs": ["Durabilidad del EPS de MU", "Durabilidad del FCF de MU", "Visibilidad LTA", "Contribuci\u00f3n de ingresos HBM", "Fortaleza de m\u00e1rgenes", "Capacidad de beneficios durante el ciclo"],
        "nomura": ["Fortaleza de demanda de IA / IA ag\u00e9ntica", "Crecimiento del uso de tokens", "Restricci\u00f3n de oferta de memoria", "Reducci\u00f3n de prima de riesgo", "Durabilidad del capex de centros de datos", "Apoyo LTA en la industria de memoria", "Riesgo energ\u00e9tico / construcci\u00f3n de centros de datos", "Riesgo de financiaci\u00f3n a tipos altos"],
        "goldman": ["Tensi\u00f3n DRAM", "Tensi\u00f3n NAND", "Tensi\u00f3n HBM", "Convergencia del ASP de HBM", "Expansi\u00f3n del TAM de HBM", "Crecimiento de ingresos HBM de Micron", "Fortaleza vinculante de LTA", "Disciplina de oferta / adiciones de capacidad limitadas"],
    },
}
IB_FACTOR_DEFAULTS = {
    "ubs": [8, 8, 8, 8, 8, 8],
    "nomura": [9, 9, 8, 8, 8, 8, 5, 5],
    "goldman": [8, 8, 9, 8, 9, 8, 8, 8],
}
IB_FACTOR_WEIGHTS = {
    "ubs": [1, 1, 1, 1, 1, 1],
    "nomura": [25, 25, 10, 10, 10, 10, 5, 5],
    "goldman": [25 / 3, 25 / 3, 25, 25 / 3, 25, 25 / 3, 25 / 3, 25 / 3],
}


def mt(key):
    language = st.session_state.get("language", "English")
    return MU_TEXT.get(language, MU_TEXT["English"]).get(key, MU_TEXT["English"].get(key, key))


def ml(key):
    language = st.session_state.get("language", "English")
    return MU_TERM_TEXT.get(language, MU_TERM_TEXT["English"]).get(key, MU_TERM_TEXT["English"].get(key, key))


def mr(key):
    language = st.session_state.get("language", "English")
    return MU_RESULT_TEXT.get(language, MU_RESULT_TEXT["English"]).get(key, key)


def ibt(key):
    language = st.session_state.get("language", "English")
    return IB_TEXT.get(language, IB_TEXT["English"]).get(key, IB_TEXT["English"].get(key, key))


def calculate_surprise(actual, forecast):
    return actual / forecast - 1 if forecast else 0.0


def calculate_margin_surprise(actual_margin, forecast_margin):
    return actual_margin - forecast_margin


def classify_surprise(score, weighted=False):
    if weighted:
        return "Strong Beat" if score >= 0.10 else "Beat" if score >= 0.03 else "In Line" if score >= -0.03 else "Miss" if score > -0.10 else "Large Miss"
    return "Strong beat" if score > 0.05 else "Beat" if score >= 0.01 else "In line" if score >= -0.01 else "Miss" if score >= -0.05 else "Large miss"


def calculate_weighted_surprise(eps, revenue, fcf, gross_margin, operating_margin):
    return 0.35 * eps + 0.25 * revenue + 0.20 * fcf + 0.10 * gross_margin + 0.10 * operating_margin


def revise_forecasts(baseline, score, pass_through):
    return {
        "Next quarter EPS": baseline["FQ3_2026"]["eps"] * (1 + score * pass_through["next_q"]),
        "FY2026 EPS": baseline["FY2026"]["eps"] * (1 + score * pass_through["fy2026"]),
        "FY2027 EPS": baseline["FY2027"]["eps"] * (1 + score * pass_through["fy2027"]),
        "C2029E EPS": baseline["C2029"]["eps"] * (1 + score * pass_through["c2029"]),
        "FY2026 FCF": baseline["FY2026"]["fcf_b"] * (1 + score * pass_through["fy2026"]),
        "FY2027 FCF": baseline["FY2027"]["fcf_b"] * (1 + score * pass_through["fy2027"]),
        "FY2028 FCF": baseline["FY2028"]["fcf_b"] * (1 + score * pass_through["fy2028"]),
    }


def calculate_industry_score(scores):
    return sum(scores)


def industry_score_to_pe(score):
    return 11.0 if score <= -6 else 13.0 if score <= -2 else 15.0 if score <= 3 else 16.0 if score <= 7 else 17.0


def industry_regime(score):
    return "Very negative" if score <= -6 else "Negative" if score <= -2 else "Neutral/Base" if score <= 3 else "Positive" if score <= 7 else "Very positive"


def calculate_target_price(eps, pe, coe, discount_years):
    return eps * pe / ((1 + coe) ** discount_years)


def calculate_analyst_target_metrics(targets, weights, current_price):
    targets = pd.to_numeric(pd.Series(targets), errors="coerce")
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    valid = targets.notna() & (targets > 0)
    targets = targets[valid].astype(float)
    weights = weights[valid].astype(float)
    if targets.empty:
        return None
    weight_total = float(weights.sum())
    weighted_target = float((targets * weights).sum() / weight_total) if weight_total > 0 else None
    sorted_targets = targets.sort_values()
    conservative = float(sorted_targets.iloc[:-1].mean()) if len(sorted_targets) > 1 else float(sorted_targets.iloc[0])
    bullish = float(sorted_targets.iloc[1:].mean()) if len(sorted_targets) > 1 else float(sorted_targets.iloc[0])
    simple_average = float(targets.mean())
    return {
        "simple_average": simple_average,
        "median": float(targets.median()),
        "weighted_target": weighted_target,
        "conservative": conservative,
        "bullish": bullish,
        "min": float(targets.min()),
        "max": float(targets.max()),
        "range": f"${targets.min():,.2f} - ${targets.max():,.2f}",
        "upside": calculate_surprise(weighted_target, current_price) if weighted_target is not None and current_price else None,
        "weight_total": weight_total,
    }


def calculate_blended_target(model_target, analyst_weighted_target, analyst_conservative_target, weights):
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    weight_total = float(weights.sum())
    if weight_total <= 0:
        return None, weight_total
    values = pd.Series([model_target, analyst_weighted_target, analyst_conservative_target], dtype=float)
    return float((values * weights / weight_total).sum()), weight_total


def calculate_normalized_score(scores, weights, reverse_indexes=()):
    scores = pd.to_numeric(pd.Series(scores), errors="coerce").fillna(0.0).clip(lower=0.0, upper=10.0)
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    for index in reverse_indexes:
        scores.iloc[index] = 10.0 - scores.iloc[index]
    weight_total = float(weights.sum())
    return float((scores * weights).sum() / weight_total * 10.0) if weight_total > 0 else None


def calculate_combined_ib_score(ubs_score, nomura_score, goldman_score, weights):
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    weight_total = float(weights.sum())
    if weight_total <= 0:
        return None, weight_total
    scores = pd.Series([ubs_score, nomura_score, goldman_score], dtype=float)
    return float((scores * weights / weight_total).sum()), weight_total


def ib_score_to_pe_adjustment(score):
    return 2.0 if score >= 80 else 1.0 if score >= 60 else 0.0 if score >= 40 else -1.5 if score >= 20 else -3.0


def ib_cycle_status(score):
    return "strong" if score >= 80 else "positive" if score >= 60 else "neutral" if score >= 40 else "weakening" if score >= 20 else "damaged"


def calculate_ib_enhanced_target(existing_target, adjusted_target, weights):
    if existing_target is None or adjusted_target is None:
        return None, 0.0
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    weight_total = float(weights.sum())
    if weight_total <= 0:
        return None, weight_total
    values = pd.Series([existing_target, adjusted_target], dtype=float)
    return float((values * weights / weight_total).sum()), weight_total


def calculate_dcf_value(fcfs, wacc, terminal_growth, net_cash_b, diluted_shares_b):
    if wacc <= terminal_growth or diluted_shares_b <= 0:
        return None
    enterprise_value = sum(fcf / ((1 + wacc) ** year) for year, fcf in enumerate(fcfs, start=1))
    terminal_value = fcfs[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    enterprise_value += terminal_value / ((1 + wacc) ** len(fcfs))
    return (enterprise_value + net_cash_b) / diluted_shares_b


def create_sensitivity_table(fcfs, net_cash_b, diluted_shares_b):
    growth_rates = [0.015, 0.020, 0.025, 0.030, 0.035]
    rows = {}
    for wacc in [0.10, 0.11, 0.12, 0.13, 0.14]:
        rows[f"{wacc:.0%}"] = {f"{growth:.1%}": calculate_dcf_value(fcfs, wacc, growth, net_cash_b, diluted_shares_b) for growth in growth_rates}
    return pd.DataFrame.from_dict(rows, orient="index").map(lambda value: f"${value:,.2f}" if value is not None else "N/A")


def _baseline_input(label, value, key, percent=False):
    displayed = value * 100 if percent else value
    updated = st.number_input(label, value=float(displayed), step=0.1 if percent else 0.01, key=key)
    return updated / 100 if percent else updated


def _render_ib_factor_sliders(group, reverse_indexes=()):
    language = st.session_state.get("language", "English")
    labels = IB_FACTOR_TEXT.get(language, IB_FACTOR_TEXT["English"])[group]
    cols = st.columns(3)
    scores = []
    for index, (label, default) in enumerate(zip(labels, IB_FACTOR_DEFAULTS[group])):
        suffix = " (risk)" if index in reverse_indexes else ""
        with cols[index % 3]:
            scores.append(st.slider(f"{label}{suffix}", 0, 10, default, key=f"mu_ib_{group}_{index}"))
    return calculate_normalized_score(scores, IB_FACTOR_WEIGHTS[group], reverse_indexes)


def render_mu_investment_bank_overlay(updated_eps, original_target_pe, original_base_target, current_price, coe, discount_years, existing_blended_target):
    st.subheader(ibt("title"))
    st.caption(ibt("note"))
    st.caption(ibt("score_help"))

    st.markdown(f"#### {ibt('ubs_overlay')}")
    ubs_score = _render_ib_factor_sliders("ubs")

    st.markdown(f"#### {ibt('nomura_overlay')}")
    st.caption(ibt("risk_help"))
    nomura_score = _render_ib_factor_sliders("nomura", reverse_indexes=(6, 7))

    st.markdown(f"#### {ibt('goldman_overlay')}")
    with st.expander(ibt("assumptions"), expanded=False):
        years = ["2026E", "2027E", "2028E"]
        st.markdown(f"##### {ibt('supply_demand')}")
        st.data_editor(
            pd.DataFrame({ibt("year"): years, ibt("dram"): [-5.0, -5.9, -3.9], ibt("nand"): [-4.4, -4.6, -3.0], ibt("hbm"): [-5.4, -6.0, -4.3]}),
            width="stretch", hide_index=True, key="mu_ib_goldman_supply_demand",
            column_config={ibt("dram"): st.column_config.NumberColumn(format="%.1f%%"), ibt("nand"): st.column_config.NumberColumn(format="%.1f%%"), ibt("hbm"): st.column_config.NumberColumn(format="%.1f%%")},
        )
        st.markdown(f"##### {ibt('hbm_outlook')}")
        st.data_editor(
            pd.DataFrame({ibt("year"): years, ibt("hbm_tam"): [56.0, 116.0, 168.0], ibt("mu_hbm_revenue"): [12.862, 25.242, 35.481], ibt("mu_hbm_share"): [23.0, 22.0, 21.0]}),
            width="stretch", hide_index=True, key="mu_ib_goldman_hbm_outlook",
            column_config={ibt("hbm_tam"): st.column_config.NumberColumn(format="%.1f"), ibt("mu_hbm_revenue"): st.column_config.NumberColumn(format="%.3f"), ibt("mu_hbm_share"): st.column_config.NumberColumn(format="%.1f%%")},
        )
    goldman_score = _render_ib_factor_sliders("goldman")

    st.markdown(f"#### {ibt('ib_weights')}")
    cols = st.columns(3)
    bank_weights = [
        cols[0].number_input(f"{ibt('ubs_weight')}, %", value=40.0, min_value=0.0, step=1.0, key="mu_ib_ubs_weight"),
        cols[1].number_input(f"{ibt('nomura_weight')}, %", value=30.0, min_value=0.0, step=1.0, key="mu_ib_nomura_weight"),
        cols[2].number_input(f"{ibt('goldman_weight')}, %", value=30.0, min_value=0.0, step=1.0, key="mu_ib_goldman_weight"),
    ]
    combined_score, bank_weight_total = calculate_combined_ib_score(ubs_score, nomura_score, goldman_score, bank_weights)
    if abs(bank_weight_total - 100.0) > 0.01:
        st.warning(ibt("weight_warning").format(total=bank_weight_total))
    if combined_score is None:
        st.warning(ibt("weight_error"))
        return

    pe_adjustment = ib_score_to_pe_adjustment(combined_score)
    adjusted_pe = original_target_pe + pe_adjustment
    adjusted_target = calculate_target_price(updated_eps, adjusted_pe, coe, discount_years)
    status = ib_cycle_status(combined_score)
    cards = st.columns(4)
    cards[0].metric(ibt("ubs_score"), f"{ubs_score:.1f}")
    cards[1].metric(ibt("nomura_score"), f"{nomura_score:.1f}")
    cards[2].metric(ibt("goldman_score"), f"{goldman_score:.1f}")
    cards[3].metric(ibt("combined_score"), f"{combined_score:.1f}")
    cards = st.columns(4)
    cards[0].metric(ibt("cycle_status"), ibt(status))
    cards[1].metric(ibt("pe_adjustment"), f"{pe_adjustment:+.1f}x")
    cards[2].metric(ibt("original_pe"), f"{original_target_pe:.1f}x")
    cards[3].metric(ibt("adjusted_pe"), f"{adjusted_pe:.1f}x")
    cards = st.columns(4)
    cards[0].metric(ibt("original_base"), f"${original_base_target:,.2f}")
    cards[1].metric(ibt("adjusted_target"), f"${adjusted_target:,.2f}")
    cards[2].metric(ibt("difference"), f"${adjusted_target - original_base_target:+,.2f}")
    cards[3].metric(ibt("upside"), f"{calculate_surprise(adjusted_target, current_price):+.1%}" if current_price else "N/A")
    st.info(ibt("explanation_strong" if combined_score >= 80 else "explanation_positive" if combined_score >= 60 else "explanation_neutral" if combined_score >= 40 else "explanation_weak"))

    st.markdown(f"#### {ibt('enhanced')}")
    st.caption(ibt("enhanced_weights"))
    cols = st.columns(2)
    enhanced_weights = [
        cols[0].number_input(f"{ibt('existing_weight')}, %", value=70.0, min_value=0.0, step=1.0, key="mu_ib_existing_weight"),
        cols[1].number_input(f"{ibt('adjusted_weight')}, %", value=30.0, min_value=0.0, step=1.0, key="mu_ib_adjusted_weight"),
    ]
    enhanced_target, enhanced_weight_total = calculate_ib_enhanced_target(existing_blended_target, adjusted_target, enhanced_weights)
    if abs(enhanced_weight_total - 100.0) > 0.01 and enhanced_target is not None:
        st.warning(ibt("enhanced_warning").format(total=enhanced_weight_total))
    if enhanced_target is None:
        st.warning(ibt("enhanced_error"))
        return
    cards = st.columns(4)
    cards[0].metric(ibt("existing_blended"), f"${existing_blended_target:,.2f}")
    cards[1].metric(ibt("adjusted_target"), f"${adjusted_target:,.2f}")
    cards[2].metric(ibt("enhanced"), f"${enhanced_target:,.2f}")
    cards[3].metric(ibt("upside"), f"{calculate_surprise(enhanced_target, current_price):+.1%}" if current_price else "N/A")


def render_mu_analyst_tracker(current_price, base_target):
    st.subheader(mt("analyst_tracker"))
    st.caption(mt("analyst_tracker_note"))
    analyst_targets = st.data_editor(
        pd.DataFrame(MU_ANALYST_TARGETS),
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="mu_analyst_targets",
        column_config={
            "Institution": st.column_config.TextColumn(mt("institution")),
            "Old Target": st.column_config.NumberColumn(mt("old_target"), min_value=0.0, step=1.0, format="$%.2f"),
            "New Target": st.column_config.NumberColumn(mt("new_target"), min_value=0.0, step=1.0, format="$%.2f"),
            "Rating": st.column_config.TextColumn(mt("rating")),
            "Credibility Weight": st.column_config.NumberColumn(mt("credibility_weight"), min_value=0.0, step=1.0, format="%.1f%%"),
            "Date": st.column_config.TextColumn(mt("date")),
            "Notes": st.column_config.TextColumn(mt("notes")),
        },
    )
    metrics = calculate_analyst_target_metrics(
        analyst_targets.get("New Target", pd.Series(dtype=float)),
        analyst_targets.get("Credibility Weight", pd.Series(dtype=float)),
        current_price,
    )
    if metrics is None:
        st.warning(mt("analyst_no_targets"))
        return None
    if abs(metrics["weight_total"] - 100.0) > 0.01:
        st.warning(mt("analyst_weight_warning").format(total=metrics["weight_total"]))
    if metrics["weighted_target"] is None:
        st.warning(mt("analyst_weight_error"))
        return None

    cards = st.columns(4)
    cards[0].metric(mt("simple_average_target"), f"${metrics['simple_average']:,.2f}")
    cards[1].metric(mt("weighted_target"), f"${metrics['weighted_target']:,.2f}")
    cards[2].metric(mt("conservative_target"), f"${metrics['conservative']:,.2f}")
    cards[3].metric(mt("median_target"), f"${metrics['median']:,.2f}")
    cards = st.columns(4)
    cards[0].metric(mt("highest_target"), f"${metrics['max']:,.2f}")
    cards[1].metric(mt("lowest_target"), f"${metrics['min']:,.2f}")
    cards[2].metric(mt("bullish_target"), f"${metrics['bullish']:,.2f}")
    cards[3].metric(mt("target_range"), metrics["range"])
    st.metric(mt("analyst_upside"), f"{metrics['upside']:+.1%}" if metrics["upside"] is not None else "N/A")

    st.markdown(f"#### {mt('target_comparison')}")
    comparison = pd.DataFrame([
        {mt("metric"): mt("model_base_target"), mt("share_price"): base_target, mt("upside"): calculate_surprise(base_target, current_price)},
        {mt("metric"): mt("analyst_weighted_target"), mt("share_price"): metrics["weighted_target"], mt("upside"): calculate_surprise(metrics["weighted_target"], current_price)},
        {mt("metric"): mt("analyst_conservative_target"), mt("share_price"): metrics["conservative"], mt("upside"): calculate_surprise(metrics["conservative"], current_price)},
    ])
    st.dataframe(comparison.style.format({mt("share_price"): "${:,.2f}", mt("upside"): "{:+.1%}"}), use_container_width=True, hide_index=True)
    analyst_gap = calculate_surprise(base_target, metrics["weighted_target"])
    st.info(mt("model_aligned" if abs(analyst_gap) <= 0.05 else "model_more_bullish" if analyst_gap > 0 else "model_more_conservative"))

    st.markdown(f"#### {mt('blend_weights')}")
    cols = st.columns(3)
    blend_weights = [
        cols[0].number_input(f"{mt('model_weight')}, %", value=50.0, min_value=0.0, step=1.0, key="mu_blend_model"),
        cols[1].number_input(f"{mt('analyst_weighted_weight')}, %", value=30.0, min_value=0.0, step=1.0, key="mu_blend_weighted"),
        cols[2].number_input(f"{mt('analyst_conservative_weight')}, %", value=20.0, min_value=0.0, step=1.0, key="mu_blend_conservative"),
    ]
    blended_target, blend_weight_total = calculate_blended_target(base_target, metrics["weighted_target"], metrics["conservative"], blend_weights)
    if abs(blend_weight_total - 100.0) > 0.01:
        st.warning(mt("blend_weight_warning").format(total=blend_weight_total))
    if blended_target is None:
        st.warning(mt("blend_weight_error"))
    else:
        st.metric(mt("blended_target"), f"${blended_target:,.2f}", f"{calculate_surprise(blended_target, current_price):+.1%}")
    return blended_target


def render_mu_valuation_model(snapshots):
    st.header(mt("title"))
    st.subheader(mt("overview"))
    st.write(mt("intro"))
    st.warning(mt("disclaimer"))
    st.info(mt("method"))

    baseline = {period: values.copy() for period, values in UBS_BASELINE.items()}
    with st.expander(mt("baseline"), expanded=False):
        st.caption(mt("baseline_note"))
        st.markdown(f"#### {mt('quarterly')}")
        cols = st.columns(5)
        for column, (field, label, percent) in zip(cols, [("revenue_b", ml("revenue_usd"), False), ("gross_margin", ml("gross_margin"), True), ("operating_margin", ml("operating_margin"), True), ("eps", ml("non_gaap_eps"), False), ("fcf_b", ml("fcf_usd"), False)]):
            with column:
                baseline["FQ3_2026"][field] = _baseline_input(label, baseline["FQ3_2026"][field], f"mu_fq3_{field}", percent)
        st.markdown(f"#### {mt('annual')}")
        for period in ("FY2026", "FY2027", "FY2028"):
            cols = st.columns(3)
            for column, (field, label) in zip(cols, [("revenue_b", ml("revenue_usd")), ("eps", "EPS"), ("fcf_b", ml("fcf_usd"))]):
                with column:
                    baseline[period][field] = _baseline_input(f"{period} {label}", baseline[period][field], f"mu_{period}_{field}")
        st.markdown(f"#### {mt('valuation')}")
        cols = st.columns(4)
        with cols[0]: baseline["C2029"]["eps"] = _baseline_input("C2029E EPS", baseline["C2029"]["eps"], "mu_c2029_eps")
        with cols[1]: baseline["C2029"]["base_pe"] = _baseline_input(ml("base_pe"), baseline["C2029"]["base_pe"], "mu_c2029_pe")
        with cols[2]: baseline["C2029"]["coe"] = _baseline_input(ml("coe"), baseline["C2029"]["coe"], "mu_c2029_coe", True)
        with cols[3]: baseline["C2029"]["discount_years"] = _baseline_input(ml("discount_years"), baseline["C2029"]["discount_years"], "mu_c2029_years")

    st.subheader(mt("actual"))
    st.caption(mt("actual_note"))
    st.info(ml("financial_note"))
    cols = st.columns(3)
    with cols[0]:
        actual_revenue = st.number_input(mt("actual_revenue"), value=23.860, step=0.01, key="mu_actual_revenue")
        actual_gm = st.number_input(mt("actual_gm"), value=74.4, step=0.1, key="mu_actual_gm") / 100
        actual_om = st.number_input(mt("actual_om"), value=67.6, step=0.1, key="mu_actual_om") / 100
        actual_eps = st.number_input(mt("actual_eps"), value=12.07, step=0.01, key="mu_actual_eps")
    with cols[1]:
        actual_fcf = st.number_input(mt("actual_fcf"), value=8.538, step=0.01, key="mu_actual_fcf")
        actual_capex = st.number_input(mt("actual_capex"), value=11.776, step=0.01, key="mu_actual_capex")
        actual_cash = st.number_input(mt("actual_cash"), value=13.908, step=0.01, key="mu_actual_cash")
        actual_debt = st.number_input(mt("actual_debt"), value=10.142, step=0.01, key="mu_actual_debt")
    mu_snapshot = snapshots.get("MU") or {}
    fetched_price = mu_snapshot.get("price")
    with cols[2]:
        diluted_shares = st.number_input(mt("shares"), value=1.142, min_value=0.001, step=0.001, key="mu_shares")
        use_quote = st.checkbox(mt("use_quote"), value=True, key="mu_use_quote")
        if use_quote and fetched_price is None:
            st.warning(mt("price_warning"))
        current_price = st.number_input(mt("share_price"), value=float(fetched_price or 100.0), min_value=0.01, step=0.1, disabled=bool(use_quote and fetched_price), key="mu_price")
        if use_quote and fetched_price:
            current_price = float(fetched_price)
        st.metric(mt("net_cash"), f"${actual_cash - actual_debt:,.3f}B")

    surprises = {
        mt("revenue_surprise"): calculate_surprise(actual_revenue, baseline["FQ3_2026"]["revenue_b"]),
        mt("eps_surprise"): calculate_surprise(actual_eps, baseline["FQ3_2026"]["eps"]),
        mt("fcf_surprise"): calculate_surprise(actual_fcf, baseline["FQ3_2026"]["fcf_b"]),
        mt("gm_surprise"): calculate_margin_surprise(actual_gm, baseline["FQ3_2026"]["gross_margin"]),
        mt("om_surprise"): calculate_margin_surprise(actual_om, baseline["FQ3_2026"]["operating_margin"]),
    }
    score = calculate_weighted_surprise(surprises[mt("eps_surprise")], surprises[mt("revenue_surprise")], surprises[mt("fcf_surprise")], surprises[mt("gm_surprise")], surprises[mt("om_surprise")])
    st.subheader(mt("surprise"))
    baseline_values = [baseline["FQ3_2026"]["revenue_b"], baseline["FQ3_2026"]["eps"], baseline["FQ3_2026"]["fcf_b"], baseline["FQ3_2026"]["gross_margin"], baseline["FQ3_2026"]["operating_margin"]]
    actual_values = [actual_revenue, actual_eps, actual_fcf, actual_gm, actual_om]
    margin_rows = {mt("gm_surprise"), mt("om_surprise")}
    surprise_rows = []
    for (label, value), forecast, actual in zip(surprises.items(), baseline_values, actual_values):
        is_margin = label in margin_rows
        surprise_rows.append({mt("metric"): label, mt("forecast"): f"{forecast:.1%}" if is_margin else f"{forecast:,.3f}", mt("actual_col"): f"{actual:.1%}" if is_margin else f"{actual:,.3f}", mt("surprise_col"): f"{value * 100:+.1f} pp" if is_margin else f"{value:+.1%}", mt("interpretation"): mr(classify_surprise(value))})
    st.dataframe(pd.DataFrame(surprise_rows), use_container_width=True, hide_index=True)
    score_cols = st.columns(2)
    score_cols[0].metric(mt("weighted"), f"{score:+.2%}")
    score_cols[1].metric(mt("overall"), mr(classify_surprise(score, weighted=True)))

    with st.expander(mt("advanced"), expanded=False):
        st.markdown(f"#### {mt('pass_through')}")
        cols = st.columns(5)
        pass_through = {}
        for column, (key, label, default) in zip(cols, [("next_q", mt("next_q"), 0.80), ("fy2026", "FY2026", 0.50), ("fy2027", "FY2027", 0.30), ("fy2028", "FY2028", 0.20), ("c2029", "C2029E EPS", 0.20)]):
            with column:
                pass_through[key] = st.number_input(f"{label}, %", value=default * 100, step=1.0, key=f"mu_pass_{key}") / 100
    revisions = revise_forecasts(baseline, score, pass_through)
    revision_baseline = {"Next quarter EPS": baseline["FQ3_2026"]["eps"], "FY2026 EPS": baseline["FY2026"]["eps"], "FY2027 EPS": baseline["FY2027"]["eps"], "C2029E EPS": baseline["C2029"]["eps"], "FY2026 FCF": baseline["FY2026"]["fcf_b"], "FY2027 FCF": baseline["FY2027"]["fcf_b"], "FY2028 FCF": baseline["FY2028"]["fcf_b"]}
    st.subheader(mt("revision"))
    st.dataframe(pd.DataFrame([{mt("forecast_item"): key, mt("forecast"): f"{revision_baseline[key]:,.2f}", mt("updated_estimate"): f"{value:,.2f}", mt("change"): f"{calculate_surprise(value, revision_baseline[key]):+.2%}"} for key, value in revisions.items()]), use_container_width=True, hide_index=True)

    st.subheader(mt("industry"))
    st.caption(mt("industry_note"))
    st.caption(mt("score_help"))
    factor_scores = []
    factor_labels = MU_FACTOR_TEXT.get(st.session_state.get("language", "English"), MU_FACTOR_TEXT["English"])
    factor_cols = st.columns(3)
    for index, (label, default) in enumerate(zip(factor_labels, MU_FACTOR_DEFAULTS)):
        with factor_cols[index % 3]:
            factor_scores.append(st.slider(label, -2, 2, default, key=f"mu_factor_{index}"))
    industry_score = calculate_industry_score(factor_scores)
    target_pe = industry_score_to_pe(industry_score)
    regime = industry_regime(industry_score)
    industry_cols = st.columns(3)
    industry_cols[0].metric(mt("industry_score"), f"{industry_score:+d}")
    industry_cols[1].metric(mt("target_pe"), f"{target_pe:.1f}x")
    industry_cols[2].metric(mt("regime"), mr(regime))

    net_cash_b = actual_cash - actual_debt
    add_net_cash = st.checkbox(mt("apply_net_cash"), value=False, key="mu_add_net_cash")
    net_cash_per_share = net_cash_b / diluted_shares if add_net_cash else 0.0
    discount = (1 + baseline["C2029"]["coe"]) ** baseline["C2029"]["discount_years"]
    base_target = calculate_target_price(revisions["C2029E EPS"], target_pe, baseline["C2029"]["coe"], baseline["C2029"]["discount_years"]) + net_cash_per_share
    bear_target = revisions["C2029E EPS"] * 0.75 * max(8.0, target_pe - 3.0) / discount + net_cash_per_share
    bull_target = revisions["C2029E EPS"] * 1.15 * (target_pe + 2.0) / discount + net_cash_per_share
    st.subheader(mt("output"))
    output_cols = st.columns(4)
    for column, label, value in zip(output_cols, [ml("updated_c2029_eps"), mt("target_pe"), mt("bear"), mt("base")], [f"${revisions['C2029E EPS']:,.2f}", f"{target_pe:.1f}x", f"${bear_target:,.2f}", f"${base_target:,.2f}"]):
        column.metric(label, value)
    output_cols = st.columns(4)
    output_cols[0].metric(mt("bull"), f"${bull_target:,.2f}")
    output_cols[1].metric(mt("upside"), f"{calculate_surprise(base_target, current_price):+.1%}")
    output_cols[2].metric(mt("weighted"), f"{score:+.2%}")
    output_cols[3].metric(mt("industry_score"), f"{industry_score:+d}")
    st.dataframe(pd.DataFrame([{mt("metric"): mt("bear"), mt("share_price"): bear_target, mt("upside"): calculate_surprise(bear_target, current_price), mt("market_cap"): bear_target * diluted_shares}, {mt("metric"): mt("base"), mt("share_price"): base_target, mt("upside"): calculate_surprise(base_target, current_price), mt("market_cap"): base_target * diluted_shares}, {mt("metric"): mt("bull"), mt("share_price"): bull_target, mt("upside"): calculate_surprise(bull_target, current_price), mt("market_cap"): bull_target * diluted_shares}]).style.format({mt("share_price"): "${:,.2f}", mt("upside"): "{:+.1%}", mt("market_cap"): "${:,.1f}B"}), use_container_width=True, hide_index=True)
    st.markdown(f"#### {mt('explanation')}")
    original_base_target = calculate_target_price(baseline["C2029"]["eps"], baseline["C2029"]["base_pe"], baseline["C2029"]["coe"], baseline["C2029"]["discount_years"])
    st.write(mt("increased" if base_target >= original_base_target else "decreased").format(regime=mr(regime)))

    existing_blended_target = render_mu_analyst_tracker(current_price, base_target)
    render_mu_investment_bank_overlay(
        revisions["C2029E EPS"],
        target_pe,
        base_target,
        current_price,
        baseline["C2029"]["coe"],
        baseline["C2029"]["discount_years"],
        existing_blended_target,
    )

    st.subheader(mt("dcf"))
    st.warning(mt("dcf_note"))
    dcf_cols = st.columns(2)
    with dcf_cols[0]: wacc = st.number_input(f"{mt('wacc')}, %", value=12.0, step=0.5, key="mu_wacc") / 100
    with dcf_cols[1]: terminal_growth = st.number_input(f"{mt('terminal_growth')}, %", value=2.5, step=0.1, key="mu_terminal_growth") / 100
    fcfs = [revisions["FY2026 FCF"], revisions["FY2027 FCF"], revisions["FY2028 FCF"]]
    fcfs.extend([fcfs[-1] * 0.90, fcfs[-1] * 0.90 * 0.95])
    dcf_value = calculate_dcf_value(fcfs, wacc, terminal_growth, net_cash_b, diluted_shares)
    if dcf_value is None:
        st.error(mt("dcf_error"))
    else:
        dcf_cols = st.columns(2)
        dcf_cols[0].metric(mt("dcf_value"), f"${dcf_value:,.2f}")
        dcf_cols[1].metric(mt("dcf_diff"), f"{calculate_surprise(dcf_value, base_target):+.1%}")
    st.markdown(f"#### {mt('sensitivity')}")
    st.dataframe(create_sensitivity_table(fcfs, net_cash_b, diluted_shares), use_container_width=True)
    with st.expander(mt("summary"), expanded=False):
        st.dataframe(pd.DataFrame({ml("assumption"): [ml("current_mu_price"), ml("actual_capex_usd"), ml("net_cash_usd"), ml("diluted_shares_b"), "COE", ml("discount_years"), "WACC", mt("terminal_growth")], ml("value"): [f"${current_price:,.2f}", f"${actual_capex:,.3f}", f"${net_cash_b:,.3f}", f"{diluted_shares:,.3f}", f"{baseline['C2029']['coe']:.1%}", f"{baseline['C2029']['discount_years']:.1f}", f"{wacc:.1%}", f"{terminal_growth:.1%}"]}), use_container_width=True, hide_index=True)


def render_watchlist_manager():
    st.sidebar.divider()
    st.sidebar.subheader(t("watchlist_manager"))
    tickers = load_watchlist()
    new_ticker = st.sidebar.text_input(t("watchlist_input"), key="watchlist_new_ticker")
    if st.sidebar.button(t("watchlist_add"), key="watchlist_add_button"):
        success, message_key, symbol = add_ticker_to_watchlist(new_ticker)
        message = t(message_key)
        if symbol:
            message = f"{message} {symbol}"
        if success:
            st.sidebar.success(message)
            st.rerun()
        else:
            st.sidebar.error(message)

    st.sidebar.caption(t("watchlist_current"))
    if tickers:
        st.sidebar.write(", ".join(tickers))
        remove_ticker = st.sidebar.selectbox(t("watchlist_remove"), tickers, key="watchlist_remove_select")
        if st.sidebar.button(t("watchlist_remove"), key="watchlist_remove_button"):
            success, message_key, symbol = remove_ticker_from_watchlist(remove_ticker)
            message = t(message_key)
            if symbol:
                message = f"{message} {symbol}"
            if success:
                st.sidebar.success(message)
                st.rerun()
            else:
                st.sidebar.error(message)


def main():
    st.set_page_config(page_title="Equity Research Terminal", layout="wide")
    reset_debug_state()
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1800px;}
        .stock-card {background:#111827; border:1px solid #263244; border-radius:10px; padding:16px; min-height:220px;}
        .ticker {font-size:1.25rem; font-weight:700; letter-spacing:.08em; color:#e5e7eb;}
        .company {font-size:.8rem; color:#94a3b8; min-height:26px;}
        .source {font-size:.68rem; color:#64748b;}
        .price {font-size:1.65rem; font-weight:700; margin-top:12px; color:#f8fafc;}
        .change {font-size:.85rem; margin-bottom:14px;}
        .card-grid {display:grid; gap:8px; font-size:.72rem; color:#94a3b8;}
        .card-grid span {display:flex; justify-content:space-between; border-top:1px solid #253044; padding-top:6px;}
        .card-grid b {color:#e5e7eb;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.selectbox(t("language"), list(TRANSLATIONS), index=0, key="language")
    render_watchlist_manager()
    st.title(t("dashboard_title"))
    st.caption(t("dashboard_caption"))
    st.caption("Using cached data when available...")

    snapshots = {}
    with st.spinner("Loading market cards..."):
        for symbol in load_watchlist():
            try:
                snapshots[symbol] = get_card_snapshot(symbol)
            except Exception:
                snapshots[symbol] = None

    render_overview_cards(snapshots)
    st.divider()

    section_labels = [
        t("technical_analysis"), t("options_gex"), t("value_investing"),
        "US Market Valuation", t("news_sentiment"), t("multi_agent_research"), t("macro"), mt("tab"),
    ]
    selected_section = st.radio("Section", section_labels, horizontal=True, key="main_section_selector")
    section_start = perf_counter()
    if selected_section == t("technical_analysis"):
        render_technical_section()
    elif selected_section == t("options_gex"):
        render_options_section()
    elif selected_section == t("value_investing"):
        render_value_section()
    elif selected_section == "US Market Valuation":
        render_us_market_valuation_dashboard()
    elif selected_section == t("news_sentiment"):
        render_news_section()
    elif selected_section == t("multi_agent_research"):
        render_multi_agent_section(st.session_state.get("language", "English"), load_watchlist())
    elif selected_section == t("macro"):
        render_macro_section()
    else:
        render_mu_valuation_model(snapshots)
    track_section_time(selected_section, perf_counter() - section_start)
    render_debug_panel()


if __name__ == "__main__":
    main()
