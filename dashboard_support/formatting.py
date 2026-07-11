"""Pure display formatting helpers used by the dashboard."""

import numpy as np
import pandas as pd


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


def card_number(value):
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
