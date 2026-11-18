param(
    [string]$NekoRoot = "D:\xiaoyu_external_audit\N.E.K.O"
)

$ErrorActionPreference = "Stop"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$Py = Join-Path $NekoRoot ".venv\Scripts\python.exe"

$Tests = @(
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_legacy_rows_default_to_private_and_never_become_global"),
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_malformed_partial_scope_fails_closed_as_legacy_private"),
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_hybrid_recall_filters_scope_before_rankers"),
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_persona_view_only_exposes_authorized_scoped_sections"),
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_scoped_synthesis_prompt_never_names_private_master"),
    ((Join-Path $NekoRoot "tests\unit\test_group_memory_scopes.py") + "::test_persona_view_authorizes_scoped_entries_per_entry"),
    ((Join-Path $NekoRoot "tests\unit\test_participant_memory_and_display_name.py") + "::test_display_name_scope_mismatch_is_fail_closed"),
    ((Join-Path $NekoRoot "tests\unit\test_participant_memory_and_display_name.py") + "::test_scope_handoff_clears_previous_display_name"),
    ((Join-Path $NekoRoot "tests\unit\test_participant_memory_and_display_name.py") + "::test_scoped_render_hides_display_name_owned_by_another_scope"),
    (Join-Path $NekoRoot "tests\unit\test_qq_open_platform_actor_identity.py"),
    (Join-Path $NekoRoot "tests\unit\test_qq_open_platform_identity_scope.py"),
    (Join-Path $NekoRoot "tests\unit\test_onebot_client_forward.py"),
    ((Join-Path $NekoRoot "tests\unit\test_subject_identity.py") + "::test_expansion_never_crosses_a_platform"),
    ((Join-Path $NekoRoot "tests\unit\test_subject_identity.py") + "::test_forget_never_fans_out_across_platforms"),
    ((Join-Path $NekoRoot "tests\unit\test_subject_identity.py") + "::test_the_same_conversation_id_on_two_platforms_never_folds"),
    ((Join-Path $NekoRoot "tests\unit\test_subject_identity.py") + "::test_a_custom_scope_is_never_folded_or_rerouted")
)

& $Py -m pytest -o 'addopts=' -p pytest_asyncio.plugin -q @Tests
exit $LASTEXITCODE
