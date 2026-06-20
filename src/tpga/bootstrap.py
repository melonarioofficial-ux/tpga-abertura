from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import probabilistic_metrics, operational_metrics


def block_bootstrap_metrics(
    df: pd.DataFrame,
    n_iterations: int = 200,
    block_size: int = 20,
    random_state: int = 42,
    cost_points: float = 2.0,
) -> dict:
    """Block bootstrap circular para IC95% das métricas."""
    rng = np.random.default_rng(random_state)
    n = len(df)
    if n < block_size * 2:
        return {"error": "Poucos dados para bootstrap", "n": n}

    prob_keys = ["brier_up", "log_loss", "auc_up", "mcc_multiclass", "accuracy"]
    op_keys = ["hit_rate_study_cases", "ev_points_per_study_case", "profit_factor", "max_drawdown_points"]

    boot_results = {k: [] for k in prob_keys + op_keys}

    for _ in range(n_iterations):
        n_blocks = int(np.ceil(n / block_size))
        starts = rng.integers(0, n, size=n_blocks)
        indices = []
        for s in starts:
            for j in range(block_size):
                indices.append(int((s + j) % n))
        indices = indices[:n]
        sample = df.iloc[indices].copy().reset_index(drop=True)

        try:
            pm = probabilistic_metrics(sample)
            for k in prob_keys:
                v = pm.get(k)
                if v is not None and np.isfinite(float(v)):
                    boot_results[k].append(float(v))
        except Exception:
            pass

        try:
            om = operational_metrics(sample, cost_points=cost_points)
            for k in op_keys:
                v = om.get(k)
                if v is not None and np.isfinite(float(v)):
                    boot_results[k].append(float(v))
        except Exception:
            pass

    summary = {}
    for k, vals in boot_results.items():
        if not vals:
            summary[k] = {"mean": None, "ci95_lower": None, "ci95_upper": None, "n_valid": 0}
        else:
            arr = np.array(vals)
            summary[k] = {
                "mean": float(np.mean(arr)),
                "ci95_lower": float(np.percentile(arr, 2.5)),
                "ci95_upper": float(np.percentile(arr, 97.5)),
                "n_valid": len(vals),
            }
    return summary
