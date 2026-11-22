param(
    [string]$MainUrl = "http://127.0.0.1:48911/",
    [string]$MemoryHealthUrl = "http://127.0.0.1:48912/health",
    [string]$AgentHealthUrl = "http://127.0.0.1:48915/health",
    [string]$PluginHealthUrl = "http://127.0.0.1:48916/health",
    [string]$Python = "python",
    [string]$DesktopExe = "D:\\xiaoyu_external_audit\\neko-nightly-desktop\\shell\\N.E.K.O.exe",
    [string]$StorageRoot = "D:\\xiaoyu_private_overlay_state\\neko-sandbox",
    [string]$ResultPath = "",
    [switch]$NoLaunch,
    [switch]$RequireQQ
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$OneClick = Join-Path $PSScriptRoot "start_xiaoyu_oneclick.ps1"
$HealthProbe = Join-Path $PSScriptRoot "probe_neko_runtime_health.py"
$ReleaseGate = Join-Path $PSScriptRoot "check_release_readiness.py"
$StableManifest = Join-Path $OverlayRoot "release\NEKO_OVERLAY_V1_FINAL.json"

if (-not $ResultPath) {
    $ResultPath = Join-Path $StorageRoot "release-acceptance\physical-latest.json"
}

function Test-TcpEndpoint([string]$HostName, [int]$Port, [int]$TimeoutMs = 300) {
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($client) { $client.Dispose() }
    }
}

function Get-ExactDesktopProcess([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    return Get-Process -Name "N.E.K.O" -ErrorAction SilentlyContinue |
        Where-Object {
            try { $_.Path -eq $resolved } catch { $false }
        } |
        Select-Object -First 1
}

function Get-QQObservation {
    $configPath = Join-Path $StorageRoot "plugins\qq_auto_reply\data\business_config.json"
    $result = [ordered]@{
        configured = $false
        mode = $null
        config_path = $configPath
        endpoint = $null
        endpoint_reachable = $false
        napcat_process_running = [bool](Get-Process -Name "NapCatQQ-Desktop" -ErrorAction SilentlyContinue | Select-Object -First 1)
        note = $null
    }
    if (-not (Test-Path -LiteralPath $configPath)) {
        $result.note = "QQ business config is absent."
        return [pscustomobject]$result
    }

    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        $result.note = "QQ business config could not be parsed."
        return [pscustomobject]$result
    }

    $result.mode = [string]$config.qq_connection_mode
    if ($result.mode -ne "napcat_forward") {
        $result.note = "QQ is not configured for local NapCat forward mode."
        return [pscustomobject]$result
    }

    $rawUrl = [string]$config.onebot_url
    if (-not $rawUrl) {
        $result.note = "NapCat forward mode has no onebot_url."
        return [pscustomobject]$result
    }

    try { $uri = [Uri]$rawUrl }
    catch {
        $result.note = "onebot_url is invalid."
        return [pscustomobject]$result
    }

    $result.configured = $true
    $result.endpoint = $rawUrl
    if ($uri.Host -notin @("127.0.0.1", "localhost", "::1")) {
        $result.note = "Remote OneBot endpoint is external process authority; reachability is not probed by this local snapshot."
        return [pscustomobject]$result
    }

    $port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq "wss") { 443 } else { 80 }
    $result.endpoint_reachable = Test-TcpEndpoint -HostName $uri.Host -Port $port
    $result.note = if ($result.endpoint_reachable) { "Local OneBot endpoint is reachable." } else { "Local OneBot endpoint is not reachable." }
    return [pscustomobject]$result
}

$startedAt = [DateTimeOffset]::Now
$launch = [ordered]@{
    attempted = (-not $NoLaunch)
    exit_code = $null
    passed = $null
}

if (-not $NoLaunch) {
    $args = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $OneClick,
        "-MainUrl", $MainUrl,
        "-MemoryHealthUrl", $MemoryHealthUrl,
        "-AgentHealthUrl", $AgentHealthUrl,
        "-Python", $Python,
        "-DesktopExe", $DesktopExe,
        "-StorageRoot", $StorageRoot,
        "-SuppressNapCatNotice"
    )
    & powershell.exe @args
    $launch.exit_code = $LASTEXITCODE
    $launch.passed = ($LASTEXITCODE -eq 0)
}
else {
    $launch.passed = $true
}

$healthPath = Join-Path ([System.IO.Path]::GetTempPath()) ("xiaoyu-physical-health-{0}.json" -f [guid]::NewGuid().ToString("N"))
$healthArgs = @(
    $HealthProbe,
    "--main-health-url", ($MainUrl.TrimEnd("/") + "/health"),
    "--memory-health-url", $MemoryHealthUrl,
    "--agent-health-url", $AgentHealthUrl,
    "--plugin-health-url", $PluginHealthUrl,
    "--result-path", $healthPath
)
if ($NoLaunch) { $healthArgs += "--safety-only" }
& $Python @healthArgs
$healthExit = $LASTEXITCODE
$healthPayload = $null
if (Test-Path -LiteralPath $healthPath) {
    try {
        $healthPayload = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    finally {
        Remove-Item -LiteralPath $healthPath -Force -ErrorAction SilentlyContinue
    }
}

& $Python $ReleaseGate
$releaseExit = $LASTEXITCODE

$manifest = $null
if (Test-Path -LiteralPath $StableManifest) {
    $manifest = Get-Content -LiteralPath $StableManifest -Raw -Encoding UTF8 | ConvertFrom-Json
}

$desktopProcess = Get-ExactDesktopProcess -Path $DesktopExe
$desktop = [ordered]@{
    expected_path = $DesktopExe
    file_present = (Test-Path -LiteralPath $DesktopExe)
    process_running = [bool]$desktopProcess
    pid = if ($desktopProcess) { [int]$desktopProcess.Id } else { $null }
}

$qq = Get-QQObservation
$qqRequiredPass = (-not $RequireQQ) -or ($qq.configured -and $qq.endpoint_reachable)

$manualRemaining = @(
    "physical microphone/realtime speech quality",
    "audible interrupt/cancel behavior",
    "rapid character/model visual switch observation",
    "real QQ inbound/outbound content observation"
)

$automatedPass =
    [bool]$launch.passed -and
    ($healthExit -eq 0) -and
    ($releaseExit -eq 0) -and
    [bool]$desktop.process_running -and
    $qqRequiredPass

$result = [ordered]@{
    schema_version = 1
    kind = "xiaoyu_physical_release_snapshot"
    captured_at = [DateTimeOffset]::Now.ToString("o")
    duration_ms = [math]::Round(([DateTimeOffset]::Now - $startedAt).TotalMilliseconds, 3)
    verdict = if ($automatedPass) { "PASS_AUTOMATED_MANUAL_OBSERVATION_REMAINS" } else { "FAIL_AUTOMATED" }
    no_launch = [bool]$NoLaunch
    require_qq = [bool]$RequireQQ
    release = [ordered]@{
        release_id = if ($manifest) { [string]$manifest.release_id } else { $null }
        status = if ($manifest) { [string]$manifest.status } else { $null }
        basis_commit = if ($manifest) { [string]$manifest.basis_commit } else { $null }
        readiness_exit_code = $releaseExit
        readiness_passed = ($releaseExit -eq 0)
    }
    launch = $launch
    runtime_health = $healthPayload
    runtime_health_exit_code = $healthExit
    desktop = $desktop
    qq = $qq
    manual_observations_remaining = $manualRemaining
}

$resultJson = $result | ConvertTo-Json -Depth 12
$resultDir = Split-Path -Parent $ResultPath
if ($resultDir) { New-Item -ItemType Directory -Force -Path $resultDir | Out-Null }
Set-Content -LiteralPath $ResultPath -Value ($resultJson + [Environment]::NewLine) -Encoding UTF8
Write-Output $resultJson
Write-Output ("XiaoYu physical release snapshot: {0}" -f $ResultPath)

if ($automatedPass) { exit 0 }
exit 8
