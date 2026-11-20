param(
    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop"),
    [string]$MainUrl = "http://127.0.0.1:48911/"
)

$ErrorActionPreference = "Stop"
$ToolsRoot = $PSScriptRoot
$OverlayRoot = (Resolve-Path (Join-Path $ToolsRoot "..")).Path
$OneClick = Join-Path $ToolsRoot "start_xiaoyu_oneclick.ps1"
$CostEntry = Join-Path $ToolsRoot "open_api_cost.cmd"

if (-not (Test-Path -LiteralPath $OneClick)) { throw "XiaoYu one-click launcher missing: $OneClick" }
if (-not (Test-Path -LiteralPath $CostEntry)) { throw "XiaoYu API cost entry missing: $CostEntry" }
if (-not (Test-Path -LiteralPath $DesktopPath)) { throw "Desktop path missing: $DesktopPath" }

$Wsh = New-Object -ComObject WScript.Shell

function Write-Shortcut {
    param([string]$Path,[string]$TargetPath,[string]$Arguments,[string]$WorkingDirectory,[string]$IconLocation = "")
    $Shortcut = $Wsh.CreateShortcut($Path)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $WorkingDirectory
    if ($IconLocation) { $Shortcut.IconLocation = $IconLocation }
    $Shortcut.Save()
}

$Fish = ([string][char]0x5C0F) + ([char]0x9C7C)
$DebugWord = ([string][char]0x8C03) + ([char]0x8BD5)
$CostWord = ([string][char]0x8D39) + ([char]0x7528)
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$MainShortcut = Join-Path $DesktopPath ("{0} XiaoYu.lnk" -f $Fish)
$DebugShortcut = Join-Path $DesktopPath ("{0} XiaoYu - {1}.lnk" -f $Fish, $DebugWord)
$CostShortcut = Join-Path $DesktopPath ("XiaoYu API {0}.lnk" -f $CostWord)

Write-Shortcut -Path $MainShortcut -TargetPath $PowerShell -Arguments ('-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $OneClick) -WorkingDirectory $ToolsRoot
Write-Shortcut -Path $DebugShortcut -TargetPath "$env:SystemRoot\explorer.exe" -Arguments $MainUrl -WorkingDirectory $OverlayRoot
Write-Shortcut -Path $CostShortcut -TargetPath $CostEntry -Arguments "" -WorkingDirectory $ToolsRoot -IconLocation "shell32.dll,165"

Write-Output "PASS: XiaoYu desktop shortcuts installed"
Write-Output "main=$MainShortcut"
Write-Output "debug=$DebugShortcut"
Write-Output "cost=$CostShortcut"
