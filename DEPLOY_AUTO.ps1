# TPGA -- Deploy automatico completo (PS 5.x, ASCII-only)
# Gera sinais -> GitHub -> Vercel
$ErrorActionPreference = "Continue"

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n/4] $msg" -ForegroundColor Cyan
    Write-Host ("-" * 55) -ForegroundColor DarkGray
}

Set-Location "C:\50-Robo_abertura_Python"

# PASSO 1: Gera os 3 sinais
Step 1 "Gerando sinais via yfinance (NDX | XAU | DAX)..."
& "C:\50-Robo_abertura_Python\.venv\Scripts\python.exe" generate_signal_ci.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVISO: sinais com erro -- continuando." -ForegroundColor Yellow
}

# PASSO 2: GitHub CLI
Step 2 "Configurando GitHub..."

$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
$ghPath = if ($ghCmd) { $ghCmd.Source } else { $null }

if (-not $ghPath) {
    Write-Host "Instalando GitHub CLI via winget..." -ForegroundColor Yellow
    winget install --id GitHub.cli -e --silent --accept-package-agreements --accept-source-agreements
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
}

Write-Host "Autenticando no GitHub (browser vai abrir -- clique Authorize)..." -ForegroundColor Yellow
gh auth login --web --git-protocol https --hostname github.com

git init 2>$null
git config user.email "melonario.official@gmail.com"
git config user.name  "Wilson"

git rm -r --cached .venv 2>$null
git rm -r --cached __pycache__ 2>$null

git add .
git add -f public/signal.json
git add -f public/signal_xauusd.json
git add -f public/signal_dax.json
git commit -m "feat: TPGA v1 -- NDX100 | XAUUSD | DAX40 -- deploy inicial"
git branch -M main

Write-Host "Criando repo publico no GitHub e fazendo push..." -ForegroundColor Yellow
$REPO_NAME = "tpga-abertura"

gh repo create $REPO_NAME --public --source=. --remote=origin --push --description "TPGA - Previsao de Gap de Abertura de Mercado" 2>&1 | Out-String | Write-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host "Repo ja existe -- push direto..." -ForegroundColor Yellow
    $ghUser = (gh api user --jq .login 2>$null)
    if ($ghUser) { $ghUser = $ghUser.Trim() }
    git remote remove origin 2>$null
    git remote add origin "https://github.com/$ghUser/$REPO_NAME.git"
    git push -u origin main --force
}

$ghUser2 = (gh api user --jq .login 2>$null)
if ($ghUser2) { $ghUser2 = $ghUser2.Trim() }
$REPO_URL = "https://github.com/$ghUser2/$REPO_NAME"
Write-Host ""
Write-Host "GitHub: $REPO_URL" -ForegroundColor Green

# PASSO 3: Vercel CLI
Step 3 "Deploy na Vercel..."

$vercelCmd = Get-Command vercel -ErrorAction SilentlyContinue
$vercelPath = if ($vercelCmd) { $vercelCmd.Source } else { $null }

if (-not $vercelPath) {
    Write-Host "Instalando Vercel CLI..." -ForegroundColor Yellow
    npm install -g vercel --silent
}

Write-Host "Login na Vercel (browser vai abrir -- clique Confirm)..." -ForegroundColor Yellow
vercel login

Write-Host "Deploy para producao..." -ForegroundColor Yellow
vercel --prod --yes --name "tpga-abertura"

# PASSO 4: Fim
Step 4 "Concluido!"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  DEPLOY CONCLUIDO!" -ForegroundColor Green
Write-Host ""
Write-Host "  Site: https://tpga-abertura.vercel.app" -ForegroundColor White
Write-Host "  GitHub: $REPO_URL" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Pressione qualquer tecla para fechar..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
