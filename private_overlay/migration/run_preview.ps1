param(
    [string]$LegacyDb = "D:\dsh-fish\identity\identity.sqlite3",
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StateRoot = "D:\xiaoyu_private_overlay_state"
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $StateRoot "migration\current"
$Sandbox = Join-Path $StateRoot "neko-sandbox"
$NekoPython = Join-Path $NekoRoot ".venv\Scripts\python.exe"

Write-Host "== Export legacy XiaoYu state read-only =="
python (Join-Path $PSScriptRoot "export_legacy_xiaoyu.py") --db $LegacyDb --out $Stage
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Run N.E.K.O native external-import preview (zero writes to production state) =="
& $NekoPython (Join-Path $PSScriptRoot "preview_neko_import.py") --neko-root $NekoRoot --stage $Stage --isolated-root $Sandbox
exit $LASTEXITCODE
