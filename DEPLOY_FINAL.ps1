# ================================================================
#  TPGA -- Deploy final (arquitetura MT5 ao vivo)
#  Publica APENAS o frontend na Vercel. Os sinais sao calculados
#  pelo servidor local (server_mt5.py) e lidos via tunel Cloudflare.
#
#  Pre-requisito: edite public\config.js com a URL do seu tunel.
#  Execute:  powershell -ExecutionPolicy Bypass -File .\DEPLOY_FINAL.ps1
# ================================================================
$ErrorActionPreference = "Continue"
Set-Location "C:\50-Robo_abertura_Python"

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n/3] $msg" -ForegroundColor Cyan
    Write-Host ("-" * 55) -ForegroundColor DarkGray
}

# ── Aviso sobre a URL do tunel ───────────────────────────────────
$cfg = Get-Content "public\config.js" -Raw
if ($cfg -match "localhost:8000") {
    Write-Host ""
    Write-Host "AVISO: public\config.js ainda aponta para localhost." -ForegroundColor Yellow
    Write-Host "O site publicado so funcionara quando voce colar a URL do" -ForegroundColor Yellow
    Write-Host "tunel Cloudflare nesse arquivo. Deseja continuar mesmo assim?" -ForegroundColor Yellow
    $resp = Read-Host "Continuar? (S/N)"
    if ($resp -ne "S" -and $resp -ne "s") {
        Write-Host "Deploy cancelado. Edite public\config.js e rode de novo." -ForegroundColor Red
        exit 1
    }
}

# ── PASSO 1: Commit + push no GitHub ─────────────────────────────
Step 1 "Enviando codigo para o GitHub..."
git add -A
git diff --staged --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "deploy: arquitetura MT5 ao vivo (servidor local + tunel)"
    git push
} else {
    Write-Host "Nada novo para commitar." -ForegroundColor DarkGray
}

# ── PASSO 2: Deploy do frontend na Vercel ────────────────────────
Step 2 "Publicando frontend na Vercel (producao)..."
$vercel = Get-Command vercel -ErrorAction SilentlyContinue
if (-not $vercel) {
    Write-Host "Instalando Vercel CLI via npm..." -ForegroundColor Yellow
    npm install -g vercel
}
vercel --prod --yes

# ── PASSO 3: Concluido ───────────────────────────────────────────
Step 3 "Concluido!"
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  DEPLOY FINAL CONCLUIDO!" -ForegroundColor Green
Write-Host ""
Write-Host "  Site:   https://tpga-abertura.vercel.app" -ForegroundColor White
Write-Host "  GitHub: https://github.com/melonarioofficial-ux/tpga-abertura" -ForegroundColor White
Write-Host ""
Write-Host "  LEMBRETE: para o site mostrar dados, deixe rodando no PC:" -ForegroundColor Yellow
Write-Host "    1) MetaTrader 5 aberto e logado" -ForegroundColor Yellow
Write-Host "    2) INICIAR_SERVIDOR.bat" -ForegroundColor Yellow
Write-Host "    3) INICIAR_TUNEL.bat  (URL colada em public\config.js)" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Pressione ENTER para fechar"
