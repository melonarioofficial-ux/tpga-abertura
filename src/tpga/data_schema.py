from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List
import pandas as pd

REQUIRED_COLUMNS = ["session_date", "prev_close", "open"]

OPTIONAL_COLUMNS = [
    "last_1m_ret",
    "last_5m_ret",
    "last_15m_ret",
    "close_volume_z",
    "vwap_distance",
    "range_position",
    "realized_vol_30m",
    "futures_overnight_ret",
    "qqq_premarket_ret",
    "spy_premarket_ret",
    "weighted_bigtech_premarket_ret",
    "vix_ret",
    "dxy_ret",
    "us10y_ret",
    "macro_event_flag",
    "earnings_risk_flag",
    "noii_imbalance_side",
    "noii_imbalance_shares",
    "noii_paired_shares",
    "noii_near_price",
    "noii_far_price",
    "noii_reference_price",
    "mt5_spread_points_at_signal",
]

@dataclass(frozen=True)
class SchemaReport:
    ok: bool
    missing_required: List[str]
    missing_optional: List[str]
    rows: int


def validate_input_frame(df: pd.DataFrame) -> SchemaReport:
    missing_required = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    missing_optional = [c for c in OPTIONAL_COLUMNS if c not in df.columns]
    return SchemaReport(
        ok=len(missing_required) == 0 and len(df) > 0,
        missing_required=missing_required,
        missing_optional=missing_optional,
        rows=len(df),
    )


def load_gap_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    report = validate_input_frame(df)
    if not report.ok:
        raise ValueError(f"CSV inválido. Faltando colunas obrigatórias: {report.missing_required}; linhas={report.rows}")
    df = df.copy()
    df["session_date"] = pd.to_datetime(df["session_date"])
    df = df.sort_values("session_date").reset_index(drop=True)
    for col in ["prev_close", "open"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["prev_close", "open"])
    return df


def ensure_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out
