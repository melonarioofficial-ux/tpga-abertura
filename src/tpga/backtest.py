from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any
import numpy as np
import pandas as pd

from .features import build_features
from .regime import add_regime_features
from .model import fit_predict_proba, add_decision_columns, baseline_predictions
from .metrics import probabilistic_metrics, operational_metrics, baseline_metrics
from .bootstrap import block_bootstrap_metrics


@dataclass
class WalkForwardConfig:
    min_train_size: int = 120
    test_size: int = 30
    step_size: int = 30
    random_state: int = 42
    flat_threshold_points: float = 5.0
    edge_threshold: float = 0.12
    confidence_threshold: float = 0.48
    fakeout_max: float = 0.70
    cost_points: float = 2.0


def walk_forward_validate(raw: pd.DataFrame, cfg: WalkForwardConfig) -> tuple[pd.DataFrame, Dict[str, Any]]:
    df, features = build_features(raw, flat_threshold_points=cfg.flat_threshold_points)
    # NAO aplicar add_regime_features no dataset completo (lookahead bias).
    # Os regimes sao calculados por fold, com quantis estimados so no treino.
    df = df.sort_values("session_date").reset_index(drop=True)

    regime_feature_names = ["regime_high_vol", "regime_low_vol", "regime_event", "regime_risk_off"]
    features = features + regime_feature_names

    predictions = []
    start = cfg.min_train_size
    fold = 0
    while start < len(df):
        end = min(start + cfg.test_size, len(df))
        train = df.iloc[:start].copy()
        test = df.iloc[start:end].copy()
        if len(test) == 0:
            break

        # Quantis de regime calculados SOMENTE no treino e aplicados ao teste.
        train_vol = train.get("realized_vol_30m", pd.Series(dtype=float)).fillna(0)
        # Se vol for tudo zero (dados diarios sem intraday), quantis ficam em 0
        # e regime.py trata esse caso retornando regime_*_vol = 0 para todos.
        vol_q70 = float(train_vol.quantile(0.70)) if train_vol.max() > 0 else 0.0
        vol_q35 = float(train_vol.quantile(0.35)) if train_vol.max() > 0 else 0.0
        risk_col = train.get("risk_off_score", pd.Series(dtype=float)).fillna(0)
        risk_q70 = float(risk_col.quantile(0.70)) if len(risk_col) > 0 else 0.0

        train = add_regime_features(train, vol_q70=vol_q70, vol_q35=vol_q35, risk_q70=risk_q70)
        test = add_regime_features(test, vol_q70=vol_q70, vol_q35=vol_q35, risk_q70=risk_q70)

        # Magnitude tipica de gap estimada apenas no treino (evita usar gap futuro).
        median_abs_gap_train = float(train["gap_points"].abs().median())

        pred = fit_predict_proba(train, test, features, random_state=cfg.random_state + fold).frame
        pred = baseline_predictions(pred, train)
        pred = add_decision_columns(
            pred,
            edge_threshold=cfg.edge_threshold,
            confidence_threshold=cfg.confidence_threshold,
            fakeout_max=cfg.fakeout_max,
            cost_points=cfg.cost_points,
            median_abs_gap=median_abs_gap_train,
        )
        pred["fold"] = fold
        predictions.append(pred)
        fold += 1
        start += cfg.step_size

    if not predictions:
        raise ValueError("Dados insuficientes para walk-forward. Aumente o historico ou reduza min_train_size.")

    result = pd.concat(predictions, ignore_index=True)

    metrics = {
        "probabilistic": probabilistic_metrics(result),
        "operational_paper": operational_metrics(result, cost_points=cfg.cost_points),
        "baselines": baseline_metrics(result),
        "folds": int(result["fold"].nunique()),
        "feature_count": len(features),
        "features": features,
    }

    # Bootstrap em bloco para IC95% das metricas.
    metrics["bootstrap"] = block_bootstrap_metrics(result, cost_points=cfg.cost_points)

    # Metricas estratificadas por regime.
    regime_cols = [c for c in result.columns if c.startswith("regime_")]
    regime_metrics: Dict[str, Any] = {}
    for col in regime_cols:
        for val in [0, 1]:
            subset = result[result[col] == val]
            if len(subset) >= 20:
                key = f"{col}={val}"
                try:
                    regime_metrics[key] = {
                        "n": int(len(subset)),
                        "probabilistic": probabilistic_metrics(subset),
                        "operational": operational_metrics(subset, cost_points=cfg.cost_points),
                    }
                except Exception:
                    pass
    metrics["by_regime"] = regime_metrics

    return result, metrics
