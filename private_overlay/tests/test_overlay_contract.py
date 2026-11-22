import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OverlayContractTests(unittest.TestCase):
    def test_single_authority_contract(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(lock["integration_mode"], "private_data_policy_overlay")
        self.assertEqual(lock["memory_authority"], "neko_native")
        self.assertEqual(lock["persona_storage_authority"], "neko_native")
        self.assertEqual(lock["evolution_authority"], "neko_native")
        self.assertEqual(lock["task_authority"], "neko_native")
        self.assertFalse(lock["allow_dual_write"])

    def test_core_patch_queue_stays_small_and_evidence_backed(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        patches = series["patches"]
        self.assertLessEqual(len(patches), lock["core_patch_budget"])
        self.assertGreaterEqual(lock["core_patch_budget"], 1)
        self.assertLessEqual(
            lock["core_patch_budget"],
            10,
            "Managed N.E.K.O patch budget must remain deliberately small",
        )
        for patch in patches:
            self.assertTrue((ROOT / "patches" / patch["file"]).is_file())
            self.assertTrue(patch["reason"].strip())
            self.assertTrue((ROOT / patch["evidence"]).is_file())

    def test_identity_contract_has_required_hard_invariants(self):
        data = json.loads(
            (ROOT / "identity" / "invariants.json").read_text(encoding="utf-8-sig")
        )
        required = {
            "same_identity_across_model_swap",
            "same_identity_across_restart",
            "same_identity_across_desktop_and_qq",
            "owner_correction_becomes_current",
            "erased_private_memory_must_not_resurrect",
            "private_context_must_not_widen_audience",
        }
        self.assertTrue(required.issubset(set(data["invariants"])))

    def test_growth_policy_is_data_only_and_neko_owns_evolution_runtime(self):
        data = json.loads(
            (ROOT / "identity" / "invariants.json").read_text(encoding="utf-8-sig")
        )
        self.assertTrue(data["allowed_growth"])
        self.assertTrue(data["forbidden_silent_changes"])

        evolution_dir = ROOT / "evolution"
        executable = list(evolution_dir.rglob("*.py")) if evolution_dir.exists() else []
        self.assertEqual(
            executable,
            [],
            "XiaoYu overlay must not grow a second persona/evolution runtime",
        )

    def test_plugin_runtime_reconcile_delegates_lifecycle_to_neko(self):
        source = (ROOT / "tools" / "reconcile_neko_plugin_runtime.py").read_text(encoding="utf-8-sig")
        self.assertIn("/plugins/refresh", source)
        self.assertIn("runtime_auto_start", source)
        self.assertIn("autostart_pending", source)
        self.assertIn("/start", source)
        self.assertNotIn("plugin.toml", source)
        self.assertNotIn("tomllib", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("topological", source)
        self.assertNotIn("rglob(", source)

    def test_private_runtime_plugins_are_exception_only_and_delegate_authority(self):
        plugins_dir = ROOT / "plugins"
        manifest = json.loads(
            (plugins_dir / "manifest.json").read_text(encoding="utf-8-sig")
        )
        allowed = manifest.get("allowed_private_runtime_plugins", [])
        allowed_ids = {item["id"] for item in allowed}

        actual_ids = {
            path.parent.name
            for path in plugins_dir.glob("*/__init__.py")
            if path.is_file()
        }
        self.assertEqual(
            actual_ids,
            allowed_ids,
            "Every private runtime plugin must be explicitly admitted by the overlay manifest",
        )

        for item in allowed:
            self.assertTrue(item["acceptance_gap"].strip())
            self.assertEqual(
                item["hard_execution_authority"],
                "neko_native:proactive_controller",
            )
            for authority_flag in (
                "owns_memory",
                "owns_persona",
                "owns_evolution",
                "owns_tasks",
                "owns_proactive_engine",
            ):
                self.assertFalse(
                    item[authority_flag],
                    f"{item['id']} must not duplicate N.E.K.O authority: {authority_flag}",
                )
            source_dir = ROOT / item["source_dir"]
            config = tomllib.loads(
                (source_dir / "plugin.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["plugin"]["id"], item["id"])
            dependency_ids = {
                dep.get("id")
                for dep in config["plugin"].get("dependency", [])
                if isinstance(dep, dict)
            }
            self.assertIn("proactive_controller", dependency_ids)
            self.assertTrue((ROOT / item["evidence"]).is_file())

    def test_startup_delegates_directly_to_neko_launcher(self):
        script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "setup_local.ps1",
            "-VerifyOnly",
            "ensure_native_embedding_assets.py",
            "--neko-root",
            "ensure_neko_storage_policy.py",
            "ensure_private_plugin.py",
            "--source",
            "plugins\\xiaoyu_interaction_policy",
            "run_checks.ps1",
            "-StartupPreflight",
            "reconcile_neko_plugin_runtime.py",
            "NEKO_STORAGE_SELECTED_ROOT",
            "NEKO_STORAGE_ANCHOR_ROOT",
            "NEKO_RUNTIME_STATE_DIR",
            "NEKO_CLOUDSAVE_DISABLED",
            "xiaoyu_private_local_authority",
            "steamworks\\__init__.py",
            "NEKO_PRIVATE_SPEECH_GATE_FILE",
            "NEKO_PRIVATE_FORCED_TOOL_NAME",
            "NEKO_PRIVATE_FORCED_TOOL_REASONING_EFFORT",
            "NEKO_PRIVATE_FORCED_TOOL_PATTERN",
            "xiaoyu_recent_activity",
            "launcher.py",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("plugins\\xiaoyu_private", script)
        self.assertNotIn("start_plugin", script)


    def test_startup_embedding_assets_delegate_to_neko_native_prepare(self):
        script = (ROOT / "tools" / "ensure_native_embedding_assets.py").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "prepare_embedding_model.py",
            "profile_is_complete",
            "jinaai/jina-embeddings-v5-text-nano-retrieval",
            "ac5d898c8d382b17167c33e5c8af644a3519b47d",
            "local-text-retrieval-v1",
            "--variant",
            "int8",
        }
        for marker in required:
            self.assertIn(marker, script)
        for forbidden in ("urllib", "httpx", "requests"):
            self.assertNotIn(forbidden, script)


    def test_recent_activity_forced_route_is_narrow_and_covers_live_wording(self):
        script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        match = re.search(
            r"\$env:NEKO_PRIVATE_FORCED_TOOL_PATTERN = '([^']*)'",
            script,
        )
        self.assertIsNotNone(match)
        pattern = match.group(1)
        self.assertTrue(all(ord(ch) < 128 for ch in pattern))
        re.compile(pattern)

        positives = (
            "\u6211\u7684\u610f\u601d\u662f\u4f60\u770b\u89c1\u8fc7\u53bb1\u4e2a\u5c0f\u65f6\u6211\u5e72\u4e86\u4ec0\u4e48\u5417",
            "\u6211\u521a\u624d\u4e00\u4e2a\u5c0f\u65f6\u4e3b\u8981\u5728\u7535\u8111\u4e0a\u5e72\u561b\uff1f",
            "\u6211\u6700\u8fd1\u662f\u5728\u5199\u4ee3\u7801\u8fd8\u662f\u6253\u6e38\u620f\uff1f",
            "\u6211\u521a\u521a\u8fd9\u6bb5\u65f6\u95f4\u662f\u4e0d\u662f\u4e00\u76f4\u6ca1\u5e72\u4e8b\uff1f",
        )
        negatives = (
            "\u8fc7\u53bb\u6211\u559c\u6b22\u6253\u6e38\u620f\u5417\uff1f",
            "\u4f60\u8bb0\u5f97\u6211\u957f\u671f\u66f4\u504f\u597d\u7684\u6c42\u804c\u57ce\u5e02\u662f\u4ec0\u4e48\u5417\uff1f",
            "\u53bb\u5e74\u8fd9\u4e2a\u65f6\u5019\u6211\u505a\u4e86\u4ec0\u4e48\uff1f",
            "\u4f60\u73b0\u5728\u770b\u89c1\u6211\u5728\u5e72\u4ec0\u4e48\uff1f",
        )
        for value in positives:
            self.assertRegex(value, pattern)
        for value in negatives:
            self.assertIsNone(re.search(pattern, value))



    def test_interaction_policy_reuses_native_plugin_store(self):
        source_dir = ROOT / "plugins" / "xiaoyu_interaction_policy"
        source = (source_dir / "__init__.py").read_text(encoding="utf-8-sig")
        config = tomllib.loads((source_dir / "plugin.toml").read_text(encoding="utf-8"))

        self.assertTrue(config["plugin"]["store"]["enabled"])
        self.assertIn("await self.store.get(", source)
        self.assertIn("await self.store.set(", source)
        self.assertIn('self.config.set("plugin.store.enabled", True', source)
        self.assertIn('"projection": "xiaoyu_reply_gate.v1"', source)
        self.assertIn('"quiet": bool(state.get("quiet"))', source)
        self.assertNotIn("tempfile.mkstemp", source)
        self.assertNotIn("os.replace(", source)

    def test_interaction_classifier_reuses_native_plugin_model_gateway(self):
        source_dir = ROOT / "plugins" / "xiaoyu_interaction_policy"
        source = (source_dir / "__init__.py").read_text(encoding="utf-8-sig")
        config = tomllib.loads((source_dir / "plugin.toml").read_text(encoding="utf-8"))

        models = config["plugin"].get("models", {})
        usage = models.get("interaction_classifier", {})
        self.assertTrue(usage.get("required"))
        self.assertEqual(usage.get("capabilities"), ["text"])
        self.assertIn("self.ctx.models.get_client()", source)
        self.assertIn('model=_CLASSIFIER_MODEL_USAGE', source)
        self.assertNotIn("from utils.config_manager import get_config_manager", source)
        self.assertNotIn("from utils.llm_client import", source)

    def test_private_plugin_ensure_uses_native_package_workflow(self):
        script = (ROOT / "tools" / "ensure_private_plugin.py").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "build_plugin",
            "PluginCliService",
            "plan_install",
            "confirm_upgrade",
            "confirmation_token",
            "build_install_source_manager",
            "reconcile",
            "USER_PLUGIN_EXEC_ROOT",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("shutil.copytree", script)
        self.assertNotIn("copy2(", script)


    def test_oneclick_uses_native_windows_power_saving_gpu_preference(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("UserGpuPreferences", script)
        self.assertIn("GpuPreference=1;", script)
        self.assertIn("Ensure-XiaoYuDesktopGpuPreference", script)
        self.assertNotIn("disableHardwareAcceleration", script)
        self.assertNotIn("disable-gpu", script)

    def test_oneclick_keeps_safety_before_ui_and_plugin_repair_after_ui(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("probe_neko_runtime_health.py", script)
        self.assertIn("runtime-health\\safety.json", script)
        self.assertIn("runtime-health\\latest.json", script)
        safety_probe = script.index("--safety-only")
        desktop_launch = script.index("Start-Process -FilePath $DesktopExe")
        recovery_probe = script.index(
            "& $Python $RuntimeHealthProbe",
            desktop_launch + 1,
        )
        recovery_notice = script.index(
            "XiaoYu is visible, but native runtime recovery",
            recovery_probe,
        )
        self.assertLess(safety_probe, desktop_launch)
        self.assertLess(desktop_launch, recovery_probe)
        self.assertLess(recovery_probe, recovery_notice)
        self.assertIn("runtime recovery incomplete", script)
        self.assertNotIn("runtime health daemon", script.lower())


    def test_oneclick_reuses_native_napcat_forward_runtime_without_owning_login(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "Ensure-XiaoYuNapCatForwardRuntime",
            "Get-XiaoYuNapCatForwardTarget",
            "napcat_forward",
            "business_config.json",
            "NapCatQQ-Desktop.exe",
            "Test-TcpEndpoint",
            "waiting-onebot",
            "desktop-missing",
            "A remote OneBot runtime is not this launcher's process authority.",
            "QQ authentication remains NapCat's authority",
            "SuppressNapCatNotice",
            "XiaoYu QQ needs login",
            "AddSeconds(15)",
        }
        for marker in required:
            self.assertIn(marker, script)

        # The overlay launches the external authority but does not copy QQ auth
        # or implement a second login/OneBot stack.
        self.assertNotIn("/QQLogin/SetQuickLogin", script)
        self.assertNotIn("/QQLogin/PasswordLogin", script)
        self.assertNotIn("NapCatWinBootHook.dll", script)


    def test_oneclick_reuses_neko_backend_single_instance_and_serializes_desktop_launch(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "Invoke-XiaoYuSingleFlight",
            "System.Threading.Mutex",
            "AbandonedMutexException",
            'Local\\XiaoYuDesktopLaunchV1',
            "$desktopOwnerDeadline = (Get-Date).AddSeconds(20)",
            "N.E.K.O launcher.py already owns backend single-instance semantics",
        }
        for marker in required:
            self.assertIn(marker, script)

        self.assertNotIn('Local\\XiaoYuBackendLaunchV1', script)
        backend_start = script.index('Start-Process -FilePath "powershell.exe"')
        desktop_mutex = script.index('Local\\XiaoYuDesktopLaunchV1')
        desktop_start = script.index('Start-Process -FilePath $DesktopExe', desktop_mutex)
        self.assertLess(backend_start, desktop_mutex)
        self.assertLess(desktop_mutex, desktop_start)

    def test_shortcut_installer_is_relocatable_and_covers_product_entries(self):
        script = (ROOT / "tools" / "install_xiaoyu_shortcuts.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "$PSScriptRoot",
            "start_xiaoyu_oneclick.ps1",
            "open_api_cost.cmd",
            "http://127.0.0.1:48911/",
            "0x5C0F",
            "0x9C7C",
            "0x8D39",
            "0x7528",
        }
        for item in required:
            self.assertIn(item, script)
        self.assertNotIn("dsh-fish-overlay-audit", script)
        self.assertNotIn("xiaoyu_private_overlay_work", script)


    def test_setup_keeps_neko_ui_native_and_repairable(self):
        script = (ROOT / "tools" / "setup_local.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "templates\\index.html",
            "frontend\\plugin-manager\\package.json",
            "frontend\\react-neko-chat\\package.json",
            "steamworks\\__init__.py",
            "frontend\\plugin-manager\\dist\\index.html",
            "static\\react\\neko-chat\\neko-chat-window.iife.js",
            "sparse-checkout add frontend templates steamworks",
            "npm run build-only",
            "npm run build",
            "Ensure-NekoCorePatches",
            "git -C $NekoRoot apply --reverse --check",
            "git -C $NekoRoot apply --check",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("build_frontend.bat", script)
        self.assertNotIn("plugins\\xiaoyu_private", script)

    def test_run_checks_anchors_unittest_discovery_to_repo_root(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$RepoRoot = Split-Path -Parent $OverlayRoot", script)
        self.assertIn("Push-Location $RepoRoot", script)
        self.assertIn("Pop-Location", script)

    def test_startup_uses_one_cold_ready_budget_for_launcher_and_plugin_reconcile(self):
        script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$StartupReadyBudgetSeconds = 180", script)
        self.assertIn(
            "$env:NEKO_SERVER_READY_TIMEOUT_SECONDS = [string]$StartupReadyBudgetSeconds",
            script,
        )
        self.assertIn(
            '"--wait-seconds", [string]$StartupReadyBudgetSeconds',
            script,
        )
        self.assertNotIn('"--wait-seconds", "90"', script)

    def test_startup_preflight_skips_developer_only_checks_but_keeps_safety_gates(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("[switch]$StartupPreflight", script)
        self.assertIn("if (-not $StartupPreflight)", script)
        for required in (
            "check_reuse_first.py",
            "check_architecture_freeze.py",
            "check_plugin_admission.py",
            "check_overlay.py",
            "check_provider_privacy.py",
            "PASS: XiaoYu runtime startup safety preflight",
        ):
            self.assertIn(required, script)

        start_script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("-StartupPreflight", start_script)
        # These expensive/developer-only checks remain in run_checks for normal
        # release validation, but start_xiaoyu must not invoke normal mode.
        self.assertIn("python -m unittest discover", script)
        self.assertIn("python -m compileall", script)
        self.assertIn("check_release_readiness.py", script)

    def test_github_agent_branches_run_machine_reuse_gate(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        for required in (
            '"agent/**"',
            '"private/neko-overlay-v1"',
            "check_reuse_first.py",
            "check_architecture_freeze.py",
            "check_plugin_admission_repo.py",
            "test_plugin_admission",
            "test_probe_neko_runtime_health",
            "check_release_readiness.py",
            "reuse-architecture-gate",
        ):
            self.assertIn(required, workflow)

    def test_release_gate_executes_pinned_qq_surface_contracts_but_startup_does_not(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "XiaoYu pinned QQ delivery/floor regression",
            "test_qq_outbound_guard.py",
            "test_group_send_safety.py",
            "test_proactive_budget_integration.py",
            "test_qq_proactive_initiative.py",
            "test_qq_auto_reply_forward_client.py",
            "test_qq_connection_status_refresh.py",
            "test_qq_buffer_no_append_after_delivery.py",
            "test_qq_buffer_send_time_floor.py",
            "test_qq_runtime_transition_lock.py",
            "test_qq_reply_buffer_switch.py",
            "$NekoPython -m pytest -q $QQSurfaceTests",
        }
        for item in required:
            self.assertIn(item, script)
        qq_gate = script.index("XiaoYu pinned QQ delivery/floor regression")
        startup_gate_end = script.index('Write-Host "== XiaoYu reuse-first admission gate =="')
        self.assertLess(qq_gate, startup_gate_end)
        self.assertIn("if (-not $StartupPreflight)", script[:qq_gate])

    def test_release_gate_executes_native_switch_and_audio_ownership_contracts(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "XiaoYu native companion switch/audio ownership regression",
            "test_character_switch_queue.py",
            "test_character_runtime_voice_identity.py",
            "test_model_switch_keeps_live_budget.py",
            "test_cosyvoice_audio_done_generation.py",
            "test_proactive_sid_guard.py",
            "test_assistant_speech_finalize_static.py",
            "test_openai_compatible_tts.py",
            "test_qwen_intl_tts_routing.py",
            "test_voice_management_tts.py",
            "chat_avatar_integration.test.cjs",
            "live2d_audio_ownership.test.cjs",
            "assistant-audio-lifecycle.test.cjs",
            "voice_recovery_races.cjs",
            "voice_preview_races.cjs",
            "$NekoPython -m pytest -q $CompanionPythonTests",
            "--test $CompanionNodeTests",
        }
        for item in required:
            self.assertIn(item, script)
        gate = script.index("XiaoYu native companion switch/audio ownership regression")
        startup_gate_end = script.index('Write-Host "== XiaoYu reuse-first admission gate =="')
        self.assertLess(gate, startup_gate_end)
        self.assertIn("if (-not $StartupPreflight)", script[:gate])

    def test_release_gate_executes_native_execution_plane_harness(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "XiaoYu native execution-plane regression",
            "check_execution_plane.py",
            "--neko-root $NekoRoot",
            "--python $NekoPython",
            "--full",
            "latest-execution-plane.json",
        }
        for item in required:
            self.assertIn(item, script)
        gate = script.index("XiaoYu native execution-plane regression")
        startup_gate_end = script.index('Write-Host "== XiaoYu reuse-first admission gate =="')
        self.assertLess(gate, startup_gate_end)
        self.assertIn("if (-not $StartupPreflight)", script[:gate])

    def test_execution_effect_state_candidate_is_reviewed_but_not_live(self):
        candidate = ROOT / "candidates" / "execution_plane" / "outbox_effect_state.patch"
        self.assertTrue(candidate.is_file())

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review_id = "candidate:execution_plane/outbox_effect_state.patch"
        self.assertIn(review_id, by_id)
        self.assertEqual(by_id[review_id]["status"], "approved")

        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        managed = {item["file"] for item in series["patches"]}
        self.assertNotIn(
            "outbox_effect_state.patch",
            managed,
            "effect-state work must remain candidate-only until end-to-end receipt/reconciliation closes",
        )

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "outbox_effect_state.patch",
            "git -C _neko_upstream apply --check",
            "verify_execution_effect_state_candidate.py",
        ):
            self.assertIn(required, workflow)

        verifier = (
            ROOT / "tools" / "verify_execution_effect_state_candidate.py"
        ).read_text(encoding="utf-8-sig")
        for invariant in (
            "outbox_mark_handoff",
            "outbox_claim_delivery",
            "outbox_release_delivery",
            "wrong-main-claim",
            "late-main-claim",
            "fresh-main-claim",
            '== "expired"',
            '== "released"',
            '== "uncertain"',
        ):
            self.assertIn(invariant, verifier)

    def test_github_gate_parses_all_product_powershell_entrypoints(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "Parse product PowerShell entrypoints",
            "System.Management.Automation.Language.Parser",
            'Get-ChildItem "private_overlay/tools" -Filter "*.ps1" -File',
            "No private_overlay PowerShell scripts were discovered.",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn("PSScriptAnalyzer", workflow)

    def test_github_gate_replays_patched_companion_switch_audio_regression(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        required = (
            "Exercise patched companion switch/audio ownership regression",
            "worktree add --detach",
            "private_overlay/patches/series.json",
            "apply --check --",
            "apply --reverse --check --",
            'uv run --project "$GITHUB_WORKSPACE/_neko_upstream" --locked --group dev',
            'PYTHONPATH="$PRODUCT_WORKTREE"',
            "test_character_switch_queue.py",
            "test_character_runtime_voice_identity.py",
            "test_model_switch_keeps_live_budget.py",
            "test_cosyvoice_audio_done_generation.py",
            "test_proactive_sid_guard.py",
            "test_assistant_speech_finalize_static.py",
            "test_openai_compatible_tts.py",
            "test_qwen_intl_tts_routing.py",
            "test_voice_management_tts.py",
            "chat_avatar_integration.test.cjs",
            "live2d_audio_ownership.test.cjs",
            "assistant-audio-lifecycle.test.cjs",
            "voice_recovery_races.cjs",
            "voice_preview_races.cjs",
        )
        for item in required:
            self.assertIn(item, workflow)
        product_gate = workflow.index(
            "Exercise patched companion switch/audio ownership regression"
        )
        clean_candidate_gate = workflow.index("Verify pinned native Execution Plane seams")
        self.assertLess(product_gate, clean_candidate_gate)
        self.assertIn("PRODUCT_WORKTREE=", workflow[product_gate:clean_candidate_gate])
        self.assertNotIn(
            'git -C _neko_upstream apply -- "$PATCH_PATH"',
            workflow[product_gate:clean_candidate_gate],
            "managed product patches must stay in the disposable worktree",
        )

    def test_native_delivery_receipt_candidate_is_reviewed_but_not_live(self):
        candidate = (
            ROOT
            / "candidates"
            / "execution_plane"
            / "native_delivery_receipt.patch"
        )
        self.assertTrue(candidate.is_file())

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review_id = "candidate:execution_plane/native_delivery_receipt.patch"
        self.assertIn(review_id, by_id)
        self.assertEqual(by_id[review_id]["status"], "approved")
        self.assertTrue(
            (
                ROOT
                / "evals"
                / "evidence"
                / "2026-11-23-native-delivery-receipt-reuse.json"
            ).is_file()
        )

        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        managed = {item["file"] for item in series["patches"]}
        self.assertNotIn(
            "native_delivery_receipt.patch",
            managed,
            "receipt work must remain candidate-only until end-to-end receipt/reconciliation is release-proven",
        )

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "native_delivery_receipt.patch",
            "verify_native_delivery_receipt_candidate.py",
            "Exercise native delivery receipt candidate",
        ):
            self.assertIn(required, workflow)

    def test_github_gate_replays_pinned_qq_surface_regression(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        required = (
            "Exercise pinned QQ delivery/floor surface regression",
            "uv run --locked --group dev python -m pytest -q",
            "test_qq_outbound_guard.py",
            "test_group_send_safety.py",
            "test_proactive_budget_integration.py",
            "test_qq_proactive_initiative.py",
            "test_qq_auto_reply_forward_client.py",
            "test_qq_connection_status_refresh.py",
            "test_qq_buffer_no_append_after_delivery.py",
            "test_qq_buffer_send_time_floor.py",
            "test_qq_runtime_transition_lock.py",
            "test_qq_reply_buffer_switch.py",
        )
        for item in required:
            self.assertIn(item, workflow)

    def test_qq_inbound_idempotency_candidate_is_reviewed_but_not_live(self):
        candidate = ROOT / "candidates" / "qq" / "live_inbound_idempotency.patch"
        self.assertTrue(candidate.is_file())

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review_id = "candidate:qq/live_inbound_idempotency.patch"
        self.assertIn(review_id, by_id)
        self.assertEqual(by_id[review_id]["status"], "approved")

        qq_lock = json.loads(
            (ROOT / "QQ_PLUGIN_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        self.assertFalse(qq_lock["core_patch_required"])
        self.assertFalse(
            bool(qq_lock.get("external_patch_required")),
            "QQ inbound idempotency must remain candidate-only until patched tests and live replay evidence close",
        )
        self.assertFalse((ROOT / "qq_patches" / "series.json").is_file())

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "live_inbound_idempotency.patch",
            "54acf36bf978edad4757e5fffc743c5618360700",
            "test_qq_catchup.py",
            "git -C _neko_upstream/plugin/plugins/qq_auto_reply apply --check",
        ):
            self.assertIn(required, workflow)

    def test_run_checks_enforces_reuse_first_gate(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("check_reuse_first.py", script)
        self.assertIn("ensure_native_embedding_assets.py", script)
        self.assertIn("--verify-only", script)
        reviews = json.loads((ROOT / "governance" / "reuse_reviews.json").read_text(encoding="utf-8-sig"))
        ids = {item["id"] for item in reviews["reviews"]}
        series = json.loads((ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig"))
        for patch in series["patches"]:
            self.assertIn("patch:" + patch["file"], ids)
        manifest = json.loads((ROOT / "plugins" / "manifest.json").read_text(encoding="utf-8-sig"))
        for plugin in manifest["allowed_private_runtime_plugins"]:
            self.assertIn("plugin:" + plugin["id"], ids)


    def test_architecture_freeze_is_machine_enforced(self):
        arch = json.loads(
            (ROOT / "governance" / "architecture_freeze.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(
            arch["decision_id"],
            "XIAOYU_ARCHITECTURE_FREEZE_V1",
        )
        self.assertEqual(arch["companion_runtime_authority"], "neko_native")
        self.assertEqual(arch["extension_plane_default"], "neko_plugin_sdk")
        self.assertTrue(arch["principles"]["no_second_runtime"])
        self.assertEqual(arch["memory"]["authority"], "neko_native")
        self.assertEqual(
            arch["memory"]["external_candidates_mode"],
            "shadow_only_until_explicit_promotion",
        )
        self.assertTrue(arch["private_core_patch_policy"]["requires_reuse_review"])
        self.assertTrue(
            arch["private_core_patch_policy"]["retire_when_native_extension_exists"]
        )
        retirement_evidence = arch["private_core_patch_policy"]["latest_retirement_audit"]
        self.assertTrue((ROOT / retirement_evidence).is_file())
        forbidden = set(arch["forbidden_xiaoyu_duplicate_authorities"])
        self.assertTrue(
            {
                "plugin_host",
                "model_gateway",
                "vector_store",
                "memory_runtime",
                "agent_runtime",
                "http_pool",
                "credential_store",
            }.issubset(forbidden)
        )

    def test_delivery_floor_contract_covers_all_user_visible_output_classes(self):
        delivery = json.loads(
            (ROOT / "governance" / "delivery_floor_v1.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(delivery["contract_id"], "XIAOYU_DELIVERY_FLOOR_V1")
        self.assertEqual(
            delivery["implementation_mode"],
            "contract_only_no_second_runtime",
        )
        self.assertEqual(delivery["publication_authority"], "neko_native")
        self.assertEqual(set(delivery["decisions"]), {"ALLOW", "HOLD", "DROP"})
        self.assertEqual(
            set(delivery["output_classes"]),
            {
                "ordinary_reply",
                "proactive",
                "work_break",
                "game_invite",
                "agent_result",
                "qq_outbound",
            },
        )
        self.assertEqual(
            delivery["output_classes"]["ordinary_reply"]["current_enforcement_adapter"],
            "patch:0006-private-speech-output-gate.patch",
        )
        for name in ("proactive", "work_break", "game_invite"):
            self.assertEqual(
                delivery["output_classes"][name]["current_enforcement_adapter"],
                "patch:0009-proactive-interruptibility-gate.patch",
            )
        self.assertEqual(
            delivery["output_classes"]["agent_result"]["current_enforcement_adapter"],
            "neko_native:task_result_outbox_to_proactive_callback",
        )
        self.assertEqual(
            delivery["output_classes"]["qq_outbound"]["current_enforcement_adapter"],
            "external:pinned_qq_auto_reply_surface_floor",
        )
        for item in delivery["output_classes"].values():
            self.assertTrue((ROOT / item["evidence"]).is_file())
        requirements = delivery["global_requirements"]
        for key in (
            "latest_state_recheck_before_claim_or_publication",
            "audience_and_privacy_must_be_valid_at_delivery",
            "nonessential_output_must_respect_interruptibility",
            "text_and_paired_tts_must_share_one_admission",
            "policy_layer_must_not_publish_directly",
            "native_delivery_remains_effect_authority",
        ):
            self.assertTrue(requirements[key], key)

    def test_external_execution_contract_reuses_neko_native_authorities(self):
        execution = json.loads(
            (ROOT / "governance" / "execution_contract_v1.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(execution["contract_id"], "XIAOYU_EXTERNAL_EXECUTION_V1")
        self.assertEqual(
            execution["implementation_mode"],
            "reuse_neko_native_no_second_agent_runtime",
        )
        self.assertEqual(execution["authority"]["commission_ledger"], "nekoclaw_host")
        self.assertEqual(execution["authority"]["permission_gate"], "nekoclaw_host")
        self.assertEqual(execution["authority"]["capability_gateway"], "nekoclaw_host")
        self.assertEqual(execution["authority"]["result_outbox"], "nekoclaw_host")
        self.assertEqual(execution["authority"]["identity_and_persona"], "neko_native")
        self.assertEqual(execution["authority"]["memory"], "neko_native")
        self.assertEqual(execution["routing"]["single_step"], "neko_plugin_direct")
        self.assertEqual(execution["routing"]["multi_step"], "nekoclaw_task_agent")
        self.assertEqual(
            execution["routing"]["capabilities"],
            "nekoclaw_mcp_capability_gateway",
        )
        self.assertTrue(execution["runtime_seam"]["builtin"]["allowed"])
        self.assertEqual(
            execution["runtime_seam"]["dsh"]["transport"],
            "ACP_JSON_RPC_stdio",
        )
        self.assertTrue(execution["runtime_seam"]["dsh"]["fallback_to_builtin"])
        self.assertFalse(execution["runtime_seam"]["openclaw"]["allowed"])
        self.assertFalse(execution["runtime_seam"]["hermes"]["allowed"])
        self.assertEqual(
            execution["external_capability_policy"]["preferred_boundary"],
            "MCP",
        )
        self.assertFalse(execution["activation"]["enable_agent_master_in_this_change"])
        self.assertFalse(execution["activation"]["install_dsh_in_this_change"])
        self.assertTrue((ROOT / execution["evidence"]).is_file())

    def test_run_checks_enforces_architecture_freeze(self):
        script = (ROOT / "tools" / "run_checks.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("check_architecture_freeze.py", script)


if __name__ == "__main__":
    unittest.main()
