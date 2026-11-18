param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O"
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$env:NEKO_ROOT = $NekoRoot
$NekoPython = Join-Path $NekoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $NekoPython)) {
    throw "N.E.K.O virtual environment is missing: $NekoPython"
}

Write-Host "== Register XiaoYu private project in N.E.K.O Workbench =="
& $NekoPython (Join-Path $PSScriptRoot "register_workbench.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Validate live N.E.K.O plugin host path =="
& $NekoPython (Join-Path $PSScriptRoot "host_smoke.py")
exit $LASTEXITCODE
