@echo off
title TPGA Deploy
echo Iniciando TPGA Deploy...
echo Rodando: powershell -ExecutionPolicy Bypass -File DEPLOY_AUTO.ps1
powershell -ExecutionPolicy Bypass -File "C:\50-Robo_abertura_Python\DEPLOY_AUTO.ps1"
echo.
echo Script finalizado com codigo: %ERRORLEVEL%
pause
