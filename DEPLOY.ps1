# ================================================================
#  TPGA — Deploy completo para GitHub + Vercel
#  Execute: .\DEPLOY.ps1
# ================================================================

$REPO_URL = "COLE_AQUI_URL_DO_SEU_REPO_GITHUB"
# Exemplo: "https://github.com/melonarioofficial/tpga-abertura.git"

# ── Validação ────────────────────────────────────────────────────
if ($REPO_URL -eq "COLE_AQUI_URL_DO_SEU_REPO_GITHUB") {
    Write-Host ""
    Write-Host "ERRO: Defina a URL do seu repo GitHub no topo deste script." -ForegroundColor Red
    Write-Host "Acesse github.com/new para criar um repositorio e cole a URL." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Set-Location "C:\50-Robo_abertura_Python"

# ── Ativa venv ───────────────────────────────────────────────────
Write-Host ""
Write-Host "=== PASSO 1: Gerando os 3 sinais para a Vercel (sem MT5) ===" -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1
python generate_signal_ci.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO ao gerar sinais. Verifique o ambiente Python." -ForegroundColor Red
    exit 1
}

# ── Git setup ────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== PASSO 2: Configurando Git ===" -ForegroundColor Cyan

git init
git remote remove origin 2>$null
git remote add origin $REPO_URL

git config user.email "melonario.official@gmail.com"
git config user.name  "Wilson"

# ── Commit & push ────────────────────────────────────────────────
Write-Host ""
Write-Host "=== PASSO 3: Commit e push para GitHub ===" -ForegroundColor Cyan

git add .
git commit -m "feat: TPGA v1 — NDX100 | XAUUSD | DAX40 — deploy Vercel"
git branch -M main
git push -u origin main --force

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERRO no push. Possivelmente precisa autenticar no GitHub." -ForegroundColor Red
    Write-Host "Solucao: instale GitHub CLI ( winget install GitHub.cli )" -ForegroundColor Yellow
    Write-Host "Depois rode: gh auth login" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  CODIGO NO GITHUB! Agora importe na Vercel:" -ForegroundColor Green
Write-Host ""
Write-Host "  1. vercel.com -> Add New -> Import Git Repository" -ForegroundColor White
Write-Host "  2. Selecione o repo que acabou de subir" -ForegroundColor White
Write-Host "  3. Framework: Other | Output Dir: public" -ForegroundColor White
Write-Host "  4. Deploy!" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
