"""
TPGA — Servidor local de sinais (MT5 ao vivo)
=============================================
Roda NA SUA MÁQUINA, com o MetaTrader 5 aberto e logado.
Calcula os sinais com dados REAIS do MT5 e os expõe via HTTP (JSON),
para que tanto o app local quanto o site na Vercel leiam a MESMA fonte real.

NADA é "subido" para a Vercel — o site apenas consome este servidor através
de um túnel público (Cloudflare Tunnel). Quando este servidor / MT5 estiver
desligado, o site mostra "offline".

Como rodar:
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements-server.txt
    python server_mt5.py

Endpoints:
    GET /api/health          -> status do servidor e do MT5
    GET /api/signal/<key>    -> sinal de um instrumento (ndx | xau | dax)
    GET /api/signals         -> os 3 sinais de uma vez
"""
from __future__ import annotations

import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "src")

from flask import Flask, jsonify
from flask_cors import CORS

from tpga.signal_engine import (
    SYMBOLS,
    ACTIVE_INSTRUMENTS,
    build_yf_dataset,
    fetch_live_macro,
    run_signal_pipeline,
)

# ──────────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────────
PORT             = 8000
REFRESH_SECONDS  = 300        # recalcula cada instrumento a cada 5 min
DATASET_TTL_SEC  = 3600       # rebaixa o histórico yfinance no máx. 1x/hora
MT5_BARS         = 2000       # barras M1 a puxar do MT5

# Brokers usam nomes diferentes para o mesmo ativo — tentamos vários.
ALT_SYMBOLS: dict[str, list[str]] = {
    "ndx": ["NDX100", "NAS100", "US100", "NASDAQ100", "NQ100", "USTECH100"],
    "xau": ["XAUUSD", "XAU/USD", "GOLD", "XAUUSD."],
    "dax": ["GER40", "DE40", "DAX40", "DAX", "GER30", "DAXEUR", "GER40."],
}

# ──────────────────────────────────────────────────────────────────────────────
# Cache em memória (preenchido por thread em background)
# ──────────────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cache: dict[str, dict] = {}          # key -> payload pronto
_dataset_cache: dict[str, tuple] = {} # key -> (df_hist, epoch)
_state = {
    "mt5_connected": False,
    "last_refresh": None,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "errors": {},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pull_mt5_bars(cfg, key):
    """Tenta puxar barras M1 do MT5 testando nomes alternativos do símbolo.
    Retorna (bars_df | None, symbol_usado | None)."""
    try:
        from tpga.mt5_client import MT5Client, MT5ConnectionConfig
    except Exception:
        return None, None

    symbols_to_try = [cfg.symbol_mt5] + [
        s for s in ALT_SYMBOLS.get(key, []) if s != cfg.symbol_mt5
    ]
    for sym in symbols_to_try:
        try:
            conn = MT5ConnectionConfig(symbol=sym)
            with MT5Client(conn) as client:
                bars = client.copy_recent_rates(
                    sym, timeframe="M1", count=MT5_BARS, tz_name=cfg.timezone
                )
            if bars is not None and not bars.empty:
                return bars, sym
        except Exception:
            continue
    return None, None


def _get_dataset(cfg, key):
    """Histórico yfinance com cache de 1h (download é lento)."""
    now = time.time()
    cached = _dataset_cache.get(key)
    if cached and (now - cached[1]) < DATASET_TTL_SEC:
        return cached[0]
    df = build_yf_dataset(cfg, verbose=False)
    if df is not None and len(df) >= 120:
        _dataset_cache[key] = (df, now)
    return df


def compute_signal(key: str) -> dict:
    """Calcula o sinal de um instrumento com MT5 ao vivo (+ macro yfinance)."""
    cfg = SYMBOLS[key]

    df = _get_dataset(cfg, key)
    if df is None or len(df) < 120:
        raise RuntimeError(f"Dados históricos insuficientes para {cfg.name}")

    mt5_bars, used_symbol = _pull_mt5_bars(cfg, key)
    mt5_ok = mt5_bars is not None and not mt5_bars.empty
    with _lock:
        _state["mt5_connected"] = _state["mt5_connected"] or mt5_ok

    macro = fetch_live_macro(cfg)

    if mt5_ok:
        source_mode = f"mt5_live_{key}"
    else:
        source_mode = f"yfinance_fallback_{key}"

    payload, _, _ = run_signal_pipeline(
        cfg, df, mt5_bars=mt5_bars, today_macro=macro, source_mode=source_mode,
    )
    payload["server_updated_at"] = _now_iso()
    payload["mt5_symbol"]        = used_symbol or ""
    payload["data_source"]       = "MT5 (real)" if mt5_ok else "yfinance (aprox.)"
    return payload


# ──────────────────────────────────────────────────────────────────────────────
# Worker em background — recalcula os 3 sinais em loop
# ──────────────────────────────────────────────────────────────────────────────
def _refresh_loop():
    while True:
        mt5_seen = False
        for key in ACTIVE_INSTRUMENTS:
            try:
                payload = compute_signal(key)
                with _lock:
                    _cache[key] = payload
                    _state["errors"].pop(key, None)
                if payload.get("mt5_symbol"):
                    mt5_seen = True
                print(f"[{_now_iso()}] {key.upper()}: {payload['decisao']} "
                      f"({payload['data_source']})")
            except Exception as e:
                with _lock:
                    _state["errors"][key] = str(e)
                print(f"[{_now_iso()}] ERRO em {key}: {e}")
                traceback.print_exc()
        with _lock:
            _state["mt5_connected"] = mt5_seen
            _state["last_refresh"]  = _now_iso()
        time.sleep(REFRESH_SECONDS)


# ──────────────────────────────────────────────────────────────────────────────
# Flask app
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)  # libera o site da Vercel a consumir esta API


@app.get("/api/health")
def health():
    with _lock:
        ready = sorted(_cache.keys())
        return jsonify({
            "status":        "online",
            "mt5_connected": _state["mt5_connected"],
            "instruments_ready": ready,
            "last_refresh":  _state["last_refresh"],
            "started_at":    _state["started_at"],
            "errors":        _state["errors"],
        })


@app.get("/api/signal/<key>")
def signal(key):
    key = key.lower()
    if key not in SYMBOLS:
        return jsonify({"error": f"Instrumento desconhecido: {key}"}), 404
    with _lock:
        payload = _cache.get(key)
        err = _state["errors"].get(key)
    if payload is None:
        return jsonify({
            "error": "Sinal ainda não calculado. Servidor aquecendo ou MT5 indisponível.",
            "detail": err,
        }), 503
    return jsonify(payload)


@app.get("/api/signals")
def signals():
    with _lock:
        return jsonify({k: _cache.get(k) for k in ACTIVE_INSTRUMENTS})


@app.get("/")
def root():
    return jsonify({"service": "TPGA MT5 signal server", "see": "/api/health"})


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  TPGA — Servidor local de sinais (MT5 ao vivo)")
    print(f"  Porta: {PORT}  |  Refresh: {REFRESH_SECONDS}s")
    print("  Deixe o MetaTrader 5 ABERTO e LOGADO.")
    print("=" * 60)

    threading.Thread(target=_refresh_loop, daemon=True).start()

    try:
        from waitress import serve
        print(f"Servindo em http://0.0.0.0:{PORT} (waitress)")
        serve(app, host="0.0.0.0", port=PORT)
    except ImportError:
        print(f"Servindo em http://0.0.0.0:{PORT} (flask dev)")
        app.run(host="0.0.0.0", port=PORT, threaded=True)
