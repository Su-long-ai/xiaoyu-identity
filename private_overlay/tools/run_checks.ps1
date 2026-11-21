param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox"
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot

Write-Host "== XiaoYu overlay unit tests =="
python -m unittest discover -s (Join-Path $OverlayRoot "tests") -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

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

Write-Host "== XiaoYu reuse-first admission gate =="
python (Join-Path $OverlayRoot "tools\check_reuse_first.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu/N.E.K.O authority contract =="
$env:NEKO_ROOT = $NekoRoot
python (Join-Path $OverlayRoot "tools\check_overlay.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu provider privacy preflight =="
python (Join-Path $OverlayRoot "tools\check_provider_privacy.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu release readiness =="
python (Join-Path $OverlayRoot "tools\check_release_readiness.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

exit 0
