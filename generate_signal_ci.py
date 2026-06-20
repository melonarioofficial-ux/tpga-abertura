"""
TPGA — Gerador de sinais diários (CI/CD, sem MT5)
===================================================
Rodado pelo GitHub Actions às 10h BRT em dias úteis.

Gera 3 sinais via yfinance e salva em public/:
  public/signal.json          -> NDX100  (Nasdaq)
  public/signal_xauusd.json   -> XAUUSD  (Ouro)
  public/signal_dax.json      -> DAX 40  (Alemanha)

Instrumentos selecionados por edge estatistico confirmado:
  NDX100  - AUC>0.57(*), MCC>0.10(*), EV confirmado (*)
  XAUUSD  - AUC>0.56(*), MCC>0.13(*), EV confirmado (*)
  DAX 40  - AUC>0.54(*), EV=+45 pts(*), PF=3.83 confirmado
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

try:
    import yfinance  # noqa
except ImportError:
    print("ERRO: yfinance nao instalado. Rode: pip install -r requirements_ci.txt")
    sys.exit(1)

from tpga.signal_engine import SYMBOLS, build_yf_dataset, fetch_live_macro, run_signal_pipeline

# Configuracao
INSTRUMENTS = ["ndx", "xau", "dax"]

OUTPUT_MAP = {
    "ndx": "public/signal.json",
    "xau": "public/signal_xauusd.json",
    "dax": "public/signal_dax.json",
}

t_start = time.time()
sep = "=" * 65

print(sep)
print("  TPGA CI/CD -- sinais diarios de abertura de mercado")
print("  NDX100 | XAUUSD | DAX 40")
print(sep)

successes = []
failures = []

for key in INSTRUMENTS:
    cfg = SYMBOLS[key]
    print(f"\n{'-'*55}")
    print(f"  [{key.upper()}] {cfg.label}")
    print(f"  flat={cfg.flat_threshold} {cfg.unit}  |  custo={cfg.cost_points} {cfg.unit}/trade")
    print(f"{'-'*55}")

    t0 = time.time()

    df = build_yf_dataset(cfg, verbose=True)
    if df is None or len(df) < 120:
        print(f"  SKIP: dados insuficientes para {cfg.name}")
        failures.append(key)
        continue

    macro = fetch_live_macro(cfg)
    filled = sum(1 for v in macro.values() if v is not None)
    print(f"  Macro hoje: {filled}/7 features preenchidas")

    try:
        payload, _, metrics = run_signal_pipeline(
            cfg, df,
            mt5_bars=None,
            today_macro=macro,
            source_mode=f"yfinance_ci_{key}",
        )
    except Exception as e:
        print(f"  ERRO no pipeline: {e}")
        failures.append(key)
        continue

    out = Path(OUTPUT_MAP[key])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    dur  = time.time() - t0
    dec  = payload["decisao"]
    edge = payload["edge"]
    pu   = payload["p_up"]
    pd_  = payload["p_down"]
    prob = metrics.get("probabilistic", {})
    auc  = prob.get("auc_up", 0) or 0
    mcc  = prob.get("mcc_multiclass", 0) or 0

    print(f"  AUC={auc:.4f}  MCC={mcc:.4f}  ({dur:.0f}s)")
    print(f"  -> {dec}  Edge={edge:+.4f}  P_up={pu:.1%}  P_down={pd_:.1%}")
    print(f"  Salvo: {out}")
    successes.append(key)

total = time.time() - t_start
print(f"\n{sep}")
print(f"  Concluido em {total:.0f}s  |  {len(successes)}/{len(INSTRUMENTS)} sinais gerados")
if successes:
    print(f"  OK:    {successes}")
if failures:
    print(f"  FALHA: {failures}")
print(sep)

if len(successes) == 0:
    sys.exit(1)
