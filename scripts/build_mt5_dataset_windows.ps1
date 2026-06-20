param(
  [string]$Symbol = "NDX100",
  [string]$Start = "2025-01-01",
  [string]$End = "2026-06-18",
  [string]$CloseTime = "17:59",
  [string]$OpenTime = "19:00",
  [string]$SignalTime = "",
  [string]$TerminalPath = ""
)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
.\.venv\Scripts\Activate.ps1
$argsList = @("-m", "tpga.cli", "mt5-build-gap-csv", "--symbol", $Symbol, "--start", $Start, "--end", $End, "--close-time", $CloseTime, "--open-time", $OpenTime, "--output", "data\mt5_gap_dataset.csv", "--raw-bars-output", "data\mt5_raw_bars.csv")
if ($SignalTime -ne "") { $argsList += @("--signal-time", $SignalTime) }
if ($TerminalPath -ne "") { $argsList += @("--terminal-path", $TerminalPath) }
python @argsList
