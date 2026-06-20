Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -r requirements-mt5.txt
pip install -e .
Write-Host "Instalação TPGA v11 concluída."
