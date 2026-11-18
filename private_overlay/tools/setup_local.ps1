param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$QQLockPath = Join-Path $OverlayRoot "QQ_PLUGIN_UPSTREAM.lock.json"

if (Test-Path $QQLockPath) {
    $QQLock = Get-Content $QQLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $QQRoot = Join-Path $NekoRoot "plugin\plugins\qq_auto_reply"

    if (-not (Test-Path (Join-Path $QQRoot ".git"))) {
        if ($VerifyOnly) {
            throw "Pinned QQ plugin is missing; run setup_local.ps1 once: $QQRoot"
        }
        if (Test-Path $QQRoot) {
            throw "QQ plugin path exists but is not a git checkout: $QQRoot"
        }
        Write-Host "== Clone pinned external QQ plugin =="
        git clone --filter=blob:none --depth 1 $QQLock.repository $QQRoot
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $Dirty = git -C $QQRoot status --porcelain
    if ($Dirty) {
        throw "Pinned QQ plugin checkout is dirty; refusing to use it: $QQRoot"
    }

    if (-not $VerifyOnly) {
        Write-Host "== Sync pinned external QQ plugin =="
        git -C $QQRoot fetch origin $QQLock.tested_commit --depth 1
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        git -C $QQRoot checkout --detach $QQLock.tested_commit
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $QQHead = (git -C $QQRoot rev-parse HEAD).Trim()
    if ($QQHead -ne $QQLock.tested_commit) {
        throw "QQ plugin pin mismatch: expected $($QQLock.tested_commit), got $QQHead"
    }
}

if ($VerifyOnly) {
    Write-Host "PASS: pinned external dependencies match locally"
} else {
    Write-Host "PASS: external dependencies are pinned; no private XiaoYu runtime plugin is required"
}
exit 0