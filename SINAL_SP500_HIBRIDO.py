"""
TPGA S&P 500 (EUA) — Sinal Híbrido
=====================================
Valida o edge ao lado do NDX100 com custo menor (1 pt round-trip).
flat_threshold=5 pts | custo=1 pt

Uso:
    python SINAL_SP500_HIBRIDO.py

Saída:
    reports/sinal_sp5_hoje.json
"""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

from tpga.signal_engine import run_instrument_pipeline

if __name__ == "__main__":
    run_instrument_pipeline("sp5", use_mt5=True, save_dir="reports")
