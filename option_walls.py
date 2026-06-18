import numpy as np
import pandas as pd


def _first_existing_column(columns, candidates):
    normalized = {str(column).strip().lower(): column for column in columns}
    for candidate in candidates:
        column = normalized.get(candidate.lower())
        if column is not None:
            return column
    return None


def _empty_wall():
    return {"strike": None, "open_interest": 0.0}


def compute_option_walls(options_df, selected_expiry, spot_price=None):
    """
    Compute option walls for one selected expiry.

    Put Wall is the put strike with the highest open interest.
    Call Wall is the call strike with the highest open interest.
    Ties prefer the strike closest to spot_price; without spot_price, the
    lowest strike among tied rows is selected.
    """
    result = {"put_wall": _empty_wall(), "call_wall": _empty_wall()}
    if options_df is None or len(options_df) == 0:
        return result

    frame = options_df.copy()
    strike_col = _first_existing_column(frame.columns, ("strike",))
    oi_col = _first_existing_column(frame.columns, ("openInterest", "open_interest", "oi"))
    type_col = _first_existing_column(frame.columns, ("optionType", "option_type", "type", "side"))
    expiry_col = _first_existing_column(frame.columns, ("expiry", "expiration", "exp_date", "expirationDate"))

    if strike_col is None or oi_col is None or type_col is None:
        return result

    normalized = pd.DataFrame({
        "strike": pd.to_numeric(frame[strike_col], errors="coerce"),
        "open_interest": pd.to_numeric(frame[oi_col], errors="coerce").fillna(0),
        "option_type": frame[type_col].astype(str).str.strip().str.lower(),
    })
    if expiry_col is not None:
        normalized["expiry"] = frame[expiry_col].astype(str)
        normalized = normalized[normalized["expiry"].eq(str(selected_expiry))]

    normalized = normalized.dropna(subset=["strike"])
    normalized = normalized[normalized["option_type"].isin(("call", "put", "calls", "puts", "c", "p"))]
    normalized["option_type"] = normalized["option_type"].replace({
        "calls": "call",
        "puts": "put",
        "c": "call",
        "p": "put",
    })
    if normalized.empty:
        return result

    try:
        spot = float(spot_price)
    except (TypeError, ValueError):
        spot = np.nan

    for option_type, key in (("put", "put_wall"), ("call", "call_wall")):
        side = normalized[normalized["option_type"].eq(option_type)]
        if side.empty:
            continue
        max_oi = side["open_interest"].max()
        candidates = side[side["open_interest"].eq(max_oi)].copy()
        if np.isfinite(spot):
            candidates["distance"] = (candidates["strike"] - spot).abs()
            candidates = candidates.sort_values(["distance", "strike"], ascending=[True, True])
        else:
            candidates = candidates.sort_values("strike", ascending=True)
        selected = candidates.iloc[0]
        result[key] = {
            "strike": float(selected["strike"]),
            "open_interest": float(selected["open_interest"]),
        }

    return result
