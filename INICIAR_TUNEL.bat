@echo off
REM ============================================================
REM  TPGA - Tunel Cloudflare (expoe o servidor local na internet)
REM  Rode DEPOIS de iniciar o servidor (INICIAR_SERVIDOR.bat).
REM
REM  Na 1a vez, instale o cloudflared:
REM     winget install --id Cloudflare.cloudflared
REM
REM  Este modo "quick tunnel" gera uma URL https aleatoria a cada
REM  execucao (ex.: https://algo-aleatorio.trycloudflare.com).
REM  Copie essa URL e cole em public\config.js (window.TPGA_API_BASE),
REM  depois rode DEPLOY_FINAL.ps1 de novo para publicar.
REM
REM  Para URL FIXA (dominio proprio), use um tunnel nomeado:
REM     cloudflared tunnel login
REM     cloudflared tunnel create tpga
REM     cloudflared tunnel route dns tpga sinais.SEUDOMINIO.com
REM     cloudflared tunnel run --url http://localhost:8000 tpga
REM ============================================================

echo Abrindo tunel Cloudflare para http://localhost:8000 ...
echo Procure a linha "https://....trycloudflare.com" abaixo e copie a URL.
echo.
cloudflared tunnel --url http://localhost:8000

pause
