"""
TPGA Signal Engine — motor multi-símbolo
=========================================
Motor reutilizável para todos os 5 instrumentos da plataforma:
  NDX100 | XAUUSD | DAX40 | NKY225 | SP500

Uso rápido:
    from tpga.signal_engine import run_instrument_pipeline
    run_instrument_pipeline("dax")     # pipeline completo, salva JSON
    run_instrument_pipeline("ndx", use_mt5=False)
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ══════════════════════════════════════════════════════════════════════════════
# SymbolConfig — parâmetros por instrumento
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SymbolConfig:
    name:            str           # "NDX100", "XAUUSD", "DAX40", "NKY225", "SP500"
    label:           str           # "NDX100 — Nasdaq"
    symbol_yf:       str           # "NQ=F"       (ticker principal yfinance)
    symbol_mt5:      str           # "NDX100"     (símbolo MT5)
    flat_threshold:  float         # 5.0 pts — zona flat
    cost_points:     float         # 2.0 pts — custo de transação (round-trip)
    output_key:      str           # "ndx" → sinal_ndx_hoje.json
    unit:            str           # "pts" | "USD"
    corr_map: Dict[str, str] = field(default_factory=dict)
    # Horários de sessão (para GapSessionConfig / MT5 M1)
    close_time: str  = "17:59"
    open_time:  str  = "19:00"
    timezone:   str  = "America/Sao_Paulo"
    years_history: int = 3
    # Features de engenharia extras (momentum/tendencia/vol/calendario).
    # Promovidas por instrumento apenas onde melhoram o OOS. Default: nenhuma.
    extra_features: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# 3 instrumentos com edge estatístico confirmado
# ══════════════════════════════════════════════════════════════════════════════

SYMBOLS: Dict[str, SymbolConfig] = {

    # ── 1. NDX100 ─────────────────────────────────────────────────────────────
    "ndx": SymbolConfig(
        name="NDX100", label="NDX100 — Nasdaq",
        symbol_yf="NQ=F", symbol_mt5="NDX100",
        flat_threshold=5.0, cost_points=2.0, output_key="ndx", unit="pts",
        close_time="17:59", open_time="19:00",
        corr_map={
            "futures_overnight_ret":          "NQ=F",
            "qqq_premarket_ret":              "QQQ",
            "spy_premarket_ret":              "SPY",
            "weighted_bigtech_premarket_ret": "QQQ",
            "vix_ret":   "^VIX",
            "dxy_ret":   "DX-Y.NYB",
            "us10y_ret": "^TNX",
        },
    ),

    # ── 2. XAUUSD (Ouro) ──────────────────────────────────────────────────────
    "xau": SymbolConfig(
        name="XAUUSD", label="XAUUSD — Ouro",
        symbol_yf="GC=F", symbol_mt5="XAUUSD",
        flat_threshold=3.0, cost_points=0.50, output_key="xau", unit="USD",
        close_time="17:59", open_time="19:00",
        corr_map={
            "futures_overnight_ret":          "GC=F",
            "qqq_premarket_ret":              "SI=F",       # Prata
            "spy_premarket_ret":              "CL=F",       # Petróleo WTI
            "weighted_bigtech_premarket_ret": "SPY",        # apetite de risco
            "vix_ret":   "^VIX",
            "dxy_ret":   "DX-Y.NYB",
            "us10y_ret": "^TNX",
        },
    ),

    # ── 3. DAX 40 (Alemanha) ──────────────────────────────────────────────────
    # Frankfurt fecha ~17:30 CET. O S&P500 fecha DEPOIS, tornando-se preditor principal.
    # EUR/USD e Euro Stoxx 50 capturam dinâmica regional.
    "dax": SymbolConfig(
        name="DAX40", label="DAX 40 — Alemanha",
        symbol_yf="^GDAXI", symbol_mt5="GER40",
        flat_threshold=25.0, cost_points=2.0, output_key="dax", unit="pts",
        # ~13:30 BRT = 17:30 Frankfurt (verão CET+2); ajuste manual para inverno
        close_time="13:30", open_time="08:00",
        # Features de engenharia: validadas OOS no DAX (MCC 0.006->0.192, AUC +0.067).
        extra_features=[
            "prev_gap_pct", "gap_5d_mean", "gap_5d_std",
            "close_sma5_dist", "close_sma10_dist", "rv_10d",
            "dow", "is_monday",
        ],
        corr_map={
            "futures_overnight_ret":          "^GSPC",      # S&P500 fecha após DAX — preditor #1
            "qqq_premarket_ret":              "EURUSD=X",   # EUR/USD
            "spy_premarket_ret":              "EZU",        # iShares MSCI Eurozone ETF
            "weighted_bigtech_premarket_ret": "DX-Y.NYB",  # Dollar Index (negativo p/ DAX exportadores)
            "vix_ret":   "^VIX",
            "dxy_ret":   "DX-Y.NYB",
            "us10y_ret": "^TNX",
        },
    ),

}

# Instrumentos ativos na plataforma (apenas os 3 com edge estatístico confirmado)
ACTIVE_INSTRUMENTS = ["ndx", "xau", "dax"]


# ══════════════════════════════════════════════════════════════════════════════
# Helpers internos
# ══════════════════════════════════════════════════════════════════════════════

def _is_finite(v) -> bool:
    try:
        return bool(np.isfinite(float(v)))
    except (TypeError, ValueError):
        return False


def _log_ret_from_raw(raw: dict, ticker: str, target_date) -> float:
    """Retorno log do ticker na data target_date (forward-fill para feriados)."""
    try:
        s = raw[ticker]["Close"].dropna()
        if s.empty:
            return np.nan
        loc = s.index.get_indexer([target_date], method="ffill")[0]
        if loc < 1:
            return np.nan
        a, b = float(s.iloc[loc]), float(s.iloc[loc - 1])
        return float(np.log(a / b)) if a > 0 and b > 0 else np.nan
    except Exception:
        return np.nan


# ══════════════════════════════════════════════════════════════════════════════
# Download yfinance
# ══════════════════════════════════════════════════════════════════════════════

def _download_tickers(tickers: list, period: str) -> dict:
    """Baixa múltiplos tickers yfinance. Retorna {ticker: DataFrame}."""
    import yfinance as yf
    raw = {}
    for ticker in sorted(set(tickers)):
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            raw[ticker] = df
        except Exception:
            raw[ticker] = pd.DataFrame()
    return raw


def build_yf_dataset(cfg: SymbolConfig, verbose: bool = True) -> Optional[pd.DataFrame]:
    """
    Baixa dados yfinance e constrói dataset histórico de gaps.
    Usa a mesma estrutura de colunas TPGA para todos os símbolos.
    Retorna DataFrame ou None se dados insuficientes.
    """
    period = f"{cfg.years_history}y"
    all_tickers = [cfg.symbol_yf] + list(cfg.corr_map.values())
    unique_tickers = list(set(all_tickers))

    if verbose:
        print(f"  Baixando {len(unique_tickers)} tickers ({period})...")

    raw = _download_tickers(unique_tickers, period)

    for ticker, df in sorted(raw.items()):
        status = f"{len(df)} dias" if not df.empty else "FALHA"
        if verbose:
            print(f"    {ticker}: {status}")

    main = raw.get(cfg.symbol_yf, pd.DataFrame())
    if main.empty or len(main) < 200:
        if verbose:
            print(f"  ERRO: {cfg.symbol_yf} insuficiente (< 200 dias).")
        return None

    mc = main["Close"]
    mo = main["Open"]
    mh = main["High"]
    ml = main["Low"]
    mv = main.get("Volume", pd.Series(0.0, index=main.index))

    rows = []
    for i in range(1, len(main)):
        prev_date = main.index[i - 1]
        curr_date = main.index[i]
        pc = float(mc.iloc[i - 1])
        op = float(mo.iloc[i])

        if not (np.isfinite(pc) and np.isfinite(op) and pc > 0 and op > 0):
            continue

        ph, pl = float(mh.iloc[i - 1]), float(ml.iloc[i - 1])
        range_pos = (pc - pl) / (ph - pl) if ph > pl else np.nan

        vol_w = mv.iloc[max(0, i - 21):i].astype(float)
        vol_z = np.nan
        if len(vol_w) >= 5:
            mu, sg = float(vol_w[:-1].mean()), float(vol_w[:-1].std(ddof=0))
            if sg > 0:
                vol_z = (float(vol_w.iloc[-1]) - mu) / sg

        prev_ret = _log_ret_from_raw(raw, cfg.symbol_yf, prev_date)

        row: dict = {
            "session_date":               curr_date.date().isoformat(),
            "prev_close":                 pc,
            "open":                       op,
            "last_1m_ret":                np.nan,
            "last_5m_ret":                prev_ret,
            "last_15m_ret":               np.nan,
            "close_volume_z":             vol_z,
            "vwap_distance":              np.nan,
            "range_position":             range_pos,
            "realized_vol_30m":           np.nan,
            "macro_event_flag":           0,
            "earnings_risk_flag":         0,
            "noii_imbalance_side":        "",
            "noii_imbalance_shares":      np.nan,
            "noii_paired_shares":         np.nan,
            "noii_near_price":            np.nan,
            "noii_far_price":             np.nan,
            "noii_reference_price":       np.nan,
            "mt5_spread_points_at_signal": np.nan,
        }

        # 7 features macro via corr_map
        for feat_col, corr_ticker in cfg.corr_map.items():
            row[feat_col] = _log_ret_from_raw(raw, corr_ticker, prev_date)

        rows.append(row)

    df_out = pd.DataFrame(rows)

    # Features de engenharia (só para instrumentos que as usam, ex.: DAX).
    if cfg.extra_features:
        from tpga.features import build_engineered_features
        eng = build_engineered_features(main)
        df_out = df_out.merge(eng, on="session_date", how="left")
        if verbose:
            print(f"  + {len(cfg.extra_features)} features de engenharia (DAX)")

    if verbose:
        print(f"  Dataset: {len(df_out)} sessões ({df_out.session_date.iloc[0]} → {df_out.session_date.iloc[-1]})")
    return df_out


def fetch_live_macro(cfg: SymbolConfig) -> dict:
    """Baixa retornos mais recentes de todos os correlatos para sinal live.

    Usa janela de 1 mês (não 5d): alguns índices — em especial os juros do
    Tesouro (^TNX) — retornam apenas 1 ponto em '5d', o que zerava a feature.
    Com 1mo há sempre >= 2 fechamentos; o retorno do dia é os 2 últimos.
    """
    import yfinance as yf
    result: dict = {}
    for feat_col, ticker in cfg.corr_map.items():
        try:
            df = yf.download(ticker, period="1mo", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if df.empty:
                result[feat_col] = np.nan
                continue
            c = df["Close"].dropna()
            result[feat_col] = (
                float(np.log(float(c.iloc[-1]) / float(c.iloc[-2]))) if len(c) >= 2 else np.nan
            )
        except Exception:
            result[feat_col] = np.nan
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline de sinal
# ══════════════════════════════════════════════════════════════════════════════

def run_signal_pipeline(
    cfg: SymbolConfig,
    df_hist: pd.DataFrame,
    mt5_bars: Optional[pd.DataFrame] = None,
    today_macro: Optional[dict] = None,
    source_mode: str = "",
) -> Tuple[dict, pd.DataFrame, dict]:
    """
    Executa walk-forward temporal + gera sinal live.

    Parâmetros
    ----------
    cfg         : configuração do símbolo
    df_hist     : dataset histórico (saída de build_yf_dataset)
    mt5_bars    : barras M1 do MT5 (opcional; fallback yfinance se None)
    today_macro : dict com retornos de hoje (saída de fetch_live_macro)
    source_mode : string identificadora para o JSON de saída

    Retorna
    -------
    (payload_dict, pred_df, metrics_dict)
    """
    from tpga.backtest import WalkForwardConfig, walk_forward_validate
    from tpga.live_signal import build_current_feature_row, train_and_score_current
    from tpga.mt5_gap_builder import GapSessionConfig

    wf_cfg = WalkForwardConfig(
        min_train_size=120, test_size=60, step_size=60, random_state=42,
        flat_threshold_points=cfg.flat_threshold,
        edge_threshold=0.12, confidence_threshold=0.48,
        fakeout_max=0.70, cost_points=cfg.cost_points,
    )

    pred, metrics = walk_forward_validate(df_hist, wf_cfg, extra_features=cfg.extra_features)

    # GapSessionConfig com times de sessão do símbolo
    try:
        gap_cfg = GapSessionConfig(
            symbol=cfg.symbol_mt5,
            timezone=cfg.timezone,
            close_time=cfg.close_time,
            open_time=cfg.open_time,
        )
    except TypeError:
        gap_cfg = GapSessionConfig(symbol=cfg.symbol_mt5, timezone=cfg.timezone)

    mt5_count = int(len(mt5_bars)) if mt5_bars is not None and not mt5_bars.empty else 0

    if mt5_count >= 30:
        current_row = build_current_feature_row(
            mt5_bars, gap_cfg, market_data=today_macro or {}
        )
        if not source_mode:
            source_mode = f"hibrido_mt5_{cfg.output_key}"
        # O caminho MT5 monta a linha do zero (intraday) e nao tem as features
        # de engenharia (diarias). Copia do ultimo registro historico, que carrega
        # o estado de momentum/tendencia/vol/calendario mais recente.
        if cfg.extra_features:
            last_hist = df_hist.iloc[-1]
            for col in cfg.extra_features:
                if col in df_hist.columns:
                    current_row[col] = last_hist[col]
    else:
        current_row = df_hist.iloc[-1:].copy()
        for col, val in (today_macro or {}).items():
            try:
                if val is not None and _is_finite(val):
                    current_row[col] = float(val)
            except (TypeError, ValueError):
                pass
        if not source_mode:
            source_mode = f"yfinance_only_{cfg.output_key}"

    signal = train_and_score_current(df_hist, current_row, gap_cfg, random_state=42,
                                     extra_features=cfg.extra_features)

    macro_filled = sum(1 for v in (today_macro or {}).values() if _is_finite(v))
    payload = _build_payload(cfg, signal, pred, metrics, mt5_count, macro_filled, source_mode, today_macro)
    return payload, pred, metrics


def _build_payload(
    cfg, signal, pred, metrics, mt5_count, macro_filled, source_mode,
    today_macro=None,
) -> dict:
    """Monta payload JSON completo compatível com dashboard local e Vercel."""
    prob = metrics["probabilistic"]
    base = metrics["baselines"]
    op   = metrics["operational_paper"]
    boot = metrics.get("bootstrap", {})  # dict de dicts, keyed por métrica

    edge   = signal.edge
    p_up   = signal.p_up
    p_down = signal.p_down
    p_flat = signal.p_flat

    # Decisão em texto legível (sem underscore)
    if abs(edge) >= 0.12 and signal.confidence >= 0.48:
        decisao = "COMPRA ESTUDO" if p_up > p_down else "VENDA ESTUDO"
    else:
        decisao = "AGUARDAR"

    def _bs(key):
        """Converte bootstrap de uma métrica para formato normalizado do payload."""
        if "error" in boot:
            return None
        b = boot.get(key)
        if not isinstance(b, dict):
            return None
        lo = float(b.get("ci95_lower") or 0)
        hi = float(b.get("ci95_upper") or 0)
        return {
            "mean":  round(float(b.get("mean") or 0), 4),
            "ci_lo": round(lo, 4),
            "ci_hi": round(hi, 4),
            "sig":   bool(lo > 0 or hi < 0),
        }

    auc_val = round(float(prob.get("auc_up") or 0), 4)
    mcc_val = round(float(prob.get("mcc_multiclass") or 0), 4)
    ts      = signal.generated_at

    # Bootstrap EV — exposto flat no topo para o dashboard ler bt.ci_lo / bt.ci_hi
    ev_bs = _bs("ev_points_per_study_case")
    boot_payload = {
        # ── topo: lido pelo dashboard ──────────────────────────────────────
        "ci_lo": ev_bs["ci_lo"] if ev_bs else None,
        "ci_hi": ev_bs["ci_hi"] if ev_bs else None,
        "mean":  ev_bs["mean"]  if ev_bs else None,
        "sig":   ev_bs["sig"]   if ev_bs else False,
        # ── por métrica: lido por _print_results ───────────────────────────
        "auc_up":                   _bs("auc_up"),
        "mcc_multiclass":           _bs("mcc_multiclass"),
        "ev_points_per_study_case": ev_bs,
    }
    if ev_bs is None:
        boot_payload["error"] = "Amostra insuficiente para bootstrap"

    # Features macro (NaN → None para JSON válido)
    macro_feat = {
        k: (round(float(v), 6) if _is_finite(v) else None)
        for k, v in (today_macro or {}).items()
    }

    return {
        # ── Identificação ─────────────────────────────────────────────────
        "generated_at":          ts,
        "timestamp":             ts,       # alias para o dashboard ler s.timestamp
        "name":                  cfg.name, # alias para s.name no header
        "symbol":                cfg.name,
        "label":                 cfg.label,
        "unit":                  cfg.unit,
        "source_mode":           source_mode,
        "macro_features_filled": macro_filled,
        "mt5_bars_used":         mt5_count,

        # ── Compat top-level (dashboard local legado) ─────────────────────
        "walk_forward_auc":      auc_val,
        "walk_forward_mcc":      mcc_val,
        "walk_forward_sessions": int(len(pred)),
        "cost_points":           cfg.cost_points,

        # ── Sinal do dia ──────────────────────────────────────────────────
        "decisao":                   decisao,
        "p_up":                      round(p_up, 4),
        "p_down":                    round(p_down, 4),
        "p_flat":                    round(p_flat, 4),
        "edge":                      round(edge, 4),
        "confidence":                round(signal.confidence, 4),
        "gap_proxy":                 round(signal.expected_gap_points_proxy, 2),  # alias dashboard
        "expected_gap_points_proxy": round(signal.expected_gap_points_proxy, 2),
        "median_abs_gap_points":     round(signal.median_abs_gap_points, 2),

        # ── Features macro de hoje ────────────────────────────────────────
        "macro_features": macro_feat,

        # ── Walk-forward detalhado ────────────────────────────────────────
        "walk_forward": {
            "sessions":          int(len(pred)),
            "total_sessions":    int(len(pred)),  # alias dashboard
            "folds":             int(metrics["folds"]),
            "accuracy":          round(float(prob.get("accuracy") or 0), 4),
            "mcc":               mcc_val,
            "mcc_multiclass":    mcc_val,          # alias dashboard
            "auc_up":            auc_val,
            "brier_up":          round(float(prob.get("brier_up") or 0), 4),
            "majority_accuracy": round(float(base.get("majority_accuracy") or 0), 4),
            "futures_accuracy":  round(float(base.get("futures_accuracy") or 0), 4),
        },

        # ── Simulação paper ───────────────────────────────────────────────
        "paper": {
            "cases":         int(op.get("study_cases") or 0),
            "total":         int(op.get("rows") or 0),
            "rate":          round(float(op.get("study_case_rate") or 0), 4),
            "hit_rate":      round(float(op.get("hit_rate_study_cases") or 0), 4),
            "ev_per_trade":  round(float(op.get("ev_points_per_study_case") or 0), 2),
            "pnl_total":     round(float(op.get("total_pnl_points") or 0), 2),
            "max_drawdown":  round(float(op.get("max_drawdown_points") or 0), 2),
            "profit_factor": round(float(op.get("profit_factor") or 0), 2),
        },

        # ── Bootstrap IC95% ───────────────────────────────────────────────
        "bootstrap": boot_payload,

        "correlatos": cfg.corr_map,
        "note": "Sinal educacional/paper. Não envia ordens. Não é recomendação de investimento.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Interface de alto nível
# ══════════════════════════════════════════════════════════════════════════════

def run_instrument_pipeline(
    key: str,
    use_mt5: bool = True,
    save_dir: str = "reports",
    verbose: bool = True,
) -> dict:
    """
    Pipeline completo: download → MT5 → macro → walk-forward → sinal → salva JSON.

    Parâmetros
    ----------
    key      : chave do símbolo ("ndx", "xau", "dax")
    use_mt5  : tenta conectar MT5 para barras M1 intraday
    save_dir : pasta de saída (reports/ local, public/ CI)
    verbose  : imprime progresso

    Retorna o payload dict (também salvo em save_dir/sinal_{key}_hoje.json).
    """
    cfg = SYMBOLS[key]
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  TPGA {cfg.label}")
    print(f"  flat={cfg.flat_threshold} {cfg.unit}  |  custo={cfg.cost_points} {cfg.unit}/trade")
    print(f"{sep}\n")

    # ── 1. Dataset histórico yfinance ─────────────────────────────────────────
    t0 = time.time()
    print("[1/4] Baixando dados históricos yfinance...")
    df = build_yf_dataset(cfg, verbose=verbose)
    if df is None or len(df) < 120:
        print(f"ERRO: dados insuficientes para {cfg.name}.")
        return {}
    print(f"  OK: {len(df)} sessões em {time.time()-t0:.1f}s\n")

    # ── 2. MT5 (opcional) ─────────────────────────────────────────────────────
    mt5_bars = None
    print("[2/4] Conectando MT5...")
    if use_mt5:
        # Mapa de símbolos alternativos por chave (brokers usam nomes diferentes)
        ALT_SYMBOLS: dict[str, list[str]] = {
            "ndx": ["NDX100", "NAS100", "US100", "NASDAQ100", "NQ100", "USTECH100"],
            "xau": ["XAUUSD", "XAU/USD", "GOLD", "XAUUSD."],
            "dax": ["GER40", "DE40", "DAX40", "DAX", "GER30", "DAXEUR", "GER40."],
        }
        symbols_to_try = [cfg.symbol_mt5] + [
            s for s in ALT_SYMBOLS.get(cfg.output_key, []) if s != cfg.symbol_mt5
        ]
        try:
            from tpga.mt5_client import MT5Client, MT5ConnectionConfig
            bars_found = None
            used_symbol = None
            for sym in symbols_to_try:
                try:
                    conn = MT5ConnectionConfig(symbol=sym)
                    with MT5Client(conn) as client:
                        bars = client.copy_recent_rates(sym, timeframe="M1", count=2000, tz_name=cfg.timezone)
                    if bars is not None and not bars.empty:
                        bars_found = bars
                        used_symbol = sym
                        break
                except Exception:
                    continue
            if bars_found is not None:
                mt5_bars = bars_found
                print(f"  MT5: {len(mt5_bars)} barras M1 de {used_symbol}")
            else:
                print(f"  MT5: nenhum símbolo encontrado {symbols_to_try[:3]}... — fallback yfinance")
        except Exception as e:
            print(f"  MT5 indisponível ({type(e).__name__}): {e}")
    else:
        print("  MT5: desativado (modo CI/yfinance-only)")

    # ── 3. Macro de hoje ──────────────────────────────────────────────────────
    print("\n[3/4] Buscando macro de hoje via yfinance...")
    macro = fetch_live_macro(cfg)
    filled = sum(1 for v in macro.values() if _is_finite(v))
    print(f"  {filled}/{len(macro)} features preenchidas\n")

    # ── 4. Walk-forward + sinal ───────────────────────────────────────────────
    print("[4/4] Walk-forward + geração de sinal...")
    t1 = time.time()
    payload, pred, metrics = run_signal_pipeline(cfg, df, mt5_bars=mt5_bars, today_macro=macro)
    dur = time.time() - t1

    _print_results(cfg, payload, metrics, dur)

    # ── Salva JSON ────────────────────────────────────────────────────────────
    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sinal_{key}_hoje.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Salvo: {out_path}\n")

    return payload


def _print_results(cfg: SymbolConfig, payload: dict, metrics: dict, dur: float = 0.0):
    """Imprime resultados formatados."""
    prob = metrics["probabilistic"]
    # Usa payload["bootstrap"] — já tem chaves ci_lo/ci_hi/sig transformadas por _build_payload
    boot = payload.get("bootstrap", {})
    op   = metrics["operational_paper"]
    base = metrics.get("baselines", {})
    sep  = "-" * 55

    print(f"\n{sep}")
    print(f"  Resultados walk-forward — {cfg.label}")
    print(sep)

    auc  = float(prob.get("auc_up") or 0)
    mcc  = float(prob.get("mcc_multiclass") or 0)
    acc  = float(prob.get("accuracy") or 0)
    maj  = float(base.get("majority_accuracy") or 0)
    wf   = payload["walk_forward"]

    print(f"  Sessões: {wf['sessions']}  |  Folds: {wf['folds']}  |  Tempo: {dur:.0f}s")
    print(f"  AUC(up vs rest):  {auc:.4f}")
    print(f"  MCC:              {mcc:.4f}")
    print(f"  Acuracia modelo:  {acc:.1%}  (maioria: {maj:.1%})")

    def _bstr(key, label):
        b = boot.get(key)
        if not b or not isinstance(b, dict):
            return f"  {label}: --"
        ci_lo = b.get("ci_lo") or b.get("ci95_lower") or 0
        ci_hi = b.get("ci_hi") or b.get("ci95_upper") or 0
        mean  = b.get("mean") or 0
        sig   = b.get("sig") or ((ci_lo > 0) or (ci_hi < 0))
        s     = " (*)" if sig else ""
        return f"  {label}: {mean:.4f}  IC95=[{ci_lo:.3f},{ci_hi:.3f}]{s}"

    if boot:
        print(_bstr("auc_up",                   "Bootstrap AUC"))
        print(_bstr("mcc_multiclass",            "Bootstrap MCC"))
        print(_bstr("ev_points_per_study_case",  "Bootstrap EV "))

    hit   = float(op.get("hit_rate_study_cases") or 0)
    ev    = float(op.get("ev_points_per_study_case") or 0)
    pnl   = float(op.get("total_pnl_points") or 0)
    pf    = float(op.get("profit_factor") or 0)
    cases = int(op.get("study_cases") or 0)
    total = int(op.get("rows") or 0)

    print(f"\n  Paper -- {cases} casos / {total} sessoes")
    print(f"  Hit Rate:      {hit:.1%}")
    print(f"  EV/trade:      {ev:+.2f} {cfg.unit}")
    print(f"  PnL total:     {pnl:+.2f} {cfg.unit}")
    print(f"  Profit Factor: {pf:.2f}")

    print(f"\n{sep}")
    print(f"  SINAL DE HOJE -- {cfg.label}")
    print(sep)

    dec   = payload["decisao"]
    edge  = payload["edge"]
    pu    = payload["p_up"]
    pd_   = payload["p_down"]
    pf_   = payload["p_flat"]
    conf  = payload["confidence"]
    gap_p = payload["expected_gap_points_proxy"]

    badges = {
        "COMPRA ESTUDO": "COMPRA ESTUDO",
        "VENDA ESTUDO":  "VENDA ESTUDO",
    }
    badge = badges.get(dec, "AGUARDAR")
    print(f"  Decisao:    {badge}")
    print(f"  Edge:       {edge:+.4f}")
    print(f"  Confianca:  {conf:.1%}")
    print(f"  P(alta):    {pu:.1%}  P(baixa): {pd_:.1%}  P(flat): {pf_:.1%}")
    print(f"  Gap proxy:  {gap_p:+.2f} {cfg.unit}")
    print()
    print("  Sinal educacional/paper. Nao envia ordens.")
    print("  Nao e recomendacao de investimento.")
    print(sep)
