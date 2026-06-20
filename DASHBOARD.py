"""
TPGA — Dashboard Local (NDX100 | XAUUSD | DAX 40)
===================================================
Inicia servidor HTTP local e abre o dashboard no navegador.

    python DASHBOARD.py

Acesse: http://localhost:8765
Ctrl+C para encerrar.

Gere os sinais antes de abrir o dashboard:
  python SINAL_HOJE_HIBRIDO.py      → NDX100
  python SINAL_XAUUSD_HIBRIDO.py   → XAUUSD
  python SINAL_DAX_HIBRIDO.py      → DAX 40
"""
from __future__ import annotations

import json
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

BASE_DIR      = Path(__file__).parent
REPORT_DIR    = BASE_DIR / "reports"
DASHBOARD_DIR = BASE_DIR / "dashboard"
PORT = 8765

# Mapeamento chave → lista de caminhos (tenta em ordem, usa o primeiro que existe)
# Lista de fallback mantém compatibilidade com nomes legados dos scripts originais
SIGNAL_FILES: dict[str, list[Path]] = {
    "ndx": [
        REPORT_DIR / "sinal_ndx_hoje.json",
        REPORT_DIR / "sinal_hibrido_hoje.json",     # legado SINAL_HOJE_HIBRIDO.py
    ],
    "xau": [
        REPORT_DIR / "sinal_xau_hoje.json",
        REPORT_DIR / "sinal_xauusd_hoje.json",      # legado SINAL_XAUUSD_HIBRIDO.py
    ],
    "dax": [
        REPORT_DIR / "sinal_dax_hoje.json",
    ],
}

SIGNAL_SCRIPTS = {
    "ndx": "SINAL_HOJE_HIBRIDO.py",
    "xau": "SINAL_XAUUSD_HIBRIDO.py",
    "dax": "SINAL_DAX_HIBRIDO.py",
}

REPORT_MD = REPORT_DIR / "resultado_hibrido.md"


def _find_signal(key: str) -> Optional[Path]:
    """Retorna o primeiro arquivo de sinal existente para a chave."""
    for p in SIGNAL_FILES.get(key, []):
        if p.exists():
            return p
    return None


class TpgaHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silencia log de cada request

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        # ── API: sinais ───────────────────────────────────────────────────────
        SIGNAL_ROUTES: dict[str, str] = {
            "/api/signal_ndx":   "ndx",
            "/api/signal_xau":   "xau",
            "/api/signal_dax":   "dax",
            # Rotas legadas (backwards compat)
            "/api/signal":       "ndx",
            "/api/signal_xauusd": "xau",
        }
        if path in SIGNAL_ROUTES:
            key = SIGNAL_ROUTES[path]
            sig_path = _find_signal(key)
            if sig_path:
                self._send(200, "application/json", sig_path.read_bytes())
            else:
                script = SIGNAL_SCRIPTS.get(key, f"SINAL_{key.upper()}_HIBRIDO.py")
                msg = json.dumps({
                    "error": (
                        f"Sinal {key.upper()} não encontrado. "
                        f"Execute: python {script}"
                    )
                }).encode()
                self._send(200, "application/json", msg)
            return

        # ── API: relatório markdown ───────────────────────────────────────────
        if path == "/api/report":
            if REPORT_MD.exists():
                text = REPORT_MD.read_text(encoding="utf-8")
                data = json.dumps({"markdown": text}).encode("utf-8")
            else:
                data = json.dumps({"markdown": "Relatório não encontrado."}).encode()
            self._send(200, "application/json", data)
            return

        # ── API: status dos 3 sinais ──────────────────────────────────────────
        if path == "/api/status":
            status_map = {}
            for key in ["ndx", "xau", "dax"]:
                p = _find_signal(key)
                status_map[key] = {
                    "exists": bool(p),
                    "path":   str(p) if p else None,
                    "mtime":  p.stat().st_mtime if p else None,
                }
            self._send(200, "application/json", json.dumps(status_map).encode())
            return

        # ── Arquivos estáticos do dashboard ───────────────────────────────────
        if path in ("/", "/index.html"):
            file_path = DASHBOARD_DIR / "index.html"
        else:
            file_path = DASHBOARD_DIR / path.lstrip("/")

        if file_path.exists() and file_path.is_file():
            ext = file_path.suffix.lower()
            ct_map = {
                ".html": "text/html; charset=utf-8",
                ".css":  "text/css",
                ".js":   "application/javascript",
                ".json": "application/json",
                ".png":  "image/png",
                ".ico":  "image/x-icon",
            }
            self._send(200, ct_map.get(ext, "application/octet-stream"), file_path.read_bytes())
        else:
            self._send(404, "text/plain", b"404 Not Found")


def main():
    if not DASHBOARD_DIR.exists() or not (DASHBOARD_DIR / "index.html").exists():
        print("ERRO: dashboard/index.html não encontrado.")
        sys.exit(1)

    # Verifica quais sinais estão presentes
    present  = [k for k in ["ndx", "xau", "dax"] if _find_signal(k)]
    missing  = [k for k in ["ndx", "xau", "dax"] if not _find_signal(k)]

    print(f"{'='*60}")
    print(f"  TPGA Dashboard — NDX100 | XAUUSD | DAX 40")
    print(f"  http://localhost:{PORT}")
    print(f"{'='*60}")

    if present:
        print(f"  Sinais prontos : {[k.upper() for k in present]}")
    if missing:
        print(f"  Sinais ausentes: {[k.upper() for k in missing]}")
        print(f"  → Gere antes de abrir o dashboard:")
        for k in missing:
            print(f"      python {SIGNAL_SCRIPTS[k]}")
    print(f"\n  Ctrl+C para encerrar\n")

    time.sleep(0.3)
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        HTTPServer(("localhost", PORT), TpgaHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
