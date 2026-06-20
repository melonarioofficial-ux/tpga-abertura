"""
TPGA Nikkei 225 (Japão) — Sinal Híbrido
==========================================
Preditor dominante: USD/JPY (documentado na literatura acadêmica)
Preditor secundário: S&P500 (fecha após Tóquio)
flat_threshold=100 pts | custo=15 pts

Uso:
    python SINAL_NIKKEI_HIBRIDO.py

Saída:
    reports/sinal_nky_hoje.json
"""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

from tpga.signal_engine import run_instrument_pipeline

if __name__ == "__main__":
    run_instrument_pipeline("nky", use_mt5=True, save_dir="reports")
