param([string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O")
$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $NekoRoot "static"))) {
    throw "N.E.K.O static/ is missing. Use a complete checkout (or add static/ to the sparse checkout) before this regression."
}
$py = Join-Path $NekoRoot ".venv\Scripts\python.exe"
$files = @(
    (Join-Path $NekoRoot "tests\unit\test_character_runtime_voice_identity.py"),
    (Join-Path $NekoRoot "tests\unit\test_voice_admission_integration.py"),
    (Join-Path $NekoRoot "tests\unit\test_voice_activation_delivery_acceptance.py"),
    (Join-Path $NekoRoot "tests\unit\test_desktop_capture.py"),
    (Join-Path $NekoRoot "tests\unit\test_request_fresh_screenshot.py"),
    (Join-Path $NekoRoot "tests\unit\test_vision_model_endpoint_switch.py"),
    (Join-Path $NekoRoot "tests\unit\test_plugin_llm_tool_sdk.py"),
    (Join-Path $NekoRoot "tests\unit\test_tool_calling.py"),
    (Join-Path $NekoRoot "tests\unit\test_tool_cancellation_boundaries.py")
)
& $py -m pytest @files -q -rs -o asyncio_mode=auto
exit $LASTEXITCODE
