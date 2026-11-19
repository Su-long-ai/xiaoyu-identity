param(
    [string]$MainUrl = "http://127.0.0.1:48911/",
    [string]$MemoryHealthUrl = "http://127.0.0.1:48912/health",
    [string]$AgentHealthUrl = "http://127.0.0.1:48915/health",
    [string]$DesktopExe = "D:\xiaoyu_external_audit\neko-nightly-desktop\shell\N.E.K.O.exe"
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

function Get-XiaoYuDesktopProcess {
    if (-not (Test-Path -LiteralPath $DesktopExe)) { return $null }
    $resolvedDesktop = (Resolve-Path -LiteralPath $DesktopExe).Path
    return Get-Process -Name "N.E.K.O" -ErrorAction SilentlyContinue |
        Where-Object {
            try { $_.Path -eq $resolvedDesktop } catch { $false }
        } |
        Select-Object -First 1
}

if (-not (Test-XiaoYuBackendReady)) {
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

if (-not (Get-XiaoYuDesktopProcess)) {
    Start-Process -FilePath $DesktopExe -WorkingDirectory (Split-Path -Parent $DesktopExe) | Out-Null

    $desktopDeadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $desktopDeadline) {
        Start-Sleep -Milliseconds 500
        if (Get-XiaoYuDesktopProcess) { break }
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

exit 0
