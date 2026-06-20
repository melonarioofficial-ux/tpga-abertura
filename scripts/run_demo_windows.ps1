Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
python -m tpga.cli make-sample --output examples/sample_gap_data.csv
python -m tpga.cli validate-demo --output reports/demo_report.md --predictions reports/demo_predictions.csv
Write-Host "Pronto. Abra reports/demo_report.md"
