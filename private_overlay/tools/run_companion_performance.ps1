param(
    [ValidateSet("live", "cold_start")]
    [string]$Profile = "live",
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [string]$DesktopExe = "D:\xiaoyu_external_audit\neko-nightly-desktop\shell\N.E.K.O.exe",
    [string]$NativeBenchmark = "",
    [double]$DurationSeconds = 60,
    [string]$ResultPath = ""
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $OverlayRoot
$Python = Join-Path $NekoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "N.E.K.O venv python not found: $Python"
}
if (-not (Test-Path -LiteralPath $StorageRoot)) {
    throw "XiaoYu storage root not found: $StorageRoot"
}

$ResolvedStorage = (Resolve-Path $StorageRoot).Path
if (-not $ResultPath) {
    $ResultPath = Join-Path $ResolvedStorage (".runtime\xiaoyu_companion_performance_{0}.json" -f $Profile)
}

$Args = @(
    "-m", "private_overlay.tools.run_companion_performance_gate",
    "--profile", $Profile,
    "--storage-root", $ResolvedStorage,
    "--neko-root", $NekoRoot,
    "--desktop-exe", $DesktopExe,
    "--duration-seconds", [string]$DurationSeconds,
    "--result-path", $ResultPath
)
if ($NativeBenchmark) {
    $Args += @("--native-benchmark", $NativeBenchmark)
}

Push-Location $RepoRoot
try {
    & $Python @Args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
