"""
TPGA Crude Oil WTI — Sinal Híbrido
=====================================
Preditor dominante: DXY (relação inversa — dólar forte = petróleo fraco)
Preditor secundário: XLE (setor energia) + S&P500 (demanda global)
flat_threshold=0.40 USD | custo=0.05 USD

Substituiu S&P500 (sem edge: EV=-0.74, PF=0.94, bootstrap IC95 inclui zero).

Uso:
    python SINAL_OIL_HIBRIDO.py

Saída:
    reports/sinal_oil_hoje.json
"""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

from tpga.signal_engine import run_instrument_pipeline

if __name__ == "__main__":
    run_instrument_pipeline("oil", use_mt5=True, save_dir="reports")
