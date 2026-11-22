param(
    [string]$MainUrl = "http://127.0.0.1:48911/",
    [string]$MemoryHealthUrl = "http://127.0.0.1:48912/health",
    [string]$AgentHealthUrl = "http://127.0.0.1:48915/health",
    [string]$Python = "python",
    [string]$DesktopExe = "D:\xiaoyu_external_audit\neko-nightly-desktop\shell\N.E.K.O.exe",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [string]$NapCatDesktopExe = "C:\Program Files\NapCatQQ Desktop\NapCatQQ-Desktop.exe",
    [switch]$SuppressNapCatNotice
)

$ErrorActionPreference = "Stop"
$StartScript = Join-Path $PSScriptRoot "start_xiaoyu.ps1"

function Test-Http200([string]$Url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-XiaoYuBackendReady {
    return (Test-Http200 $MainUrl) -and
           (Test-Http200 $MemoryHealthUrl) -and
           (Test-Http200 $AgentHealthUrl)
}

function Invoke-XiaoYuSingleFlight {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [int]$WaitMilliseconds = 1500
    )
    $mutex = [System.Threading.Mutex]::new($false, $Name)
    $owned = $false
    try {
        try {
            $owned = $mutex.WaitOne([Math]::Max(0, $WaitMilliseconds))
        } catch [System.Threading.AbandonedMutexException] {
            # The previous launcher died while owning the launch decision.
            # Windows transfers ownership to us; the action rechecks live state.
            $owned = $true
        }
        if (-not $owned) { return $false }
        & $Action
        return $true
    }
    finally {
        if ($owned) {
            try { $mutex.ReleaseMutex() } catch {}
        }
        $mutex.Dispose()
    }
}

function Test-TcpEndpoint([string]$HostName, [int]$Port, [int]$TimeoutMs = 250) {
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        if ($client) { $client.Close() }
    }
}

function Get-XiaoYuNapCatForwardTarget {
    $configPath = Join-Path $StorageRoot "plugins\qq_auto_reply\data\business_config.json"
    if (-not (Test-Path -LiteralPath $configPath)) { return $null }
    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
    if ([string]$config.qq_connection_mode -ne "napcat_forward") { return $null }

    $rawUrl = [string]$config.onebot_url
    if (-not $rawUrl) { return $null }
    try {
        $uri = [Uri]$rawUrl
    } catch {
        return $null
    }
    if ($uri.Scheme -notin @("ws", "wss")) { return $null }
    if ($uri.Host -notin @("127.0.0.1", "localhost", "::1")) {
        # A remote OneBot runtime is not this launcher's process authority.
        return $null
    }
    $port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq "wss") { 443 } else { 80 }
    return [pscustomobject]@{
        Host = $uri.Host
        Port = [int]$port
        ConfigPath = $configPath
    }
}

function Ensure-XiaoYuNapCatForwardRuntime {
    # Reuse the already-installed NapCat Desktop.  This launcher owns only
    # process availability; QQ authentication remains NapCat's authority.
    $target = Get-XiaoYuNapCatForwardTarget
    if (-not $target) { return "not-configured" }
    if (Test-TcpEndpoint $target.Host $target.Port) { return "ready" }

    $existing = Get-Process -Name "NapCatQQ-Desktop" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($existing) { return "waiting-onebot" }
    if (-not (Test-Path -LiteralPath $NapCatDesktopExe)) { return "desktop-missing" }

    Start-Process -FilePath $NapCatDesktopExe -WorkingDirectory (Split-Path -Parent $NapCatDesktopExe) | Out-Null
    return "started"
}

function Get-XiaoYuDesktopProcess {
    if (-not (Test-Path -LiteralPath $DesktopExe)) { return $null }
    $resolvedDesktop = (Resolve-Path -LiteralPath $DesktopExe).Path
    return Get-Process -Name "N.E.K.O" -ErrorAction SilentlyContinue |
        Where-Object {
            try { $_.Path -eq $resolvedDesktop } catch { $false }
        } |
        Select-Object -First 1
}

function Ensure-XiaoYuDesktopGpuPreference {
    # Reuse Windows native per-app GPU policy instead of patching Electron.
    # GpuPreference=1 selects the power-saving adapter while retaining GPU acceleration.
    if ($env:OS -ne "Windows_NT") { return }
    if (-not (Test-Path -LiteralPath $DesktopExe)) { return }

    $resolvedDesktop = (Resolve-Path -LiteralPath $DesktopExe).Path
    $gpuPreferenceKey = "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences"
    $desiredPreference = "GpuPreference=1;"
    New-Item -Path $gpuPreferenceKey -Force | Out-Null

    $currentPreference = $null
    try {
        $currentPreference = Get-ItemPropertyValue -Path $gpuPreferenceKey -Name $resolvedDesktop -ErrorAction Stop
    } catch {}

    if ($currentPreference -ne $desiredPreference) {
        New-ItemProperty -Path $gpuPreferenceKey -Name $resolvedDesktop -Value $desiredPreference -PropertyType String -Force | Out-Null
    }
}

$NapCatRuntimeStatus = Ensure-XiaoYuNapCatForwardRuntime
Write-Output ("XiaoYu NapCat forward runtime: {0}" -f $NapCatRuntimeStatus)

if (-not (Test-XiaoYuBackendReady)) {
    # N.E.K.O launcher.py already owns backend single-instance semantics via
    # its native OS file lock and authoritative launcher record. Reuse that
    # authority instead of layering a second XiaoYu backend mutex.
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $StartScript)
    ) -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-XiaoYuBackendReady) { break }
    }
}

if (-not (Test-XiaoYuBackendReady)) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "XiaoYu backend did not become ready. Use the XiaoYu debug shortcut to inspect the web UI.",
        0,
        "XiaoYu startup failed",
        0x10
    )
    exit 1
}

# Before exposing the desktop UI, fail closed only on non-negotiable
# runtime safety: service reachability and forbidden Agent capability state.
# Missing auto-start plugins are recorded here but repaired only after the UI
# is visible, so an optional plugin cannot hold desktop readiness behind a
# bounded recovery timeout.
$RuntimeHealthProbe = Join-Path $PSScriptRoot "probe_neko_runtime_health.py"
$RuntimeSafetyResult = Join-Path $StorageRoot "runtime-health\safety.json"
$RuntimeHealthResult = Join-Path $StorageRoot "runtime-health\latest.json"
& $Python $RuntimeHealthProbe `
    --main-health-url ($MainUrl.TrimEnd('/') + "/health") `
    --memory-health-url $MemoryHealthUrl `
    --agent-health-url $AgentHealthUrl `
    --safety-only `
    --result-path $RuntimeSafetyResult
if ($LASTEXITCODE -ne 0) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "XiaoYu backend is reachable, but the native runtime safety preflight failed. See $RuntimeSafetyResult.",
        0,
        "XiaoYu runtime safety failed",
        0x10
    )
    exit 4
}

if (-not (Test-Path -LiteralPath $DesktopExe)) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "The official N.E.K.O desktop host is missing: $DesktopExe",
        0,
        "XiaoYu desktop host missing",
        0x10
    )
    exit 2
}

Ensure-XiaoYuDesktopGpuPreference

if (-not (Get-XiaoYuDesktopProcess)) {
    $ownedDesktopLaunch = Invoke-XiaoYuSingleFlight -Name "Local\XiaoYuDesktopLaunchV1" -Action {
        if (-not (Get-XiaoYuDesktopProcess)) {
            Start-Process -FilePath $DesktopExe -WorkingDirectory (Split-Path -Parent $DesktopExe) | Out-Null
        }
        $desktopOwnerDeadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $desktopOwnerDeadline) {
            if (Get-XiaoYuDesktopProcess) { break }
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ownedDesktopLaunch -and -not (Get-XiaoYuDesktopProcess)) {
        $desktopFollowerDeadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $desktopFollowerDeadline) {
            if (Get-XiaoYuDesktopProcess) { break }
            Start-Sleep -Milliseconds 500
        }
    }
}

if (-not (Get-XiaoYuDesktopProcess)) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "XiaoYu backend is ready, but the desktop host did not start.",
        0,
        "XiaoYu desktop startup failed",
        0x10
    )
    exit 3
}

# The visible companion wins the readiness race. Once the desktop process is
# confirmed, perform one bounded native repair for missing host-declared
# auto-start plugins. Core safety is still checked again by the same probe.
& $Python $RuntimeHealthProbe `
    --main-health-url ($MainUrl.TrimEnd('/') + "/health") `
    --memory-health-url $MemoryHealthUrl `
    --agent-health-url $AgentHealthUrl `
    --result-path $RuntimeHealthResult
if ($LASTEXITCODE -ne 0) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "XiaoYu is visible, but native runtime recovery did not fully converge. See $RuntimeHealthResult.",
        8,
        "XiaoYu runtime recovery incomplete",
        0x30
    )
}

$NapCatTarget = Get-XiaoYuNapCatForwardTarget
if ($NapCatTarget -and $NapCatRuntimeStatus -eq "started") {
    # Give a freshly launched external runtime a short chance to restore a
    # still-valid QQ session before deciding that user action is needed.
    $napcatDeadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $napcatDeadline) {
        if (Test-TcpEndpoint $NapCatTarget.Host $NapCatTarget.Port) { break }
        Start-Sleep -Milliseconds 500
    }
}

if (
    -not $SuppressNapCatNotice -and
    $NapCatTarget -and
    -not (Test-TcpEndpoint $NapCatTarget.Host $NapCatTarget.Port)
) {
    $wshell = New-Object -ComObject WScript.Shell
    $null = $wshell.Popup(
        "XiaoYu is running, but QQ is waiting for NapCat/QQ login. Open NapCatQQ Desktop and complete login once; OneBot will reconnect automatically.",
        8,
        "XiaoYu QQ needs login",
        0x40
    )
}

exit 0
