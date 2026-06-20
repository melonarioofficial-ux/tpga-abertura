from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_gap_data(n: int = 420, seed: int = 42) -> pd.DataFrame:
    """Gera dados sintéticos para testar o pipeline.

    A relação é propositalmente fraca e ruidosa, simulando um mercado onde nenhuma
    variável isolada é suficiente. Não use este arquivo como prova de edge real.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    prev_close = 15000 + np.cumsum(rng.normal(0, 55, size=n))

    futures = rng.normal(0, 0.004, size=n)
    qqq = futures * 0.70 + rng.normal(0, 0.0025, size=n)
    bigtech = futures * 0.80 + rng.normal(0, 0.003, size=n)
    last5 = rng.normal(0, 0.0025, size=n)
    last15 = 0.4 * last5 + rng.normal(0, 0.003, size=n)
    vix = -0.35 * futures + rng.normal(0, 0.004, size=n)
    dxy = rng.normal(0, 0.002, size=n)
    us10y = rng.normal(0, 0.002, size=n)
    volz = rng.normal(0, 1, size=n)
    macro = (rng.random(n) < 0.12).astype(int)
    earnings = (rng.random(n) < 0.18).astype(int)

    latent = (
        0.55 * futures
        + 0.25 * qqq
        + 0.30 * bigtech
        - 0.18 * vix
        - 0.10 * macro * np.sign(vix)
        + 0.08 * last15
        + rng.standard_t(df=4, size=n) * 0.0035
    )
    gap_points = prev_close * latent
    open_ = prev_close + gap_points

    noii_side = np.where(latent > 0.001, "B", np.where(latent < -0.001, "S", "N"))
    paired = rng.integers(100_000, 900_000, size=n).astype(float)
    imbalance = np.abs(latent) * paired * rng.uniform(5, 25, size=n)

    return pd.DataFrame({
        "session_date": dates,
        "prev_close": prev_close,
        "open": open_,
        "last_1m_ret": rng.normal(0, 0.0015, size=n),
        "last_5m_ret": last5,
        "last_15m_ret": last15,
        "close_volume_z": volz,
        "vwap_distance": rng.normal(0, 0.004, size=n),
        "range_position": rng.uniform(0, 1, size=n),
        "realized_vol_30m": np.abs(rng.normal(0.006, 0.003, size=n)),
        "futures_overnight_ret": futures,
        "qqq_premarket_ret": qqq,
        "spy_premarket_ret": futures * 0.55 + rng.normal(0, 0.003, size=n),
        "weighted_bigtech_premarket_ret": bigtech,
        "vix_ret": vix,
        "dxy_ret": dxy,
        "us10y_ret": us10y,
        "macro_event_flag": macro,
        "earnings_risk_flag": earnings,
        "noii_imbalance_side": noii_side,
        "noii_imbalance_shares": imbalance,
        "noii_paired_shares": paired,
        "noii_near_price": open_ + rng.normal(0, 8, size=n),
        "noii_far_price": open_ + rng.normal(0, 15, size=n),
        "noii_reference_price": prev_close + rng.normal(0, 5, size=n),
    })
