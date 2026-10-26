# Stop local dev environment started by start-dev.ps1
$ErrorActionPreference = 'Continue'
$pids = "e:\Project\FN\KwinkOffice\.tools\dev-logs\pids.txt"
if (Test-Path $pids) {
    Get-Content $pids | ForEach-Object {
        $p = $_.Trim()
        if ($p -match '^\d+$') { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item $pids -ErrorAction SilentlyContinue
}
Write-Output "dev environment stopped"
