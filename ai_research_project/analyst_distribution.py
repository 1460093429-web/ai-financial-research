from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


TIER_WEIGHTS = {
    "tier1": 1.25,
    "tier 1": 1.25,
    "t1": 1.25,
    "tier2": 1.0,
    "tier 2": 1.0,
    "t2": 1.0,
    "tier3": 0.75,
    "tier 3": 0.75,
    "t3": 0.75,
}


@dataclass(frozen=True)
class AnalystTarget:
    ticker: str
    firm: str
    target: float
    rating: str = ""
    date: str = ""
    tier: str = "tier2"
    source: str = "broker"

    @property
    def weight(self) -> float:
        return TIER_WEIGHTS.get(self.tier.strip().lower(), 1.0)


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def weighted_percentile(records: List[AnalystTarget], q: float) -> Optional[float]:
    if not records:
        return None
    ordered = sorted(records, key=lambda item: item.target)
    total_weight = sum(max(item.weight, 0) for item in ordered)
    if total_weight <= 0:
        return percentile([item.target for item in ordered], q)

    threshold = total_weight * q
    running = 0.0
    for item in ordered:
        running += max(item.weight, 0)
        if running >= threshold:
            return item.target
    return ordered[-1].target


def parse_broker_targets(text: str) -> List[AnalystTarget]:
    records: List[AnalystTarget] = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [
            part.strip()
            for part in re.split(r"\s*[,\t|]\s*", line)
            if part.strip()
        ]

        if len(parts) < 3 and ":" in line:
            firm, target = [part.strip() for part in line.split(":", 1)]
            parts = ["", firm, target]

        if len(parts) < 3:
            continue

        ticker = parts[0].upper()
        firm = parts[1]
        target = safe_float(parts[2])
        if not ticker or not firm or target is None:
            continue

        records.append(
            AnalystTarget(
                ticker=ticker,
                firm=firm,
                target=target,
                rating=parts[3] if len(parts) > 3 else "",
                date=parts[4] if len(parts) > 4 else "",
                tier=parts[5] if len(parts) > 5 else "tier2",
                source="manual",
            )
        )

    return records


def build_aggregate_proxy_records(
    ticker: str,
    consensus_target: Optional[float],
    median_target: Optional[float],
    low_target: Optional[float],
    high_target: Optional[float],
) -> List[AnalystTarget]:
    proxies = []
    fields = [
        ("Aggregate Low", low_target, "aggregate_low"),
        ("Aggregate Median", median_target, "aggregate_median"),
        ("Aggregate Mean", consensus_target, "aggregate_mean"),
        ("Aggregate High", high_target, "aggregate_high"),
    ]
    for firm, target, source in fields:
        value = safe_float(target)
        if value is None:
            continue
        proxies.append(
            AnalystTarget(
                ticker=ticker,
                firm=firm,
                target=value,
                tier="tier2",
                source=source,
            )
        )
    return proxies


def detect_outliers(records: List[AnalystTarget]) -> Dict[str, str]:
    values = [item.target for item in records]
    median = percentile(values, 0.5)
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    if median is None or q1 is None or q3 is None:
        return {}

    iqr = q3 - q1
    if iqr <= 0:
        return {}

    high_cutoff = q3 + 1.5 * iqr
    low_cutoff = q1 - 1.5 * iqr
    outliers = {}
    for item in records:
        key = f"{item.firm}|{item.target}|{item.source}"
        if item.target >= high_cutoff:
            outliers[key] = "bull_case_outlier"
        elif item.target <= low_cutoff:
            outliers[key] = "bear_case_outlier"
    return outliers


def summarize_distribution(
    records: Iterable[AnalystTarget],
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    items = list(records)
    values = [item.target for item in items]
    outlier_map = detect_outliers(items)

    rows = []
    for item in sorted(items, key=lambda record: record.target, reverse=True):
        upside_pct = None
        if current_price not in (None, 0):
            upside_pct = (item.target - current_price) / current_price * 100
        key = f"{item.firm}|{item.target}|{item.source}"
        rows.append({
            "Ticker": item.ticker,
            "Firm": item.firm,
            "Target": item.target,
            "Rating": item.rating,
            "Date": item.date,
            "Tier": item.tier,
            "Weight": item.weight,
            "Source": item.source,
            "Scenario Tag": outlier_map.get(key, ""),
            "Upside %": upside_pct,
        })

    mean = sum(values) / len(values) if values else None
    weighted_mean = None
    total_weight = sum(item.weight for item in items)
    if total_weight:
        weighted_mean = sum(item.target * item.weight for item in items) / total_weight

    return {
        "count": len(items),
        "bear_target": weighted_percentile(items, 0.10),
        "base_target": weighted_percentile(items, 0.50),
        "bull_target": weighted_percentile(items, 0.90),
        "low_target": min(values) if values else None,
        "high_target": max(values) if values else None,
        "mean_target": mean,
        "weighted_mean_target": weighted_mean,
        "outlier_count": len(outlier_map),
        "rows": rows,
    }
