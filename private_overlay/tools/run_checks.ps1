param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O",
    [string]$StorageRoot = "D:\xiaoyu_private_overlay_state\neko-sandbox",
    [switch]$StartupPreflight
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
        (Join-Path $QQPluginRoot "tests\test_qq_send_observability.py"),
        (Join-Path $QQPluginRoot "tests\test_group_send_safety.py"),
        (Join-Path $QQPluginRoot "tests\test_proactive_budget_integration.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_proactive_initiative.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_auto_reply_forward_client.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_connection_status_refresh.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_catchup.py"),
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

    Write-Host "== XiaoYu pinned QQ identity/context continuity regression =="
    $QQIdentityFiles = @(
        (Join-Path $QQPluginRoot "tests\test_companion_context.py"),
        (Join-Path $QQPluginRoot "tests\test_qq_free_route_persona.py"),
        (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py"),
        (Join-Path $QQPluginRoot "tests\test_account_identity.py")
    )
    $QQIdentityTargets = @(
        ("{0}::test_live_binding_revocation" -f (Join-Path $QQPluginRoot "tests\test_companion_context.py")),
        ("{0}::test_generation_and_both_delivery_paths_recheck_same_token" -f (Join-Path $QQPluginRoot "tests\test_companion_context.py")),
        ("{0}::test_buffer_union_and_rebinding_never_resurrect_old_draft" -f (Join-Path $QQPluginRoot "tests\test_companion_context.py")),
        ("{0}::test_external_section_is_never_frozen_in_session_base" -f (Join-Path $QQPluginRoot "tests\test_companion_context.py")),
        ("{0}::test_persona_comes_from_the_host_not_from_a_new_prompt" -f (Join-Path $QQPluginRoot "tests\test_qq_free_route_persona.py")),
        ("{0}::test_every_self_built_request_asks_the_shared_helper" -f (Join-Path $QQPluginRoot "tests\test_qq_free_route_persona.py")),
        ("{0}::test_switching_speaker_does_not_inherit_owner_identity" -f (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py")),
        ("{0}::test_revoked_owner_is_rechecked_after_await" -f (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py")),
        ("{0}::test_shared_session_refreshes_identity_for_each_turn" -f (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py")),
        ("{0}::test_identity_never_uses_private_companion_configuration" -f (Join-Path $QQPluginRoot "tests\test_group_owner_identity.py")),
        ("{0}::test_only_live_onebot_identity_is_shared" -f (Join-Path $QQPluginRoot "tests\test_account_identity.py"))
    )
    foreach ($QQIdentityFile in $QQIdentityFiles) {
        if (-not (Test-Path -LiteralPath $QQIdentityFile)) {
            throw "Pinned QQ identity/context regression test missing: $QQIdentityFile"
        }
    }
    Push-Location $NekoRoot
    try {
        & $NekoPython -m pytest -q $QQIdentityTargets
        $QQIdentityExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($QQIdentityExit -ne 0) { exit $QQIdentityExit }

    Write-Host "== XiaoYu native companion switch/audio ownership regression =="
    $CompanionPythonTests = @(
        (Join-Path $NekoRoot "tests\unit\test_character_switch_queue.py"),
        (Join-Path $NekoRoot "tests\unit\test_character_runtime_voice_identity.py"),
        (Join-Path $NekoRoot "tests\unit\test_model_switch_keeps_live_budget.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_config.py"),
        (Join-Path $NekoRoot "tests\unit\test_avatar_model_load_race_static_contracts.py"),
        (Join-Path $NekoRoot "tests\unit\test_qwen_voice_bundle.py"),
        (Join-Path $NekoRoot "tests\unit\test_cosyvoice_audio_done_generation.py"),
        (Join-Path $NekoRoot "tests\unit\test_private_speech_output_gate.py"),
        (Join-Path $NekoRoot "tests\unit\test_windows_interruptibility_signal.py"),
        (Join-Path $NekoRoot "tests\unit\test_xiaoyu_capability_shadow.py"),
        (Join-Path $NekoRoot "tests\unit\test_xiaoyu_plugin_visible_final_admission.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_sid_guard.py"),
        (Join-Path $NekoRoot "tests\unit\test_assistant_speech_finalize_static.py"),
        (Join-Path $NekoRoot "tests\unit\test_openai_compatible_tts.py"),
        (Join-Path $NekoRoot "tests\unit\test_qwen_intl_tts_routing.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_management_tts.py"),
        (Join-Path $NekoRoot "tests\unit\test_xiaoyu_startup_performance.py"),
        (Join-Path $NekoRoot "tests\unit\test_cloudsave_lifecycle_flow.py")
    )
    $CompanionOwnershipFiles = @(
        (Join-Path $NekoRoot "tests\unit\test_audio_stream_queue.py"),
        (Join-Path $NekoRoot "tests\unit\test_realtime_close_ownership.py"),
        (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_connection_recovery.py"),
        (Join-Path $NekoRoot "tests\unit\runtime\test_realtime_host_turn_identity.py"),
        (Join-Path $NekoRoot "tests\unit\test_tts_handoff_ownership.py"),
        (Join-Path $NekoRoot "tests\unit\test_tts_handoff_transport_failures.py"),
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
        ("{0}::test_timed_out_handler_does_not_block_successor_tts_start" -f (Join-Path $NekoRoot "tests\unit\test_tts_handoff_transport_failures.py")),
        ("{0}::test_stalled_frame_closes_only_captured_socket_and_releases_lock" -f (Join-Path $NekoRoot "tests\unit\test_tts_handoff_transport_failures.py")),
        ("{0}::test_pipeline_clear_cannot_steal_stopping_handlers_wakeup" -f (Join-Path $NekoRoot "tests\unit\test_tts_handoff_transport_failures.py")),
        ("{0}::test_a_superseded_flow_cannot_release_the_newer_starts_slot" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_slot_ownership.py")),
        ("{0}::test_the_automatic_restart_stands_down_at_every_resumption_point" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_slot_ownership.py"))
    )
    $CompanionVoiceFiles = @(
        (Join-Path $NekoRoot "tests\unit\test_voice_session.py"),
        (Join-Path $NekoRoot "tests\unit\test_glm_tts.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_start_teardown_paths.py"),
        (Join-Path $NekoRoot "tests\unit\test_realtime_response_ownership.py"),
        (Join-Path $NekoRoot "tests\unit\test_qwen_provider_fallback.py"),
        (Join-Path $NekoRoot "tests\unit\test_voice_turn_wrap_up_hold.py")
    )
    $CompanionVoiceTargets = @(
        ("{0}::test_connect_qwen_server_vad_type_follows_model" -f (Join-Path $NekoRoot "tests\unit\test_voice_session.py")),
        ("{0}::test_glm_tts_frontend_and_backend_are_wired" -f (Join-Path $NekoRoot "tests\unit\test_glm_tts.py")),
        ("{0}::test_cross_mode_restart_stands_down_and_unwinds_only_for_a_text_takeover" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_teardown_paths.py")),
        ("{0}::test_the_automatic_restart_survives_anything_that_happens_in_its_delay" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_teardown_paths.py")),
        ("{0}::test_a_cancellation_after_a_takeover_outranks_it" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_teardown_paths.py")),
        ("{0}::test_the_onclose_cleanup_does_not_disarm_the_restart_it_schedules" -f (Join-Path $NekoRoot "tests\unit\test_voice_start_teardown_paths.py")),
        ("{0}::test_retired_created_overlap_with_server_vad_fails_closed" -f (Join-Path $NekoRoot "tests\unit\test_realtime_response_ownership.py")),
        ("{0}::test_late_created_is_one_shot_and_idless_successor_completes" -f (Join-Path $NekoRoot "tests\unit\test_realtime_response_ownership.py")),
        ("{0}::test_transport_ignores_retired_created_before_exposing_successor" -f (Join-Path $NekoRoot "tests\unit\test_realtime_response_ownership.py")),
        ("{0}::test_reconnect_retries_without_losing_held_audio" -f (Join-Path $NekoRoot "tests\unit\test_qwen_provider_fallback.py")),
        ("{0}::test_stale_pause_cannot_finish_next_provider_turn" -f (Join-Path $NekoRoot "tests\unit\test_qwen_provider_fallback.py")),
        ("{0}::test_old_unclaimed_final_cannot_cover_pcm_sent_before_new_pause" -f (Join-Path $NekoRoot "tests\unit\test_qwen_provider_fallback.py")),
        ("{0}::test_a_voice_onset_holds_the_debt_until_its_own_reply_pays_it" -f (Join-Path $NekoRoot "tests\unit\test_voice_turn_wrap_up_hold.py")),
        ("{0}::test_the_hold_is_taken_before_the_interruption_awaits" -f (Join-Path $NekoRoot "tests\unit\test_voice_turn_wrap_up_hold.py")),
        ("{0}::test_a_newer_voice_turn_takes_the_hold_over" -f (Join-Path $NekoRoot "tests\unit\test_voice_turn_wrap_up_hold.py")),
        ("{0}::test_a_voice_onset_cutting_a_voice_reply_owes_its_wrap_up" -f (Join-Path $NekoRoot "tests\unit\test_voice_turn_wrap_up_hold.py"))
    )
    $CompanionInteractionFiles = @(
        (Join-Path $NekoRoot "tests\unit\test_tool_calling.py"),
        (Join-Path $NekoRoot "tests\unit\test_client_registration.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_feedback_router.py")
    )
    $CompanionInteractionTargets = @(
        ("{0}::test_private_provider_native_route_requires_registered_matching_tool" -f (Join-Path $NekoRoot "tests\unit\test_tool_calling.py")),
        ("{0}::test_private_provider_native_route_forces_only_first_round" -f (Join-Path $NekoRoot "tests\unit\test_tool_calling.py")),
        ("{0}::test_registration_client_reuses_native_internal_and_external_pools" -f (Join-Path $NekoRoot "tests\unit\test_client_registration.py")),
        ("{0}::test_default_factory_builds_ssl_context_off_event_loop" -f (Join-Path $NekoRoot "tests\unit\test_proactive_feedback_router.py"))
    )
    $CompanionPolicyFiles = @(
        (Join-Path $NekoRoot "tests\unit\test_mini_game_invite.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_service_boundary.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_vision_revocation.py"),
        (Join-Path $NekoRoot "tests\unit\test_system_presence.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_unanswered_repeat.py"),
        (Join-Path $NekoRoot "tests\unit\test_proactive_user_directives.py")
    )
    $CompanionPolicyTargets = @(
        ("{0}::test_maybe_deliver_is_leisure_only" -f (Join-Path $NekoRoot "tests\unit\test_mini_game_invite.py")),
        ("{0}::test_maybe_deliver_allows_explicit_leisure_states" -f (Join-Path $NekoRoot "tests\unit\test_mini_game_invite.py")),
        ("{0}::test_break_reminder_respects_round_ownership" -f (Join-Path $NekoRoot "tests\unit\test_proactive_service_boundary.py")),
        ("{0}::test_voice_nudge_respects_interruptibility_gate" -f (Join-Path $NekoRoot "tests\unit\test_proactive_vision_revocation.py")),
        ("{0}::test_display_off_then_on_suppresses_and_keeps_quiet_after_return" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_lock_then_unlock" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_suspend_then_resume" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_remote_disconnect_forgets_state_and_reconnect_rearms_from_scratch" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_missed_resume_broadcast_does_not_silence_forever" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_voice_session_ignores_display_off_and_return_quiet" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_voice_session_still_gated_by_lock_and_suspend" -f (Join-Path $NekoRoot "tests\unit\test_system_presence.py")),
        ("{0}::test_normal_delivery_guards_tts_and_commit_with_engagement_snapshot" -f (Join-Path $NekoRoot "tests\unit\test_proactive_unanswered_repeat.py")),
        ("{0}::test_regenerated_delivery_aborts_when_engagement_cutoff_advances" -f (Join-Path $NekoRoot "tests\unit\test_proactive_unanswered_repeat.py")),
        ("{0}::test_guard_regenerates_then_drops_still_unanswered_repeat" -f (Join-Path $NekoRoot "tests\unit\test_proactive_unanswered_repeat.py")),
        ("{0}::test_ban_gate_runs_before_any_repeat_detection" -f (Join-Path $NekoRoot "tests\unit\test_proactive_user_directives.py")),
        ("{0}::test_banned_draft_is_dropped_without_any_llm_call" -f (Join-Path $NekoRoot "tests\unit\test_proactive_user_directives.py")),
        ("{0}::test_material_exempt_channel_is_still_gated" -f (Join-Path $NekoRoot "tests\unit\test_proactive_user_directives.py")),
        ("{0}::test_regen_output_is_gated_too" -f (Join-Path $NekoRoot "tests\unit\test_proactive_user_directives.py"))
    )
    $CompanionNodeTests = @(
        (Join-Path $NekoRoot "tests\frontend\chat_avatar_integration.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\live2d_mode_selection_restore.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\live2d_audio_ownership.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\assistant-audio-lifecycle.test.cjs"),
        (Join-Path $NekoRoot "tests\frontend\voice_recovery_races.cjs"),
        (Join-Path $NekoRoot "tests\frontend\voice_preview_races.cjs")
    )
    foreach ($CompanionTest in @($CompanionPythonTests + $CompanionOwnershipFiles + $CompanionVoiceFiles + $CompanionInteractionFiles + $CompanionPolicyFiles + $CompanionNodeTests)) {
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

        & $NekoPython -m pytest -q $CompanionVoiceTargets
        $CompanionVoiceExit = $LASTEXITCODE
        if ($CompanionVoiceExit -ne 0) { exit $CompanionVoiceExit }

        & $NekoPython -m pytest -q $CompanionInteractionTargets
        $CompanionInteractionExit = $LASTEXITCODE
        if ($CompanionInteractionExit -ne 0) { exit $CompanionInteractionExit }

        & $NekoPython -m pytest -q $CompanionPolicyTargets
        $CompanionPolicyExit = $LASTEXITCODE
        if ($CompanionPolicyExit -ne 0) { exit $CompanionPolicyExit }

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
}
else {
    Write-Host "PASS: XiaoYu runtime startup safety preflight"
}

exit 0
