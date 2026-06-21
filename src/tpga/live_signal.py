from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .features import build_features
from .regime import add_regime_features
from .model import fit_predict_proba
from .mt5_gap_builder import GapSessionConfig, _prepare_m1, _ret_lookback, _volume_z, _vwap_distance, _range_position, _realized_vol


@dataclass(frozen=True)
class PaperSignal:
    generated_at: str
    symbol: str
    p_up: float
    p_down: float
    p_flat: float
    edge: float
    confidence: float
    side: str
    median_abs_gap_points: float
    expected_gap_points_proxy: float
    note: str


def build_current_feature_row(
    recent_m1: pd.DataFrame,
    cfg: GapSessionConfig,
    now: datetime | None = None,
    market_data: dict | None = None,
) -> pd.DataFrame:
    bars = _prepare_m1(recent_m1)
    if bars.empty or len(bars) < 30:
        raise ValueError("Poucos candles M1 recentes para gerar snapshot atual.")
    now_local = now or datetime.now(ZoneInfo(cfg.timezone))
    win = bars.copy().tail(max(cfg.lookback_minutes, 260))
    last = win.iloc[-1]
    current_close = float(last["close"])

    # Evita training-serving skew: tenta preencher features macro com dados reais
    # de pre-abertura. Se yfinance/rede indisponivel, mantem NaN (como no treino).
    if market_data is None:
        try:
            from .market_data import fetch_premarket_features
            market_data = fetch_premarket_features()
        except Exception:
            market_data = {}
    market_data = market_data or {}

    def _md(key):
        val = market_data.get(key, np.nan)
        try:
            return float(val)
        except (TypeError, ValueError):
            return np.nan

    row = {
        "session_date": now_local.date().isoformat(),
        "symbol": cfg.symbol,
        "timezone": cfg.timezone,
        "prev_close": current_close,
        # Dummy only to pass schema/feature builder. It is NOT used as known future open.
        "open": current_close,
        "last_1m_ret": _ret_lookback(win, 1),
        "last_5m_ret": _ret_lookback(win, 5),
        "last_15m_ret": _ret_lookback(win, 15),
        "close_volume_z": _volume_z(win, 60),
        "vwap_distance": _vwap_distance(win.tail(cfg.lookback_minutes)),
        "range_position": _range_position(win.tail(cfg.lookback_minutes)),
        "realized_vol_30m": _realized_vol(win, 30),
        "mt5_spread_points_at_signal": float(last.get("spread", np.nan)) if "spread" in last else np.nan,
        "futures_overnight_ret": _md("futures_overnight_ret"),
        "qqq_premarket_ret": _md("qqq_premarket_ret"),
        "spy_premarket_ret": _md("spy_premarket_ret"),
        "weighted_bigtech_premarket_ret": _md("weighted_bigtech_premarket_ret"),
        "vix_ret": _md("vix_ret"),
        "dxy_ret": _md("dxy_ret"),
        "us10y_ret": _md("us10y_ret"),
        "macro_event_flag": 0,
        "earnings_risk_flag": 0,
        "noii_imbalance_side": "",
        "noii_imbalance_shares": np.nan,
        "noii_paired_shares": np.nan,
        "noii_near_price": np.nan,
        "noii_far_price": np.nan,
        "noii_reference_price": np.nan,
    }
    return pd.DataFrame([row])


def train_and_score_current(historical_gap_df: pd.DataFrame, current_row: pd.DataFrame, cfg: GapSessionConfig, random_state: int = 42, extra_features: list | None = None) -> PaperSignal:
    train, features = build_features(historical_gap_df, extra_features=extra_features)
    train = train.sort_values("session_date").reset_index(drop=True)

    # Quantis de regime estimados apenas no historico (treino), aplicados ao snapshot.
    train_vol = train.get("realized_vol_30m", pd.Series(dtype=float)).fillna(0)
    vol_q70 = float(train_vol.quantile(0.70)) if len(train_vol) > 0 else 0.0
    vol_q35 = float(train_vol.quantile(0.35)) if len(train_vol) > 0 else 0.0
    risk_col = train.get("risk_off_score", pd.Series(dtype=float)).fillna(0)
    risk_q70 = float(risk_col.quantile(0.70)) if len(risk_col) > 0 else 0.0

    train = add_regime_features(train, vol_q70=vol_q70, vol_q35=vol_q35, risk_q70=risk_q70)
    regime_features = [c for c in train.columns if c.startswith("regime_")]
    features = features + regime_features

    test, _ = build_features(current_row, extra_features=extra_features)
    test = add_regime_features(test, vol_q70=vol_q70, vol_q35=vol_q35, risk_q70=risk_q70)
    for col in features:
        if col not in test.columns:
            test[col] = np.nan

    pred = fit_predict_proba(train, test, features, random_state=random_state).frame.iloc[0]
    p_up = float(pred.get("p_up", 0.0))
    p_down = float(pred.get("p_down", 0.0))
    p_flat = float(pred.get("p_flat", 0.0))
    edge = p_up - p_down
    confidence = max(p_up, p_down, p_flat)
    median_abs_gap = float((train["open"] - train["prev_close"]).abs().median())
    expected_proxy = edge * median_abs_gap
    side = "BUY_STUDY" if edge > 0 else "SELL_STUDY" if edge < 0 else "NO_EDGE"
    return PaperSignal(
        generated_at=datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
        symbol=cfg.symbol,
        p_up=p_up,
        p_down=p_down,
        p_flat=p_flat,
        edge=edge,
        confidence=confidence,
        side=side,
        median_abs_gap_points=median_abs_gap,
        expected_gap_points_proxy=float(expected_proxy),
        note="Sinal educacional/paper. Nao envia ordens e nao e recomendacao financeira.",
    )
