"""
TPGA DAX 40 (Alemanha) — Sinal Híbrido
========================================
Preditor principal: S&P500 (fecha após Frankfurt) + EUR/USD + Euro Stoxx
flat_threshold=25 pts | custo=2 pts

Uso:
    python SINAL_DAX_HIBRIDO.py

Saída:
    reports/sinal_dax_hoje.json
"""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

from tpga.signal_engine import run_instrument_pipeline

if __name__ == "__main__":
    run_instrument_pipeline("dax", use_mt5=True, save_dir="reports")
