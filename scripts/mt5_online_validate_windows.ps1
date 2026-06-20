param(
  [string]$Symbol = "NDX100",
  [int]$HistoryBars = 200000
)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
python -m tpga.cli mt5-online-validate --symbol $Symbol --history-bars $HistoryBars --close-time 17:59 --open-time 19:00 --signal-time 17:49 --output reports\mt5_online_report.md
