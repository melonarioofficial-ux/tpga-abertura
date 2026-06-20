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
$argsList = @("-m", "tpga.cli", "mt5-live-once", "--symbol", $Symbol, "--start", $Start, "--end", $End, "--close-time", $CloseTime, "--open-time", $OpenTime, "--recent-bars", "600", "--output", "reports\mt5_live_once.json")
if ($SignalTime -ne "") { $argsList += @("--signal-time", $SignalTime) }
if ($TerminalPath -ne "") { $argsList += @("--terminal-path", $TerminalPath) }
python @argsList
notepad reports\mt5_live_once.json
