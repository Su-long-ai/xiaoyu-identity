param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O"
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$PluginRoot = Join-Path $OverlayRoot "plugins\xiaoyu_private"

Write-Host "== XiaoYu overlay unit tests =="
python -m unittest discover -s (Join-Path $OverlayRoot "tests") -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu overlay compile =="
python -m compileall -q $PluginRoot (Join-Path $OverlayRoot "tools") (Join-Path $OverlayRoot "tests")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu/N.E.K.O authority contract =="
$env:NEKO_ROOT = $NekoRoot
python (Join-Path $OverlayRoot "tools\check_overlay.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== N.E.K.O official plugin check =="
uv run --project $NekoRoot neko-plugin check $PluginRoot
exit $LASTEXITCODE
