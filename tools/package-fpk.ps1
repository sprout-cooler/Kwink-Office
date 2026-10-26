# Build FPK package: web build -> encoding -> clean -> tests -> slim -> gate -> build-fpk.js (auto version bump + versioned archive) -> restore.
# Usage: powershell -ExecutionPolicy Bypass -File tools\package-fpk.ps1 [-Bump patch|minor|major] [-SetVersion X.Y.Z] [-Tag] [-Message "..."]
# Prereq: none -- the web bundle is built automatically (step 0).
#
# Step 0 is PERMANENT and must never be removed again (it was deleted during the
# 1.0.18 rollback and immediately caused this build to fail with
# "frontend bundle is stale" because only src had changed). Never rely on
# remembering to run `npm run build` by hand.
# NOTE: ASCII-only file (PowerShell 5.1 BOM-less ANSI parsing).
#
# PowerShell trap avoided here: with $ErrorActionPreference='Stop', a native
# command (node/python/fnpack) returning a non-zero exit code aborts the script
# before we can read $LASTEXITCODE. Each step therefore goes through
# Invoke-Step, which checks the exit code explicitly and always restores the
# slimmed-out dependencies before exiting.
#
# Versioning (since the releases/ migration): packaging goes through
# scripts/build-fpk.js, which auto-bumps manifest.version (default patch) BEFORE
# fnpack build, archives to releases/<appname>_<version>_<platform>_<YYYYMMDD>[_n].fpk
# (never overwrites an existing package), appends releases/build-log.json, and
# hard-fails when git tag v<new-version> already exists (version reuse).
# Use -Bump/-SetVersion to control the bump, -Tag to also create the annotated
# tag, -Message for the build-log note. Old flow (fnpack build + rename to
# omnioffice-X.Y.Z.fpk) is gone -- do not reintroduce a manual rename.

# PowerShell 5.1 requires param() to be the FIRST statement in the file.
# It used to sit after $ErrorActionPreference, which made every invocation fail
# with "InvalidLeftHandSide" while parsing [string]$Bump = "patch".
param(
    [string]$Bump = "patch",
    [string]$SetVersion = "",
    [switch]$Tag,
    [string]$Message = ""
)
$ErrorActionPreference = 'Stop'
$proj = "e:\Project\FN\KwinkOffice"
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
    # 关键：原生命令（node/python/fnpack/npm）把**正常输出**写到 stderr 时，
    # 在 $ErrorActionPreference='Stop' 下会被 PowerShell 包成 ErrorRecord 并
    # 直接中止脚本 —— 哪怕退出码是 0。
    # 真实踩坑（2026-10-25，v1.0.27 打包）：vite 在 chunk 变大时输出
    # "(!) Some chunks are larger than 500 kB..." 警告到 stderr，
    # build-web 步骤被误判为失败，而 npm 实际 exit=0、构建完全成功。
    # 因此这里临时降级为 Continue，让**退出码成为唯一成败判据**
    # （这正是本函数注释声称的设计意图），结束后恢复原设置。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Action | Out-Host
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($LASTEXITCODE -ne 0) {
        Restore-Deps
        Write-Error "$Name FAILED (exit=$LASTEXITCODE)"
    }
}

try {
    # 0) normalize encoding FIRST (UTF-8 no BOM + LF for everything that goes to Linux).
    #
    #    ORDER MATTERS -- do not swap these two steps back.
    #    normalize-encoding.mjs fixes CRLF/BOM in app/web/src/**/*.vue by writing
    #    the file back, which refreshes the SOURCE mtime. check-fpk.mjs then gates on
    #    "src.mtime > out.mtime" (frontend bundle staleness). Running normalize AFTER
    #    the build therefore makes fresh sources look newer than a bundle that was
    #    actually built from them -> hard gate failure
    #    ("前端产物陈旧：源码最新改动 ... 晚于产物 ...").
    #    Real failure: v1.0.31 packaging, 13 .vue files fixed -> build aborted at
    #    check-fpk-gate with src 15:26:47.356 vs out 15:26:46.810 (0.5s apart).
    #
    #    The old comment claimed the opposite ("build first, so the fresh output gets
    #    normalized too") -- that was wrong: normalize-encoding.mjs SKIP_DIRS contains
    #    "public", so server/public is never scanned and the bundle was never
    #    normalized at all. The bundle is LF/no-BOM straight out of vite anyway.
    Invoke-Step "normalize-encoding" { & $node "$proj\build\normalize-encoding.mjs" }

    # 1) build the web bundle -- after normalization, so the bundle is never
    #    older than the sources it was built from.
    #    Uses the project-local node/npm under .tools (no global install, no PATH).
    Invoke-Step "build-web" {
        Push-Location "$proj\omnioffice\app\web"
        try { & "$proj\.tools\node\npm.cmd" run build } finally { Pop-Location }
    }

    # 1b) drop stale hashed web bundles (vite emptyOutDir=false leaves them behind)
    Invoke-Step "clean-web-assets" { & $python "$proj\build\clean_web_assets.py" }

    # 1c) server unit tests (portable python; failures block packaging).
    #     MUST run BEFORE slim-package: the test run regenerates __pycache__.
    #     If slim ran first, those freshly written bytecode dirs would still sit
    #     on disk when check-fpk-gate scans the package -> hard failure
    #     ("app/server/app/__pycache__ will be packed"). Test first, slim last.
    Invoke-Step "server-unit-tests" { & $python "$proj\omnioffice\app\server\run_tests.py" }

    # 1d) move node_modules / __pycache__ out of the FPK (after the test run,
    #     so test-generated bytecode is cleaned too).
    #     .dockerignore only applies to `docker build`; fnpack ignores it, so
    #     13k files would otherwise ship inside app.tgz and slow down install.
    Invoke-Step "slim-package" { & $python $slim }
    $slimmed = $true

    # 3) packaging gate (hard gate before fnpack build)
    Invoke-Step "check-fpk-gate" { & $node "$proj\build\check-fpk.mjs" }

    # 4) versioned packaging via scripts/build-fpk.js (portable node + .tools/fnpack):
    #    auto-bumps manifest.version -> fnpack build -> archives to releases/
    #    (never overwrites) -> appends releases/build-log.json -> tag collision
    #    check -> git dual-remote archival reminder (with -Tag: annotated tag too).
    $buildArgs = @("omnioffice")
    if ($SetVersion) { $buildArgs += @("--set-version", $SetVersion) }
    else { $buildArgs += @("--bump", $Bump) }
    if ($Message) { $buildArgs += @("--message", $Message) }
    if ($Tag) { $buildArgs += "--tag" }
    Invoke-Step "fnpack-build" { & $node "$proj\scripts\build-fpk.js" @buildArgs }
} finally {
    # Always restore, so the next frontend build still has its dependency tree.
    Restore-Deps
}

Get-ChildItem "$proj\releases\*.fpk" -ErrorAction SilentlyContinue |
    Sort-Object Name |
    ForEach-Object { Write-Output ("FPK: {0} ({1} MB)" -f $_.FullName, [math]::Round($_.Length / 1MB, 2)) }
