from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, matthews_corrcoef, accuracy_score


def max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    peak = equity.cummax()
    dd = equity - peak
    return float(dd.min())


def safe_auc(y_true: pd.Series, y_score: pd.Series) -> float | None:
    try:
        if len(pd.Series(y_true).dropna().unique()) < 2:
            return None
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return None


def safe_log_loss(y_true_labels: pd.Series, proba: pd.DataFrame, labels: list[str]) -> float | None:
    try:
        return float(log_loss(y_true_labels, proba[labels], labels=labels))
    except Exception:
        return None


def probabilistic_metrics(df: pd.DataFrame) -> dict:
    y_up = (df["direction"] == "up").astype(int)
    p_up = df["p_up"].clip(1e-6, 1 - 1e-6)
    labels = ["down", "flat", "up"]
    proba = pd.DataFrame({label: df[f"p_{label}"].clip(1e-6, 1 - 1e-6) for label in labels})
    proba = proba.div(proba.sum(axis=1), axis=0)
    pred = proba.idxmax(axis=1)
    return {
        "brier_up": float(brier_score_loss(y_up, p_up)),
        "log_loss": safe_log_loss(df["direction"].astype(str), proba, labels),
        "auc_up": safe_auc(y_up, p_up),
        "mcc_multiclass": float(matthews_corrcoef(df["direction"].astype(str), pred.astype(str))) if len(df) else 0.0,
        "accuracy": float(accuracy_score(df["direction"].astype(str), pred.astype(str))) if len(df) else 0.0,
    }


def operational_metrics(df: pd.DataFrame, cost_points: float = 2.0) -> dict:
    out = df.copy()
    out["paper_pnl_points"] = np.where(out["study_candidate"], out["side"] * out["gap_points"] - cost_points, 0.0)
    study_cases = out[out["study_candidate"]].copy()
    equity = out["paper_pnl_points"].cumsum()
    wins = study_cases[study_cases["paper_pnl_points"] > 0]
    losses = study_cases[study_cases["paper_pnl_points"] < 0]
    gross_win = wins["paper_pnl_points"].sum() if len(wins) else 0.0
    gross_loss = -losses["paper_pnl_points"].sum() if len(losses) else 0.0
    return {
        "rows": int(len(out)),
        "study_cases": int(len(study_cases)),
        "study_case_rate": float(len(study_cases) / len(out)) if len(out) else 0.0,
        "hit_rate_study_cases": float((study_cases["paper_pnl_points"] > 0).mean()) if len(study_cases) else None,
        "total_pnl_points": float(study_cases["paper_pnl_points"].sum()) if len(study_cases) else 0.0,
        "ev_points_per_study_case": float(study_cases["paper_pnl_points"].mean()) if len(study_cases) else None,
        "max_drawdown_points": max_drawdown(equity),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else None,
    }


def baseline_metrics(df: pd.DataFrame) -> dict:
    y = df["direction"].astype(str)
    out = {}
    if "base_futures_pred" in df.columns:
        out["futures_accuracy"] = float(accuracy_score(y, df["base_futures_pred"].astype(str)))
        out["futures_mcc"] = float(matthews_corrcoef(y, df["base_futures_pred"].astype(str)))
    if "base_close_pred" in df.columns:
        out["close_accuracy"] = float(accuracy_score(y, df["base_close_pred"].astype(str)))
        out["close_mcc"] = float(matthews_corrcoef(y, df["base_close_pred"].astype(str)))
    maj_cols = ["base_majority_p_down", "base_majority_p_flat", "base_majority_p_up"]
    if all(c in df.columns for c in maj_cols):
        pred = pd.Series(
            np.select(
                [df["base_majority_p_down"] == 1, df["base_majority_p_flat"] == 1, df["base_majority_p_up"] == 1],
                ["down", "flat", "up"],
                default="flat",
            ),
            index=df.index,
        )
        out["majority_accuracy"] = float(accuracy_score(y, pred.astype(str)))
        out["majority_mcc"] = float(matthews_corrcoef(y, pred.astype(str)))
    return out
