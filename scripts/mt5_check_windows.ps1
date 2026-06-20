param(
  [string]$Symbol = "NDX100",
  [string]$TerminalPath = ""
)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
.\.venv\Scripts\Activate.ps1
if ($TerminalPath -eq "") {
  python -m tpga.cli mt5-check --symbol $Symbol
} else {
  python -m tpga.cli mt5-check --symbol $Symbol --terminal-path $TerminalPath
}
