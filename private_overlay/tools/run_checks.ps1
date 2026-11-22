param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$StartupPreflight
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $OverlayRoot

if (-not $StartupPreflight) {
    Write-Host "== XiaoYu overlay unit tests =="
    # unittest discovery imports tests as modules. Anchor cwd to the repository root
    # so package imports stay relocatable and do not depend on the shortcut/caller cwd.
    Push-Location $RepoRoot
    try {
        python -m unittest discover -s (Join-Path $OverlayRoot "tests") -v
        $UnitTestExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($UnitTestExit -ne 0) { exit $UnitTestExit }

    Write-Host "== XiaoYu overlay compile =="
    python -m compileall -q (Join-Path $OverlayRoot "tools") (Join-Path $OverlayRoot "tests") (Join-Path $OverlayRoot "migration") (Join-Path $OverlayRoot "evals")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== XiaoYu ActivityWatch reuse dependency =="
    python (Join-Path $OverlayRoot "tools\check_activitywatch.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== XiaoYu native embedding asset pin =="
    $NekoPython = Join-Path $NekoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $NekoPython)) {
        throw "N.E.K.O venv python not found for embedding asset verification: $NekoPython"
    }
    & $NekoPython (Join-Path $OverlayRoot "tools\ensure_native_embedding_assets.py") --neko-root $NekoRoot --verify-only
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "== XiaoYu reuse-first admission gate =="
python (Join-Path $OverlayRoot "tools\check_reuse_first.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu frozen architecture/delivery contract =="
python (Join-Path $OverlayRoot "tools\check_architecture_freeze.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu plugin autostart admission =="
python (Join-Path $OverlayRoot "tools\check_plugin_admission.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu/N.E.K.O authority contract =="
$env:NEKO_ROOT = $NekoRoot
python (Join-Path $OverlayRoot "tools\check_overlay.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu provider privacy preflight =="
python (Join-Path $OverlayRoot "tools\check_provider_privacy.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $StartupPreflight) {
    Write-Host "== XiaoYu release readiness =="
    python (Join-Path $OverlayRoot "tools\check_release_readiness.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
else {
    Write-Host "PASS: XiaoYu runtime startup safety preflight"
}

exit 0
