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

function Get-ManagedPatchPaths([object[]]$Patches) {
    $Paths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($Patch in $Patches) {
        $PatchPath = Join-Path $OverlayRoot ("patches\" + [string]$Patch.file)
        foreach ($Line in [System.IO.File]::ReadLines($PatchPath)) {
            if ($Line -match '^(?:--- a/|\+\+\+ b/)(.+)$') {
                $RelativePath = $Matches[1].Trim()
                if ($RelativePath -and $RelativePath -ne "/dev/null") {
                    [void]$Paths.Add($RelativePath)
                }
            }
        }
    }
    return @($Paths | Sort-Object)
}

function Get-NekoManagedPatchPrefixLength([object[]]$Patches, [string]$TestedCommit) {
    $ManagedPaths = @(Get-ManagedPatchPaths $Patches)
    $ActualIndex = Join-Path ([System.IO.Path]::GetTempPath()) (
        "xiaoyu-patch-actual-" + [guid]::NewGuid().ToString("N") + ".idx"
    )
    $ExpectedIndex = Join-Path ([System.IO.Path]::GetTempPath()) (
        "xiaoyu-patch-expected-" + [guid]::NewGuid().ToString("N") + ".idx"
    )
    $PreviousIndex = $env:GIT_INDEX_FILE
    try {
        $env:GIT_INDEX_FILE = $ActualIndex
        git -C $NekoRoot read-tree $TestedCommit
        Assert-LastExitCode "git read-tree actual managed patch baseline"
        if ($ManagedPaths.Count -gt 0) {
            $BaselineManagedPaths = [System.Collections.Generic.HashSet[string]]::new(
                [System.StringComparer]::Ordinal
            )
            $BaselineTracked = @(git -C $NekoRoot ls-tree -r --name-only $TestedCommit -- $ManagedPaths)
            Assert-LastExitCode "git ls-tree managed patch baseline paths"
            foreach ($RelativePath in $BaselineTracked) {
                if ($RelativePath) {
                    [void]$BaselineManagedPaths.Add([string]$RelativePath)
                }
            }

            $ActualManagedPaths = [System.Collections.Generic.List[string]]::new()
            foreach ($RelativePath in $ManagedPaths) {
                $WorktreePath = Join-Path $NekoRoot $RelativePath
                if ((Test-Path -LiteralPath $WorktreePath) -or $BaselineManagedPaths.Contains($RelativePath)) {
                    # Existing paths capture modifications/additions. Paths that
                    # existed at the pin but are now absent capture deletions.
                    # Future patch-only paths absent from both are intentionally
                    # omitted until their introducing patch is present.
                    $ActualManagedPaths.Add($RelativePath)
                }
            }
            if ($ActualManagedPaths.Count -gt 0) {
                git -C $NekoRoot add -A --sparse -- @($ActualManagedPaths)
                Assert-LastExitCode "git add actual managed patch paths"
            }
        }
        $ActualTree = (git -C $NekoRoot write-tree).Trim()
        Assert-LastExitCode "git write-tree actual managed patch state"

        $env:GIT_INDEX_FILE = $ExpectedIndex
        git -C $NekoRoot read-tree $TestedCommit
        Assert-LastExitCode "git read-tree expected managed patch baseline"
        $ExpectedTree = (git -C $NekoRoot write-tree).Trim()
        Assert-LastExitCode "git write-tree expected prefix 0"
        $MatchedPrefix = if ($ExpectedTree -eq $ActualTree) { 0 } else { -1 }

        for ($Index = 0; $Index -lt $Patches.Count; $Index++) {
            $Patch = $Patches[$Index]
            $PatchPath = Join-Path $OverlayRoot ("patches\" + [string]$Patch.file)
            git -C $NekoRoot apply --cached --check -- $PatchPath
            Assert-LastExitCode ("git apply --cached --check " + $Patch.file)
            git -C $NekoRoot apply --cached -- $PatchPath
            Assert-LastExitCode ("git apply --cached " + $Patch.file)
            $ExpectedTree = (git -C $NekoRoot write-tree).Trim()
            Assert-LastExitCode ("git write-tree expected prefix " + ($Index + 1))
            if ($ExpectedTree -eq $ActualTree) {
                $MatchedPrefix = $Index + 1
            }
        }
        return $MatchedPrefix
    }
    finally {
        if ($null -eq $PreviousIndex) {
            Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        }
        else {
            $env:GIT_INDEX_FILE = $PreviousIndex
        }
        Remove-Item -LiteralPath $ActualIndex -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($ActualIndex + ".lock") -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ExpectedIndex -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($ExpectedIndex + ".lock") -Force -ErrorAction SilentlyContinue
    }
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
        $PatchPath = Join-Path $OverlayRoot ("patches\" + [string]$Patch.file)
        if (-not (Test-Path $PatchPath)) {
            throw "Managed N.E.K.O patch is missing: $PatchPath"
        }
    }

    $InstalledPrefix = Get-NekoManagedPatchPrefixLength $Patches $NekoLock.tested_commit
    if ($InstalledPrefix -eq $Patches.Count) {
        Write-Host (
            "PASS: exact managed N.E.K.O patch chain already applied (" +
            $Patches.Count + "/" + $Patches.Count + ")"
        )
        return
    }
    if ($InstalledPrefix -lt 0) {
        throw (
            "N.E.K.O managed paths do not match any legal prefix of the ordered patch series; " +
            "refusing to guess through partial, reordered, or manual changes"
        )
    }
    if ($VerifyOnly) {
        throw (
            "Managed N.E.K.O patch chain is only at prefix " +
            $InstalledPrefix + "/" + $Patches.Count +
            "; run setup_local.ps1 once"
        )
    }

    for ($Index = $InstalledPrefix; $Index -lt $Patches.Count; $Index++) {
        $Patch = $Patches[$Index]
        $PatchPath = Join-Path $OverlayRoot ("patches\" + [string]$Patch.file)
        Write-Host (
            "== Apply managed N.E.K.O patch [" + ($Index + 1) + "/" +
            $Patches.Count + "]: " + $Patch.file + " =="
        )
        git -C $NekoRoot apply --check -- $PatchPath
        Assert-LastExitCode ("git apply --check " + $Patch.file)
        git -C $NekoRoot apply -- $PatchPath
        Assert-LastExitCode ("git apply " + $Patch.file)
    }

    $FinalPrefix = Get-NekoManagedPatchPrefixLength $Patches $NekoLock.tested_commit
    if ($FinalPrefix -ne $Patches.Count) {
        throw (
            "Managed N.E.K.O patch chain failed exact post-apply verification: " +
            $FinalPrefix + "/" + $Patches.Count
        )
    }
    Write-Host ("PASS: managed N.E.K.O core patches ready (" + $Patches.Count + ")")
}

function Ensure-NekoUiAssets {
    $TemplateIndex = Join-Path $NekoRoot "templates\index.html"
    $PluginManagerPackage = Join-Path $NekoRoot "frontend\plugin-manager\package.json"
    $ChatPackage = Join-Path $NekoRoot "frontend\react-neko-chat\package.json"
    $SteamworksPackage = Join-Path $NekoRoot "steamworks\__init__.py"
    $PluginManagerDist = Join-Path $NekoRoot "frontend\plugin-manager\dist\index.html"
    $ChatBundle = Join-Path $NekoRoot "static\react\neko-chat\neko-chat-window.iife.js"

    $SourceAssets = @($TemplateIndex, $PluginManagerPackage, $ChatPackage, $SteamworksPackage)
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
        git -C $NekoRoot sparse-checkout add frontend templates steamworks
        Assert-LastExitCode "git sparse-checkout add frontend templates steamworks"

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

    Write-Host "PASS: native N.E.K.O UI/runtime source and build artifacts are ready"
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
