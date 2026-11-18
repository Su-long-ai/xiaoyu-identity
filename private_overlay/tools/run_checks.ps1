param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$HostSmoke
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$PluginRoot = Join-Path $OverlayRoot "plugins\xiaoyu_private"

Write-Host "== XiaoYu overlay unit tests =="
python -m unittest discover -s (Join-Path $OverlayRoot "tests") -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu overlay compile =="
python -m compileall -q $PluginRoot (Join-Path $OverlayRoot "tools") (Join-Path $OverlayRoot "tests") (Join-Path $OverlayRoot "migration") (Join-Path $OverlayRoot "evals")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu/N.E.K.O authority contract =="
$env:NEKO_ROOT = $NekoRoot
python (Join-Path $OverlayRoot "tools\check_overlay.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu provider privacy preflight =="
python (Join-Path $OverlayRoot "tools\check_provider_privacy.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== N.E.K.O official plugin check =="
uv run --project $NekoRoot neko-plugin check $PluginRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($HostSmoke) {
    Write-Host "== N.E.K.O live host smoke =="
    $NekoPython = Join-Path $NekoRoot ".venv\Scripts\python.exe"
    & $NekoPython (Join-Path $OverlayRoot "tools\host_smoke.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

exit 0
