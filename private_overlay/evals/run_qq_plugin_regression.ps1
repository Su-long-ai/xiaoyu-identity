param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$QQPluginRoot = ""
)
$ErrorActionPreference = "Stop"
if (-not $QQPluginRoot) {
    $QQPluginRoot = Join-Path $NekoRoot "plugin\plugins\qq_auto_reply"
}
$py = Join-Path $NekoRoot ".venv\Scripts\python.exe"
$tests = @(
    (Join-Path $QQPluginRoot "tests\test_account_identity.py"),
    (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_identity_links.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_memory_directionality.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_memory_preflight.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_forward_memory.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_session_handoff.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_auto_reply_forward_client.py"),
    (Join-Path $QQPluginRoot "tests\test_qq_onebot_adapter_names.py")
)
& $py -m pytest @tests -q -o asyncio_mode=auto
exit $LASTEXITCODE