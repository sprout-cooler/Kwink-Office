# Release helper: commit current tree, tag by manifest version, push all remotes.
# Usage: powershell -ExecutionPolicy Bypass -File tools\release.ps1 [-Message "..."]
# NOTE: ASCII-only file. Tokens are NOT stored here -- they live in the remote
# URLs (.git/config), so this script is safe to commit and share.
# Prereq: remotes "gitee", "gitcode" and "github" already added (see git remote -v).

$ErrorActionPreference = 'Stop'
$proj = "e:\Project\FN\All-in-OneOffice"

# 1) version from manifest
$verLine = Select-String -Path "$proj\omnioffice\manifest" -Pattern '^version=(.+)$' | Select-Object -First 1
if (-not $verLine) { Write-Error "manifest version not found"; exit 1 }
$ver = $verLine.Matches.Groups[1].Value.Trim()
$tag = "v$ver"

# 2) commit if dirty
$status = git -C $proj status --porcelain
if ($status) {
    git -C $proj add -A
    $msg = if ($Message) { $Message } else { "release: $tag" }
    git -C $proj commit -m $msg | Out-Host
} else {
    Write-Host "==> working tree clean, nothing to commit"
}

# 3) tag (skip if exists)
$existing = git -C $proj tag --list $tag
if (-not $existing) {
    git -C $proj tag $tag
    Write-Host "==> tagged $tag"
} else {
    Write-Host "==> tag $tag already exists, skipping"
}

# 4) push all remotes with tags.
#    gitee + gitcode are the long-standing mirrors; github was added in
#    v1.0.28 (git@github.com:sprout-cooler/kwinkoffice.git, SSH key
#    id_ed25519_fn_repos per ~/.ssh/config).
$remotes = @("gitee", "gitcode", "github")
foreach ($r in $remotes) {
    if (-not (git -C $proj remote | Where-Object { $_ -eq $r })) {
        Write-Host "==> remote '$r' not configured, skipping"
        continue
    }
    Write-Host "==> push $r"
    git -C $proj push $r main --tags
}
Write-Host "==> done ($tag)"
