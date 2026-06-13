from __future__ import annotations

import csv
import io
import warnings

import pandas as pd


SECTION_OUTPUT_KEYS = {
    "Trades": "trades",
    "Open Positions": "positions",
    "Net Asset Value": "nav",
    "Cash Report": "cash",
    "Realized & Unrealized Performance Summary": "performance",
}

SECTION_ALIASES = {
    "Trades": ["Trades", "交易", "交易记录", "成交", "Transactions"],
    "Open Positions": ["Open Positions", "未平仓头寸", "持仓", "持仓报告", "Positions"],
    "Net Asset Value": ["Net Asset Value", "资产净值", "净资产值", "NAV"],
    "Cash Report": ["Cash Report", "现金报告", "现金", "Cash"],
    "Realized & Unrealized Performance Summary": [
        "Realized & Unrealized Performance Summary",
        "已实现和未实现表现总结",
        "已实现与未实现盈亏",
    ],
}

SUPPORTED_SECTIONS = SECTION_OUTPUT_KEYS

REQUIRED_SECTIONS = {
    "Trades",
    "Open Positions",
    "Net Asset Value",
    "Cash Report",
}


def _clean_csv_token(value):
    return str(value or "").replace("\ufeff", "").strip()


def _normalize_csv_token(value):
    return " ".join(_clean_csv_token(value).casefold().split())


SECTION_ALIAS_LOOKUP = {
    _normalize_csv_token(alias): section
    for section, aliases in SECTION_ALIASES.items()
    for alias in aliases
}


def parse_ibkr_activity_statement_csv(uploaded_file, emit_warnings=True):
    """Parse IBKR's sectioned Activity Statement CSV format.

    IBKR Activity Statement CSV exports are not rectangular CSV files. Each
    section has its own Header/Data rows and may have a different field count.
    """
    text = read_uploaded_file_text(uploaded_file)
    reader = csv.reader(io.StringIO(text))

    section_rows = {section: [] for section in SUPPORTED_SECTIONS}
    headers = {}
    detected_section_names = []
    detected_section_name_keys = set()
    recognized_sections = set()

    for row in reader:
        if not row or len(row) < 2:
            continue

        detected_section = _clean_csv_token(row[0])
        if detected_section and _normalize_csv_token(detected_section) not in detected_section_name_keys:
            detected_section_name_keys.add(_normalize_csv_token(detected_section))
            detected_section_names.append(detected_section)

        section = _canonical_section_name(row[0])
        row_type = _normalize_csv_token(row[1])

        if section not in SUPPORTED_SECTIONS:
            continue
        recognized_sections.add(section)

        if row_type == "header":
            headers[section] = [_clean_csv_token(column) for column in row[2:]]
            continue

        if row_type == "data":
            header = headers.get(section)
            if not header:
                continue

            values = row[2:]
            if len(values) < len(header):
                values = values + [""] * (len(header) - len(values))
            elif len(values) > len(header):
                values = values[: len(header)]

            section_rows[section].append(dict(zip(header, values)))

    frames = {
        output_key: pd.DataFrame(section_rows[section])
        for section, output_key in SUPPORTED_SECTIONS.items()
    }

    for section, output_key in SUPPORTED_SECTIONS.items():
        if not emit_warnings or section not in REQUIRED_SECTIONS:
            continue
        if frames[output_key].empty:
            warnings.warn(
                f"IBKR Activity Statement section missing or empty: {section}",
                RuntimeWarning,
                stacklevel=2,
            )

    return {
        "trades": frames["trades"],
        "positions": frames["positions"],
        "nav": frames["nav"],
        "cash": frames["cash"],
        "performance": frames["performance"],
        "detected_section_names": detected_section_names,
        "recognized_section_names": sorted(recognized_sections),
    }


def read_uploaded_file_text(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        raw = uploaded_file.getvalue()
    elif hasattr(uploaded_file, "read"):
        raw = uploaded_file.read()
    else:
        raw = uploaded_file

    if isinstance(raw, bytes):
        return raw.decode("utf-8-sig", errors="replace")
    return str(raw)


def preview_uploaded_csv(uploaded_file, lines=20):
    text = read_uploaded_file_text(uploaded_file)
    return "\n".join(text.splitlines()[:lines])


def _canonical_section_name(value):
    return SECTION_ALIAS_LOOKUP.get(_normalize_csv_token(value))
