from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
import pandas as pd


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def build_markdown_report(predictions: pd.DataFrame, metrics: Dict[str, Any], title: str = "Relatorio TPGA") -> str:
    prob = metrics.get("probabilistic", {})
    op = metrics.get("operational_paper", {})
    base = metrics.get("baselines", {})
    lines = [
        f"# {title}",
        "",
        "## Resumo honesto",
        "",
        "Este relatorio valida o pipeline estatistico em modo educacional/paper. Ele nao e recomendacao de investimento e nao prova lucro real sem dados reais, custos, spread e sessao corretos.",
        "",
        "## Metricas probabilisticas fora da amostra",
        "",
        "| Metrica | Valor |",
        "|---|---:|",
    ]
    for key in ["brier_up", "log_loss", "auc_up", "mcc_multiclass", "accuracy"]:
        lines.append(f"| {key} | {_fmt(prob.get(key))} |")

    lines += [
        "",
        "## Baselines simples",
        "",
        "| Baseline | Valor |",
        "|---|---:|",
    ]
    for key in ["majority_accuracy", "majority_mcc", "futures_accuracy", "futures_mcc", "close_accuracy", "close_mcc"]:
        lines.append(f"| {key} | {_fmt(base.get(key))} |")

    lines += [
        "",
        "## Simulacao educacional filtrada por edge",
        "",
        "| Metrica | Valor |",
        "|---|---:|",
    ]
    for key in ["rows", "study_cases", "study_case_rate", "hit_rate_study_cases", "total_pnl_points", "ev_points_per_study_case", "max_drawdown_points", "profit_factor"]:
        lines.append(f"| {key} | {_fmt(op.get(key))} |")

    boot = metrics.get("bootstrap", {})
    if boot and "error" not in boot:
        lines += [
            "",
            "## Bootstrap IC95% (block bootstrap circular)",
            "",
            "Intervalos de confianca a 95% das metricas, via reamostragem em blocos para preservar autocorrelacao temporal.",
            "",
            "| Metrica | Media | IC95% inferior | IC95% superior | n validos |",
            "|---|---:|---:|---:|---:|",
        ]
        boot_keys = [
            "brier_up", "log_loss", "auc_up", "mcc_multiclass", "accuracy",
            "hit_rate_study_cases", "ev_points_per_study_case", "profit_factor", "max_drawdown_points",
        ]
        for key in boot_keys:
            stat = boot.get(key)
            if isinstance(stat, dict):
                mean = _fmt(stat.get("mean"))
                lo = _fmt(stat.get("ci95_lower"))
                hi = _fmt(stat.get("ci95_upper"))
                nv = _fmt(stat.get("n_valid"))
                lines.append(f"| {key} | {mean} | {lo} | {hi} | {nv} |")
    elif isinstance(boot, dict) and boot.get("error"):
        lines += [
            "",
            "## Bootstrap IC95%",
            "",
            f"Bootstrap nao executado: {boot.get('error')} (n={boot.get('n')}).",
        ]

    by_regime = metrics.get("by_regime", {})
    if by_regime:
        lines += [
            "",
            "## Metricas por Regime",
            "",
            "Desempenho condicional a cada regime de mercado (subconjuntos com n >= 20).",
            "",
            "| Regime | n | accuracy | mcc | auc_up | hit_rate | EV/caso | profit_factor |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for key in sorted(by_regime.keys()):
            rm = by_regime[key]
            prob_r = rm.get("probabilistic", {})
            op_r = rm.get("operational", {})
            n_r = _fmt(rm.get("n"))
            acc = _fmt(prob_r.get("accuracy"))
            mcc = _fmt(prob_r.get("mcc_multiclass"))
            auc = _fmt(prob_r.get("auc_up"))
            hit = _fmt(op_r.get("hit_rate_study_cases"))
            ev = _fmt(op_r.get("ev_points_per_study_case"))
            pf = _fmt(op_r.get("profit_factor"))
            lines.append(f"| {key} | {n_r} | {acc} | {mcc} | {auc} | {hit} | {ev} | {pf} |")

    lines += [
        "",
        "## Primeiras previsoes fora da amostra",
        "",
    ]
    cols = ["session_date", "prev_close", "open", "gap_points", "direction", "p_up", "p_down", "p_flat", "edge", "fakeout_risk", "study_candidate"]
    visible = predictions[[c for c in cols if c in predictions.columns]].head(20).copy()
    if "session_date" in visible.columns:
        visible["session_date"] = visible["session_date"].astype(str)
    # Gera tabela markdown sem dependencia de tabulate
    def _df_to_md(df: pd.DataFrame) -> str:
        header = "| " + " | ".join(str(c) for c in df.columns) + " |"
        sep    = "| " + " | ".join("---" for _ in df.columns) + " |"
        rows_md = []
        for _, row in df.iterrows():
            cells = []
            for v in row:
                if isinstance(v, float):
                    cells.append(f"{v:.4f}" if not (v != v) else "")
                else:
                    cells.append(str(v))
            rows_md.append("| " + " | ".join(cells) + " |")
        return "\n".join([header, sep] + rows_md)

    lines.append(_df_to_md(visible))

    lines += [
        "",
        "## Feature count",
        "",
        f"Features usadas: {metrics.get('feature_count', 'n/a')}",
        "",
        "## Criterio de aprovacao",
        "",
        "A teoria so deve ser considerada operacionalmente promissora se Brier/LogLoss vencerem baselines, MCC for positivo, o resultado sobreviver a custos e o drawdown nao estiver concentrado em poucos eventos.",
    ]
    return "\n".join(lines)


def save_report(path: str | Path, predictions: pd.DataFrame, metrics: Dict[str, Any], title: str = "Relatorio TPGA") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown_report(predictions, metrics, title=title), encoding="utf-8")


def save_predictions(path: str | Path, predictions: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(path, index=False)
