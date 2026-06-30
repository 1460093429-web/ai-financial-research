# -*- coding: utf-8 -*-
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import yfinance as yf

REQUIRED_TICKERS = ["SPY", "QQQ", "RSP", "VTV", "VUG", "VLUE", "MTUM", "QUAL", "USMV", "IWM", "SMH", "SOXX", "XLP", "XLV", "XLU"]

FACTOR_DEFINITIONS = [
    ("Value vs Growth", "VTV / VUG", "VTV", "VUG"),
    ("Value vs Long-duration Growth", "VLUE / QQQ", "VLUE", "QQQ"),
    ("Momentum", "MTUM / SPY", "MTUM", "SPY"),
    ("Quality", "QUAL / SPY", "QUAL", "SPY"),
    ("Low Vol / Defensive", "USMV / SPY", "USMV", "SPY"),
    ("Small Cap", "IWM / SPY", "IWM", "SPY"),
    ("Equal Weight / Breadth", "RSP / SPY", "RSP", "SPY"),
    ("Semiconductor strength", "SMH / SPY", "SMH", "SPY"),
    ("Semiconductor strength", "SOXX / SPY", "SOXX", "SPY"),
    ("Defensive Staples vs Growth", "XLP / QQQ", "XLP", "QQQ"),
    ("Utilities vs Growth", "XLU / QQQ", "XLU", "QQQ"),
]

FACTOR_COLUMNS = [
    "Factor",
    "Ratio",
    "Current",
    "Percentile_1Y",
    "Percentile_3Y",
    "Percentile_5Y",
    "ZScore_3Y",
    "Trend_20D",
    "Trend_60D",
    "Signal",
    "Numerator Top Holdings",
    "Denominator Top Holdings",
]

SUMMARY_FACTORS = {
    "summary_value": "VTV / VUG",
    "summary_momentum": "MTUM / SPY",
    "summary_defensive": "USMV / SPY",
    "summary_breadth": "RSP / SPY",
    "summary_semiconductor": "SMH / SPY",
}

FACTOR_TEXT = {
    "zh": {
        "ui": {
            "title": "因子监控 · Factor Watch",
            "caption": "基于 ETF 的风格因子代理监控，使用 yfinance adjusted close / close 数据。",
            "loading": "正在加载 Factor Watch 数据...",
            "download_error": "Factor Watch 数据下载失败：{error}",
            "empty_prices": "无法从 yfinance 获取 Factor Watch 数据，请稍后重试。",
            "empty_metrics": "已下载价格数据，但可用 ETF 不足，无法计算因子 ratio。",
            "missing_tickers": "以下 ETF 缺少价格数据，相关 ratio 已跳过：{tickers}",
            "ratio_select": "选择 Ratio",
            "chart_title": "{ratio} 历史走势",
            "chart_missing": "所选 ratio 的历史数据不足，无法绘制走势图。",
            "summary_title": "中文总结",
            "factor_explanations": "因子解释",
            "selected_explanation": "所选 ratio 的解释与交易含义",
            "no_data": "无数据",
            "date": "日期",
            "ratio": "Ratio",
            "factor": "因子",
            "current": "当前值",
            "percentile_1y": "1年分位",
            "percentile_3y": "3年分位",
            "percentile_5y": "5年分位",
            "zscore_3y": "3年Z分数",
            "trend_20d": "20日趋势",
            "trend_60d": "60日趋势",
            "signal": "信号",
            "explanation": "解释",
            "numerator_top_holdings": "分子ETF前5大持仓",
            "denominator_top_holdings": "分母ETF前5大持仓",
            "holdings_exposure": "成分股暴露",
            "numerator_etf": "分子 ETF",
            "denominator_etf": "分母 ETF",
            "top_5_holdings": "前 5 大持仓",
            "weight": "权重",
            "holdings_unavailable": "持仓数据暂不可用",
            "concentration_note": "这个 ratio 不只是风格因子，也代表两个 ETF 底层成分股暴露的相对表现。前 5 大持仓可以帮助判断该因子是否过度集中在少数股票。",
            "holdings_disclaimer": "ETF 持仓权重可能滞后，具体以基金公司官网披露为准。",
            "summary_value": "Value vs Growth",
            "summary_momentum": "Momentum",
            "summary_defensive": "Defensive / Low Vol",
            "summary_breadth": "Market Breadth",
            "summary_semiconductor": "Semiconductor",
        },
        "signals": {
            "Cheap": "便宜",
            "Strong": "偏强",
            "Overheated": "过热",
            "Neutral": "中性",
            "Defensive strengthening": "防御走强",
            "Momentum crowded": "动量拥挤",
        },
        "explanations": {
            "VTV / VUG": "价值股相对成长股。Ratio 上升通常表示价值股跑赢成长股，市场可能从高成长、高估值资产切向低估值资产；Ratio 下降说明成长股继续占优。",
            "VLUE / QQQ": "价值因子相对长久期成长股。QQQ 对利率和 AI/科技情绪更敏感。Ratio 上升说明市场可能降低对长久期科技成长的偏好。",
            "MTUM / SPY": "动量股相对大盘。Ratio 上升说明市场追逐强势股；如果处于高历史分位，可能代表动量拥挤，回撤时容易踩踏。",
            "QUAL / SPY": "高质量公司相对大盘。Ratio 上升说明市场偏好盈利稳定、资产负债表强、现金流质量高的公司。",
            "USMV / SPY": "低波动/防御股相对大盘。Ratio 上升通常表示市场风险偏好下降，资金开始偏向防御。",
            "IWM / SPY": "小盘股相对大盘。Ratio 上升说明市场宽度改善、风险偏好扩散；Ratio 下降说明上涨可能集中在大盘龙头。",
            "RSP / SPY": "等权标普相对市值加权标普。Ratio 上升说明更多股票参与上涨；Ratio 下降说明市场可能只靠少数巨头支撑。",
            "SMH / SPY": "半导体相对大盘。Ratio 上升说明半导体强于市场；如果同时处于高分位，可能说明 AI/芯片交易拥挤。",
            "SOXX / SPY": "半导体行业相对大盘，和 SMH/SPY 类似，用于交叉验证半导体强度。两个 ratio 同时走强，说明板块趋势更可靠。",
            "XLP / QQQ": "必需消费防御股相对纳指成长股。Ratio 上升通常代表市场从成长/科技切向防御。",
            "XLU / QQQ": "公用事业相对纳指成长股。Ratio 上升通常表示避险、防御和利率敏感资产开始相对走强。",
        },
        "summary": {
            "empty": "当前缺少因子数据，无法生成摘要。",
            "risk_on": "当前风险偏好与市场状态偏 Risk-on。",
            "risk_off": "当前风险偏好与市场状态偏 Risk-off / 谨慎。",
            "momentum_unknown": "动量数据不足，暂时无法判断是否拥挤。",
            "momentum_crowded": "动量处在高分位，存在拥挤交易风险。",
            "momentum_strong": "动量仍然占优，但尚未达到明显拥挤区间。",
            "momentum_weak": "动量优势不强，追逐高动量资产的胜率下降。",
            "semi_unknown": "半导体数据不足，暂时无法判断是否过热。",
            "semi_hot": "半导体相对强度偏热，需要留意回撤和估值消化。",
            "semi_ok": "半导体仍有相对强度，但过热信号不算极端。",
            "value_unknown": "价值因子数据不足，反转信号还不清晰。",
            "value_reversal": "价值因子开始改善，可能出现从成长向价值的局部反转。",
            "value_weak": "价值反转尚未确认，成长风格仍占相对优势。",
            "def_unknown": "防御因子数据不足。",
            "def_strong": "防御因子走强，说明资金对低波动和稳定现金流的需求上升。",
            "def_weak": "防御因子没有明显走强，市场仍愿意承担一定风险。",
            "breadth_unknown": "市场宽度数据不足。",
            "breadth_healthy": "市场宽度相对健康，上涨参与面尚可。",
            "breadth_weak": "市场宽度偏弱，上涨可能集中在少数权重股。",
            "risk_tip": "对高 beta 和半导体仓位，应关注高分位后的回撤风险，不宜只用趋势信号加仓。",
        },
    },
    "en": {
        "ui": {
            "title": "Factor Watch",
            "caption": "ETF-based factor proxy monitor using adjusted close / close data from yfinance.",
            "loading": "Loading Factor Watch data...",
            "download_error": "Factor Watch data download failed: {error}",
            "empty_prices": "Could not fetch Factor Watch data from yfinance. Please try again later.",
            "empty_metrics": "Price data was downloaded, but available ETFs were insufficient to compute factor ratios.",
            "missing_tickers": "The following ETFs are missing price data; related ratios were skipped: {tickers}",
            "ratio_select": "Select ratio",
            "chart_title": "{ratio} history",
            "chart_missing": "The selected ratio does not have enough history to plot.",
            "summary_title": "English summary",
            "factor_explanations": "Factor explanations",
            "selected_explanation": "Selected ratio explanation and trading implication",
            "no_data": "No data",
            "date": "Date",
            "ratio": "Ratio",
            "factor": "Factor",
            "current": "Current",
            "percentile_1y": "1Y percentile",
            "percentile_3y": "3Y percentile",
            "percentile_5y": "5Y percentile",
            "zscore_3y": "3Y z-score",
            "trend_20d": "20D trend",
            "trend_60d": "60D trend",
            "signal": "Signal",
            "explanation": "Explanation",
            "numerator_top_holdings": "Numerator ETF Top 5",
            "denominator_top_holdings": "Denominator ETF Top 5",
            "holdings_exposure": "Holdings exposure",
            "numerator_etf": "Numerator ETF",
            "denominator_etf": "Denominator ETF",
            "top_5_holdings": "Top 5 holdings",
            "weight": "Weight",
            "holdings_unavailable": "Holdings data unavailable",
            "concentration_note": "This ratio is not only a style proxy; it also reflects the relative performance of the underlying ETF holdings. Top holdings help identify concentration risk.",
            "holdings_disclaimer": "ETF holding weights may lag official fund disclosures.",
            "summary_value": "Value vs Growth",
            "summary_momentum": "Momentum",
            "summary_defensive": "Defensive / Low Vol",
            "summary_breadth": "Market Breadth",
            "summary_semiconductor": "Semiconductor",
        },
        "signals": {
            "Cheap": "Cheap",
            "Strong": "Strong",
            "Overheated": "Overheated",
            "Neutral": "Neutral",
            "Defensive strengthening": "Defensive strengthening",
            "Momentum crowded": "Momentum crowded",
        },
        "explanations": {
            "VTV / VUG": "Value stocks versus growth stocks. A rising ratio means value is outperforming growth; a falling ratio means growth remains dominant.",
            "VLUE / QQQ": "Value factor versus long-duration growth. QQQ is more sensitive to rates and tech/AI sentiment. A rising ratio suggests rotation away from long-duration growth.",
            "MTUM / SPY": "Momentum stocks versus the broad market. A rising ratio means winners keep winning; very high percentiles may indicate crowded momentum.",
            "QUAL / SPY": "Quality companies versus the broad market. A rising ratio indicates preference for profitable, stable, high-quality balance sheet companies.",
            "USMV / SPY": "Low-volatility defensive stocks versus the broad market. A rising ratio usually signals lower risk appetite and defensive rotation.",
            "IWM / SPY": "Small caps versus large caps. A rising ratio suggests improving breadth and broader risk appetite; a falling ratio suggests leadership concentrated in large caps.",
            "RSP / SPY": "Equal-weight S&P 500 versus cap-weighted S&P 500. A rising ratio means broader participation; a falling ratio means gains are concentrated in mega caps.",
            "SMH / SPY": "Semiconductors versus the broad market. A rising ratio means semis are outperforming; high percentiles may indicate crowded AI/chip exposure.",
            "SOXX / SPY": "Semiconductors versus the broad market, similar to SMH/SPY. It is used as cross-check for semiconductor strength.",
            "XLP / QQQ": "Consumer staples versus Nasdaq growth. A rising ratio usually indicates rotation from growth/tech into defensive assets.",
            "XLU / QQQ": "Utilities versus Nasdaq growth. A rising ratio often signals defensive rotation and stronger relative performance of rate-sensitive defensives.",
        },
        "summary": {
            "empty": "Factor data is currently unavailable, so no summary can be generated.",
            "risk_on": "The current market regime leans Risk-on.",
            "risk_off": "The current market regime leans Risk-off / cautious.",
            "momentum_unknown": "Momentum data is insufficient to judge crowding.",
            "momentum_crowded": "Momentum is at a high percentile, which points to crowding risk.",
            "momentum_strong": "Momentum remains strong, but it is not yet in an extreme crowding zone.",
            "momentum_weak": "Momentum leadership is not strong, reducing the odds of chasing high-momentum assets.",
            "semi_unknown": "Semiconductor data is insufficient to judge overheating.",
            "semi_hot": "Semiconductor relative strength looks overheated; watch for pullbacks and valuation digestion.",
            "semi_ok": "Semiconductors still show relative strength, but overheating signals are not extreme.",
            "value_unknown": "Value data is insufficient and the reversal signal is unclear.",
            "value_reversal": "Value is improving, suggesting a possible rotation from growth into value.",
            "value_weak": "A value reversal is not confirmed; growth still holds relative leadership.",
            "def_unknown": "Defensive factor data is insufficient.",
            "def_strong": "Defensive factors are strengthening, suggesting higher demand for low-volatility and stable cash-flow assets.",
            "def_weak": "Defensive factors are not clearly strengthening, so the market is still willing to take some risk.",
            "breadth_unknown": "Market breadth data is insufficient.",
            "breadth_healthy": "Market breadth looks relatively healthy, with acceptable participation.",
            "breadth_weak": "Market breadth is weak, so gains may be concentrated in a narrow set of large-cap leaders.",
            "risk_tip": "For high-beta and semiconductor exposure, watch drawdown risk after high-percentile moves rather than adding solely because trend is positive.",
        },
    },
    "es": {
        "ui": {
            "title": "Monitor de factores · Factor Watch",
            "caption": "Monitor de factores proxy basado en ETF, usando datos adjusted close / close de yfinance.",
            "loading": "Cargando datos de Factor Watch...",
            "download_error": "Error al descargar datos de Factor Watch: {error}",
            "empty_prices": "No se pudieron obtener datos de Factor Watch desde yfinance. Inténtelo más tarde.",
            "empty_metrics": "Se descargaron precios, pero los ETF disponibles no bastan para calcular los ratios.",
            "missing_tickers": "Faltan precios para estos ETF; los ratios relacionados se omitieron: {tickers}",
            "ratio_select": "Seleccionar ratio",
            "chart_title": "Histórico de {ratio}",
            "chart_missing": "El ratio seleccionado no tiene suficiente histórico para graficar.",
            "summary_title": "Resumen en español",
            "factor_explanations": "Explicación de factores",
            "selected_explanation": "Explicación e implicación operativa del ratio seleccionado",
            "no_data": "Sin datos",
            "date": "Fecha",
            "ratio": "Ratio",
            "factor": "Factor",
            "current": "Actual",
            "percentile_1y": "Percentil 1A",
            "percentile_3y": "Percentil 3A",
            "percentile_5y": "Percentil 5A",
            "zscore_3y": "Z-score 3A",
            "trend_20d": "Tendencia 20D",
            "trend_60d": "Tendencia 60D",
            "signal": "Señal",
            "explanation": "Explicación",
            "numerator_top_holdings": "Top 5 ETF numerador",
            "denominator_top_holdings": "Top 5 ETF denominador",
            "holdings_exposure": "Exposición por posiciones",
            "numerator_etf": "ETF numerador",
            "denominator_etf": "ETF denominador",
            "top_5_holdings": "Top 5 posiciones",
            "weight": "Peso",
            "holdings_unavailable": "Datos de posiciones no disponibles",
            "concentration_note": "Este ratio no es solo un proxy de estilo; también refleja el rendimiento relativo de las posiciones subyacentes de los ETF. Las principales posiciones ayudan a identificar riesgo de concentración.",
            "holdings_disclaimer": "Las ponderaciones de los ETF pueden tener retraso respecto a las publicaciones oficiales.",
            "summary_value": "Value vs Growth",
            "summary_momentum": "Momentum",
            "summary_defensive": "Defensivo / Baja volatilidad",
            "summary_breadth": "Amplitud de mercado",
            "summary_semiconductor": "Semiconductores",
        },
        "signals": {
            "Cheap": "Barato",
            "Strong": "Fuerte",
            "Overheated": "Sobrecalentado",
            "Neutral": "Neutral",
            "Defensive strengthening": "Defensivo fortaleciéndose",
            "Momentum crowded": "Momentum saturado",
        },
        "explanations": {
            "VTV / VUG": "Acciones value frente a acciones growth. Si el ratio sube, value está superando a growth; si baja, growth sigue dominando.",
            "VLUE / QQQ": "Factor value frente a growth de larga duración. QQQ es más sensible a tipos de interés y sentimiento tech/IA. Un ratio al alza sugiere rotación fuera de growth de larga duración.",
            "MTUM / SPY": "Acciones momentum frente al mercado amplio. Si sube, los ganadores siguen liderando; percentiles muy altos pueden indicar momentum saturado.",
            "QUAL / SPY": "Compañías de calidad frente al mercado amplio. Un ratio al alza indica preferencia por empresas rentables, estables y con balances sólidos.",
            "USMV / SPY": "Acciones defensivas de baja volatilidad frente al mercado. Un ratio al alza suele indicar menor apetito por riesgo y rotación defensiva.",
            "IWM / SPY": "Small caps frente a large caps. Un ratio al alza sugiere mejora de amplitud y mayor apetito por riesgo; a la baja indica liderazgo concentrado en grandes compañías.",
            "RSP / SPY": "S&P 500 equiponderado frente al ponderado por capitalización. Si sube, hay mayor participación; si baja, las subidas dependen de pocas mega caps.",
            "SMH / SPY": "Semiconductores frente al mercado amplio. Un ratio al alza indica liderazgo del sector; percentiles altos pueden señalar exposición IA/chips saturada.",
            "SOXX / SPY": "Semiconductores frente al mercado amplio, similar a SMH/SPY. Sirve como confirmación cruzada de la fuerza del sector.",
            "XLP / QQQ": "Consumo básico defensivo frente a growth Nasdaq. Un ratio al alza suele indicar rotación desde growth/tech hacia activos defensivos.",
            "XLU / QQQ": "Utilities frente a growth Nasdaq. Un ratio al alza suele señalar rotación defensiva y mejor comportamiento relativo de sectores sensibles a tipos.",
        },
        "summary": {
            "empty": "No hay datos suficientes de factores, por lo que no se puede generar un resumen.",
            "risk_on": "El régimen actual del mercado se inclina a Risk-on.",
            "risk_off": "El régimen actual del mercado se inclina a Risk-off / cautela.",
            "momentum_unknown": "No hay datos suficientes para juzgar si el momentum está saturado.",
            "momentum_crowded": "Momentum está en percentiles altos, lo que apunta a riesgo de saturación.",
            "momentum_strong": "Momentum sigue fuerte, pero aún no está en una zona extrema de saturación.",
            "momentum_weak": "El liderazgo momentum no es fuerte, reduciendo el atractivo de perseguir activos de alto momentum.",
            "semi_unknown": "No hay datos suficientes para juzgar si semiconductores están sobrecalentados.",
            "semi_hot": "La fuerza relativa de semiconductores parece sobrecalentada; vigile retrocesos y digestión de valoración.",
            "semi_ok": "Semiconductores aún muestran fuerza relativa, pero las señales de sobrecalentamiento no son extremas.",
            "value_unknown": "Los datos value son insuficientes y la señal de reversión no está clara.",
            "value_reversal": "Value está mejorando, lo que sugiere posible rotación desde growth hacia value.",
            "value_weak": "La reversión hacia value no está confirmada; growth mantiene liderazgo relativo.",
            "def_unknown": "Los datos defensivos son insuficientes.",
            "def_strong": "Los factores defensivos se fortalecen, señalando mayor demanda por baja volatilidad y flujos de caja estables.",
            "def_weak": "Los factores defensivos no se fortalecen claramente, por lo que el mercado aún acepta cierto riesgo.",
            "breadth_unknown": "Los datos de amplitud de mercado son insuficientes.",
            "breadth_healthy": "La amplitud de mercado parece relativamente sana, con participación aceptable.",
            "breadth_weak": "La amplitud de mercado es débil, por lo que las subidas pueden concentrarse en pocos líderes de gran capitalización.",
            "risk_tip": "Para exposición high beta y semiconductores, vigile el riesgo de drawdown tras movimientos en percentiles altos en vez de añadir solo porque la tendencia es positiva.",
        },
    },
}


STATIC_ETF_HOLDINGS = {
    "SPY": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 7.3},
        {"Ticker": "MSFT", "Name": "Microsoft Corp.", "Weight": 6.8},
        {"Ticker": "AAPL", "Name": "Apple Inc.", "Weight": 5.9},
        {"Ticker": "AMZN", "Name": "Amazon.com Inc.", "Weight": 3.8},
        {"Ticker": "META", "Name": "Meta Platforms Inc.", "Weight": 2.8},
    ],
    "QQQ": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 8.8},
        {"Ticker": "MSFT", "Name": "Microsoft Corp.", "Weight": 8.1},
        {"Ticker": "AAPL", "Name": "Apple Inc.", "Weight": 7.5},
        {"Ticker": "AMZN", "Name": "Amazon.com Inc.", "Weight": 5.4},
        {"Ticker": "AVGO", "Name": "Broadcom Inc.", "Weight": 4.7},
    ],
    "RSP": [
        {"Ticker": "GEV", "Name": "GE Vernova Inc.", "Weight": 0.4},
        {"Ticker": "NRG", "Name": "NRG Energy Inc.", "Weight": 0.3},
        {"Ticker": "PLTR", "Name": "Palantir Technologies Inc.", "Weight": 0.3},
        {"Ticker": "VST", "Name": "Vistra Corp.", "Weight": 0.3},
        {"Ticker": "CEG", "Name": "Constellation Energy Corp.", "Weight": 0.3},
    ],
    "VTV": [
        {"Ticker": "BRK.B", "Name": "Berkshire Hathaway Inc.", "Weight": 3.5},
        {"Ticker": "JPM", "Name": "JPMorgan Chase & Co.", "Weight": 3.0},
        {"Ticker": "XOM", "Name": "Exxon Mobil Corp.", "Weight": 2.5},
        {"Ticker": "JNJ", "Name": "Johnson & Johnson", "Weight": 2.2},
        {"Ticker": "PG", "Name": "Procter & Gamble Co.", "Weight": 2.0},
    ],
    "VUG": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 11.0},
        {"Ticker": "MSFT", "Name": "Microsoft Corp.", "Weight": 10.2},
        {"Ticker": "AAPL", "Name": "Apple Inc.", "Weight": 9.4},
        {"Ticker": "AMZN", "Name": "Amazon.com Inc.", "Weight": 6.0},
        {"Ticker": "META", "Name": "Meta Platforms Inc.", "Weight": 4.2},
    ],
    "VLUE": [
        {"Ticker": "INTC", "Name": "Intel Corp.", "Weight": 5.5},
        {"Ticker": "T", "Name": "AT&T Inc.", "Weight": 4.4},
        {"Ticker": "GM", "Name": "General Motors Co.", "Weight": 4.1},
        {"Ticker": "F", "Name": "Ford Motor Co.", "Weight": 3.8},
        {"Ticker": "VZ", "Name": "Verizon Communications Inc.", "Weight": 3.6},
    ],
    "MTUM": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 6.6},
        {"Ticker": "AVGO", "Name": "Broadcom Inc.", "Weight": 5.5},
        {"Ticker": "META", "Name": "Meta Platforms Inc.", "Weight": 4.7},
        {"Ticker": "NFLX", "Name": "Netflix Inc.", "Weight": 4.0},
        {"Ticker": "COST", "Name": "Costco Wholesale Corp.", "Weight": 3.5},
    ],
    "QUAL": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 6.8},
        {"Ticker": "MSFT", "Name": "Microsoft Corp.", "Weight": 5.8},
        {"Ticker": "AAPL", "Name": "Apple Inc.", "Weight": 4.9},
        {"Ticker": "V", "Name": "Visa Inc.", "Weight": 3.1},
        {"Ticker": "MA", "Name": "Mastercard Inc.", "Weight": 2.8},
    ],
    "USMV": [
        {"Ticker": "MCD", "Name": "McDonald's Corp.", "Weight": 1.8},
        {"Ticker": "PEP", "Name": "PepsiCo Inc.", "Weight": 1.7},
        {"Ticker": "PG", "Name": "Procter & Gamble Co.", "Weight": 1.7},
        {"Ticker": "JNJ", "Name": "Johnson & Johnson", "Weight": 1.6},
        {"Ticker": "WMT", "Name": "Walmart Inc.", "Weight": 1.6},
    ],
    "IWM": [
        {"Ticker": "FTAI", "Name": "FTAI Aviation Ltd.", "Weight": 0.6},
        {"Ticker": "INSM", "Name": "Insmed Inc.", "Weight": 0.5},
        {"Ticker": "SFM", "Name": "Sprouts Farmers Market Inc.", "Weight": 0.5},
        {"Ticker": "CRS", "Name": "Carpenter Technology Corp.", "Weight": 0.4},
        {"Ticker": "AIT", "Name": "Applied Industrial Technologies Inc.", "Weight": 0.4},
    ],
    "SMH": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 20.0},
        {"Ticker": "TSM", "Name": "Taiwan Semiconductor Manufacturing Co.", "Weight": 13.0},
        {"Ticker": "AVGO", "Name": "Broadcom Inc.", "Weight": 8.0},
        {"Ticker": "ASML", "Name": "ASML Holding NV", "Weight": 5.5},
        {"Ticker": "AMD", "Name": "Advanced Micro Devices Inc.", "Weight": 5.0},
    ],
    "SOXX": [
        {"Ticker": "NVDA", "Name": "NVIDIA Corp.", "Weight": 10.0},
        {"Ticker": "AVGO", "Name": "Broadcom Inc.", "Weight": 8.5},
        {"Ticker": "AMD", "Name": "Advanced Micro Devices Inc.", "Weight": 7.0},
        {"Ticker": "QCOM", "Name": "Qualcomm Inc.", "Weight": 6.5},
        {"Ticker": "TXN", "Name": "Texas Instruments Inc.", "Weight": 6.0},
    ],
    "XLP": [
        {"Ticker": "COST", "Name": "Costco Wholesale Corp.", "Weight": 11.0},
        {"Ticker": "WMT", "Name": "Walmart Inc.", "Weight": 10.0},
        {"Ticker": "PG", "Name": "Procter & Gamble Co.", "Weight": 9.5},
        {"Ticker": "KO", "Name": "Coca-Cola Co.", "Weight": 8.0},
        {"Ticker": "PEP", "Name": "PepsiCo Inc.", "Weight": 5.0},
    ],
    "XLV": [
        {"Ticker": "LLY", "Name": "Eli Lilly and Co.", "Weight": 12.0},
        {"Ticker": "UNH", "Name": "UnitedHealth Group Inc.", "Weight": 8.0},
        {"Ticker": "JNJ", "Name": "Johnson & Johnson", "Weight": 6.5},
        {"Ticker": "ABBV", "Name": "AbbVie Inc.", "Weight": 5.5},
        {"Ticker": "MRK", "Name": "Merck & Co. Inc.", "Weight": 5.0},
    ],
    "XLU": [
        {"Ticker": "NEE", "Name": "NextEra Energy Inc.", "Weight": 13.0},
        {"Ticker": "SO", "Name": "Southern Co.", "Weight": 8.0},
        {"Ticker": "DUK", "Name": "Duke Energy Corp.", "Weight": 7.5},
        {"Ticker": "CEG", "Name": "Constellation Energy Corp.", "Weight": 6.0},
        {"Ticker": "SRE", "Name": "Sempra", "Weight": 5.0},
    ],
}


def _empty_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FACTOR_COLUMNS)


def normalize_factor_language(language=None) -> str:
    text = str(language or "").strip()
    lowered = text.lower()
    if text == "中文" or lowered in ("zh", "cn", "chinese"):
        return "zh"
    if text == "Español" or lowered in ("es", "spanish", "español") or text.startswith("Espa"):
        return "es"
    return "en"


def factor_ui_text(lang, key) -> str:
    language = normalize_factor_language(lang)
    return FACTOR_TEXT[language]["ui"].get(key, FACTOR_TEXT["en"]["ui"].get(key, key))


def get_factor_explanation(ratio_label: str, lang="zh") -> str:
    language = normalize_factor_language(lang)
    return FACTOR_TEXT[language]["explanations"].get(ratio_label, "")


def get_factor_short_explanation(ratio_label: str, lang="zh") -> str:
    explanation = get_factor_explanation(ratio_label, lang)
    if not explanation:
        return ""
    separators = ["。", ". ", "; ", "；"]
    end_positions = [explanation.find(separator) for separator in separators if explanation.find(separator) > 0]
    if end_positions:
        end = min(end_positions)
        return explanation[: end + 1].strip()
    return explanation[:120].strip()


def translate_factor_signal(signal: str, lang="zh") -> str:
    language = normalize_factor_language(lang)
    return FACTOR_TEXT[language]["signals"].get(signal, signal)


def _normalize_holding_item(ticker, name, weight):
    symbol = str(ticker or "").strip().upper()
    company_name = str(name or symbol).strip()
    try:
        numeric_weight = float(weight)
    except (TypeError, ValueError):
        numeric_weight = float("nan")
    if not pd.isna(numeric_weight) and numeric_weight <= 1:
        numeric_weight *= 100
    if not symbol:
        return None
    return {"Ticker": symbol, "Name": company_name, "Weight": round(numeric_weight, 2) if not pd.isna(numeric_weight) else float("nan")}


def _extract_yfinance_holdings(raw_holdings, top_n):
    if raw_holdings is None:
        return []
    if isinstance(raw_holdings, pd.DataFrame):
        frame = raw_holdings.copy()
        if frame.empty:
            return []
        ticker_column = next((column for column in frame.columns if str(column).lower() in ("ticker", "symbol")), None)
        name_column = next((column for column in frame.columns if str(column).lower() in ("name", "holding name", "company")), None)
        weight_column = next(
            (
                column
                for column in frame.columns
                if str(column).lower() in ("weight", "holding percent", "holdingpercent", "percent", "pct")
            ),
            None,
        )
        if ticker_column is None:
            frame = frame.reset_index().rename(columns={"index": "Ticker"})
            ticker_column = "Ticker"
        if weight_column is None:
            weight_column = next((column for column in frame.columns if "weight" in str(column).lower() or "percent" in str(column).lower()), None)
        holdings = []
        for _, row in frame.head(top_n).iterrows():
            item = _normalize_holding_item(
                row.get(ticker_column),
                row.get(name_column) if name_column else row.get(ticker_column),
                row.get(weight_column) if weight_column else float("nan"),
            )
            if item:
                holdings.append(item)
        return holdings[:top_n]
    if isinstance(raw_holdings, list):
        holdings = []
        for item in raw_holdings[:top_n]:
            if not isinstance(item, dict):
                continue
            holding = _normalize_holding_item(
                item.get("Ticker") or item.get("ticker") or item.get("symbol"),
                item.get("Name") or item.get("name") or item.get("holdingName"),
                item.get("Weight") or item.get("weight") or item.get("holdingPercent"),
            )
            if holding:
                holdings.append(holding)
        return holdings
    return []


def _fetch_yfinance_top_holdings(etf: str, top_n: int):
    try:
        ticker = yf.Ticker(etf)
        funds_data = getattr(ticker, "funds_data", None)
        raw_holdings = getattr(funds_data, "top_holdings", None) if funds_data is not None else None
        return _extract_yfinance_holdings(raw_holdings, top_n)
    except Exception:
        return []


@lru_cache(maxsize=64)
def get_etf_top_holdings(etf: str, top_n: int = 5) -> list[dict]:
    symbol = str(etf or "").strip().upper()
    if not symbol or top_n <= 0:
        return []

    live_holdings = _fetch_yfinance_top_holdings(symbol, top_n)
    if live_holdings:
        return live_holdings[:top_n]

    fallback = STATIC_ETF_HOLDINGS.get(symbol, [])
    return [dict(item) for item in fallback[:top_n]]


def format_holdings(holdings, lang="zh") -> str:
    language = normalize_factor_language(lang)
    unavailable = FACTOR_TEXT[language]["ui"]["holdings_unavailable"]
    if not holdings:
        return unavailable
    formatted = []
    for holding in holdings:
        ticker = holding.get("Ticker", "")
        weight = holding.get("Weight")
        if pd.isna(weight):
            formatted.append(str(ticker))
        else:
            formatted.append(f"{ticker} {float(weight):.1f}%")
    return ", ".join(formatted) if formatted else unavailable


def _ratio_etfs(ratio_label: str):
    for _, label, ticker_a, ticker_b in FACTOR_DEFINITIONS:
        if label == ratio_label:
            return ticker_a, ticker_b
    return "", ""


def _extract_close_prices(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data, pd.Series):
        return data.to_frame(name=data.name or REQUIRED_TICKERS[0])
    if not isinstance(data.columns, pd.MultiIndex):
        return data

    level_0_values = set(data.columns.get_level_values(0))
    level_1_values = set(data.columns.get_level_values(1))
    for field in ("Adj Close", "Close"):
        if field in level_0_values:
            return data.xs(field, axis=1, level=0)
        if field in level_1_values:
            return data.xs(field, axis=1, level=1)
    return pd.DataFrame()


def fetch_factor_price_data(start_date=None, end_date=None) -> pd.DataFrame:
    if start_date is None:
        start_date = date.today() - timedelta(days=5 * 365)
    if end_date is None:
        end_date = date.today()
    try:
        data = yf.download(
            REQUIRED_TICKERS,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception:
        return pd.DataFrame()
    if data.empty:
        return pd.DataFrame()
    data = _extract_close_prices(data)
    if data.empty:
        return pd.DataFrame()
    data = data.copy()
    data.index = pd.to_datetime(data.index)
    return data.dropna(how="all")


def _safe_ratio(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    return series_a.div(series_b.replace(0, pd.NA)).replace([np.inf, -np.inf], pd.NA)


def _percentile(series: pd.Series) -> float:
    values = series.dropna()
    if values.empty:
        return float("nan")
    if len(values) == 1:
        return 50.0
    return float((values.rank(pct=True).iloc[-1]) * 100)


def _zscore(series: pd.Series) -> float:
    values = series.dropna()
    if values.empty or len(values) < 2:
        return float("nan")
    return float((series.iloc[-1] - values.mean()) / values.std())


def _trend(series: pd.Series, window: int) -> float:
    values = series.dropna()
    if len(values) < window:
        return float("nan")
    return float(values.iloc[-1] / values.iloc[-window] - 1)


def _signal_from_metrics(factor_name: str, zscore: float, percentile_3y: float, trend_20d: float, trend_60d: float) -> str:
    if pd.isna(zscore) or pd.isna(percentile_3y):
        return "Neutral"
    if factor_name == "Momentum" and percentile_3y >= 85 and trend_20d > 0:
        return "Momentum crowded"
    if factor_name == "Low Vol / Defensive" and trend_20d > 0 and trend_60d > 0:
        return "Defensive strengthening"
    if factor_name in ("Defensive Staples vs Growth", "Utilities vs Growth") and trend_20d > 0 and percentile_3y >= 60:
        return "Defensive strengthening"
    if factor_name == "Semiconductor strength" and (percentile_3y >= 85 or zscore >= 1.5):
        return "Overheated"
    if factor_name.startswith("Value") and percentile_3y <= 25 and trend_20d >= 0:
        return "Cheap"
    if zscore >= 0.8 and trend_20d > 0:
        return "Strong"
    if zscore <= -1.0 and percentile_3y <= 25:
        return "Cheap"
    return "Neutral"


def _signal_from_zscore(zscore: float, current: float, trend_20d: float, trend_60d: float) -> str:
    if pd.isna(zscore) or pd.isna(current):
        return "Neutral"
    if zscore >= 1.0 and trend_20d > 0 and trend_60d > 0:
        return "Strong"
    if zscore <= -1.0 and trend_20d < 0 and trend_60d < 0:
        return "Cheap"
    return "Neutral"


def build_factor_watch_df(price_data: pd.DataFrame) -> pd.DataFrame:
    if price_data is None or price_data.empty:
        return _empty_factor_frame()
    normalized = price_data.copy()
    for ticker in REQUIRED_TICKERS:
        if ticker in normalized.columns:
            normalized[ticker] = pd.to_numeric(normalized[ticker], errors="coerce")
    normalized = normalized.dropna(how="all")
    if normalized.empty:
        return _empty_factor_frame()

    rows = []
    for factor_name, ratio_label, ticker_a, ticker_b in FACTOR_DEFINITIONS:
        if ticker_a not in normalized.columns or ticker_b not in normalized.columns:
            continue
        series = _safe_ratio(normalized[ticker_a], normalized[ticker_b]).dropna()
        if series.empty:
            continue
        current = float(series.iloc[-1])
        one_year = series.tail(252)
        three_year = series.tail(756)
        five_year = series
        percentile_1y = float(one_year.rank(pct=True).iloc[-1] * 100) if not one_year.empty else float("nan")
        percentile_3y = float(three_year.rank(pct=True).iloc[-1] * 100) if not three_year.empty else float("nan")
        percentile_5y = float(five_year.rank(pct=True).iloc[-1] * 100) if not five_year.empty else float("nan")
        zscore_3y = float((current - three_year.mean()) / three_year.std()) if not three_year.empty and three_year.std() not in (None, 0) else float("nan")
        trend_20d = _trend(series, 20)
        trend_60d = _trend(series, 60)
        signal = _signal_from_metrics(factor_name, zscore_3y, percentile_3y, trend_20d, trend_60d)
        numerator_holdings = format_holdings(get_etf_top_holdings(ticker_a, 5), "en")
        denominator_holdings = format_holdings(get_etf_top_holdings(ticker_b, 5), "en")
        rows.append({
            "Factor": factor_name,
            "Ratio": ratio_label,
            "Current": current,
            "Percentile_1Y": percentile_1y,
            "Percentile_3Y": percentile_3y,
            "Percentile_5Y": percentile_5y,
            "ZScore_3Y": zscore_3y,
            "Trend_20D": trend_20d,
            "Trend_60D": trend_60d,
            "Signal": signal,
            "Numerator Top Holdings": numerator_holdings,
            "Denominator Top Holdings": denominator_holdings,
        })
    return pd.DataFrame(rows, columns=FACTOR_COLUMNS)


build_factor_metrics = build_factor_watch_df


def generate_factor_summary(df: pd.DataFrame, lang="zh") -> str:
    language = normalize_factor_language(lang)
    summary_text = FACTOR_TEXT[language]["summary"]
    if df is None or df.empty:
        return summary_text["empty"]
    df = df.copy()
    momentum_row = df[df["Factor"].eq("Momentum")]
    value_rows = df[df["Factor"].isin(["Value vs Growth", "Value vs Long-duration Growth"])]
    defensive_rows = df[
        df["Factor"].isin(["Low Vol / Defensive", "Defensive Staples vs Growth", "Utilities vs Growth", "Defensive"])
    ]
    breadth_rows = df[df["Factor"].isin(["Equal Weight / Breadth", "Equal Weight/Breadth"])]
    semiconductor_rows = df[df["Factor"].isin(["Semiconductor strength", "Semiconductor"])]

    momentum_pct = _row_mean(momentum_row, "Percentile_3Y")
    value_trend = _row_mean(value_rows, "Trend_60D")
    defensive_trend = _row_mean(defensive_rows, "Trend_60D")
    breadth_pct = _row_mean(breadth_rows, "Percentile_3Y")
    semiconductor_pct = _row_mean(semiconductor_rows, "Percentile_3Y")
    semiconductor_z = _row_mean(semiconductor_rows, "ZScore_3Y")

    risk_on_score = 0
    if not pd.isna(momentum_pct) and momentum_pct >= 60:
        risk_on_score += 1
    if not pd.isna(semiconductor_pct) and semiconductor_pct >= 60:
        risk_on_score += 1
    if not pd.isna(breadth_pct) and breadth_pct >= 45:
        risk_on_score += 1
    if not pd.isna(defensive_trend) and defensive_trend > 0.02:
        risk_on_score -= 1
    risk_text = summary_text["risk_on"] if risk_on_score >= 2 else summary_text["risk_off"]

    if pd.isna(momentum_pct):
        momentum_text = summary_text["momentum_unknown"]
    elif momentum_pct >= 85:
        momentum_text = summary_text["momentum_crowded"]
    elif momentum_pct >= 60:
        momentum_text = summary_text["momentum_strong"]
    else:
        momentum_text = summary_text["momentum_weak"]

    if pd.isna(semiconductor_pct) and pd.isna(semiconductor_z):
        semiconductor_text = summary_text["semi_unknown"]
    elif (not pd.isna(semiconductor_pct) and semiconductor_pct >= 85) or (
        not pd.isna(semiconductor_z) and semiconductor_z >= 1.5
    ):
        semiconductor_text = summary_text["semi_hot"]
    else:
        semiconductor_text = summary_text["semi_ok"]

    if pd.isna(value_trend):
        value_text = summary_text["value_unknown"]
    elif value_trend > 0:
        value_text = summary_text["value_reversal"]
    else:
        value_text = summary_text["value_weak"]

    if pd.isna(defensive_trend):
        defensive_text = summary_text["def_unknown"]
    elif defensive_trend > 0:
        defensive_text = summary_text["def_strong"]
    else:
        defensive_text = summary_text["def_weak"]

    if pd.isna(breadth_pct):
        breadth_text = summary_text["breadth_unknown"]
    elif breadth_pct >= 45:
        breadth_text = summary_text["breadth_healthy"]
    else:
        breadth_text = summary_text["breadth_weak"]

    return " ".join([risk_text, momentum_text, semiconductor_text, value_text, defensive_text, breadth_text, summary_text["risk_tip"]])


def _row_mean(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return float("nan")
    return float(pd.to_numeric(df[column], errors="coerce").mean())


def build_ratio_series(price_data: pd.DataFrame, ratio_label: str) -> pd.Series:
    if price_data is None or price_data.empty:
        return pd.Series(dtype=float)
    for _, label, ticker_a, ticker_b in FACTOR_DEFINITIONS:
        if label == ratio_label:
            if ticker_a not in price_data.columns or ticker_b not in price_data.columns:
                return pd.Series(dtype=float)
            series = _safe_ratio(price_data[ticker_a], price_data[ticker_b]).dropna()
            series.name = ratio_label
            return series
    return pd.Series(dtype=float)


def build_factor_display_df(df: pd.DataFrame, lang="zh") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    language = normalize_factor_language(lang)
    ui = FACTOR_TEXT[language]["ui"]
    display_df = df.copy()
    display_df[ui["explanation"]] = display_df["Ratio"].apply(lambda ratio: get_factor_short_explanation(ratio, language))
    display_df["Numerator Top Holdings"] = display_df["Ratio"].apply(
        lambda ratio: format_holdings(get_etf_top_holdings(_ratio_etfs(ratio)[0], 5), language)
    )
    display_df["Denominator Top Holdings"] = display_df["Ratio"].apply(
        lambda ratio: format_holdings(get_etf_top_holdings(_ratio_etfs(ratio)[1], 5), language)
    )
    display_df["Signal"] = display_df["Signal"].apply(lambda signal: translate_factor_signal(signal, language))
    return display_df.rename(
        columns={
            "Factor": ui["factor"],
            "Ratio": ui["ratio"],
            "Current": ui["current"],
            "Percentile_1Y": ui["percentile_1y"],
            "Percentile_3Y": ui["percentile_3y"],
            "Percentile_5Y": ui["percentile_5y"],
            "ZScore_3Y": ui["zscore_3y"],
            "Trend_20D": ui["trend_20d"],
            "Trend_60D": ui["trend_60d"],
            "Signal": ui["signal"],
            "Numerator Top Holdings": ui["numerator_top_holdings"],
            "Denominator Top Holdings": ui["denominator_top_holdings"],
        }
    )


def holdings_to_display_df(holdings, lang="zh") -> pd.DataFrame:
    language = normalize_factor_language(lang)
    ui = FACTOR_TEXT[language]["ui"]
    if not holdings:
        return pd.DataFrame(columns=["Ticker", "Name", ui["weight"]])
    rows = []
    for holding in holdings:
        rows.append(
            {
                "Ticker": holding.get("Ticker", ""),
                "Name": holding.get("Name", ""),
                ui["weight"]: holding.get("Weight", float("nan")),
            }
        )
    return pd.DataFrame(rows)


def render_factor_watch_section():
    import plotly.graph_objects as go
    import streamlit as st

    language = normalize_factor_language(st.session_state.get("language", "中文"))
    ui = FACTOR_TEXT[language]["ui"]

    st.header(ui["title"])
    st.caption(ui["caption"])

    with st.spinner(ui["loading"]):
        try:
            price_data = fetch_factor_price_data()
        except Exception as exc:
            st.error(ui["download_error"].format(error=exc))
            return

    if price_data.empty:
        st.warning(ui["empty_prices"])
        return

    df = build_factor_metrics(price_data)
    if df.empty:
        st.warning(ui["empty_metrics"])
        return

    missing_tickers = [ticker for ticker in REQUIRED_TICKERS if ticker not in price_data.columns]
    if missing_tickers:
        st.warning(ui["missing_tickers"].format(tickers=", ".join(missing_tickers)))

    _render_summary_cards(df, language)

    display_df = build_factor_display_df(df, language)
    st.dataframe(
        display_df.style.format(
            {
                ui["current"]: "{:.4f}",
                ui["percentile_1y"]: "{:.1f}",
                ui["percentile_3y"]: "{:.1f}",
                ui["percentile_5y"]: "{:.1f}",
                ui["zscore_3y"]: "{:.2f}",
                ui["trend_20d"]: "{:.2%}",
                ui["trend_60d"]: "{:.2%}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    ratio_options = df["Ratio"].tolist()
    selected_ratio = st.selectbox(ui["ratio_select"], ratio_options, key="factor_watch_ratio_selector")
    ratio_series = build_ratio_series(price_data, selected_ratio)
    chart_column, explanation_column = st.columns([2, 1])
    if ratio_series.empty:
        chart_column.warning(ui["chart_missing"])
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=ratio_series.index,
                y=ratio_series.values,
                mode="lines",
                name=selected_ratio,
                line=dict(width=2),
            )
        )
        fig.update_layout(
            title=ui["chart_title"].format(ratio=selected_ratio),
            xaxis_title=ui["date"],
            yaxis_title=ui["ratio"],
            height=420,
            margin=dict(l=20, r=20, t=60, b=30),
        )
        chart_column.plotly_chart(fig, use_container_width=True)
    explanation_column.info(f"**{ui['selected_explanation']}**\n\n{get_factor_explanation(selected_ratio, language)}")

    numerator_etf, denominator_etf = _ratio_etfs(selected_ratio)
    st.markdown(f"### {ui['holdings_exposure']}")
    st.caption(ui["concentration_note"])
    holdings_columns = st.columns(2)
    numerator_holdings = get_etf_top_holdings(numerator_etf, 5)
    denominator_holdings = get_etf_top_holdings(denominator_etf, 5)
    with holdings_columns[0]:
        st.markdown(f"**{numerator_etf} · {ui['numerator_etf']} · {ui['top_5_holdings']}**")
        if numerator_holdings:
            st.dataframe(
                holdings_to_display_df(numerator_holdings, language).style.format({ui["weight"]: "{:.1f}%"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning(ui["holdings_unavailable"])
    with holdings_columns[1]:
        st.markdown(f"**{denominator_etf} · {ui['denominator_etf']} · {ui['top_5_holdings']}**")
        if denominator_holdings:
            st.dataframe(
                holdings_to_display_df(denominator_holdings, language).style.format({ui["weight"]: "{:.1f}%"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning(ui["holdings_unavailable"])

    st.markdown(f"### {ui['factor_explanations']}")
    for _, row in df.iterrows():
        with st.expander(f"{row['Ratio']} · {row['Factor']}"):
            st.write(get_factor_explanation(row["Ratio"], language))

    st.markdown(f"### {ui['summary_title']}")
    st.write(generate_factor_summary(df, language))
    st.caption(ui["holdings_disclaimer"])


def _render_summary_cards(df: pd.DataFrame, lang="zh"):
    import streamlit as st

    language = normalize_factor_language(lang)
    ui = FACTOR_TEXT[language]["ui"]
    columns = st.columns(len(SUMMARY_FACTORS))
    for column, (label_key, ratio_label) in zip(columns, SUMMARY_FACTORS.items()):
        row = df[df["Ratio"].eq(ratio_label)]
        if row.empty:
            column.metric(ui[label_key], "N/A", ui["no_data"])
            continue
        current = row["Current"].iloc[0]
        trend = row["Trend_60D"].iloc[0]
        signal = translate_factor_signal(row["Signal"].iloc[0], language)
        delta = None if pd.isna(trend) else f"{trend:.2%} 60D · {signal}"
        column.metric(ui[label_key], f"{current:.4f}", delta)
