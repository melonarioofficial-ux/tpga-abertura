@echo off
echo ============================================
echo  TPGA NDX100 - BACKTEST COM DADOS REAIS MT5
echo ============================================
echo.
echo ATENCAO: O MetaTrader 5 precisa estar aberto
echo e logado com o simbolo NDX100 visivel.
echo.
cd /d "%~dp0"

REM Ativa o ambiente virtual se existir
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo Ambiente virtual ativado.
) else (
    echo Usando Python global.
)

echo.
echo [1/2] Rodando validacao com dados reais do MT5...
echo      Isso pode levar 2-5 minutos (download + walk-forward)
echo.

python -m tpga.cli mt5-online-validate ^
    --symbol NDX100 ^
    --min-train-size 120 ^
    --history-bars 300000 ^
    --output reports\resultado_real_mt5.md

echo.
echo [2/2] Gerando sinal ao vivo atual...
echo.

python -m tpga.cli mt5-online-once ^
    --symbol NDX100 ^
    --history-bars 300000

echo.
echo ============================================
echo Resultados salvos em: reports\resultado_real_mt5.md
echo ============================================
pause
