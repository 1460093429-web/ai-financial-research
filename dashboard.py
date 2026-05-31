# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta
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
    t("news_sentiment"), t("multi_agent_research"), t("data_diagnostics"), t("macro"),
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
