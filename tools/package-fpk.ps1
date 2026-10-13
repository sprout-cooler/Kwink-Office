# Build FPK package: encoding -> clean -> slim -> tests -> gate -> fnpack build -> restore.
# Usage: powershell -ExecutionPolicy Bypass -File tools\package-fpk.ps1
# Prereq: web built -- run `npm run build` in omnioffice/app/web first.
# NOTE: ASCII-only file (PowerShell 5.1 BOM-less ANSI parsing).
#
# PowerShell trap avoided here: with $ErrorActionPreference='Stop', a native
# command (node/python/fnpack) returning a non-zero exit code aborts the script
# before we can read $LASTEXITCODE. Each step therefore goes through
# Invoke-Step, which checks the exit code explicitly and always restores the
# slimmed-out dependencies before exiting.

$ErrorActionPreference = 'Stop'
$proj = "e:\Project\FN\All-in-OneOffice"
$node = "$proj\.tools\node\node.exe"
$python = "$proj\.tools\python\python.exe"
$fnpack = "$proj\.tools\fnpack.exe"
$slim = "$proj\build\slim_package.py"
$slimmed = $false

function Restore-Deps {
    if ($script:slimmed) {
        Write-Host "[restore] putting node_modules / __pycache__ back"
        & $python $slim --restore | Out-Host
        $script:slimmed = $false
    }
}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "==> $Name"
    $global:LASTEXITCODE = 0
    & $Action | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Restore-Deps
        Write-Error "$Name FAILED (exit=$LASTEXITCODE)"
    }
}

try {
    # 1) normalize encoding for every file that goes to Linux (hard rule, guide 1.3)
    Invoke-Step "normalize-encoding" { & $node "$proj\build\normalize-encoding.mjs" }

    # 1b) drop stale hashed web bundles (vite emptyOutDir=false leaves them behind)
    Invoke-Step "clean-web-assets" { & $python "$proj\build\clean_web_assets.py" }

    # 1c) move node_modules / __pycache__ out of the FPK.
    #     .dockerignore only applies to `docker build`; fnpack ignores it, so
    #     13k files would otherwise ship inside app.tgz and slow down install.
    Invoke-Step "slim-package" { & $python $slim }
    $slimmed = $true

    # 2) server unit tests (portable python; failures block packaging)
    Invoke-Step "server-unit-tests" { & $python "$proj\omnioffice\app\server\run_tests.py" }

    # 3) packaging gate (hard gate before fnpack build)
    Invoke-Step "check-fpk-gate" { & $node "$proj\build\check-fpk.mjs" }

    # 4) fnpack build (cwd = package root) -> outputs omnioffice.fpk
    Invoke-Step "fnpack-build" {
        Push-Location "$proj\omnioffice"
        try { & $fnpack build } finally { Pop-Location }
    }

    # 4b) rename to a versioned file so previous releases are NEVER overwritten.
    #     manifest carries `version=X.Y.Z`; the build's plain omnioffice.fpk
    #     always becomes omnioffice-<version>.fpk. Historic versions stay on disk.
    $verLine = Select-String -Path "$proj\omnioffice\manifest" -Pattern '^version=(.+)$' | Select-Object -First 1
    if ($verLine) {
        $ver = $verLine.Matches.Groups[1].Value.Trim()
        $src = "$proj\omnioffice\omnioffice.fpk"
        $dst = "$proj\omnioffice\omnioffice-$ver.fpk"
        if (Test-Path $src) {
            Move-Item -Force $src $dst
            Write-Host ("==> versioned FPK: omnioffice-{0}.fpk" -f $ver)
        }
    } else {
        Write-Warning "manifest version not found; leaving omnioffice.fpk as-is"
    }
} finally {
    # Always restore, so the next frontend build still has its dependency tree.
    Restore-Deps
}

Get-ChildItem "$proj\omnioffice\omnioffice-*.fpk" -ErrorAction SilentlyContinue |
    Sort-Object Name |
    ForEach-Object { Write-Output ("FPK: {0} ({1} MB)" -f $_.FullName, [math]::Round($_.Length / 1MB, 2)) }
