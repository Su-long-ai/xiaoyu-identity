param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$StartupPreflight,
    [switch]$CompanionPerformance,
    [ValidateSet("live", "cold_start")]
    [string]$PerformanceProfile = "live",
    [string]$NativeBenchmark = ""
)

$ErrorActionPreference = "Stop"
$OverlayRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $OverlayRoot

if (-not $StartupPreflight) {
    Write-Host "== XiaoYu overlay unit tests =="
    # unittest discovery imports tests as modules. Anchor cwd to the repository root
    # so package imports stay relocatable and do not depend on the shortcut/caller cwd.
    Push-Location $RepoRoot
    try {
        python -m unittest discover -s (Join-Path $OverlayRoot "tests") -v
        $UnitTestExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($UnitTestExit -ne 0) { exit $UnitTestExit }

    Write-Host "== XiaoYu overlay compile =="
    python -m compileall -q (Join-Path $OverlayRoot "tools") (Join-Path $OverlayRoot "tests") (Join-Path $OverlayRoot "migration") (Join-Path $OverlayRoot "evals")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== XiaoYu ActivityWatch reuse dependency =="
    python (Join-Path $OverlayRoot "tools\check_activitywatch.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== XiaoYu native embedding asset pin =="
    $NekoPython = Join-Path $NekoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $NekoPython)) {
        throw "N.E.K.O venv python not found for embedding asset verification: $NekoPython"
    }
    & $NekoPython (Join-Path $OverlayRoot "tools\ensure_native_embedding_assets.py") --neko-root $NekoRoot --verify-only
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== XiaoYu pinned QQ delivery/floor regression =="
    $QQPluginRoot = Join-Path $NekoRoot "plugin\plugins\qq_auto_reply"
    $QQSurfaceTests = @(
        (Join-Path $QQPluginRoot "tests\test_qq_outbound_guard.py"),
        (Join-Path $QQPluginRoot "tests\test_group_send_safety.py"),
        (Join-Path $QQPluginRoot "tests\test_proactive_budget_integration.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_proactive_initiative.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_auto_reply_forward_client.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_connection_status_refresh.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_buffer_no_append_after_delivery.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_buffer_send_time_floor.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_runtime_transition_lock.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_reply_buffer_switch.py")
    )
    foreach ($QQSurfaceTest in $QQSurfaceTests) {
        if (-not (Test-Path -LiteralPath $QQSurfaceTest)) {
            throw "Pinned QQ delivery/floor regression test missing: $QQSurfaceTest"
        }
    }
    Push-Location $NekoRoot
    try {
        & $NekoPython -m pytest -q $QQSurfaceTests
        $QQSurfaceExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($QQSurfaceExit -ne 0) { exit $QQSurfaceExit }

    Write-Host "== XiaoYu native companion switch/audio ownership regression =="
    $CompanionPythonTests = @(
        (Join-Path $NekoRoot "tests\unit\test_character_switch_queue.py"),
        (Join-Path $NekoRoot "tests\unit\test_character_runtime_voice_identity.py"),
        (Join-Path $NekoRoot "tests\unit\test_model_switch_keeps_live_budget.py"),
        (Join-Path $NekoRoot "tests\unit\test_cosyvoice_audio_done_generation.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_sid_guard.py"),
        (Join-Path $NekoRoot "tests\unit\test_assistant_speech_finalize_static.py"),
        (Join-Path $NekoRoot "tests\unit\test_openai_compatible_tts.py"),
        (Join-Path $NekoRoot "tests\unit\test_qwen_intl_tts_routing.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_management_tts.py")
    )
    $CompanionOwnershipFiles = @(
        (Join-Path $NekoRoot "tests\unit\test_audio_stream_queue.py"),
        (Join-Path $NekoRoot "tests\unit\test_realtime_close_ownership.py"),
        (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_connection_recovery.py"),
        (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_host_turn_identity.py"),
        (Join-Path $NekoRoot "tests\unit\test_tts_handoff_ownership.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_start_slot_ownership.py")
    )
    $CompanionOwnershipTargets = @(
        ("{0}::test_native_realtime_loud_ingress_publishes_activity_before_worker" -f (Join-Path $NekoRoot "tests\unit\test_audio_stream_queue.py")),
        ("{0}::test_teardown_outliving_its_connection_does_not_touch_the_replacement" -f (Join-Path $NekoRoot "tests\unit\test_realtime_close_ownership.py")),
        ("{0}::test_retired_teardown_does_not_shut_the_replacements_arbiter_down" -f (Join-Path $NekoRoot "tests\unit\test_realtime_close_ownership.py")),
        ("{0}::test_retired_receive_loop_cannot_condemn_or_report_the_replacement" -f (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_connection_recovery.py")),
        ("{0}::test_late_failure_from_a_retired_generation_cannot_recover_the_successor" -f (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_connection_recovery.py")),
        ("{0}::test_neither_hook_runs_once_the_host_is_on_a_new_turn" -f (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_host_turn_identity.py")),
        ("{0}::test_the_rotation_stands_down_when_a_turn_starts_during_response_done" -f (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_host_turn_identity.py")),
        ("{0}::test_old_runtime_audio_waiting_for_frame_lock_is_not_sent" -f (Join-Path $NekoRoot "tests\unit\test_tts_handoff_ownership.py")),
        ("{0}::test_runtime_handoff_drains_status_blocked_inside_websocket_send" -f (Join-Path $NekoRoot "tests\unit\test_tts_handoff_ownership.py")),
        ("{0}::test_a_superseded_flow_cannot_release_the_newer_starts_slot" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_slot_ownership.py")),
        ("{0}::test_the_automatic_restart_stands_down_at_every_resumption_point" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_slot_ownership.py"))
    )
    $CompanionNodeTests = @(
        (Join-Path $NekoRoot "tests\frontend\chat_avatar_integration.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\live2d_audio_ownership.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\assistant-audio-lifecycle.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\voice_recovery_races.cjs"),
        (Join-Path $NekoRoot "tests\frontend\voice_preview_races.cjs")
    )
    foreach ($CompanionTest in @($CompanionPythonTests + $CompanionOwnershipFiles + $CompanionNodeTests)) {
        if (-not (Test-Path -LiteralPath $CompanionTest)) {
            throw "Native companion regression test missing: $CompanionTest"
        }
    }
    Push-Location $NekoRoot
    try {
        & $NekoPython -m pytest -q $CompanionPythonTests
        $CompanionPythonExit = $LASTEXITCODE
        if ($CompanionPythonExit -ne 0) { exit $CompanionPythonExit }

        & $NekoPython -m pytest -q $CompanionOwnershipTargets
        $CompanionOwnershipExit = $LASTEXITCODE
        if ($CompanionOwnershipExit -ne 0) { exit $CompanionOwnershipExit }

        $NodeCommand = Get-Command node -ErrorAction Stop
        & $NodeCommand.Source --test $CompanionNodeTests
        $CompanionNodeExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($CompanionNodeExit -ne 0) { exit $CompanionNodeExit }

    Write-Host "== XiaoYu native execution-plane regression =="
    $ExecutionEvidence = Join-Path $OverlayRoot "evals\evidence\latest-execution-plane.json"
    & $NekoPython (Join-Path $OverlayRoot "tools\check_execution_plane.py") `
        --neko-root $NekoRoot `
        --python $NekoPython `
        --full `
        --json-out $ExecutionEvidence
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "== XiaoYu reuse-first admission gate =="
python (Join-Path $OverlayRoot "tools\check_reuse_first.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu frozen architecture/delivery contract =="
python (Join-Path $OverlayRoot "tools\check_architecture_freeze.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu plugin autostart admission =="
python (Join-Path $OverlayRoot "tools\check_plugin_admission.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu/N.E.K.O authority contract =="
$env:NEKO_ROOT = $NekoRoot
python (Join-Path $OverlayRoot "tools\check_overlay.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== XiaoYu provider privacy preflight =="
python (Join-Path $OverlayRoot "tools\check_provider_privacy.py") --neko-root $NekoRoot --storage-root $StorageRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $StartupPreflight) {
    Write-Host "== XiaoYu release readiness =="
    python (Join-Path $OverlayRoot "tools\check_release_readiness.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if ($CompanionPerformance) {
        Write-Host "== XiaoYu Companion performance gate =="
        & (Join-Path $OverlayRoot "tools\run_companion_performance.ps1") `
            -Profile $PerformanceProfile `
            -NekoRoot $NekoRoot `
            -StorageRoot $StorageRoot `
            -NativeBenchmark $NativeBenchmark
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
else {
    Write-Host "PASS: XiaoYu runtime startup safety preflight"
}

exit 0
