from typing import Optional


def format_metric(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "N/A"

    return f"{value:,.2f}{suffix}"


def format_fx_rate(value: Optional[float]) -> str:
    if value is None:
        return "N/A"

    return f"{value:,.6f}"


def format_large_number(value: Optional[float], currency: str = "") -> str:
    if value is None:
        return "N/A"

    prefix = f"{currency} " if currency else ""

    abs_value = abs(value)

    if abs_value >= 1e12:
        return f"{prefix}{value / 1e12:,.2f}T"

    if abs_value >= 1e9:
        return f"{prefix}{value / 1e9:,.2f}B"

    if abs_value >= 1e6:
        return f"{prefix}{value / 1e6:,.2f}M"

    return f"{prefix}{value:,.2f}"