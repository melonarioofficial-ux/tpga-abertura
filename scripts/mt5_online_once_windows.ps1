param(
  [string]$Symbol = "NDX100",
  [int]$HistoryBars = 200000,
  [int]$RecentBars = 600
)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
python -m tpga.cli mt5-online-once --symbol $Symbol --history-bars $HistoryBars --recent-bars $RecentBars --close-time 17:59 --open-time 19:00 --signal-time 17:49
