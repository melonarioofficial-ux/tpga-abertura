from __future__ import annotations

import numpy as np
import pandas as pd
from .data_schema import OPTIONAL_COLUMNS, ensure_numeric_columns

BASE_FEATURES = [
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
    "noii_imbalance_shares",
    "noii_paired_shares",
    "noii_near_distance",
    "noii_far_distance",
    "noii_pressure",
    "closing_pressure_score",
    "fair_value_score",
    "component_confirmation",
    "risk_off_score",
    "fakeout_risk",
    "mt5_spread_points_at_signal",
]


# Features de engenharia (momentum / tendencia / vol / calendario).
# Validadas out-of-sample: melhoram o DAX (MCC 0.006->0.192). Aplicadas por
# instrumento via SymbolConfig.extra_features — NAO sao globais.
ENGINEERED_FEATURES = [
    "prev_gap_pct", "gap_5d_mean", "gap_5d_std",
    "close_sma5_dist", "close_sma10_dist", "rv_10d",
    "dow", "is_monday",
]


def build_engineered_features(main_ohlc: pd.DataFrame) -> pd.DataFrame:
    """Calcula as features de engenharia a partir do OHLC diario do instrumento
    principal. Tudo PAST-ONLY (deslocado): usa apenas info disponivel antes da
    abertura da sessao alvo. Indexado por session_date (ISO).

    Espera um DataFrame com DatetimeIndex e colunas Open/Close.
    """
    m = main_ohlc.dropna(subset=["Open", "Close"]).copy()
    pc   = m["Close"].shift(1)
    gpct = (m["Open"] - pc) / pc
    ret  = np.log(m["Close"] / m["Close"].shift(1))
    sma5  = m["Close"].rolling(5).mean()
    sma10 = m["Close"].rolling(10).mean()
    dow   = pd.Series(m.index.dayofweek, index=m.index)

    f = pd.DataFrame(index=m.index)
    f["session_date"]     = [d.date().isoformat() for d in m.index]
    f["prev_gap_pct"]     = gpct.shift(1)
    f["gap_5d_mean"]      = gpct.shift(1).rolling(5).mean()
    f["gap_5d_std"]       = gpct.shift(1).rolling(5).std()
    f["close_sma5_dist"]  = (m["Close"].shift(1) / sma5.shift(1) - 1.0)
    f["close_sma10_dist"] = (m["Close"].shift(1) / sma10.shift(1) - 1.0)
    f["rv_10d"]           = ret.shift(1).rolling(10).std()
    f["dow"]              = dow.astype(float)
    f["is_monday"]        = (dow == 0).astype(float)
    return f.reset_index(drop=True)


def _safe_log_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return np.log(a / b.replace(0, np.nan))


def add_gap_labels(df: pd.DataFrame, flat_threshold_points: float = 5.0) -> pd.DataFrame:
    out = df.copy()
    out["gap_points"] = out["open"] - out["prev_close"]
    out["gap_pct"] = (out["open"] / out["prev_close"] - 1.0) * 100.0
    out["gap_log"] = _safe_log_ratio(out["open"], out["prev_close"])
    out["direction"] = np.where(
        out["gap_points"] > flat_threshold_points,
        "up",
        np.where(out["gap_points"] < -flat_threshold_points, "down", "flat"),
    )
    out["target_up"] = (out["direction"] == "up").astype(int)
    return out


def encode_noii_side(series: pd.Series) -> pd.Series:
    mapping = {"B": 1.0, "BUY": 1.0, "S": -1.0, "SELL": -1.0, "N": 0.0, "O": 0.0, "": 0.0}
    return series.astype(str).str.upper().str.strip().map(mapping).fillna(0.0)


def build_features(df: pd.DataFrame, flat_threshold_points: float = 5.0,
                   extra_features: list[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    out = add_gap_labels(df, flat_threshold_points=flat_threshold_points)
    out = ensure_numeric_columns(out, OPTIONAL_COLUMNS)

    for col in OPTIONAL_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    out["noii_side_num"] = encode_noii_side(out["noii_imbalance_side"])
    out["mt5_spread_points_at_signal"] = out["mt5_spread_points_at_signal"].fillna(0.0)

    out["noii_near_distance"] = (out["noii_near_price"] - out["prev_close"]) / out["prev_close"]
    out["noii_far_distance"] = (out["noii_far_price"] - out["prev_close"]) / out["prev_close"]
    paired = out["noii_paired_shares"].replace(0, np.nan)
    out["noii_pressure"] = out["noii_side_num"] * (out["noii_imbalance_shares"] / paired)

    out["closing_pressure_score"] = (
        0.45 * out["last_5m_ret"].fillna(0)
        + 0.35 * out["last_15m_ret"].fillna(0)
        + 0.20 * out["vwap_distance"].fillna(0)
    )

    out["fair_value_score"] = (
        0.50 * out["futures_overnight_ret"].fillna(0)
        + 0.30 * out["qqq_premarket_ret"].fillna(0)
        + 0.20 * out["spy_premarket_ret"].fillna(0)
    )

    out["component_confirmation"] = out["weighted_bigtech_premarket_ret"].fillna(0) * np.sign(out["fair_value_score"].fillna(0))

    out["risk_off_score"] = (
        0.45 * out["vix_ret"].fillna(0)
        + 0.25 * out["dxy_ret"].fillna(0)
        + 0.30 * out["us10y_ret"].fillna(0)
    )

    # Fakeout: fechamento vendendo mas fair value/componentes não confirmam baixa, ou o inverso.
    close_sign = np.sign(out["closing_pressure_score"].fillna(0))
    fair_sign = np.sign(out["fair_value_score"].fillna(0) + out["weighted_bigtech_premarket_ret"].fillna(0))
    divergence = (close_sign != 0) & (fair_sign != 0) & (close_sign != fair_sign)
    abnormal_close = np.clip(np.abs(out["close_volume_z"].fillna(0)) / 3.0, 0, 1)
    vwap_stretch = np.clip(np.abs(out["vwap_distance"].fillna(0)) * 50.0, 0, 1)
    out["fakeout_risk"] = np.clip(0.45 * divergence.astype(float) + 0.30 * abnormal_close + 0.25 * vwap_stretch, 0, 1)

    feature_list = BASE_FEATURES.copy()
    # Features extras por instrumento (ex.: engenharia do DAX). Mantidas se
    # presentes no df; ausentes viram NaN (o modelo trata NaN nativamente).
    for col in (extra_features or []):
        if col not in feature_list:
            feature_list.append(col)

    for col in feature_list:
        if col not in out.columns:
            out[col] = np.nan

    return out, feature_list
