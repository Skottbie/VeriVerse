# start_all.ps1 — One-click launcher for VeriVerse BSC Dashboard
# Usage: .\start_all.ps1
# Starts: PCEG FastAPI (port 8002) + Express dashboard (port 3001)

$Root = $PSScriptRoot

# ── 1. Start PCEG FastAPI in a new window ─────────────────────────────────────
$pcegDir = Join-Path $Root "PCEG"
$venvPython = Join-Path $Root ".." ".venv\Scripts\python.exe" | Resolve-Path -ErrorAction SilentlyContinue
if (-not $venvPython) {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
}
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$pcegDir'; & '$venvPython' run_pceg_api.py"
) -WindowStyle Normal

Write-Host "[1/2] PCEG FastAPI starting on http://127.0.0.1:8002 ..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

# ── 2. Start Express dashboard in a new window ────────────────────────────────
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$Root'; node server.js"
) -WindowStyle Normal

Write-Host "[2/2] Express dashboard starting on http://127.0.0.1:3001 ..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

# ── 3. Open browser ───────────────────────────────────────────────────────────
Start-Process "http://127.0.0.1:3001"

Write-Host ""
Write-Host "All services launched." -ForegroundColor Green
Write-Host "  Dashboard : http://127.0.0.1:3001" -ForegroundColor White
Write-Host "  Agent 4   : http://127.0.0.1:3001/verify/agent/4" -ForegroundColor White
Write-Host "  Agent 9   : http://127.0.0.1:3001/verify/agent/9" -ForegroundColor White
Write-Host "  PCEG API  : http://127.0.0.1:8002/pceg/rankings" -ForegroundColor White
