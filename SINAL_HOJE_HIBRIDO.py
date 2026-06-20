"""
TPGA NDX100 — Sinal Híbrido: yfinance (treino/backtest) + MT5 (intraday ao vivo)
==================================================================================
Arquitetura:
  1. Baixa 3 anos de histórico via yfinance  →  treino + walk-forward
  2. Conecta ao MT5 e puxa barras M1 recentes  →  features intraday de hoje
  3. yfinance busca macro do pré-mercado de hoje  →  VIX, DXY, TNX, QQQ, SPY
  4. Sinal híbrido: treino com histórico rico (yfinance) + snapshot com M1 real (MT5)

Vantagem sobre usar só MT5:
  - Treino usa 3 anos (756+ sessões) em vez dos ~68 do broker
  - Macro features (QQQ, VIX, etc.) estão presentes no treino E na previsão
  - Features intraday reais (vwap_distance, realized_vol_30m, last_1m_ret) do MT5

Como rodar (VS Code PowerShell, dentro de C:\\50-Robo_abertura_Python):
    python SINAL_HOJE_HIBRIDO.py

Requer:
    pip install yfinance
    MetaTrader 5 aberto e logado com NDX100 visível no Market Watch

Saída:
    reports/sinal_hibrido_hoje.json   — snapshot do sinal
    reports/resultado_hibrido.md      — relatório de validação walk-forward
    dados_reais_ndx.csv               — dataset histórico (cache local)

AVISO: Sinal educacional/paper. Não envia ordens. Não é recomendação de investimento.
"""

from __future__ import annotations

import sys, warnings, time, json, os
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

# ── Dependências obrigatórias ───────────────────────────────────────────────
try:
    import yfinance as yf
except ImportError:
    print("ERRO: yfinance não instalado.")
    print("Rode:  pip install yfinance")
    sys.exit(1)

import numpy as np
import pandas as pd

from tpga.backtest import WalkForwardConfig, walk_forward_validate
from tpga.features import add_gap_labels
from tpga.live_signal import build_current_feature_row, train_and_score_current
from tpga.mt5_gap_builder import GapSessionConfig
from tpga.report import save_report
from tpga.market_data import fetch_premarket_features

# ── Configuração ────────────────────────────────────────────────────────────
ANOS_HISTORICO  = 3
FLAT_THRESHOLD  = 5.0       # pontos — gap abaixo disso = "flat"
MT5_SYMBOL      = "NDX100"
TIMEZONE        = "America/Sao_Paulo"
CLOSE_TIME      = "17:59"
OPEN_TIME       = "19:00"
LOOKBACK_MIN    = 240       # janela de features intraday (4h antes do fechamento)
HISTORY_BARS_MT5 = 2000     # barras M1 recentes para features de hoje (~33h)
OUTPUT_CSV      = "dados_reais_ndx.csv"
OUTPUT_MD       = "reports/resultado_hibrido.md"
OUTPUT_SIGNAL   = "reports/sinal_hibrido_hoje.json"

print("=" * 65)
print("  TPGA v14 — Sinal Híbrido (yfinance backtest + MT5 intraday)")
print("=" * 65)


# ──────────────────────────────────────────────────────────────────────────────
# FASE 1 — Histórico yfinance (treino)
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n[1/4] Baixando {ANOS_HISTORICO} anos de histórico via yfinance...")

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
              f"({df.index[0].date()} → {df.index[-1].date()})")
    except Exception as e:
        print(f"  {name:5s}: FALHA ({e})")
        raw[name] = pd.DataFrame()

nq = raw.get("NQ", pd.DataFrame())
if nq.empty or len(nq) < 200:
    print("\nERRO: Não foi possível baixar NQ=F. Verifique a conexão.")
    sys.exit(1)


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


print("\nMontando dataset histórico de sessões...")

nq_close  = nq["Close"]
nq_open   = nq["Open"]
nq_high   = nq["High"]
nq_low    = nq["Low"]
nq_volume = nq["Volume"]

rows = []
for i in range(1, len(nq)):
    prev_date = nq.index[i - 1]
    curr_date = nq.index[i]
    prev_close = float(nq_close.iloc[i - 1])
    open_price = float(nq_open.iloc[i])
    if not (np.isfinite(prev_close) and np.isfinite(open_price)):
        continue
    if prev_close <= 0 or open_price <= 0:
        continue

    ph = float(nq_high.iloc[i - 1])
    pl = float(nq_low.iloc[i - 1])
    range_pos = (prev_close - pl) / (ph - pl) if ph > pl else np.nan

    vol_window = nq_volume.iloc[max(0, i - 21):i].astype(float)
    vol_z = np.nan
    if len(vol_window) >= 5:
        mu = float(vol_window[:-1].mean())
        sigma = float(vol_window[:-1].std(ddof=0))
        if sigma > 0:
            vol_z = (float(vol_window.iloc[-1]) - mu) / sigma

    nq_prev_ret = safe_log_ret(nq_close, i - 1)
    vix_ret     = macro_ret("VIX", prev_date)
    dxy_ret     = macro_ret("DXY", prev_date)
    us10y_ret   = macro_ret("TNX", prev_date)
    qqq_ret     = macro_ret("QQQ", prev_date)
    spy_ret     = macro_ret("SPY", prev_date)

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
        "last_5m_ret":    nq_prev_ret,
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

labeled = add_gap_labels(df_real, flat_threshold_points=FLAT_THRESHOLD)
dist = labeled["direction"].value_counts()
print(f"\n  Dataset histórico: {len(df_real)} sessões  "
      f"({df_real.session_date.iloc[0]} → {df_real.session_date.iloc[-1]})")
print(f"  Distribuição:  ", end="")
for k, v in dist.items():
    print(f"{k}={v} ({v/len(df_real):.0%})  ", end="")
print()


# ──────────────────────────────────────────────────────────────────────────────
# FASE 2 — Walk-forward no histórico yfinance (validação)
# ──────────────────────────────────────────────────────────────────────────────
print("\n[2/4] Walk-forward no histórico yfinance...")
print("      (valida a teoria com 3 anos de dados — ~30 a 60s)")

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

prob = metrics["probabilistic"]
base = metrics["baselines"]
op   = metrics["operational_paper"]

print(f"\n  ─── RESULTADO WALK-FORWARD ({elapsed:.0f}s) ───────────────────────────")
print(f"  Sessões out-of-sample: {len(pred)}  |  Folds: {metrics['folds']}")
print(f"\n  {'Métrica':<28} {'TPGA v14':>10}  {'Maioria':>10}  {'Futuros':>10}")
print(f"  {'-'*60}")
print(f"  {'Acurácia':<28} {prob['accuracy']:>9.1%}  {base.get('majority_accuracy',0):>9.1%}  {base.get('futures_accuracy',0):>9.1%}")
print(f"  {'MCC':<28} {prob['mcc_multiclass']:>10.4f}  {base.get('majority_mcc',0):>10.4f}  {base.get('futures_mcc',0):>10.4f}")
print(f"  {'AUC (up vs rest)':<28} {prob.get('auc_up') or 0:>10.4f}")
print(f"  {'Brier Score':<28} {prob['brier_up']:>10.4f}")

print(f"\n  ─── SIMULAÇÃO PAPER ─────────────────────────────────────────────")
print(f"  Casos operados:  {op['study_cases']} de {op['rows']} ({op['study_case_rate']:.1%})")
hr = op.get("hit_rate_study_cases")
ev = op.get("ev_points_per_study_case")
pf = op.get("profit_factor")
print(f"  Hit Rate:        {f'{hr:.1%}' if hr is not None else 'n/a'}")
print(f"  EV por trade:    {f'{ev:.1f} pts' if ev is not None else 'n/a'}")
print(f"  PnL total:       {op['total_pnl_points']:.1f} pts")
print(f"  Max Drawdown:    {op['max_drawdown_points']:.1f} pts")
print(f"  Profit Factor:   {f'{pf:.2f}' if pf is not None else 'n/a'}")

if "bootstrap" in metrics and "error" not in metrics.get("bootstrap", {}):
    bs = metrics["bootstrap"]
    print(f"\n  ─── BOOTSTRAP IC95% ─────────────────────────────────────────────")
    for k in ["auc_up", "mcc_multiclass", "ev_points_per_study_case"]:
        if k in bs and isinstance(bs[k], dict) and bs[k].get("mean") is not None:
            m = bs[k]
            sig = "(*)" if (m["ci95_lower"] > 0 or m["ci95_upper"] < 0) else ""
            print(f"  {k:<30}  média={m['mean']:.4f}  IC95=[{m['ci95_lower']:.4f}, {m['ci95_upper']:.4f}] {sig}")

os.makedirs("reports", exist_ok=True)
save_report(OUTPUT_MD, pred, metrics, title="TPGA v14 — Híbrido: yfinance treino + MT5 intraday")
print(f"\n  Relatório salvo: {OUTPUT_MD}")


# ──────────────────────────────────────────────────────────────────────────────
# FASE 3 — Barras M1 do MT5 (features intraday de hoje)
# ──────────────────────────────────────────────────────────────────────────────
print("\n[3/4] Buscando barras M1 recentes no MetaTrader 5...")

gap_cfg = GapSessionConfig(
    symbol=MT5_SYMBOL,
    timezone=TIMEZONE,
    close_time=CLOSE_TIME,
    open_time=OPEN_TIME,
    lookback_minutes=LOOKBACK_MIN,
)

mt5_available = False
recent_m1 = pd.DataFrame()

try:
    from tpga.mt5_client import MT5Client, MT5ConnectionConfig
    conn = MT5ConnectionConfig(symbol=MT5_SYMBOL)
    with MT5Client(conn) as client:
        recent_m1 = client.copy_recent_rates(
            MT5_SYMBOL, timeframe="M1", count=HISTORY_BARS_MT5, tz_name=TIMEZONE
        )
    if not recent_m1.empty:
        mt5_available = True
        last_bar_time = recent_m1["time_local"].iloc[-1] if "time_local" in recent_m1.columns else "?"
        print(f"  MT5 conectado  |  {len(recent_m1)} barras M1  |  última: {last_bar_time}")
    else:
        print("  MT5 conectado mas sem barras recentes. Usando snapshot yfinance-only.")
except Exception as e:
    print(f"  MT5 não disponível ({type(e).__name__}: {e})")
    print("  Fallback: sinal gerado só com features yfinance (sem M1 intraday).")


# ──────────────────────────────────────────────────────────────────────────────
# FASE 4 — Sinal de hoje (híbrido ou yfinance-only)
# ──────────────────────────────────────────────────────────────────────────────
print("\n[4/4] Gerando sinal de hoje...")

print("  Buscando macro do pré-mercado via yfinance...")
market_data = fetch_premarket_features(symbol_futures="NQ=F")
md_found = sum(1 for v in market_data.values() if np.isfinite(float(v) if v is not None else np.nan))
print(f"  Macro preenchida: {md_found}/7 features  "
      f"(VIX={market_data.get('vix_ret', np.nan):.4f}  "
      f"DXY={market_data.get('dxy_ret', np.nan):.4f}  "
      f"TNX={market_data.get('us10y_ret', np.nan):.4f})")

if mt5_available and len(recent_m1) >= 30:
    # Sinal HÍBRIDO: intraday de M1 real + macro de yfinance
    print("  Modo HÍBRIDO: features intraday do MT5 + macro do yfinance")
    current_row = build_current_feature_row(recent_m1, gap_cfg, market_data=market_data)
    source_mode = "hibrido_mt5_intraday_yfinance_macro"
else:
    # Fallback: snapshot baseado apenas no último registro histórico (proxy)
    print("  Modo YFINANCE-ONLY: usando última sessão como proxy de hoje")
    # Usa o último row do histórico como proxy (sem features intraday)
    last_hist = df_real.iloc[-1:].copy()
    last_hist["last_1m_ret"] = np.nan
    last_hist["vwap_distance"] = np.nan
    last_hist["realized_vol_30m"] = np.nan
    # Substitui macro com valores de hoje do yfinance
    for key, col in [
        ("futures_overnight_ret", "futures_overnight_ret"),
        ("qqq_premarket_ret", "qqq_premarket_ret"),
        ("spy_premarket_ret", "spy_premarket_ret"),
        ("weighted_bigtech_premarket_ret", "weighted_bigtech_premarket_ret"),
        ("vix_ret", "vix_ret"),
        ("dxy_ret", "dxy_ret"),
        ("us10y_ret", "us10y_ret"),
    ]:
        if key in market_data and np.isfinite(float(market_data[key]) if market_data[key] is not None else np.nan):
            last_hist[col] = market_data[key]
    current_row = last_hist
    source_mode = "yfinance_only_sem_m1"

signal = train_and_score_current(df_real, current_row, gap_cfg, random_state=42)

# ── Exibir resultado ─────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  SINAL TPGA v14 — HOJE")
print(f"{'='*65}")
print(f"\n  Gerado em:    {signal.generated_at}")
print(f"  Símbolo:      {signal.symbol}")
print(f"  Fonte:        {source_mode}")
print()
print(f"  P(alta):      {signal.p_up:.1%}")
print(f"  P(baixa):     {signal.p_down:.1%}")
print(f"  P(flat):      {signal.p_flat:.1%}")
print(f"  Edge:         {signal.edge:+.4f}  (threshold ±0.12)")
print(f"  Confiança:    {signal.confidence:.1%}")
print(f"  Gap esperado: {signal.expected_gap_points_proxy:+.1f} pts (proxy)")
print(f"  Gap mediano:  {signal.median_abs_gap_points:.1f} pts (histórico)")
print()

if abs(signal.edge) >= 0.12 and signal.confidence >= 0.48:
    if signal.p_up > signal.p_down:
        decisao = "COMPRA ESTUDO (paper)"
        icone = "▲"
    else:
        decisao = "VENDA ESTUDO (paper)"
        icone = "▼"
    print(f"  {icone} SINAL: {decisao}")
else:
    print("  ◉  AGUARDAR — edge insuficiente (< 0.12) ou confiança baixa")
    decisao = "SEM_SINAL"

print()
print(f"  AVISO: Sinal educacional. Não é recomendação de investimento.")
print(f"{'='*65}")

# ── Salvar JSON ──────────────────────────────────────────────────────────────
payload = signal.__dict__.copy()
payload["source_mode"] = source_mode
payload["mt5_bars_used"] = int(len(recent_m1)) if mt5_available else 0
payload["macro_features_filled"] = int(md_found)
payload["decisao"] = decisao
payload["walk_forward_auc"] = float(prob.get("auc_up") or 0)
payload["walk_forward_mcc"] = float(prob.get("mcc_multiclass") or 0)
payload["walk_forward_sessions"] = int(len(pred))

os.makedirs("reports", exist_ok=True)
with open(OUTPUT_SIGNAL, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)
print(f"\n  Sinal salvo em: {OUTPUT_SIGNAL}")
print(f"  Relatório:      {OUTPUT_MD}")
