"""
EXPERIMENTO — features candidatas (rigoroso, out-of-sample)
===========================================================
NAO altera producao. Mede, via walk-forward, se features novas melhoram
o AUC/MCC out-of-sample de cada instrumento. So devem ser promovidas as
que melhoram de forma consistente.

Candidatas (todas PAST-ONLY, sem lookahead, sem novos tickers):
  prev_gap_pct      gap (open/prev_close-1) da sessao anterior
  gap_5d_mean       media dos ultimos 5 gaps (deslocada)
  gap_5d_std        desvio dos ultimos 5 gaps
  close_sma5_dist   distancia do prev_close a SMA5
  close_sma10_dist  distancia do prev_close a SMA10
  rv_10d            volatilidade realizada 10d (retornos diarios)
  dow               dia da semana (0=seg..4=sex)
  is_monday         1 se segunda-feira
"""
from __future__ import annotations
import sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

import yfinance as yf
import tpga.features as F
from tpga.signal_engine import SYMBOLS, build_yf_dataset, ACTIVE_INSTRUMENTS
from tpga.backtest import WalkForwardConfig, walk_forward_validate

NEW_FEATURES = [
    "prev_gap_pct", "gap_5d_mean", "gap_5d_std",
    "close_sma5_dist", "close_sma10_dist", "rv_10d",
    "dow", "is_monday",
]

ORIGINAL_BASE = list(F.BASE_FEATURES)  # snapshot para restaurar


def engineered(cfg) -> pd.DataFrame:
    """Features de momentum/tendencia/vol/calendario, alinhadas por session_date.
    Tudo deslocado para usar SOMENTE informacao disponivel antes da abertura."""
    main = yf.download(cfg.symbol_yf, period=f"{cfg.years_history}y",
                       progress=False, auto_adjust=True)
    if isinstance(main.columns, pd.MultiIndex):
        main.columns = [c[0] for c in main.columns]
    main = main.dropna(subset=["Open", "Close"])

    pc   = main["Close"].shift(1)
    gpct = (main["Open"] - pc) / pc            # gap % da sessao
    ret  = np.log(main["Close"] / main["Close"].shift(1))
    sma5  = main["Close"].rolling(5).mean()
    sma10 = main["Close"].rolling(10).mean()
    dow   = pd.Series(main.index.dayofweek, index=main.index)

    f = pd.DataFrame(index=main.index)
    f["session_date"]     = [d.date().isoformat() for d in main.index]
    f["prev_gap_pct"]     = gpct.shift(1)                      # gap de ontem (passado)
    f["gap_5d_mean"]      = gpct.shift(1).rolling(5).mean()
    f["gap_5d_std"]       = gpct.shift(1).rolling(5).std()
    f["close_sma5_dist"]  = (main["Close"].shift(1) / sma5.shift(1) - 1.0)
    f["close_sma10_dist"] = (main["Close"].shift(1) / sma10.shift(1) - 1.0)
    f["rv_10d"]           = ret.shift(1).rolling(10).std()
    f["dow"]              = dow.astype(float)
    f["is_monday"]        = (dow == 0).astype(float)
    return f.reset_index(drop=True)


def run_wf(raw: pd.DataFrame, cfg, feature_list):
    """Roda walk-forward com uma lista de features especifica (monkeypatch em memoria)."""
    F.BASE_FEATURES = list(feature_list)
    wf_cfg = WalkForwardConfig(
        min_train_size=120, test_size=60, step_size=60, random_state=42,
        flat_threshold_points=cfg.flat_threshold,
        edge_threshold=0.12, confidence_threshold=0.48,
        fakeout_max=0.70, cost_points=cfg.cost_points,
    )
    _, metrics = walk_forward_validate(raw, wf_cfg)
    p  = metrics["probabilistic"]
    op = metrics["operational_paper"]
    return {
        "auc": float(p.get("auc_up") or 0),
        "mcc": float(p.get("mcc_multiclass") or 0),
        "acc": float(p.get("accuracy") or 0),
        "ev":  float(op.get("ev_points_per_study_case") or 0),
        "pf":  float(op.get("profit_factor") or 0),
        "hit": float(op.get("hit_rate_study_cases") or 0),
        "cases": int(op.get("study_cases") or 0),
    }


def main():
    print("=" * 72)
    print("  EXPERIMENTO DE FEATURES — baseline vs aumentado (out-of-sample)")
    print("=" * 72)

    summary = []
    for key in ACTIVE_INSTRUMENTS:
        cfg = SYMBOLS[key]
        print(f"\n[{key.upper()}] {cfg.label} — baixando e construindo dataset...")
        raw = build_yf_dataset(cfg, verbose=False)
        if raw is None or len(raw) < 150:
            print(f"  SKIP: dados insuficientes."); continue

        eng = engineered(cfg)
        raw_aug = raw.merge(eng, on="session_date", how="left")

        print("  Rodando BASELINE (features atuais)...")
        base = run_wf(raw, cfg, ORIGINAL_BASE)

        print("  Rodando AUMENTADO (+8 candidatas)...")
        aug = run_wf(raw_aug, cfg, ORIGINAL_BASE + NEW_FEATURES)

        d_auc = aug["auc"] - base["auc"]
        d_mcc = aug["mcc"] - base["mcc"]
        verdict = "MELHOROU" if (d_auc > 0.003 and d_mcc >= -0.005) or (d_mcc > 0.01 and d_auc >= -0.003) else "neutro/pior"
        summary.append((key, base, aug, d_auc, d_mcc, verdict))

        print(f"  AUC:  {base['auc']:.4f} -> {aug['auc']:.4f}  ({d_auc:+.4f})")
        print(f"  MCC:  {base['mcc']:.4f} -> {aug['mcc']:.4f}  ({d_mcc:+.4f})")
        print(f"  Acc:  {base['acc']:.4f} -> {aug['acc']:.4f}")
        print(f"  EV :  {base['ev']:+.2f} -> {aug['ev']:+.2f}   PF: {base['pf']:.2f} -> {aug['pf']:.2f}")
        print(f"  >>> {verdict}")

    F.BASE_FEATURES = ORIGINAL_BASE  # restaura
    print("\n" + "=" * 72)
    print("  RESUMO")
    print("=" * 72)
    for key, base, aug, d_auc, d_mcc, verdict in summary:
        print(f"  {key.upper():4}  AUC {base['auc']:.3f}->{aug['auc']:.3f} ({d_auc:+.3f}) | "
              f"MCC {base['mcc']:.3f}->{aug['mcc']:.3f} ({d_mcc:+.3f}) | {verdict}")
    print("=" * 72)


if __name__ == "__main__":
    main()
