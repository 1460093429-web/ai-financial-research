"""Static company display metadata and stateless ticker helpers."""

import re


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


def normalize_ticker(ticker):
    return re.sub(r"\s+", "", str(ticker or "")).upper()


def company_name(ticker, snapshot=None):
    if snapshot and snapshot.get("name"):
        return snapshot["name"]
    return COMPANY_NAMES.get(ticker, ticker)


def supply_chain_role(ticker):
    return SUPPLY_CHAIN_ROLES.get(ticker, "Dynamic watchlist stock")
