# Start local dev environment: backend (TCP 8787) + fake-gateway (8788).
# Usage: powershell -ExecutionPolicy Bypass -File tools\start-dev.ps1
#   backend identity: gateway mode by default (X-Trim headers required, fake-gateway injects them)
# Stop: stop-dev.ps1
# NOTE: ASCII-only file (PowerShell 5.1 BOM-less ANSI parsing).
$ErrorActionPreference = 'Stop'
$proj = "e:\Project\FN\KwinkOffice"
$tools = "$proj\.tools"
$logs = "$proj\.tools\dev-logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$node = "$tools\node\node.exe"
$python = "$tools\python\python.exe"
if (-not (Test-Path $python)) { Write-Error "python not ready: run .tools\bootstrap.ps1 first" }
if (-not (Test-Path $node)) { Write-Error "node not ready: run .tools\bootstrap.ps1 first" }

$env:APP_VERSION = "1.0.0"
$env:IDENTITY_MODE = "gateway"
$env:DATA_DIR = "$proj\data"
$env:PYTHONPATH = "$proj\omnioffice\app\server"

# 1) backend on TCP 8787 (gateway mode: trusts X-Trim headers, fake-gateway injects them)
$backend = Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8787", "--app-dir", "$proj\omnioffice\app\server"
) -PassThru -WindowStyle Hidden -RedirectStandardOutput "$logs\backend.log" -RedirectStandardError "$logs\backend.err.log"

# 2) fake gateway on 8788 -> 8787 (prefix-forwarding + X-Trim injection, aligns fnOS gateway)
$gw = Start-Process -FilePath $node -ArgumentList @("$proj\tools\fake-gateway.mjs") -PassThru -WindowStyle Hidden -RedirectStandardOutput "$logs\gateway.log" -RedirectStandardError "$logs\gateway.err.log"

Start-Sleep -Seconds 3
Write-Output "backend pid=$($backend.Id)  log=$logs\backend.log"
Write-Output "gateway pid=$($gw.Id)  log=$logs\gateway.log"
Write-Output "app url  : http://127.0.0.1:8788/app/omnioffice/"
Write-Output "smoke    : $node $proj\tools\smoke.mjs"
Write-Output "stop     : powershell -ExecutionPolicy Bypass -File tools\stop-dev.ps1"
Set-Content -Encoding ascii "$proj\.tools\dev-logs\pids.txt" "$($backend.Id)`n$($gw.Id)"
