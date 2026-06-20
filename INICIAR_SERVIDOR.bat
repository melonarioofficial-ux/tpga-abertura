@echo off
REM ============================================================
REM  TPGA - Servidor local de sinais (MT5 ao vivo)
REM  Deixe o MetaTrader 5 ABERTO e LOGADO antes de rodar.
REM ============================================================
cd /d C:\50-Robo_abertura_Python
call .venv\Scripts\activate.bat

echo Instalando/atualizando dependencias do servidor...
pip install -q -r requirements-server.txt

echo.
echo Iniciando servidor em http://localhost:8000 ...
echo (Deixe esta janela ABERTA enquanto quiser os sinais no ar)
echo.
python server_mt5.py

pause
