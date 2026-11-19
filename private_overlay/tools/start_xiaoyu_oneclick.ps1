param(
    [string]$Url = "http://127.0.0.1:48911/"
)

$ErrorActionPreference = "Stop"
$StartScript = Join-Path $PSScriptRoot "start_xiaoyu.ps1"

function Test-XiaoYuReady {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (-not (Test-XiaoYuReady)) {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $StartScript)
    ) -WindowStyle Minimized | Out-Null

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-XiaoYuReady) { break }
    }
}

if (Test-XiaoYuReady) {
    Start-Process $Url
    exit 0
}

$wshell = New-Object -ComObject WScript.Shell
$null = $wshell.Popup("XiaoYu did not start within 120 seconds. Check the launcher window for details.", 0, "XiaoYu startup failed", 0x10)
exit 1
