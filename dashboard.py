# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta
import hashlib
import json
import os
import re

import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm
import streamlit as st
import yfinance as yf

from config import CACHE_DIR, get_openai_client
from financials import fetch_company_news, fetch_general_news, fetch_historical_prices, get_company_snapshot as get_fmp_company_snapshot
from macro_data import build_macro_snapshot, fetch_indicator, fetch_macro_calendar, fetch_market_series, fetch_treasury_rates


YFINANCE_CACHE_DIR = CACHE_DIR / "yfinance"
os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
yf.cache.set_cache_location(YFINANCE_CACHE_DIR)

WATCHLIST = ["NVDA", "MU", "SNDK", "LITE", "RKLB"]
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
        "multi_agent_research": "Multi-Agent Research", "data_diagnostics": "Data Diagnostics", "macro": "Macro",
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
        "days_until_earnings": "Days Until Earnings", "multi_agent_caption": "Run the five-agent workflow for the whole watchlist. Each stock receives a separate verdict.",
        "run_multi_agent": "Run All-Stock Multi-Agent Analysis", "running_agents": "Running research agents for", "final_verdict": "Final Verdict",
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
    },
    "中文": {
        "language": "语言", "dashboard_title": "股票研究终端", "dashboard_caption": "跨公司仪表板 | AI 基础设施与成长股观察列表",
        "technical_analysis": "技术分析", "options_gex": "期权与 GEX", "value_investing": "价值投资", "news_sentiment": "新闻与情绪",
        "multi_agent_research": "多智能体研究", "data_diagnostics": "数据诊断", "macro": "宏观", "source": "来源", "price": "价格",
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
        "eps_surprise": "EPS 超预期幅度", "days_until_earnings": "距离财报天数", "multi_agent_caption": "为整个观察列表运行五智能体工作流。每只股票都会获得单独结论。",
        "run_multi_agent": "运行全股票多智能体分析", "running_agents": "正在运行研究智能体：", "final_verdict": "最终结论", "agent_detail": "智能体详情",
        "fundamental_analysis": "基本面分析", "options_analysis": "期权分析", "data_unavailable": "数据不可用", "data_source": "数据来源",
        "revenue_growth_yoy": "营收同比增长", "last_updated": "最后更新", "diagnostic_note": "诊断说明", "macro_caption": "未来 30 天的动态宏观仪表板，优先使用 FMP 数据。市场序列备用来源使用 yfinance。",
        "refresh_macro": "刷新宏观数据", "calendar_window": "日历区间", "macro_risk_score": "宏观风险评分", "treasury_source": "美债数据来源",
        "dynamic_macro_calendar": "动态 30 天宏观日历", "show_all_macro_events": "显示所有宏观日历事件", "no_highlighted_macro_events": "未来 30 天没有重点宏观事件。",
        "economic_calendar_unavailable": "经济日历不可用。", "historical_data_unavailable": "历史数据不可用", "cpi_index": "CPI 指数", "us_10y_treasury_yield": "美国 10 年期国债收益率",
        "brent_crude_oil": "布伦特原油", "unemployment": "失业率", "gdp_growth_yoy": "GDP 同比增长", "no_watchlist_news": "暂无新闻", "no_market_news": "暂无新闻",
        "market_news_caption": "筛选 FMP 综合新闻中的半导体、AI、内存、DRAM、NAND、数据中心、Nvidia 和 Micron 相关内容。",
    },
    "Español": {
        "language": "Idioma", "dashboard_title": "Terminal de análisis bursátil", "dashboard_caption": "Panel comparativo | Infraestructura de IA y lista de seguimiento de crecimiento",
        "technical_analysis": "Análisis técnico", "options_gex": "Opciones y GEX", "value_investing": "Inversión en valor", "news_sentiment": "Noticias y sentimiento",
        "multi_agent_research": "Análisis multiagente", "data_diagnostics": "Diagnóstico de datos", "macro": "Macro", "source": "Fuente", "price": "Precio",
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
        "eps_surprise": "Sorpresa del BPA", "days_until_earnings": "Días hasta resultados", "multi_agent_caption": "Ejecute el flujo de cinco agentes para toda la lista. Cada acción recibe un veredicto independiente.",
        "run_multi_agent": "Ejecutar análisis multiagente", "running_agents": "Ejecutando agentes de análisis para", "final_verdict": "Veredicto final", "agent_detail": "Detalle de agentes",
        "fundamental_analysis": "Análisis fundamental", "options_analysis": "Análisis de opciones", "data_unavailable": "datos no disponibles", "data_source": "Fuente de datos",
        "revenue_growth_yoy": "Crecimiento interanual de ingresos", "last_updated": "Última actualización", "diagnostic_note": "Nota de diagnóstico", "macro_caption": "Panel macro dinámico para los próximos 30 días, con prioridad para FMP. Los respaldos usan yfinance.",
        "refresh_macro": "Actualizar datos macro", "calendar_window": "Ventana del calendario", "macro_risk_score": "Puntuación de riesgo macro", "treasury_source": "Fuente de bonos del Tesoro",
        "dynamic_macro_calendar": "Calendario macro dinámico de 30 días", "show_all_macro_events": "Mostrar todos los eventos macro", "no_highlighted_macro_events": "No hay eventos macro destacados en los próximos 30 días.",
        "economic_calendar_unavailable": "Calendario económico no disponible.", "historical_data_unavailable": "datos históricos no disponibles", "cpi_index": "Índice IPC", "us_10y_treasury_yield": "Rendimiento del Tesoro de EE. UU. a 10 años",
        "brent_crude_oil": "Petróleo Brent", "unemployment": "Desempleo", "gdp_growth_yoy": "Crecimiento interanual del PIB", "no_watchlist_news": "No hay noticias disponibles", "no_market_news": "No hay noticias disponibles",
        "market_news_caption": "Noticias generales de FMP filtradas por semiconductores, IA, memoria, DRAM, NAND, centros de datos, Nvidia y Micron.",
    },
}


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


@st.cache_data(ttl=900)
def get_company_snapshot(ticker):
    return {**get_fmp_company_snapshot(ticker), "role": SUPPLY_CHAIN_ROLES[ticker]}


@st.cache_data(ttl=900)
def get_technical_data(ticker, period="6mo"):
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


@st.cache_data(ttl=900)
def get_options_data(ticker):
    stock = yf.Ticker(ticker)
    history = stock.history(period="1d")
    expirations = stock.options
    if history.empty or not expirations:
        raise ValueError("No options data returned.")
    current_price = float(history["Close"].iloc[-1])
    exp_date = expirations[0]
    chain = stock.option_chain(exp_date)
    calls = chain.calls.fillna(0)
    puts = chain.puts.fillna(0)
    total_call_oi = float(calls["openInterest"].sum())
    total_put_oi = float(puts["openInterest"].sum())
    calls_above = calls[calls["strike"] > current_price]
    puts_below = puts[puts["strike"] < current_price]
    call_wall = calls_above.loc[calls_above["openInterest"].idxmax(), "strike"] if not calls_above.empty else None
    put_wall = puts_below.loc[puts_below["openInterest"].idxmax(), "strike"] if not puts_below.empty else None
    strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
    pain = {}
    for strike in strikes:
        call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
        put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
        pain[strike] = call_loss + put_loss
    total_gex = {}
    for expiration in expirations[:2]:
        try:
            exp_chain = stock.option_chain(expiration)
            time_to_expiry = max((datetime.strptime(expiration, "%Y-%m-%d") - datetime.now()).days / 365, 0.001)
            for option_type, direction in ((exp_chain.calls, 1), (exp_chain.puts, -1)):
                for _, row in option_type.fillna(0).iterrows():
                    strike, volatility, oi = row["strike"], row["impliedVolatility"], row["openInterest"]
                    if volatility > 0 and oi > 0:
                        gamma = black_scholes_gamma(current_price, strike, time_to_expiry, 0.05, volatility)
                        total_gex[strike] = total_gex.get(strike, 0) + direction * gamma * oi * 100 * current_price
        except Exception:
            continue
    return {
        "current_price": current_price,
        "exp_date": exp_date,
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
    }


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
    filtered = options[
        (options["strike"] >= current_price * (1 - price_range))
        & (options["strike"] <= current_price * (1 + price_range))
    ]
    return filtered if not filtered.empty else options


def render_option_chain_chart(ticker, option_type, options, current_price, exp_date, color):
    filtered = filter_options_near_price(options, current_price)
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
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_{option_type.lower()}_options")


def render_gex_chart(ticker, gex_by_strike, current_price):
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
    st.plotly_chart(fig, use_container_width=True, key=f"{ticker}_gex")


def render_technical_section():
    st.caption(t("technical_caption"))
    for ticker in WATCHLIST:
        with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]}", expanded=ticker == "NVDA"):
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
    for ticker in WATCHLIST:
        with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]} Gamma Exposure", expanded=ticker == "NVDA"):
            try:
                opt = get_options_data(ticker)
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
                st.info(f"{t('gamma_squeeze_risk')}: {squeeze}. {regime} {t('nearest_expiration')}: {opt['exp_date']}.")
                chart_columns = st.columns(2)
                with chart_columns[0]:
                    render_option_chain_chart(ticker, "Call", opt["calls"], opt["current_price"], opt["exp_date"], "#22c55e")
                with chart_columns[1]:
                    render_option_chain_chart(ticker, "Put", opt["puts"], opt["current_price"], opt["exp_date"], "#ef4444")
                render_gex_chart(ticker, opt["gex_by_strike"], opt["current_price"])
            except Exception as exc:
                st.warning(f"{ticker} {t('options_unavailable')}: {exc}")


def render_value_section(snapshots):
    st.caption(t("value_caption"))
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker)
        with st.expander(f"{ticker} | {snapshot['name'] if snapshot else COMPANY_NAMES[ticker]}", expanded=ticker == "NVDA"):
            st.markdown(f"**{ticker} | {COMPANY_NAMES[ticker]}**")
            st.caption(SUPPLY_CHAIN_ROLES[ticker])
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


@st.cache_data(ttl=3600)
def get_cached_company_news(ticker, limit=5):
    return fetch_company_news(ticker, limit)


@st.cache_data(ttl=1800)
def get_cached_watchlist_news(tickers, limit_per_ticker=20):
    return [
        item
        for ticker in tickers
        for item in fetch_company_news(ticker, limit_per_ticker)
    ]


@st.cache_data(ttl=1800)
def get_cached_market_news(limit=150):
    return fetch_general_news(limit)


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
    return item.get("published_date") or ""


def news_sentiment_label(sentiment):
    return t(sentiment.lower()) if sentiment in ("Positive", "Neutral", "Negative") else sentiment


NEWS_SUMMARY_LABELS = {
    "English": "AI Summary",
    "\u4e2d\u6587": "AI \u603b\u7ed3",
    "Espa\u00f1ol": "Resumen de IA",
}
AI_SUMMARY_VERSION = "v2"
NEWS_SUMMARY_LANGUAGE_NAMES = {
    "English": "English",
    "\u4e2d\u6587": "Chinese",
    "Espa\u00f1ol": "Spanish",
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
    return language if language in NEWS_SUMMARY_LABELS else "English"


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
    prompt = (
        "Create a concise but detailed investment-focused article summary using only the supplied news metadata. "
        "Do not fetch or infer content from the article URL. Preserve company names, tickers, source names, "
        f"and other proper nouns exactly as supplied. Write the values in {NEWS_SUMMARY_LANGUAGE_NAMES[language]}. "
        "Return JSON only with keys news_overview, why_it_matters, potential_stock_impact, positive_factors, "
        "risk_factors, what_to_watch_next, ai_view, confidence. news_overview must be 2-3 sentences. "
        "positive_factors, risk_factors, and what_to_watch_next must each be arrays with 2-3 concise items. "
        "potential_stock_impact must state whether the article is Bullish, Neutral, or Bearish for the related stock and explain why. "
        "ai_view must be Bullish, Neutral, or Bearish. confidence must be Low, Medium, or High. "
        "Keep the full response around 120-180 English words, 180-260 Chinese characters, or 130-190 Spanish words. "
        "Translate the section values naturally for the requested language, including the view and confidence labels, "
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
                st.markdown(f"**{labels[field]}:** {summary[field]}")
            for field in ("positive_factors", "risk_factors", "what_to_watch_next"):
                st.markdown(f"**{labels[field]}:**")
                for value in summary[field]:
                    st.markdown(f"- {value}")
            for field in ("ai_view", "confidence"):
                st.markdown(f"**{labels[field]}:** {summary[field]}")
            if st.button(refresh_label, key=f"refresh_news_summary_{summary_key}"):
                refresh_key = f"news_summary_refresh_{summary_key}"
                st.session_state[refresh_key] = st.session_state.get(refresh_key, 0) + 1
                st.rerun()
        except Exception as exc:
            st.warning(f"AI summary unavailable: {exc}")


def render_news_item(item):
    title = item.get("title") or t("untitled_article")
    url = item.get("url")
    st.markdown("#### " + title)
    publisher = item.get("publisher") or t("unknown_publisher")
    st.caption(
        f"{item.get('published_date') or t('date_unavailable')} | "
        f"{publisher} | {item.get('ticker') or t('market')} | "
        f"{item.get('source') or t('unknown_source')} | {news_sentiment_label(item['sentiment'])}"
    )
    if item.get("text"):
        st.write(item["text"])
    render_ai_news_summary(item)
    if url:
        st.link_button(t("open_article"), url)
    st.divider()


def render_news_section():
    st.caption(t("fmp_news_fallback"))
    try:
        stock_news = get_cached_watchlist_news(tuple(WATCHLIST))
    except Exception as exc:
        st.warning(f"{t('stock_news_unavailable')}: {exc}")
        stock_news = []

    prepared_news = [
        {**item, "sentiment": classify_news_sentiment(item)}
        for item in stock_news
        if item.get("title")
    ]
    filter_columns = st.columns(4)
    ticker_filter_label = filter_columns[0].selectbox(t("select_ticker"), [t("all"), *WATCHLIST], key="news_ticker")
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


def fetch_news_headlines(ticker, limit=5):
    fmp_news = get_cached_company_news(ticker, limit)
    if fmp_news:
        return [item["title"] for item in fmp_news if item.get("title")]
    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    return [entry.title for entry in feed.entries[:limit]]


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
    price = float(latest["Close"])
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
        "max_pain": opt["max_pain"],
        "net_gex": opt["net_gex"],
        "call_wall": opt["call_wall"],
        "put_wall": opt["put_wall"],
    }


def build_ai_summary_payload(snapshots, macro_snapshot=None):
    stocks = []
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker) or {}
        stock_data = {
            "ticker": ticker,
            "company_name": COMPANY_NAMES[ticker],
            "supply_chain_role": SUPPLY_CHAIN_ROLES[ticker],
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
- Explain how macro affects NVDA, MU, SNDK, LITE, and RKLB based on their supplied roles and metrics.
- Treat NVDA as an AI growth stock with rate-sensitive valuation; MU and SNDK as memory/storage-cycle names sensitive to global demand and USD; LITE as optical AI-infrastructure exposure sensitive to capex; and RKLB as a high-duration growth stock sensitive to rates and risk appetite.
"""


def render_daily_report(snapshots):
    st.caption(t("daily_report_caption"))
    if st.button(t("generate_daily_report"), key="daily_report"):
        st.subheader(f"{t('daily_watchlist_report')} | {datetime.now():%Y-%m-%d}")
        render_overview_cards(snapshots)
        st.markdown(f"#### {t('technical_snapshot')}")
        rows = []
        for ticker in WATCHLIST:
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
        for ticker in WATCHLIST:
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
        for ticker in WATCHLIST:
            snapshot = snapshots.get(ticker)
            valuation_rows.append({
                t("ticker"): ticker, t("company"): COMPANY_NAMES[ticker], t("supply_chain_role"): SUPPLY_CHAIN_ROLES[ticker],
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
        for ticker in WATCHLIST:
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
            for ticker in WATCHLIST:
                try:
                    sentiment_rows.append({t("ticker"): ticker, **fetch_news_sentiment(ticker, client)})
                except Exception as exc:
                    sentiment_rows.append({t("ticker"): ticker, "sentiment": "N/A", "score": 0, "summary": str(exc)})
            st.dataframe(pd.DataFrame(sentiment_rows), use_container_width=True, hide_index=True)
            summary_payload = build_ai_summary_payload(snapshots, summarize_macro_snapshot(build_macro_snapshot()))
            prompt = build_ai_summary_prompt(summary_payload)
            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
            st.markdown(f"#### {t('ai_summary')}")
            st.write(response.choices[0].message.content)
        except Exception as exc:
            st.warning(f"{t('ai_summary_unavailable')}: {exc}")


def render_multi_agent_section():
    st.caption(t("multi_agent_caption"))
    if st.button(t("run_multi_agent"), key="multi_agent"):
        from multi_agent import agent_fundamental, agent_news, agent_options, agent_risk_manager, agent_technical
        for ticker in WATCHLIST:
            with st.expander(f"{ticker} | {COMPANY_NAMES[ticker]} Multi-Agent Research", expanded=ticker == "NVDA"):
                with st.spinner(f"{t('running_agents')} {ticker}..."):
                    technical = agent_technical(ticker)
                    fundamental = agent_fundamental(ticker)
                    options = agent_options(ticker)
                    news = agent_news(ticker)
                    verdict = agent_risk_manager(ticker, technical, fundamental, options, news)
                st.markdown(f"##### {t('final_verdict')}")
                st.info(verdict)
                with st.expander(t("agent_detail")):
                    st.markdown(f"**{t('technical_analysis')}**")
                    st.write(technical)
                    st.markdown(f"**{t('fundamental_analysis')}**")
                    st.write(fundamental)
                    st.markdown(f"**{t('options_analysis')}**")
                    st.write(options)
                    st.markdown(f"**{t('news_sentiment')}**")
                    st.write(news)


def render_overview_cards(snapshots):
    columns = st.columns(len(WATCHLIST))
    for column, ticker in zip(columns, WATCHLIST):
        snapshot = snapshots.get(ticker)
        if snapshot:
            render_snapshot_card(column, snapshot)
        else:
            column.warning(f"{ticker} {t('data_unavailable')}")


def render_diagnostics(snapshots):
    rows = []
    for ticker in WATCHLIST:
        snapshot = snapshots.get(ticker) or {}
        rows.append({
            t("ticker"): ticker, t("company"): snapshot.get("name") or COMPANY_NAMES[ticker],
            t("data_source"): snapshot.get("source") or "unavailable", t("revenue"): format_money(snapshot.get("revenue")),
            t("net_margin"): format_percent(snapshot.get("net_margin")),
            "P/E": format_ratio(snapshot.get("trailing_pe")),
            "P/B": format_ratio(snapshot.get("price_to_book")),
            t("revenue_growth_yoy"): format_percent(snapshot.get("revenue_growth_yoy")),
            t("analyst_target"): format_money(snapshot.get("analyst_target"), 2), t("next_earnings_date"): snapshot.get("next_earnings_date") or "N/A",
            t("last_updated"): snapshot.get("last_updated") or "N/A", t("diagnostic_note"): snapshot.get("diagnostic_note") or "N/A",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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


def render_macro_chart(title, history):
    if history is None or history.empty:
        st.caption(f"{title}: {t('historical_data_unavailable')}")
        return
    chart = history[["date", "value"]].dropna().set_index("date")
    values = pd.to_numeric(chart["value"], errors="coerce").dropna()
    if values.empty:
        st.caption(f"{title}: {t('historical_data_unavailable')}")
        return
    minimum = float(values.min())
    maximum = float(values.max())
    padding = (maximum - minimum) * 0.1 or max(abs(maximum) * 0.05, 0.01)
    figure = go.Figure(go.Scatter(x=chart.index, y=chart["value"], mode="lines"))
    figure.update_layout(
        height=220, margin={"l": 8, "r": 8, "t": 8, "b": 8},
        template="plotly_dark", showlegend=False,
        yaxis={"range": [minimum - padding, maximum + padding]},
    )
    st.plotly_chart(figure, use_container_width=True, key=f"macro_{title}")
    st.caption(title)


def render_macro_section():
    st.caption(t("macro_caption"))
    if st.button(t("refresh_macro"), key="refresh_macro"):
        fetch_treasury_rates.clear()
        fetch_market_series.clear()
        fetch_indicator.clear()
        fetch_macro_calendar.clear()
        st.rerun()
    macro = build_macro_snapshot()
    rates = macro["rates"]
    markets = macro["markets"]
    indicators = macro["indicators"]
    st.caption(f"{t('last_updated')}: {macro['last_updated']} | {t('calendar_window')}: {macro['calendar']['start_date']} to {macro['calendar']['end_date']}")
    render_metric_row([
        (t("macro_risk_score"), f"{macro['macro_risk_score']}/10"),
        ("US 2Y", "N/A" if rates["year2"] is None else f"{rates['year2']:.2f}%"),
        ("US 10Y", "N/A" if rates["year10"] is None else f"{rates['year10']:.2f}%"),
        ("US 30Y", "N/A" if rates["year30"] is None else f"{rates['year30']:.2f}%"),
        ("10Y - 2Y", "N/A" if rates["spread_10y_2y"] is None else f"{rates['spread_10y_2y']:+.2f}%"),
        ("10Y - 3M", "N/A" if rates["spread_10y_3m"] is None else f"{rates['spread_10y_3m']:+.2f}%"),
    ])
    st.caption(f"{t('treasury_source')}: {rates['source']}")
    render_metric_row([(label, format_ratio(markets[label]["value"])) for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY")])
    st.caption(" | ".join(f"{label}: {markets[label]['source']}" for label in ("EUR/USD", "USD/CNY", "USD/JPY", "DXY")))
    render_metric_row([
        ("CPI YoY", "N/A" if macro["cpi_yoy"] is None else f"{macro['cpi_yoy']:.2f}%"),
        ("Core CPI YoY", "N/A"),
        ("PCE / Core PCE", "N/A"),
        (t("unemployment"), "N/A" if indicators["unemploymentRate"]["value"] is None else f"{indicators['unemploymentRate']['value']:.2f}%"),
        (t("gdp_growth_yoy"), "N/A" if macro["gdp_growth_yoy"] is None else f"{macro['gdp_growth_yoy']:.2f}%"),
    ])
    render_metric_row([(label, format_money(markets[label]["value"], 2)) for label in ("Brent crude oil", "WTI crude oil", "Gold", "Copper")])
    st.caption(" | ".join(f"{label}: {markets[label]['source']}" for label in ("Brent crude oil", "WTI crude oil", "Gold", "Copper")))
    chart_columns = st.columns(4)
    with chart_columns[0]:
        treasury_history = rates["history"]
        render_macro_chart(t("us_10y_treasury_yield"), treasury_history.rename(columns={"year10": "value"})[["date", "value"]].dropna() if "year10" in treasury_history else pd.DataFrame())
    with chart_columns[1]:
        render_macro_chart("EUR/USD", markets["EUR/USD"]["history"])
    with chart_columns[2]:
        render_macro_chart(t("brent_crude_oil"), markets["Brent crude oil"]["history"])
    with chart_columns[3]:
        render_macro_chart(t("cpi_index"), indicators["CPI"]["history"])
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


def mt(key):
    language = st.session_state.get("language", "English")
    return MU_TEXT.get(language, MU_TEXT["English"]).get(key, MU_TEXT["English"].get(key, key))


def ml(key):
    language = st.session_state.get("language", "English")
    return MU_TERM_TEXT.get(language, MU_TERM_TEXT["English"]).get(key, MU_TERM_TEXT["English"].get(key, key))


def mr(key):
    language = st.session_state.get("language", "English")
    return MU_RESULT_TEXT.get(language, MU_RESULT_TEXT["English"]).get(key, key)


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
        return
    if abs(metrics["weight_total"] - 100.0) > 0.01:
        st.warning(mt("analyst_weight_warning").format(total=metrics["weight_total"]))
    if metrics["weighted_target"] is None:
        st.warning(mt("analyst_weight_error"))
        return

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

    render_mu_analyst_tracker(current_price, base_target)

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


st.set_page_config(page_title="Equity Research Terminal", layout="wide")
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
st.title(t("dashboard_title"))
st.caption(t("dashboard_caption"))

snapshots = {}
for symbol in WATCHLIST:
    try:
        snapshots[symbol] = get_company_snapshot(symbol)
    except Exception:
        snapshots[symbol] = None

render_overview_cards(snapshots)
st.divider()

tabs = st.tabs([
    t("technical_analysis"), t("options_gex"), t("value_investing"),
    t("news_sentiment"), t("multi_agent_research"), t("data_diagnostics"), t("macro"), mt("tab"),
])
with tabs[0]:
    render_technical_section()
with tabs[1]:
    render_options_section()
with tabs[2]:
    render_value_section(snapshots)
with tabs[3]:
    render_news_section()
with tabs[4]:
    render_multi_agent_section()
with tabs[5]:
    render_diagnostics(snapshots)
with tabs[6]:
    render_macro_section()
with tabs[7]:
    render_mu_valuation_model(snapshots)
