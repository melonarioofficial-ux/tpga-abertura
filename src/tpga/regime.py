from __future__ import annotations

import numpy as np
import pandas as pd


def add_regime_features(
    df: pd.DataFrame,
    vol_q70: float | None = None,
    vol_q35: float | None = None,
    risk_q70: float | None = None,
) -> pd.DataFrame:
    """Adiciona features de regime.

    Para evitar lookahead bias no walk-forward, os thresholds (quantis) podem ser
    passados explicitamente (calculados apenas no treino). Se nao forem passados,
    sao calculados internamente sobre o df recebido (compatibilidade backward).
    """
    out = df.copy()
    vol = out.get("realized_vol_30m", pd.Series(np.nan, index=out.index)).fillna(0)
    risk = out.get("risk_off_score", pd.Series(0.0, index=out.index)).fillna(0)
    macro = out.get("macro_event_flag", pd.Series(0.0, index=out.index)).fillna(0)

    if vol_q70 is None:
        vol_q70 = float(vol.quantile(0.70)) if vol.notna().any() else 0.0
    if vol_q35 is None:
        vol_q35 = float(vol.quantile(0.35)) if vol.notna().any() else 0.0
    if risk_q70 is None:
        risk_q70 = float(risk.quantile(0.70)) if risk.notna().any() else 0.0

    # Se vol for tudo zero (ex: realized_vol_30m = NaN em dados diarios),
    # os regimes de volatilidade nao sao informativos — marcamos como 0.
    if vol.max() > 0:
        out["regime_high_vol"] = (vol >= vol_q70).astype(int)
        out["regime_low_vol"] = (vol <= vol_q35).astype(int)
    else:
        out["regime_high_vol"] = 0
        out["regime_low_vol"] = 0

    out["regime_event"] = (macro > 0.5).astype(int)
    out["regime_risk_off"] = (risk > risk_q70).astype(int)
    return out
