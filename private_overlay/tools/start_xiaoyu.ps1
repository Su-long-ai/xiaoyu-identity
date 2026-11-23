param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$ToolsRoot = $PSScriptRoot
$OverlayRoot = (Resolve-Path (Join-Path $ToolsRoot "..")).Path
$PrivatePluginSource = Join-Path $OverlayRoot "plugins\xiaoyu_interaction_policy"

if (-not (Test-Path $StorageRoot)) {
    throw "XiaoYu storage root not found: $StorageRoot"
}

$Python = Join-Path $NekoRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $NekoRoot "launcher.py"
if (-not (Test-Path $Python)) { throw "N.E.K.O venv python not found: $Python" }
if (-not (Test-Path $Launcher)) { throw "N.E.K.O launcher not found: $Launcher" }

$ResolvedStorage = (Resolve-Path $StorageRoot).Path
$env:NEKO_STORAGE_SELECTED_ROOT = $ResolvedStorage
$env:NEKO_STORAGE_ANCHOR_ROOT = $ResolvedStorage
$env:NEKO_RUNTIME_STATE_DIR = Join-Path $ResolvedStorage ".runtime"
# XiaoYu's private overlay uses this local storage root as the authority. Reuse
# N.E.K.O's native session fence so Steam Auto-Cloud cannot import/export this
# private state while still leaving Steamworks available to other native features.
$env:NEKO_CLOUDSAVE_DISABLED = "xiaoyu_private_local_authority"
# One product startup budget drives both the native launcher readiness window
# and the detached native-plugin reconcile waiter. N.E.K.O keeps its own
# default at 60s when this overlay is not active.
$StartupReadyBudgetSeconds = 180
$env:NEKO_SERVER_READY_TIMEOUT_SECONDS = [string]$StartupReadyBudgetSeconds

# Private product routing: N.E.K.O core only exposes the generic first-round
# forced-tool bridge. XiaoYu owns the tool name and conservative retrospective
# activity pattern here, so no product-specific wording lives in N.E.K.O.
$env:NEKO_PRIVATE_FORCED_TOOL_NAME = "xiaoyu_recent_activity"
$env:NEKO_PRIVATE_FORCED_TOOL_REASONING_EFFORT = "none"
$env:NEKO_PRIVATE_FORCED_TOOL_PATTERN = '(?i)(?:(?:\u521a\u624d|\u521a\u521a|\u6700\u8fd1|\u8fd9\u6bb5\u65f6\u95f4|\u8fc7\u53bb\s*\d+\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u524d\s*\d+\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u8fd9\s*\d*\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u4e0a\u4e2a\u5c0f\u65f6|\u4e0a\u4e00\u5c0f\u65f6|\d+\s*\u4e2a?\s*\u5c0f\u65f6\u524d|\u4e00\u4e2a\u5c0f\u65f6\u524d).{0,48}(?:\u5728\u5e72\u561b|\u5e72\u561b|\u5e72\u4ec0\u4e48|\u5e72\u4e86\u4ec0\u4e48|\u5e72\u4e86\u5565|\u5e72\u4e86\u4e9b\u4ec0\u4e48|\u505a\u4ec0\u4e48|\u505a\u4e86\u4ec0\u4e48|\u505a\u4e86\u5565|\u505a\u4e86\u4e9b\u4ec0\u4e48|\u5728\u505a\u4ec0\u4e48|\u6ca1\u5e72\u4e8b|\u6ca1\u505a\u4e8b|\u5fd9\u4ec0\u4e48|\u7535\u8111|\u5199\u4ee3\u7801|\u7f16\u7a0b|\u6253\u6e38\u620f|\u73a9\u6e38\u620f|\u7528\u4e86\u4ec0\u4e48(?:\u8f6f\u4ef6|\u5e94\u7528)?|\u7528\u4ec0\u4e48(?:\u8f6f\u4ef6|\u5e94\u7528)?)|(?:\u7535\u8111|\u5199\u4ee3\u7801|\u7f16\u7a0b|\u6253\u6e38\u620f|\u73a9\u6e38\u620f|\u7528\u4ec0\u4e48(?:\u8f6f\u4ef6|\u5e94\u7528)?).{0,48}(?:\u521a\u624d|\u521a\u521a|\u6700\u8fd1|\u8fd9\u6bb5\u65f6\u95f4|\u8fc7\u53bb\s*\d+\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u524d\s*\d+\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u8fd9\s*\d*\s*\u4e2a?\s*(?:\u5206\u949f|\u5c0f\u65f6)|\u4e0a\u4e2a\u5c0f\u65f6|\u4e0a\u4e00\u5c0f\u65f6|\d+\s*\u4e2a?\s*\u5c0f\u65f6\u524d|\u4e00\u4e2a\u5c0f\u65f6\u524d))'
$env:NEKO_PRIVATE_SPEECH_GATE_FILE = Join-Path $ResolvedStorage "plugins\xiaoyu_interaction_policy\data\state.json"

Write-Host "== Ensure ActivityWatch external activity authority =="
$ActivityWatchExe = Join-Path $env:LOCALAPPDATA "Programs\ActivityWatch\aw-qt.exe"
$ActivityWatchCheck = Join-Path $ToolsRoot "check_activitywatch.py"
& $Python $ActivityWatchCheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $PreflightOnly) {
    $ActivityWatchReady = $false
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:5600/api/0/info" -TimeoutSec 1
        $ActivityWatchReady = $true
    } catch {}
    if (-not $ActivityWatchReady) {
        Start-Process -FilePath $ActivityWatchExe | Out-Null
        for ($i = 0; $i -lt 20 -and -not $ActivityWatchReady; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $null = Invoke-RestMethod -Uri "http://127.0.0.1:5600/api/0/info" -TimeoutSec 1
                $ActivityWatchReady = $true
            } catch {}
        }
        if (-not $ActivityWatchReady) {
            throw "ActivityWatch local API did not become ready"
        }
    }
}

Write-Host "== Ensure N.E.K.O native embedding assets =="
$EmbeddingAssetsEnsure = Join-Path $ToolsRoot "ensure_native_embedding_assets.py"
if (-not (Test-Path $EmbeddingAssetsEnsure)) {
    throw "Native embedding asset ensure helper not found: $EmbeddingAssetsEnsure"
}
$EmbeddingArgs = @(
    $EmbeddingAssetsEnsure,
    "--neko-root", $NekoRoot
)
if ($PreflightOnly) {
    $EmbeddingArgs += "--verify-only"
}
& $Python @EmbeddingArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Verify pinned external components =="
$SetupLocal = Join-Path $ToolsRoot "setup_local.ps1"
$NativeSteamworks = Join-Path $NekoRoot "steamworks\__init__.py"
if (-not $PreflightOnly -and -not (Test-Path $NativeSteamworks)) {
    Write-Host "== Repair pinned sparse checkout for native runtime assets =="
    & $SetupLocal -NekoRoot $NekoRoot
} else {
    & $SetupLocal -NekoRoot $NekoRoot -VerifyOnly
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Ensure native N.E.K.O storage selection =="
& $Python (Join-Path $ToolsRoot "ensure_neko_storage_policy.py") --neko-root $NekoRoot --storage-root $ResolvedStorage
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Ensure XiaoYu private activity preferences =="
$ActivityPrefsEnsure = Join-Path $ToolsRoot "ensure_xiaoyu_activity_preferences.py"
if (-not (Test-Path $ActivityPrefsEnsure)) {
    throw "XiaoYu activity preference ensure helper not found: $ActivityPrefsEnsure"
}
$ActivityPrefsArgs = @(
    $ActivityPrefsEnsure,
    "--storage-root", $ResolvedStorage
)
if ($PreflightOnly) {
    $ActivityPrefsArgs += "--verify-only"
}
& $Python @ActivityPrefsArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Ensure XiaoYu private plugin through N.E.K.O package workflow =="
$PrivatePluginEnsure = Join-Path $ToolsRoot "ensure_private_plugin.py"
if (-not (Test-Path $PrivatePluginEnsure)) {
    throw "XiaoYu private plugin ensure helper not found: $PrivatePluginEnsure"
}
$PrivatePluginArgs = @(
    $PrivatePluginEnsure,
    "--neko-root", $NekoRoot,
    "--storage-root", $ResolvedStorage,
    "--source", $PrivatePluginSource
)
if ($PreflightOnly) {
    $PrivatePluginArgs += "--verify-only"
}
& $Python @PrivatePluginArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu private startup preflight =="
& (Join-Path $ToolsRoot "run_checks.ps1") -NekoRoot $NekoRoot -StorageRoot $ResolvedStorage -StartupPreflight
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($PreflightOnly) {
    Write-Host "PASS: XiaoYu startup preflight complete"
    exit 0
}

Write-Host "== Arm N.E.K.O native plugin runtime reconciliation =="
$PluginRestore = Join-Path $ToolsRoot "reconcile_neko_plugin_runtime.py"
$PluginRestoreResult = Join-Path $env:NEKO_RUNTIME_STATE_DIR "xiaoyu_plugin_runtime_reconcile.json"
$RuntimeRecordPath = Join-Path $env:NEKO_RUNTIME_STATE_DIR "launcher.json"
if (-not (Test-Path $PluginRestore)) {
    throw "XiaoYu native plugin runtime reconcile helper not found: $PluginRestore"
}
$RestoreArgs = @(
    $PluginRestore,
    "--plugin-url", "http://127.0.0.1:48916",
    "--agent-url", "http://127.0.0.1:48915",
    "--runtime-record", $RuntimeRecordPath,
    "--lanlan-name", "XiaoYu",
    "--wait-seconds", [string]$StartupReadyBudgetSeconds,
    "--result-path", $PluginRestoreResult
)
Start-Process -FilePath $Python -ArgumentList $RestoreArgs -WindowStyle Hidden | Out-Null

Write-Host "== Start original N.E.K.O with XiaoYu private state =="
Push-Location $NekoRoot
try {
    & $Python $Launcher
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}