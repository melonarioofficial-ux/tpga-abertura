"""
TPGA NDX100 - Backtest com dados REAIS via yfinance (sem MT5)
=============================================================
Baixa 3 anos de dados do Yahoo Finance e roda o walk-forward completo.

Como rodar (no seu terminal Windows, dentro da pasta do projeto):
    python RODAR_SEM_MT5_yfinance.py

Requer: pip install yfinance
"""

import sys, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

# ── Verificar dependencias ──────────────────────────────────────────────────
try:
    import yfinance as yf
except ImportError:
    print("ERRO: yfinance nao instalado.")
    print("Rode:  pip install yfinance")
    sys.exit(1)

import numpy as np
import pandas as pd
from tpga.backtest import WalkForwardConfig, walk_forward_validate
from tpga.features import add_gap_labels

# ── Configuracao ────────────────────────────────────────────────────────────
ANOS_HISTORICO = 3
FLAT_THRESHOLD = 5.0   # pontos — gap abaixo disso = "flat"
OUTPUT_CSV  = "dados_reais_ndx.csv"
OUTPUT_MD   = "reports/resultado_real_yfinance.md"

print("=" * 60)
print("  TPGA v14 — Backtest com Dados Reais (yfinance)")
print("=" * 60)
print(f"\nBaixando {ANOS_HISTORICO} anos de dados...")

# ── Download ─────────────────────────────────────────────────────────────────
tickers = {
    "NQ":   "NQ=F",
    "QQQ":  "QQQ",
    "SPY":  "SPY",
    "VIX":  "^VIX",
    "DXY":  "DX-Y.NYB",
    "TNX":  "^TNX",
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "NVDA": "NVDA",
    "AMZN": "AMZN",
    "META": "META",
}

raw = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, period=f"{ANOS_HISTORICO}y", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        raw[name] = df
        print(f"  {name:5s}: {len(df):4d} dias  "
              f"({df.index[0].date()} -> {df.index[-1].date()})")
    except Exception as e:
        print(f"  {name:5s}: FALHA ({e})")
        raw[name] = pd.DataFrame()

nq = raw.get("NQ", pd.DataFrame())
if nq.empty or len(nq) < 200:
    print("\nERRO: Nao foi possivel baixar dados do NQ=F. Verifique sua conexao.")
    sys.exit(1)

# ── Montar dataset de sessoes ────────────────────────────────────────────────
print("\nMontando dataset de sessoes...")

def safe_log_ret(series, idx, lag=1):
    try:
        a = float(series.iloc[idx])
        b = float(series.iloc[max(0, idx - lag)])
        return float(np.log(a / b)) if a > 0 and b > 0 and idx >= lag else np.nan
    except Exception:
        return np.nan

def macro_ret(key, target_date):
    try:
        s = raw[key]["Close"].dropna()
        loc = s.index.get_indexer([target_date], method="ffill")[0]
        if loc < 1:
            return np.nan
        a, b = float(s.iloc[loc]), float(s.iloc[loc - 1])
        return float(np.log(a / b)) if a > 0 and b > 0 else np.nan
    except Exception:
        return np.nan

rows = []
nq_close  = nq["Close"]
nq_open   = nq["Open"]
nq_high   = nq["High"]
nq_low    = nq["Low"]
nq_volume = nq["Volume"]

for i in range(1, len(nq)):
    prev_date = nq.index[i - 1]
    curr_date = nq.index[i]

    prev_close = float(nq_close.iloc[i - 1])
    open_price = float(nq_open.iloc[i])

    if not (np.isfinite(prev_close) and np.isfinite(open_price)):
        continue
    if prev_close <= 0 or open_price <= 0:
        continue

    # --- range position do dia anterior ---
    ph = float(nq_high.iloc[i - 1])
    pl = float(nq_low.iloc[i - 1])
    range_pos = (prev_close - pl) / (ph - pl) if ph > pl else np.nan

    # --- volume z-score (20 dias) ---
    vol_window = nq_volume.iloc[max(0, i - 21):i].astype(float)
    vol_z = np.nan
    if len(vol_window) >= 5:
        mu = float(vol_window[:-1].mean())
        sigma = float(vol_window[:-1].std(ddof=0))
        if sigma > 0:
            vol_z = (float(vol_window.iloc[-1]) - mu) / sigma

    # --- retorno NQ dia anterior (proxy de momentum) ---
    nq_prev_ret = safe_log_ret(nq_close, i - 1)

    # --- macro (retorno do dia anterior de cada ativo) ---
    vix_ret   = macro_ret("VIX", prev_date)
    dxy_ret   = macro_ret("DXY", prev_date)
    us10y_ret = macro_ret("TNX", prev_date)
    qqq_ret   = macro_ret("QQQ", prev_date)
    spy_ret   = macro_ret("SPY", prev_date)

    # --- bigtech ponderado ---
    bigtech_w = {"AAPL": 0.12, "MSFT": 0.12, "NVDA": 0.08, "AMZN": 0.07, "META": 0.05}
    bt_rets, bt_ws = [], []
    for tkr, w in bigtech_w.items():
        r = macro_ret(tkr, prev_date)
        if np.isfinite(r):
            bt_rets.append(r)
            bt_ws.append(w)
    weighted_bt = (
        sum(r * w for r, w in zip(bt_rets, bt_ws)) / sum(bt_ws)
        if bt_ws else np.nan
    )

    rows.append({
        "session_date":   curr_date.date().isoformat(),
        "prev_close":     prev_close,
        "open":           open_price,
        "last_1m_ret":    np.nan,
        "last_5m_ret":    nq_prev_ret,   # proxy: retorno NQ do dia anterior
        "last_15m_ret":   np.nan,
        "close_volume_z": vol_z,
        "vwap_distance":  np.nan,
        "range_position": range_pos,
        "realized_vol_30m": np.nan,
        "futures_overnight_ret":          nq_prev_ret,
        "qqq_premarket_ret":              qqq_ret,
        "spy_premarket_ret":              spy_ret,
        "weighted_bigtech_premarket_ret": weighted_bt,
        "vix_ret":    vix_ret,
        "dxy_ret":    dxy_ret,
        "us10y_ret":  us10y_ret,
        "macro_event_flag":      0,
        "earnings_risk_flag":    0,
        "noii_imbalance_side":   "",
        "noii_imbalance_shares": np.nan,
        "noii_paired_shares":    np.nan,
        "noii_near_price":       np.nan,
        "noii_far_price":        np.nan,
        "noii_reference_price":  np.nan,
        "mt5_spread_points_at_signal": np.nan,
    })

df_real = pd.DataFrame(rows)
df_real.to_csv(OUTPUT_CSV, index=False)

# Distribuicao de classes
labeled = add_gap_labels(df_real, flat_threshold_points=FLAT_THRESHOLD)
dist = labeled["direction"].value_counts()
print(f"\nDataset real: {len(df_real)} sessoes")
print(f"Periodo:      {df_real.session_date.iloc[0]} -> {df_real.session_date.iloc[-1]}")
print(f"Threshold:    ±{FLAT_THRESHOLD} pts")
print("\nDistribuicao de gaps:")
for k, v in dist.items():
    bar = "█" * int(v / len(df_real) * 40)
    print(f"  {k:6s}: {v:4d} ({v/len(df_real):.1%})  {bar}")

# ── Walk-Forward ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Rodando walk-forward com dados REAIS...")
print("(isso leva ~30-60s dependendo do hardware)")
print("=" * 60)

cfg = WalkForwardConfig(
    min_train_size=120,
    test_size=60,
    step_size=60,
    random_state=42,
    flat_threshold_points=FLAT_THRESHOLD,
    edge_threshold=0.12,
    confidence_threshold=0.48,
    fakeout_max=0.70,
    cost_points=2.0,
)

t0 = time.time()
pred, metrics = walk_forward_validate(df_real, cfg)
elapsed = time.time() - t0

# ── Resultados ───────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RESULTADOS — DADOS REAIS NDX100 ({elapsed:.0f}s)")
print(f"{'='*60}")
print(f"\nSessoes testadas: {len(pred)} | Folds: {metrics['folds']} | Features: {metrics['feature_count']}")

prob = metrics["probabilistic"]
base = metrics["baselines"]
op   = metrics["operational_paper"]

print("\n--- MODELO vs BASELINES (fora da amostra) ---")
print(f"  {'Metrica':<28} {'TPGA v14':>10} {'Futuros':>10} {'Maioria':>10}")
print(f"  {'-'*58}")
print(f"  {'Acuracia':<28} {prob['accuracy']:>9.1%} {base.get('futures_accuracy',0):>9.1%} {base.get('majority_accuracy',0):>9.1%}")
print(f"  {'MCC':<28} {prob['mcc_multiclass']:>10.4f} {base.get('futures_mcc',0):>10.4f} {base.get('majority_mcc',0):>10.4f}")
print(f"  {'AUC (up vs rest)':<28} {(prob['auc_up'] or 0):>10.4f}")
print(f"  {'Brier Score':<28} {prob['brier_up']:>10.4f}")
print(f"  {'Log Loss':<28} {(prob['log_loss'] or 0):>10.4f}")

print("\n--- OPERACIONAL (simulacao paper, sem ordens reais) ---")
print(f"  Casos operados:  {op['study_cases']} de {op['rows']} ({op['study_case_rate']:.1%})")
hr = op.get("hit_rate_study_cases")
ev = op.get("ev_points_per_study_case")
pf = op.get("profit_factor")
print(f"  Hit Rate:        {f'{hr:.1%}' if hr is not None else 'n/a'}")
print(f"  EV por trade:    {f'{ev:.1f} pts' if ev is not None else 'n/a'}")
print(f"  PnL total:       {op['total_pnl_points']:.1f} pts")
print(f"  Max Drawdown:    {op['max_drawdown_points']:.1f} pts")
print(f"  Profit Factor:   {f'{pf:.2f}' if pf is not None else 'n/a'}")

if "bootstrap" in metrics and "error" not in metrics["bootstrap"]:
    bs = metrics["bootstrap"]
    print("\n--- BOOTSTRAP IC95% ---")
    for k in ["auc_up", "mcc_multiclass", "accuracy", "brier_up", "ev_points_per_study_case"]:
        if k in bs and bs[k]["mean"] is not None:
            m = bs[k]
            sig = "(*)" if (m["ci95_lower"] > 0 or m["ci95_upper"] < 0) else ""
            print(f"  {k:<30} media={m['mean']:.4f}  IC95=[{m['ci95_lower']:.4f}, {m['ci95_upper']:.4f}] {sig}")

if "by_regime" in metrics and metrics["by_regime"]:
    print("\n--- METRICAS POR REGIME ---")
    for reg, rm in metrics["by_regime"].items():
        acc = rm["probabilistic"]["accuracy"]
        mcc = rm["probabilistic"]["mcc_multiclass"]
        n   = rm["n"]
        ev2 = rm["operational"].get("ev_points_per_study_case")
        print(f"  {reg:<35} n={n:3d}  acc={acc:.1%}  mcc={mcc:.3f}  EV={f'{ev2:.1f}pts' if ev2 else 'n/a'}")

# ── Salvar relatorio ─────────────────────────────────────────────────────────
import os
os.makedirs("reports", exist_ok=True)
from tpga.report import save_report
save_report(OUTPUT_MD, pred, metrics, title="TPGA v14 — Dados Reais yfinance NDX100")
pred.to_csv(OUTPUT_CSV.replace(".csv", "_predictions.csv"), index=False)

print(f"\n{'='*60}")
print(f"Relatorio salvo: {OUTPUT_MD}")
print(f"Previsoes salvas: {OUTPUT_CSV.replace('.csv','_predictions.csv')}")
print(f"{'='*60}")

# ── Sinal atual ──────────────────────────────────────────────────────────────
print("\n--- SINAL DE HOJE (baseado em dados do dia anterior) ---")
last = pred.sort_values("session_date").iloc[-1]
print(f"  Data:         {last['session_date']}")
print(f"  P(up):        {last.get('p_up', 0):.1%}")
print(f"  P(down):      {last.get('p_down', 0):.1%}")
print(f"  P(flat):      {last.get('p_flat', 0):.1%}")
print(f"  Edge:         {last.get('edge', 0):.4f}")
print(f"  Fakeout Risk: {last.get('fakeout_risk', 0):.2f}")
sc = last.get("study_candidate", False)
print(f"  Sinal valido: {'SIM — OPERAR (papel)' if sc else 'NAO — aguardar'}")
print()
print("AVISO: Sinal educacional. Nao e recomendacao de investimento.")
