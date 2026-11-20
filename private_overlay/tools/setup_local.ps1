param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$NekoLockPath = Join-Path $OverlayRoot "NEKO_UPSTREAM.lock.json"
$PatchSeriesPath = Join-Path $OverlayRoot "patches\\series.json"
$QQLockPath = Join-Path $OverlayRoot "QQ_PLUGIN_UPSTREAM.lock.json"

function Assert-LastExitCode([string]$What) {
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

function Test-NekoPatchApplied([string]$PatchPath) {
    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        git -C $NekoRoot apply --reverse --check -- $PatchPath 2>$null | Out-Null
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
    return ($ExitCode -eq 0)
}

function Ensure-NekoCorePatches {
    $NekoLock = Get-Content $NekoLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $PatchSeries = Get-Content $PatchSeriesPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $NekoHead = (git -C $NekoRoot rev-parse HEAD).Trim()
    if ($NekoHead -ne $NekoLock.tested_commit) {
        throw "N.E.K.O pin mismatch: expected $($NekoLock.tested_commit), got $NekoHead"
    }

    $Patches = @($PatchSeries.patches)
    if ($Patches.Count -gt [int]$NekoLock.core_patch_budget) {
        throw "N.E.K.O core patch queue exceeds declared budget"
    }

    foreach ($Patch in $Patches) {
        $PatchPath = Join-Path $OverlayRoot ("patches\\" + [string]$Patch.file)
        if (-not (Test-Path $PatchPath)) {
            throw "Managed N.E.K.O patch is missing: $PatchPath"
        }

        $AlreadyApplied = Test-NekoPatchApplied $PatchPath
        if ($AlreadyApplied) {
            Write-Host ("PASS: managed N.E.K.O patch already applied: " + $Patch.file)
            continue
        }

        if ($VerifyOnly) {
            throw "Managed N.E.K.O patch is not applied; run setup_local.ps1 once: $($Patch.file)"
        }

        Write-Host ("== Apply managed N.E.K.O patch: " + $Patch.file + " ==")
        git -C $NekoRoot apply --check -- $PatchPath
        Assert-LastExitCode ("git apply --check " + $Patch.file)
        git -C $NekoRoot apply -- $PatchPath
        Assert-LastExitCode ("git apply " + $Patch.file)

        if (-not (Test-NekoPatchApplied $PatchPath)) {
            throw "Managed N.E.K.O patch did not verify after apply: $($Patch.file)"
        }
    }

    Write-Host ("PASS: managed N.E.K.O core patches ready (" + $Patches.Count + ")")
}

function Ensure-NekoUiAssets {
    $TemplateIndex = Join-Path $NekoRoot "templates\index.html"
    $PluginManagerPackage = Join-Path $NekoRoot "frontend\plugin-manager\package.json"
    $ChatPackage = Join-Path $NekoRoot "frontend\react-neko-chat\package.json"
    $PluginManagerDist = Join-Path $NekoRoot "frontend\plugin-manager\dist\index.html"
    $ChatBundle = Join-Path $NekoRoot "static\react\neko-chat\neko-chat-window.iife.js"

    $SourceAssets = @($TemplateIndex, $PluginManagerPackage, $ChatPackage)
    $MissingSource = @($SourceAssets | Where-Object { -not (Test-Path $_) })

    if ($MissingSource.Count -gt 0) {
        if ($VerifyOnly) {
            throw "N.E.K.O UI source is incomplete; run setup_local.ps1 once to expand the pinned checkout. Missing: $($MissingSource -join ', ')"
        }

        $SparseCheckout = (git -C $NekoRoot config --bool core.sparseCheckout 2>$null)
        if (-not $SparseCheckout -or $SparseCheckout.Trim() -ne "true") {
            throw "N.E.K.O UI source is missing from a non-sparse checkout: $($MissingSource -join ', ')"
        }

        Write-Host "== Expand pinned N.E.K.O checkout for native UI =="
        git -C $NekoRoot sparse-checkout add frontend templates
        Assert-LastExitCode "git sparse-checkout add frontend templates"

        $MissingSource = @($SourceAssets | Where-Object { -not (Test-Path $_) })
        if ($MissingSource.Count -gt 0) {
            throw "N.E.K.O UI source is still incomplete after sparse expansion: $($MissingSource -join ', ')"
        }
    }

    $BuildAssets = @($PluginManagerDist, $ChatBundle)
    $MissingBuild = @($BuildAssets | Where-Object { -not (Test-Path $_) })
    if ($MissingBuild.Count -gt 0) {
        if ($VerifyOnly) {
            throw "N.E.K.O UI build artifacts are missing; run setup_local.ps1 once. Missing: $($MissingBuild -join ', ')"
        }

        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            throw "npm is required to build the pinned N.E.K.O UI"
        }

        if (-not (Test-Path $PluginManagerDist)) {
            Write-Host "== Build native N.E.K.O plugin manager UI =="
            $PluginManagerRoot = Join-Path $NekoRoot "frontend\plugin-manager"
            Push-Location $PluginManagerRoot
            try {
                if (-not (Test-Path (Join-Path $PluginManagerRoot "node_modules\.bin\vite.cmd"))) {
                    npm ci
                    Assert-LastExitCode "npm ci (plugin-manager)"
                }
                npm run build-only
                Assert-LastExitCode "npm run build-only (plugin-manager)"
            }
            finally {
                Pop-Location
            }
        }

        if (-not (Test-Path $ChatBundle)) {
            Write-Host "== Build native N.E.K.O chat UI =="
            $ChatRoot = Join-Path $NekoRoot "frontend\react-neko-chat"
            Push-Location $ChatRoot
            try {
                if (-not (Test-Path (Join-Path $ChatRoot "node_modules"))) {
                    npm ci
                    Assert-LastExitCode "npm ci (react-neko-chat)"
                }
                npm run build
                Assert-LastExitCode "npm run build (react-neko-chat)"
            }
            finally {
                Pop-Location
            }
        }

        $MissingBuild = @($BuildAssets | Where-Object { -not (Test-Path $_) })
        if ($MissingBuild.Count -gt 0) {
            throw "N.E.K.O UI build did not produce required artifacts: $($MissingBuild -join ', ')"
        }
    }

    Write-Host "PASS: native N.E.K.O UI source and build artifacts are ready"
}

Ensure-NekoCorePatches

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
        Assert-LastExitCode "git clone QQ plugin"
    }

    $Dirty = git -C $QQRoot status --porcelain
    if ($Dirty) {
        throw "Pinned QQ plugin checkout is dirty; refusing to use it: $QQRoot"
    }

    if (-not $VerifyOnly) {
        Write-Host "== Sync pinned external QQ plugin =="
        git -C $QQRoot fetch origin $QQLock.tested_commit --depth 1
        Assert-LastExitCode "git fetch QQ plugin"
        git -C $QQRoot checkout --detach $QQLock.tested_commit
        Assert-LastExitCode "git checkout QQ plugin pin"
    }

    $QQHead = (git -C $QQRoot rev-parse HEAD).Trim()
    if ($QQHead -ne $QQLock.tested_commit) {
        throw "QQ plugin pin mismatch: expected $($QQLock.tested_commit), got $QQHead"
    }
}

Ensure-NekoUiAssets

if ($VerifyOnly) {
    Write-Host "PASS: pinned external dependencies and native UI assets match locally"
} else {
    Write-Host "PASS: external dependencies are pinned and native UI is ready; XiaoYu private plugin code is installed/verified separately by start_xiaoyu.ps1 through N.E.K.O package workflow"
}
exit 0
