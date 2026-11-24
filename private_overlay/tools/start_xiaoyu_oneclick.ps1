param(
    [string]$MainUrl = "http://127.0.0.1:48911/",
    [string]$MemoryHealthUrl = "http://127.0.0.1:48912/health",
    [string]$AgentHealthUrl = "http://127.0.0.1:48915/health",
    [string]$PluginUrl = "http://127.0.0.1:48916",
    [string]$Python = "python",
    [string]$DesktopExe = "D:\xiaoyu_external_audit\neko-nightly-desktop\shell\N.E.K.O.exe",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [string]$NapCatDesktopExe = "C:\Program Files\NapCatQQ Desktop\NapCatQQ-Desktop.exe",
    [switch]$SuppressNapCatNotice
)

$ErrorActionPreference = "Stop"
$StartScript = Join-Path $PSScriptRoot "start_xiaoyu.ps1"
$RuntimeRecordPath = Join-Path $StorageRoot ".runtime\launcher.json"
$script:XiaoYuRuntimeRecordStatus = "missing"
$script:AgentUrl = $AgentHealthUrl.TrimEnd("/")
if ($script:AgentUrl.EndsWith("/health")) {
    $script:AgentUrl = $script:AgentUrl.Substring(0, $script:AgentUrl.Length - "/health".Length)
}
$script:PluginHealthUrl = $PluginUrl.TrimEnd("/") + "/health"

function Sync-XiaoYuEndpointsFromNativeRuntimeRecord {
    # N.E.K.O launcher.json is the endpoint/readiness authority. XiaoYu never
    # acquires its lock or owns process lifecycle; it only consumes the record.
    if (-not (Test-Path -LiteralPath $RuntimeRecordPath)) {
        $script:XiaoYuRuntimeRecordStatus = "missing"
        return "fallback"
    }

    try {
        $record = Get-Content -LiteralPath $RuntimeRecordPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        $script:XiaoYuRuntimeRecordStatus = "invalid"
        return "wait"
    }

    if ($record.app -and [string]$record.app -ne "N.E.K.O") {
        $script:XiaoYuRuntimeRecordStatus = "invalid-app"
        return "wait"
    }

    $state = [string]$record.state
    if ($state -ne "ready") {
        if (-not $state) { $state = "starting" }
        $script:XiaoYuRuntimeRecordStatus = $state
        return "wait"
    }

    try {
        $mainPort = [int]$record.ports.MAIN_SERVER_PORT
        $memoryPort = [int]$record.ports.MEMORY_SERVER_PORT
        $agentPort = [int]$record.ports.TOOL_SERVER_PORT
        $pluginPort = [int]$record.internal_ports.USER_PLUGIN_SERVER_PORT
        foreach ($port in @($mainPort, $memoryPort, $agentPort, $pluginPort)) {
            if ($port -lt 1 -or $port -gt 65535) {
                throw "invalid native runtime port: $port"
            }
        }
    } catch {
        $script:XiaoYuRuntimeRecordStatus = "invalid-ports"
        return "wait"
    }

    $script:MainUrl = "http://127.0.0.1:$mainPort/"
    $script:MemoryHealthUrl = "http://127.0.0.1:$memoryPort/health"
    $script:AgentUrl = "http://127.0.0.1:$agentPort"
    $script:AgentHealthUrl = "$script:AgentUrl/health"
    $script:PluginUrl = "http://127.0.0.1:$pluginPort"
    $script:PluginHealthUrl = "$script:PluginUrl/health"
    $script:XiaoYuRuntimeRecordStatus = "ready"
    return "record"
}
# Readiness observation is intentionally short-lived and read-only. Reuse
# .NET's native HTTP/task primitives so one polling iteration is bounded by
# one request timeout instead of serially paying three independent timeouts.
$script:XiaoYuReadyHttpClient = [System.Net.Http.HttpClient]::new()
$script:XiaoYuReadyHttpClient.Timeout = [TimeSpan]::FromSeconds(2)

function Test-XiaoYuBackendReady {
    $endpointSource = Sync-XiaoYuEndpointsFromNativeRuntimeRecord
    if ($endpointSource -eq "wait") {
        return $false
    }

    $tasks = @(
        $script:XiaoYuReadyHttpClient.GetAsync($MainUrl),
        $script:XiaoYuReadyHttpClient.GetAsync($MemoryHealthUrl),
        $script:XiaoYuReadyHttpClient.GetAsync($AgentHealthUrl)
    )
    $responses = @()
    try {
        $all = [System.Threading.Tasks.Task]::WhenAll(
            [System.Threading.Tasks.Task[]]$tasks
        )
        $all.GetAwaiter().GetResult() | Out-Null

        foreach ($task in $tasks) {
            $response = $task.GetAwaiter().GetResult()
            $responses += $response
            if (-not $response.IsSuccessStatusCode) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    } finally {
        foreach ($response in $responses) {
            try { $response.Dispose() } catch {}
        }
    }
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

$BackendLauncherProcess = $null
$BackendLauncherExitCode = $null

if (-not (Test-XiaoYuBackendReady)) {
    # N.E.K.O launcher.py already owns backend single-instance semantics via
    # its native OS file lock and authoritative launcher record. Reuse that
    # authority instead of layering a second XiaoYu backend mutex.
    #
    # Keep only the Process handle. Do not redirect stdout/stderr: a healthy
    # source launcher is long-lived, so doing that here would turn the one-click
    # observer into an unbounded runtime log sink. Native diagnostics remain
    # available through start_xiaoyu.ps1 / StartupPreflight when needed.
    $BackendLauncherProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $StartScript),
        "-StorageRoot", ('"{0}"' -f $StorageRoot)
    ) -WindowStyle Hidden -PassThru

    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1

        # Readiness wins over the observer: another native launcher may own the
        # current generation while this follower exits. In particular, exit 0
        # is never treated as failure because N.E.K.O single-instance handoff
        # can legitimately finish that follower before the owner is ready.
        if (Test-XiaoYuBackendReady) { break }

        if ($BackendLauncherProcess -and $BackendLauncherProcess.HasExited) {
            $candidateExitCode = $BackendLauncherProcess.ExitCode
            if ($candidateExitCode -ne 0) {
                $BackendLauncherExitCode = $candidateExitCode
                break
            }
        }
    }
}

if (-not (Test-XiaoYuBackendReady)) {
    $wshell = New-Object -ComObject WScript.Shell

    if ($null -ne $BackendLauncherExitCode) {
        $preflightCommand = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -StorageRoot "{1}" -PreflightOnly' -f $StartScript, $StorageRoot)
        $null = $wshell.Popup(
            ("XiaoYu backend launcher exited before readiness (code {0}).`nNative record: {1}`nRecord: {2}`nRun for detailed native/preflight diagnostics:`n{3}" -f $BackendLauncherExitCode, $script:XiaoYuRuntimeRecordStatus, $RuntimeRecordPath, $preflightCommand),
            0,
            "XiaoYu startup failed early",
            0x10
        )
        exit 5
    }

    $null = $wshell.Popup(
        ("XiaoYu backend did not become ready.`nNative record: {0}`nMain: {1}`nMemory: {2}`nAgent: {3}`nRecord: {4}" -f $script:XiaoYuRuntimeRecordStatus, $MainUrl, $MemoryHealthUrl, $AgentHealthUrl, $RuntimeRecordPath),
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
    --plugin-health-url $script:PluginHealthUrl `
    --plugin-url $script:PluginUrl `
    --agent-url $script:AgentUrl `
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
    --plugin-health-url $script:PluginHealthUrl `
    --plugin-url $script:PluginUrl `
    --agent-url $script:AgentUrl `
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
