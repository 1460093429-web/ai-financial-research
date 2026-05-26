from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from analyst_distribution import AnalystTarget, summarize_distribution


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANALYST_DB_PATH = os.path.join(BASE_DIR, "analyst_targets.csv")
ANALYST_COLUMNS = ["ticker", "firm", "target", "rating", "date", "tier"]


def normalize_ticker(ticker: Any) -> str:
    value = str(ticker or "").upper().strip()
    if "." in value:
        symbol, suffix = value.split(".", 1)
        if suffix in {"O", "N", "A", "K"}:
            return symbol
    return value


def empty_analyst_db() -> pd.DataFrame:
    return pd.DataFrame(columns=ANALYST_COLUMNS)


def normalize_analyst_db(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_analyst_db()

    normalized = df.copy()
    for column in ANALYST_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""

    normalized = normalized[ANALYST_COLUMNS]
    normalized["ticker"] = normalized["ticker"].map(normalize_ticker)
    normalized["firm"] = normalized["firm"].astype(str).str.strip()
    normalized["target"] = pd.to_numeric(normalized["target"], errors="coerce")
    normalized["rating"] = normalized["rating"].fillna("").astype(str).str.strip()
    normalized["date"] = normalized["date"].fillna("").astype(str).str.strip()
    normalized["tier"] = (
        normalized["tier"]
        .fillna("tier2")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    normalized = normalized.dropna(subset=["target"])
    normalized = normalized[
        (normalized["ticker"] != "")
        & (normalized["firm"] != "")
    ]
    normalized = normalized.drop_duplicates(
        subset=["ticker", "firm", "date", "target"],
        keep="last",
    )
    return normalized.reset_index(drop=True)


def ensure_analyst_db() -> None:
    if not os.path.exists(ANALYST_DB_PATH):
        empty_analyst_db().to_csv(ANALYST_DB_PATH, index=False)


def load_analyst_db() -> pd.DataFrame:
    ensure_analyst_db()
    try:
        return normalize_analyst_db(pd.read_csv(ANALYST_DB_PATH))
    except Exception:
        return empty_analyst_db()


def save_analyst_db(df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_analyst_db(df)
    normalized.to_csv(ANALYST_DB_PATH, index=False)
    return normalized


def records_from_dataframe(df: pd.DataFrame) -> List[AnalystTarget]:
    records: List[AnalystTarget] = []
    normalized = normalize_analyst_db(df)

    for row in normalized.to_dict("records"):
        records.append(
            AnalystTarget(
                ticker=row["ticker"],
                firm=row["firm"],
                target=float(row["target"]),
                rating=row.get("rating", ""),
                date=row.get("date", ""),
                tier=row.get("tier", "tier2"),
                source="analyst_db",
            )
        )

    return records


def get_analyst_records(ticker: Optional[str] = None) -> List[AnalystTarget]:
    df = load_analyst_db()
    if ticker:
        df = df[df["ticker"] == normalize_ticker(ticker)]
    return records_from_dataframe(df)


def get_target_stats(
    ticker: str,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    records = get_analyst_records(ticker)
    if not records:
        return {
            "ticker": normalize_ticker(ticker),
            "consensus": None,
            "weighted": None,
            "bear_target": None,
            "base_target": None,
            "bull_target": None,
            "max_target": None,
            "min_target": None,
            "count": 0,
            "outlier_count": 0,
            "rows": [],
        }

    distribution = summarize_distribution(records, current_price)
    return {
        "ticker": normalize_ticker(ticker),
        "consensus": distribution["mean_target"],
        "weighted": distribution["weighted_mean_target"],
        "bear_target": distribution["bear_target"],
        "base_target": distribution["base_target"],
        "bull_target": distribution["bull_target"],
        "max_target": distribution["high_target"],
        "min_target": distribution["low_target"],
        "count": distribution["count"],
        "outlier_count": distribution["outlier_count"],
        "rows": distribution["rows"],
    }
