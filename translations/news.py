"""Static news labels, UI text, language mappings, and version constants."""

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
        "sentiment_bands": ((0.35, "Bullish"), (0.10, "Slightly Bullish"), (-0.10, "Neutral"), (-0.35, "Slightly Bearish"), (-1.01, "Bearish")),
    },
    "\u4e2d\u6587": {
        "credibility": "\u53ef\u4fe1\u5ea6",
        "sentiment": "\u60c5\u7eea",
        "credibility_bands": ((80, "\u9ad8"), (60, "\u4e2d\u9ad8"), (40, "\u4e2d"), (0, "\u4f4e")),
        "sentiment_bands": ((0.35, "\u504f\u591a"), (0.10, "\u8f7b\u5fae\u504f\u591a"), (-0.10, "\u4e2d\u6027"), (-0.35, "\u8f7b\u5fae\u504f\u7a7a"), (-1.01, "\u504f\u7a7a")),
    },
    "Espa\u00f1ol": {
        "credibility": "Credibilidad",
        "sentiment": "Sentimiento",
        "credibility_bands": ((80, "Alta"), (60, "Media-alta"), (40, "Media"), (0, "Baja")),
        "sentiment_bands": ((0.35, "Alcista"), (0.10, "Ligeramente alcista"), (-0.10, "Neutral"), (-0.35, "Ligeramente bajista"), (-1.01, "Bajista")),
    },
}
NEWS_SUMMARY_LANGUAGE_NAMES = {"English": "English", "\u4e2d\u6587": "Chinese", "Espa\u00f1ol": "Spanish"}
NEWS_SUMMARY_LANGUAGE_ALIASES = {
    "en": "English", "english": "English", "zh": "\u4e2d\u6587", "chinese": "\u4e2d\u6587", "\u4e2d\u6587": "\u4e2d\u6587",
    "es": "Espa\u00f1ol", "spanish": "Espa\u00f1ol", "espa\u00f1ol": "Espa\u00f1ol",
}
NEWS_SUMMARY_FIELD_LABELS = {
    "English": {
        "news_overview": "News Overview", "why_it_matters": "Why It Matters", "potential_stock_impact": "Potential Stock Impact",
        "positive_factors": "Positive Factors", "risk_factors": "Risk Factors", "what_to_watch_next": "What to Watch Next",
        "ai_view": "AI View", "confidence": "Confidence",
    },
    "\u4e2d\u6587": {
        "news_overview": "\u65b0\u95fb\u6982\u8ff0", "why_it_matters": "\u4e3a\u4f55\u91cd\u8981", "potential_stock_impact": "\u6f5c\u5728\u80a1\u4ef7\u5f71\u54cd",
        "positive_factors": "\u79ef\u6781\u56e0\u7d20", "risk_factors": "\u98ce\u9669\u56e0\u7d20", "what_to_watch_next": "\u540e\u7eed\u5173\u6ce8",
        "ai_view": "AI \u89c2\u70b9", "confidence": "\u7f6e\u4fe1\u5ea6",
    },
    "Espa\u00f1ol": {
        "news_overview": "Resumen de la noticia", "why_it_matters": "Por qu\u00e9 importa", "potential_stock_impact": "Impacto potencial en la acci\u00f3n",
        "positive_factors": "Factores positivos", "risk_factors": "Factores de riesgo", "what_to_watch_next": "Qu\u00e9 vigilar",
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
