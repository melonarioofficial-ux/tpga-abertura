"""
TPGA XAUUSD (Ouro) — Sinal Híbrido: yfinance (treino) + MT5 M1 (intraday)
===========================================================================
Arquitetura idêntica ao NDX100, correlatos adaptados para ouro:
  - GC=F   → Gold futures (principal)
  - SI=F   → Silver (correlato positivo)
  - CL=F   → Oil (correlato de risco)
  - DX-Y.NYB → Dollar (correlato negativo forte)
  - ^TNX   → US 10Y yield (real rates — principal driver de gold)
  - ^VIX   → Volatilidade (safe-haven demand)
  - SPY    → Risk appetite geral

Como rodar:
    python SINAL_XAUUSD_HIBRIDO.py

Requer: pip install yfinance  |  MT5 aberto com XAUUSD visível (opcional)

Saída:
    reports/sinal_xauusd_hoje.json
    reports/resultado_xauusd.md
    dados_reais_xauusd.csv

AVISO: Sinal educacional/paper. Não envia ordens. Não é recomendação de investimento.
"""

from __future__ import annotations

import sys, warnings, time, json, os
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

try:
    import yfinance as yf
except ImportError:
    print("ERRO: yfinance não instalado. Rode: pip install yfinance")
    sys.exit(1)

import numpy as np
import pandas as pd

from tpga.backtest import WalkForwardConfig, walk_forward_validate
from tpga.features import add_gap_labels
from tpga.live_signal import build_current_feature_row, train_and_score_current
from tpga.mt5_gap_builder import GapSessionConfig
from tpga.report import save_report
from tpga.market_data import fetch_premarket_features

# ── Configuração XAUUSD ──────────────────────────────────────────────────────
ANOS_HISTORICO   = 3
FLAT_THRESHOLD   = 3.0       # USD — gap menor que $3 = flat para gold
MT5_SYMBOL       = "XAUUSD"  # Ajuste se seu broker usa "XAU/USD" ou "GOLD"
TIMEZONE         = "America/Sao_Paulo"
CLOSE_TIME       = "17:59"   # fim sessão NY (gold fecha brevemente)
OPEN_TIME        = "19:00"   # reabertura (Sydney/Ásia)
LOOKBACK_MIN     = 240
HISTORY_BARS_MT5 = 2000
OUTPUT_CSV       = "dados_reais_xauusd.csv"
OUTPUT_MD        = "reports/resultado_xauusd.md"
OUTPUT_SIGNAL    = "reports/sinal_xauusd_hoje.json"

print("=" * 65)
print("  TPGA XAUUSD — Sinal Híbrido (yfinance backtest + MT5 intraday)")
print("=" * 65)


# ──────────────────────────────────────────────────────────────────────────────
# FASE 1 — Histórico yfinance
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n[1/4] Baixando {ANOS_HISTORICO} anos de histórico via yfinance...")

tickers = {
    "XAU": "GC=F",        # Gold futures
    "XAG": "SI=F",        # Silver (correlato positivo de ouro)
    "OIL": "CL=F",        # Oil (correlato de risco/inflação)
    "VIX": "^VIX",        # Volatilidade (safe-haven)
    "DXY": "DX-Y.NYB",   # Dollar (correlato negativo forte de ouro)
    "TNX": "^TNX",        # US 10Y yield (real rates — driver fundamental)
    "SPY": "SPY",         # Risk appetite (proxy equity)
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

xau = raw.get("XAU", pd.DataFrame())
if xau.empty or len(xau) < 200:
    print("\nERRO: Não foi possível baixar GC=F. Verifique a conexão.")
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


print("\nMontando dataset histórico de sessões (XAUUSD)...")

xau_close  = xau["Close"]
xau_open   = xau["Open"]
xau_high   = xau["High"]
xau_low    = xau["Low"]
xau_volume = xau["Volume"]

rows = []
for i in range(1, len(xau)):
    prev_date  = xau.index[i - 1]
    curr_date  = xau.index[i]
    prev_close = float(xau_close.iloc[i - 1])
    open_price = float(xau_open.iloc[i])

    if not (np.isfinite(prev_close) and np.isfinite(open_price)):
        continue
    if prev_close <= 0 or open_price <= 0:
        continue

    ph = float(xau_high.iloc[i - 1])
    pl = float(xau_low.iloc[i - 1])
    range_pos = (prev_close - pl) / (ph - pl) if ph > pl else np.nan

    vol_window = xau_volume.iloc[max(0, i - 21):i].astype(float)
    vol_z = np.nan
    if len(vol_window) >= 5:
        mu    = float(vol_window[:-1].mean())
        sigma = float(vol_window[:-1].std(ddof=0))
        if sigma > 0:
            vol_z = (float(vol_window.iloc[-1]) - mu) / sigma

    xau_prev_ret = safe_log_ret(xau_close, i - 1)

    # Correlatos de ouro mapeados nas mesmas colunas do schema TPGA
    #   futures_overnight_ret         = retorno GC=F dia anterior
    #   qqq_premarket_ret             = retorno Prata (SI=F)
    #   spy_premarket_ret             = retorno Petróleo (CL=F)
    #   weighted_bigtech_premarket_ret= retorno SPY (apetite a risco)
    #   vix_ret, dxy_ret, us10y_ret   = mesmos (VIX, DXY, TNX)
    rows.append({
        "session_date":   curr_date.date().isoformat(),
        "prev_close":     prev_close,
        "open":           open_price,
        "last_1m_ret":    np.nan,
        "last_5m_ret":    xau_prev_ret,
        "last_15m_ret":   np.nan,
        "close_volume_z": vol_z,
        "vwap_distance":  np.nan,
        "range_position": range_pos,
        "realized_vol_30m": np.nan,
        # Macro / correlatos ouro
        "futures_overnight_ret":          xau_prev_ret,
        "qqq_premarket_ret":              macro_ret("XAG", prev_date),   # Prata
        "spy_premarket_ret":              macro_ret("OIL", prev_date),   # Petróleo
        "weighted_bigtech_premarket_ret": macro_ret("SPY", prev_date),   # Risk appetite
        "vix_ret":    macro_ret("VIX", prev_date),
        "dxy_ret":    macro_ret("DXY", prev_date),
        "us10y_ret":  macro_ret("TNX", prev_date),
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
print(f"\n  Dataset XAUUSD: {len(df_real)} sessões  "
      f"({df_real.session_date.iloc[0]} → {df_real.session_date.iloc[-1]})")
print(f"  Threshold:  ±${FLAT_THRESHOLD}  |  Distribuição: ", end="")
for k, v in dist.items():
    print(f"{k}={v} ({v/len(df_real):.0%})  ", end="")
print()


# ──────────────────────────────────────────────────────────────────────────────
# FASE 2 — Walk-forward
# ──────────────────────────────────────────────────────────────────────────────
print("\n[2/4] Walk-forward no histórico XAUUSD (yfinance)...")

cfg = WalkForwardConfig(
    min_train_size=120,
    test_size=60,
    step_size=60,
    random_state=42,
    flat_threshold_points=FLAT_THRESHOLD,
    edge_threshold=0.12,
    confidence_threshold=0.48,
    fakeout_max=0.70,
    cost_points=0.50,   # custo menor para gold (spread menor que NDX100)
)

t0 = time.time()
pred, metrics = walk_forward_validate(df_real, cfg)
elapsed = time.time() - t0

prob = metrics["probabilistic"]
base = metrics["baselines"]
op   = metrics["operational_paper"]

print(f"\n  ─── RESULTADO ({elapsed:.0f}s) ────────────────────────────────────────")
print(f"  Sessões out-of-sample: {len(pred)}  |  Folds: {metrics['folds']}")
print(f"\n  {'Métrica':<28} {'TPGA':>10}  {'Maioria':>10}  {'Futuros':>10}")
print(f"  {'-'*60}")
print(f"  {'Acurácia':<28} {prob['accuracy']:>9.1%}  {base.get('majority_accuracy',0):>9.1%}  {base.get('futures_accuracy',0):>9.1%}")
print(f"  {'MCC':<28} {prob['mcc_multiclass']:>10.4f}  {base.get('majority_mcc',0):>10.4f}")
print(f"  {'AUC (up vs rest)':<28} {prob.get('auc_up') or 0:>10.4f}")
print(f"  {'Brier Score':<28} {prob['brier_up']:>10.4f}")

print(f"\n  ─── SIMULAÇÃO PAPER ─────────────────────────────────────────────")
print(f"  Casos operados:  {op['study_cases']} de {op['rows']} ({op['study_case_rate']:.1%})")
hr = op.get("hit_rate_study_cases")
ev = op.get("ev_points_per_study_case")
pf = op.get("profit_factor")
print(f"  Hit Rate:        {f'{hr:.1%}' if hr else 'n/a'}")
print(f"  EV por trade:    {f'{ev:.2f} USD' if ev else 'n/a'}")
print(f"  PnL total:       {op['total_pnl_points']:.2f} USD")
print(f"  Max Drawdown:    {op['max_drawdown_points']:.2f} USD")
print(f"  Profit Factor:   {f'{pf:.2f}' if pf else 'n/a'}")

if "bootstrap" in metrics and "error" not in metrics.get("bootstrap", {}):
    bs = metrics["bootstrap"]
    print(f"\n  ─── BOOTSTRAP IC95% ─────────────────────────────────────────────")
    for k in ["auc_up", "mcc_multiclass", "ev_points_per_study_case"]:
        if k in bs and isinstance(bs[k], dict) and bs[k].get("mean") is not None:
            m = bs[k]
            sig = "(*)" if (m["ci95_lower"] > 0 or m["ci95_upper"] < 0) else ""
            print(f"  {k:<30}  média={m['mean']:.4f}  IC95=[{m['ci95_lower']:.4f}, {m['ci95_upper']:.4f}] {sig}")

os.makedirs("reports", exist_ok=True)
save_report(OUTPUT_MD, pred, metrics, title="TPGA XAUUSD — Híbrido yfinance + MT5")
print(f"\n  Relatório salvo: {OUTPUT_MD}")


# ──────────────────────────────────────────────────────────────────────────────
# FASE 3 — Barras M1 do MT5 (XAUUSD)
# ──────────────────────────────────────────────────────────────────────────────
print("\n[3/4] Buscando barras M1 de XAUUSD no MetaTrader 5...")

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
        print(f"  MT5 conectado  |  {len(recent_m1)} barras M1 de XAUUSD  |  última: {last_bar_time}")
    else:
        print("  MT5 sem barras. Usando fallback yfinance.")
except Exception as e:
    print(f"  MT5 não disponível ({type(e).__name__}: {e})")
    print("  Fallback: sinal com features yfinance (sem M1 intraday).")


# ──────────────────────────────────────────────────────────────────────────────
# FASE 4 — Sinal de hoje
# ──────────────────────────────────────────────────────────────────────────────
print("\n[4/4] Gerando sinal XAUUSD de hoje...")

# Macro específica de ouro via yfinance
print("  Buscando correlatos do ouro via yfinance (prata, petróleo, dollar, yields)...")
try:
    import yfinance as yf
    def _safe_yf_ret(ticker, period="2d"):
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if df.empty or len(df) < 2: return np.nan
            c = df["Close"].dropna()
            if len(c) < 2: return np.nan
            return float(np.log(c.iloc[-1] / c.iloc[-2]))
        except Exception:
            return np.nan

    market_data = {
        "futures_overnight_ret":          _safe_yf_ret("GC=F", "5d"),
        "qqq_premarket_ret":              _safe_yf_ret("SI=F"),   # Prata
        "spy_premarket_ret":              _safe_yf_ret("CL=F"),   # Petróleo
        "weighted_bigtech_premarket_ret": _safe_yf_ret("SPY"),    # Risk appetite
        "vix_ret":    _safe_yf_ret("^VIX"),
        "dxy_ret":    _safe_yf_ret("DX-Y.NYB"),
        "us10y_ret":  _safe_yf_ret("^TNX"),
    }
    md_found = sum(1 for v in market_data.values() if v is not None and np.isfinite(float(v)))
    print(f"  Macro preenchida: {md_found}/7 — "
          f"Prata={market_data.get('qqq_premarket_ret', np.nan):.4f}  "
          f"DXY={market_data.get('dxy_ret', np.nan):.4f}  "
          f"TNX={market_data.get('us10y_ret', np.nan):.4f}")
except Exception as e:
    market_data = {}
    md_found = 0
    print(f"  Falha ao buscar macro ({e})")

if mt5_available and len(recent_m1) >= 30:
    print("  Modo HÍBRIDO: M1 XAUUSD do MT5 + correlatos do yfinance")
    current_row = build_current_feature_row(recent_m1, gap_cfg, market_data=market_data)
    source_mode = "hibrido_mt5_intraday_yfinance_macro_xauusd"
else:
    print("  Modo YFINANCE-ONLY: usando último registro histórico como proxy")
    last_hist = df_real.iloc[-1:].copy()
    last_hist["last_1m_ret"] = np.nan
    last_hist["vwap_distance"] = np.nan
    last_hist["realized_vol_30m"] = np.nan
    col_map = {
        "futures_overnight_ret":          "futures_overnight_ret",
        "qqq_premarket_ret":              "qqq_premarket_ret",
        "spy_premarket_ret":              "spy_premarket_ret",
        "weighted_bigtech_premarket_ret": "weighted_bigtech_premarket_ret",
        "vix_ret":   "vix_ret",
        "dxy_ret":   "dxy_ret",
        "us10y_ret": "us10y_ret",
    }
    for key, col in col_map.items():
        val = market_data.get(key)
        try:
            if val is not None and np.isfinite(float(val)):
                last_hist[col] = float(val)
        except (TypeError, ValueError):
            pass
    current_row = last_hist
    source_mode = "yfinance_only_xauusd"

signal = train_and_score_current(df_real, current_row, gap_cfg, random_state=42)

# ── Exibir resultado ─────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  SINAL TPGA XAUUSD — HOJE")
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
print(f"  Gap esperado: {signal.expected_gap_points_proxy:+.2f} USD (proxy)")
print(f"  Gap mediano:  {signal.median_abs_gap_points:.2f} USD (histórico)")
print()

edge = signal.edge
if abs(edge) >= 0.12 and signal.confidence >= 0.48:
    decisao = "COMPRA_ESTUDO" if signal.p_up > signal.p_down else "VENDA_ESTUDO"
    icone = "▲" if "COMPRA" in decisao else "▼"
    print(f"  {icone} SINAL: {decisao.replace('_', ' ')} (paper)")
else:
    decisao = "AGUARDAR"
    print("  ◉  AGUARDAR — edge insuficiente ou confiança baixa")

print()
print(f"  AVISO: Sinal educacional. Não é recomendação de investimento.")
print(f"{'='*65}")

# ── Salvar JSON ──────────────────────────────────────────────────────────────
boot = metrics.get("bootstrap", {})
def _bs(key):
    if "error" in boot: return None
    b = boot.get(key)
    if not isinstance(b, dict): return None
    return {
        "mean":  round(b.get("mean") or 0, 4),
        "ci_lo": round(b.get("ci95_lower") or 0, 4),
        "ci_hi": round(b.get("ci95_upper") or 0, 4),
        "sig":   bool((b.get("ci95_lower") or 0) > 0 or (b.get("ci95_upper") or 0) < 0),
    }

payload = {
    "generated_at": signal.generated_at,
    "symbol":       "XAUUSD",
    "source_mode":  source_mode,
    "macro_features_filled": int(md_found),
    "mt5_bars_used": int(len(recent_m1)) if mt5_available else 0,

    "decisao":    decisao,
    "p_up":       round(signal.p_up, 4),
    "p_down":     round(signal.p_down, 4),
    "p_flat":     round(signal.p_flat, 4),
    "edge":       round(signal.edge, 4),
    "confidence": round(signal.confidence, 4),
    "expected_gap_points_proxy": round(signal.expected_gap_points_proxy, 2),
    "median_abs_gap_points":     round(signal.median_abs_gap_points, 2),

    "walk_forward": {
        "sessions":          int(len(pred)),
        "folds":             int(metrics["folds"]),
        "accuracy":          round(prob.get("accuracy") or 0, 4),
        "mcc":               round(prob.get("mcc_multiclass") or 0, 4),
        "auc_up":            round(prob.get("auc_up") or 0, 4),
        "brier_up":          round(prob.get("brier_up") or 0, 4),
        "majority_accuracy": round(base.get("majority_accuracy") or 0, 4),
        "futures_accuracy":  round(base.get("futures_accuracy") or 0, 4),
    },

    "paper": {
        "cases":        int(op.get("study_cases") or 0),
        "total":        int(op.get("rows") or 0),
        "rate":         round(op.get("study_case_rate") or 0, 4),
        "hit_rate":     round(op.get("hit_rate_study_cases") or 0, 4),
        "ev_per_trade": round(op.get("ev_points_per_study_case") or 0, 2),
        "pnl_total":    round(op.get("total_pnl_points") or 0, 2),
        "max_drawdown": round(op.get("max_drawdown_points") or 0, 2),
        "profit_factor":round(op.get("profit_factor") or 0, 2),
    },

    "bootstrap": {k: _bs(k) for k in ["auc_up", "mcc_multiclass", "ev_points_per_study_case"]},

    "correlatos": {
        "futures_overnight_ret":          "GC=F (Gold Futures)",
        "qqq_premarket_ret":              "SI=F (Silver)",
        "spy_premarket_ret":              "CL=F (Oil/WTI)",
        "weighted_bigtech_premarket_ret": "SPY (Risk Appetite)",
        "vix_ret":   "^VIX",
        "dxy_ret":   "DX-Y.NYB (Dollar Index)",
        "us10y_ret": "^TNX (US 10Y Yield)",
    },

    "note": "Sinal educacional/paper. Não envia ordens. Não é recomendação de investimento.",
}

os.makedirs("reports", exist_ok=True)
with open(OUTPUT_SIGNAL, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)
print(f"\n  Sinal salvo em: {OUTPUT_SIGNAL}")
print(f"  Relatório:      {OUTPUT_MD}")
