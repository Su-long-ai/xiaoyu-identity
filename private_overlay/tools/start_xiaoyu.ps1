param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$ToolsRoot = $PSScriptRoot

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

Write-Host "== Verify pinned external components =="
& (Join-Path $ToolsRoot "setup_local.ps1") -NekoRoot $NekoRoot -VerifyOnly
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Ensure native N.E.K.O storage selection =="
& $Python (Join-Path $ToolsRoot "ensure_neko_storage_policy.py") --neko-root $NekoRoot --storage-root $ResolvedStorage
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu private startup preflight =="
& (Join-Path $ToolsRoot "run_checks.ps1") -NekoRoot $NekoRoot -StorageRoot $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($PreflightOnly) {
    Write-Host "PASS: XiaoYu startup preflight complete"
    exit 0
}

Write-Host "== Arm native N.E.K.O plugin autostart reconciliation =="
$PluginRestore = Join-Path $ToolsRoot "restore_neko_plugin_autostart.py"
$PluginRestoreResult = Join-Path $env:NEKO_RUNTIME_STATE_DIR "xiaoyu_plugin_autostart_restore.json"
if (-not (Test-Path $PluginRestore)) {
    throw "XiaoYu plugin autostart reconciler not found: $PluginRestore"
}
$RestoreArgs = @(
    $PluginRestore,
    "--main-url", "http://127.0.0.1:48911",
    "--plugin-url", "http://127.0.0.1:48916",
    "--lanlan-name", "XiaoYu",
    "--wait-seconds", "90",
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