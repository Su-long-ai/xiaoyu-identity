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
        architecture = json.loads(
            (ROOT / "governance" / "architecture_freeze.json").read_text(
                encoding="utf-8-sig"
            )
        )
        exception_policy = json.loads(
            (
                ROOT
                / "governance"
                / "core_patch_correctness_exceptions_v1.json"
            ).read_text(encoding="utf-8-sig")
        )
        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        patches = series["patches"]
        patch_files = [item["file"] for item in patches]
        patch_policy = architecture["private_core_patch_policy"]
        base_budget = patch_policy["base_managed_patch_budget"]
        exception_budget = patch_policy["correctness_exception_budget"]
        total_budget = patch_policy["max_managed_patch_budget"]
        exceptions = [item["file"] for item in exception_policy["exceptions"]]

        self.assertLessEqual(base_budget, 10)
        self.assertLessEqual(exception_budget, 4)
        self.assertEqual(total_budget, base_budget + exception_budget)
        self.assertEqual(lock["core_patch_budget"], total_budget)
        self.assertLessEqual(len(patches), total_budget)
        self.assertLessEqual(len(exceptions), exception_budget)
        self.assertLessEqual(len(patches) - len(exceptions), base_budget)
        self.assertEqual(
            set(exceptions),
            {
                "0011-execution-outbox-effect-state.patch",
                "0012-native-delivery-receipt.patch",
                "0013-plugin-run-unknown-effect.patch",
                "0014-plugin-run-idempotency.patch",
            },
        )
        self.assertTrue(set(exceptions).issubset(set(patch_files)))
        self.assertTrue(
            {
                Path(item).name
                for item in exception_policy["candidate_only_exclusions"]
            }.isdisjoint(set(patch_files))
        )

        grouped = set()
        for group in exception_policy["promotion_groups"]:
            self.assertTrue(group["blockers_closed"])
            self.assertTrue(group["patches"])
            for evidence in group["evidence"]:
                self.assertTrue((ROOT / evidence).is_file())
            grouped.update(group["patches"])
        self.assertEqual(grouped, set(exceptions))

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

    def test_oneclick_parallelizes_backend_readiness_without_new_lifecycle_authority(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        for required in (
            "System.Net.Http.HttpClient",
            "System.Threading.Tasks.Task]::WhenAll",
            "$script:XiaoYuReadyHttpClient.GetAsync($MainUrl)",
            "$script:XiaoYuReadyHttpClient.GetAsync($MemoryHealthUrl)",
            "$script:XiaoYuReadyHttpClient.GetAsync($AgentHealthUrl)",
            "N.E.K.O launcher.py already owns backend single-instance semantics",
        ):
            self.assertIn(required, script)
        self.assertNotIn("function Test-Http200", script)
        self.assertNotIn("Invoke-WebRequest -UseBasicParsing -Uri $Url", script)

    def test_oneclick_consumes_native_launcher_record_and_negotiated_ports(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        starter = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        reconcile = (
            ROOT / "tools" / "reconcile_neko_plugin_runtime.py"
        ).read_text(encoding="utf-8-sig")

        for required in (
            '.runtime\\launcher.json',
            'record.state',
            'MAIN_SERVER_PORT',
            'MEMORY_SERVER_PORT',
            'TOOL_SERVER_PORT',
            'USER_PLUGIN_SERVER_PORT',
            'XiaoYuRuntimeRecordStatus',
            '--plugin-health-url',
            '--plugin-url',
            '--agent-url',
            '"-StorageRoot"',
        ):
            self.assertIn(required, script)
        self.assertIn('--runtime-record', starter)
        self.assertIn('launcher.json', starter)
        self.assertIn('resolve_native_runtime_record', reconcile)
        self.assertIn('neko_launcher_record', reconcile)
        self.assertIn('explicit_urls_fallback', reconcile)
        self.assertNotIn('XiaoYuBackendLaunch', script)
        self.assertEqual(
            script.count("function Sync-XiaoYuEndpointsFromNativeRuntimeRecord"),
            1,
        )
        self.assertEqual(script.count("function Test-XiaoYuBackendReady"), 1)


    def test_oneclick_fails_fast_only_on_nonzero_hidden_backend_exit(self):
        script = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )

        for required in (
            "$BackendLauncherProcess = Start-Process",
            "-WindowStyle Hidden -PassThru",
            "$BackendLauncherProcess.HasExited",
            "$BackendLauncherProcess.ExitCode",
            "$candidateExitCode -ne 0",
            "$BackendLauncherExitCode = $candidateExitCode",
            "$null -ne $BackendLauncherExitCode",
            "XiaoYu backend launcher exited before readiness",
            "-PreflightOnly",
            "exit 5",
        ):
            self.assertIn(required, script)

        loop_ready = script.index(
            "if (Test-XiaoYuBackendReady) { break }",
            script.index("$deadline = (Get-Date).AddSeconds(180)"),
        )
        child_exit = script.index(
            "$BackendLauncherProcess.HasExited",
            loop_ready,
        )
        self.assertLess(loop_ready, child_exit)
        self.assertNotIn("RedirectStandardOutput", script)
        self.assertNotIn("RedirectStandardError", script)

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
            "Get-NekoManagedPatchPrefixLength",
            "git -C $NekoRoot apply --cached --check",
            "git -C $NekoRoot ls-tree -r --name-only",
            "refusing to guess through partial, reordered, or manual changes",
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

    def test_public_main_mirror_uses_same_machine_gate(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        self.assertGreaterEqual(workflow.count('      - "main"'), 2)
        self.assertIn('      - "private/neko-overlay-v1"', workflow)
        self.assertIn('      - "agent/**"', workflow)
        for required in (
            "Public repository secret leak gate",
            "Reuse-first hard gate",
            "Frozen architecture hard gate",
            "Repository-only plugin admission gate",
            "Release evidence gate",
        ):
            self.assertIn(required, workflow)

    def test_github_gate_blocks_public_secret_leaks(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            '      - "private/neko-overlay-v1"',
            '      - "agent/**"',
            "fetch-depth: 0",
            "Public repository secret leak gate",
            "gitleaks/gitleaks-action@v3",
            'GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}',
            'GITLEAKS_ENABLE_COMMENTS: "false"',
            'GITLEAKS_ENABLE_UPLOAD_ARTIFACT: "false"',
        ):
            self.assertIn(required, workflow)
        checkout = workflow.index("Checkout candidate")
        secrets_gate = workflow.index("Public repository secret leak gate")
        reuse_gate = workflow.index("Reuse-first hard gate")
        architecture_gate = workflow.index("Frozen architecture hard gate")
        self.assertLess(checkout, secrets_gate)
        self.assertLess(secrets_gate, reuse_gate)
        self.assertLess(reuse_gate, architecture_gate)

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

    def test_github_gate_exercises_report_wait_host_restart_candidate(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Exercise report-wait host-restart candidate",
            "candidates/execution_plane/host_restart_report_wait.patch",
            "candidates/execution_plane/test_host_restart_report_wait_candidate.py",
            "test_unfinished_commissions_of_an_earlier_process_fail_on_open",
            "test_what_an_earlier_process_left_unfinished_is_reported_with_its_failure",
            "test_an_answer_after_the_idle_session_was_closed_takes_it_up_again",
        )
        for item in required:
            self.assertIn(item, workflow)

        uncertain = workflow.index("Verify managed plugin-run unknown-effect in product worktree")
        regression = workflow.index("Regress managed native Execution Plane")
        report_wait = workflow.index("Exercise report-wait host-restart candidate")
        permission_wait = workflow.index("Exercise permission-wait host-restart candidate")
        self.assertLess(uncertain, regression)
        self.assertLess(regression, report_wait)
        self.assertLess(report_wait, permission_wait)
        self.assertNotIn("continue-on-error", workflow[report_wait:permission_wait])

    def test_github_gate_exercises_permission_wait_host_restart_candidate(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Exercise permission-wait host-restart candidate",
            "candidates/execution_plane/host_restart_permission_wait.patch",
            "candidates/execution_plane/test_host_restart_permission_wait_candidate.py",
            "test_missing_result_gets_synthetic_interruption",
            "test_outside_reads_and_their_model_results_share_one_user_answer",
        )
        for item in required:
            self.assertIn(item, workflow)

        regression = workflow.index("Regress managed native Execution Plane")
        report_wait = workflow.index("Exercise report-wait host-restart candidate")
        permission_wait = workflow.index("Exercise permission-wait host-restart candidate")
        qq_checkout = workflow.index("Checkout pinned QQ plugin candidate base")
        self.assertLess(regression, report_wait)
        self.assertLess(report_wait, permission_wait)
        self.assertLess(permission_wait, qq_checkout)
        self.assertNotIn("continue-on-error", workflow[permission_wait:qq_checkout])

    def test_github_gate_exercises_managed_plugin_run_unknown_effect_patch(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Verify managed plugin-run unknown-effect in product worktree",
            "Prepare managed N.E.K.O product worktree",
            'PYTHONPATH="$GITHUB_WORKSPACE/_neko_product"',
            "candidates/execution_plane/test_plugin_run_unknown_effect_candidate.py",
            "test_unreadable_status_answers_end_the_wait",
            "test_a_run_given_up_on_stays_known_until_its_cancel_is_accepted",
            "test_failed_plugin_call_ends_failed_with_a_report",
            "test_failed_run_is_an_error_result",
        )
        for item in required:
            self.assertIn(item, workflow)

        idempotency = workflow.index("Verify managed plugin-run idempotency in product worktree")
        uncertain = workflow.index("Verify managed plugin-run unknown-effect in product worktree")
        regression = workflow.index("Regress managed native Execution Plane")
        self.assertLess(uncertain, idempotency)
        self.assertLess(idempotency, regression)
        self.assertNotIn("continue-on-error", workflow[uncertain:regression])

    def test_github_gate_exercises_managed_plugin_run_idempotency_patch(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "tests/unit/nekoclaw/test_host_plugin_runs.py",
            "plugin/tests/unit/server/test_run_manager_idempotency.py",
            "Verify managed plugin-run idempotency in product worktree",
            "Prepare managed N.E.K.O product worktree",
            'PYTHONPATH="$GITHUB_WORKSPACE/_neko_product"',
            "candidates/execution_plane/test_plugin_run_idempotency_candidate.py",
            "test_retry_after_lost_response_executes_once",
        )
        for item in required:
            self.assertIn(item, workflow)

        baseline = workflow.index("Capture clean native Execution Plane regression baseline")
        uncertain = workflow.index("Verify managed plugin-run unknown-effect in product worktree")
        candidate = workflow.index("Verify managed plugin-run idempotency in product worktree")
        regression = workflow.index("Regress managed native Execution Plane")
        self.assertLess(baseline, uncertain)
        self.assertLess(uncertain, candidate)
        self.assertLess(candidate, regression)
        self.assertNotIn("continue-on-error", workflow[uncertain:regression])

    def test_github_gate_probes_host_restart_continuity_gap(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Probe native host-restart commission continuity gap",
            "candidates/execution_plane/probe_host_restart_continuity_gap.py",
            "test_unfinished_commissions_of_an_earlier_process_fail_on_open",
            "test_what_an_earlier_process_left_unfinished_is_reported_with_its_failure",
            "test_an_answer_held_by_a_closing_session_survives_its_runtime_going_away",
            "test_a_blocked_commission_is_taken_up_again_where_it_stopped",
            "test_a_result_takes_up_again_a_parent_whose_idle_session_was_closed",
        )
        for item in required:
            self.assertIn(item, workflow)

        probe = workflow.index("Probe native host-restart commission continuity gap")
        dsh = workflow.index("Exercise native dsh optional-runtime product acceptance")
        self.assertLess(probe, dsh)
        self.assertNotIn("continue-on-error", workflow[probe:dsh])

    def test_github_gate_executes_native_dsh_optional_runtime_acceptance(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Exercise native dsh optional-runtime product acceptance",
            "test_dsh_acp.py::test_a_request_that_gets_no_answer_times_out_and_a_late_answer_is_dropped",
            "test_dsh_acp.py::test_a_start_that_is_cancelled_ends_the_process_it_started",
            "test_dsh_driver.py::test_abort_stops_the_turn_and_drops_what_was_queued",
            "test_dsh_driver.py::test_a_session_resumes_in_a_new_process_without_being_told_again",
            "test_dsh_driver.py::test_a_dsh_whose_guard_did_not_load_is_not_used",
            "test_dsh_driver.py::test_a_gateway_tool_is_ruled_on_by_the_host_before_the_call_is_made",
            "test_dsh_driver.py::test_the_hosts_tools_reach_dsh_as_a_service_and_keep_their_names_in_events",
            "test_dsh_host_tools.py::test_a_call_whose_token_is_revoked_while_its_body_comes_in_is_refused",
            "test_dsh_profile.py::test_nothing_is_uploaded",
            "test_dsh_profile.py::test_the_environment_is_the_hosts_without_what_would_configure_dsh",
            "test_dsh_install.py::test_another_version_on_the_disk_is_not_used",
            "test_host_runtimes.py::test_whatever_keeps_dsh_from_working_the_commission_is_still_done",
            "test_host_dsh_wiring.py::test_a_search_allowed_before_its_call_is_refused_when_the_settings_forbid_it_since",
            "test_console_routes.py::test_the_runtime_page_reads_dsh_and_its_plugins_and_sets_the_preference",
            "test_console_routes.py::test_installing_dsh_runs_behind_the_request_and_the_status_says_how_it_went",
            "test_dsh_forward.py::test_the_real_model_and_key_replace_dshs_and_the_rest_is_kept",
        )
        for item in required:
            self.assertIn(item, workflow)

        dsh_gate = workflow.index("Exercise native dsh optional-runtime product acceptance")
        execution_gate = workflow.index("Exercise native Execution Plane product E2E")
        self.assertLess(dsh_gate, execution_gate)
        self.assertNotIn("continue-on-error", workflow[dsh_gate:execution_gate])

    def test_github_gate_executes_native_execution_product_e2e(self):
        workflow = (ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml").read_text(
            encoding="utf-8-sig"
        )
        required = (
            "Exercise native Execution Plane product E2E",
            "test_runtime_tools_fs.py::test_read_numbers_lines_and_reports_the_end",
            "test_runtime_shell_jobs.py::test_a_cancelled_spawn_does_not_leave_a_process_behind",
            "test_builtin_provider.py::test_cancelling_a_desktop_call_sets_its_stop_event_and_waits_for_the_worker",
            "test_runtime_shell_jobs.py::test_output_saved_before_a_restart_survives_the_next_long_command",
            "test_host_task_agents.py::test_a_blocked_commission_is_taken_up_again_where_it_stopped",
            "test_host_task_agents.py::test_web_search_runs_the_search_plugin",
            "test_host_gateway.py::test_each_mcp_server_is_asked_about_once_when_always_is_chosen",
            "test_host_gateway.py::test_registered_browser_is_discovered_called_and_released_through_the_gateway",
            "test_host_gateway.py::test_revoking_browser_approval_while_queued_keeps_the_next_provider_call_from_running",
            "test_builtin_browser_tools.py::test_the_browser_is_started_by_the_first_call_and_kept_for_the_next",
            "test_builtin_browser_tools.py::test_a_click_that_was_not_carried_out_is_not_said_to_have_succeeded",
            "from nekoclaw.builtin.browser import launcher",
            "launcher.find_browsers()",
            "BLOCK_REAL_BROWSER_ACCEPTANCE",
            "NEKO_TEST_REAL_BROWSER=1",
            "test_builtin_browser_real.py::test_a_form_is_filled_in_sent_and_its_result_read",
            "test_builtin_browser_real.py::test_history_tabs_keys_and_an_embedded_document",
        )
        for item in required:
            self.assertIn(item, workflow)

        self.assertNotIn("test_stopping_a_commission_stops_a_builtin_call_under_way", workflow)

        product_e2e = workflow.index("Exercise native Execution Plane product E2E")
        effect_candidate = workflow.index("Verify managed effect-state patch in product worktree")
        self.assertLess(product_e2e, effect_candidate)
        self.assertNotIn("continue-on-error", workflow[product_e2e:effect_candidate])

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
            "test_native_realtime_loud_ingress_publishes_activity_before_worker",
            "test_teardown_outliving_its_connection_does_not_touch_the_replacement",
            "test_retired_teardown_does_not_shut_the_replacements_arbiter_down",
            "test_retired_receive_loop_cannot_condemn_or_report_the_replacement",
            "test_late_failure_from_a_retired_generation_cannot_recover_the_successor",
            "test_neither_hook_runs_once_the_host_is_on_a_new_turn",
            "test_the_rotation_stands_down_when_a_turn_starts_during_response_done",
            "test_old_runtime_audio_waiting_for_frame_lock_is_not_sent",
            "test_runtime_handoff_drains_status_blocked_inside_websocket_send",
            "test_a_superseded_flow_cannot_release_the_newer_starts_slot",
            "test_the_automatic_restart_stands_down_at_every_resumption_point",
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
            "$NekoPython -m pytest -q $CompanionOwnershipTargets",
            "$CompanionOwnershipFiles",
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

    def test_execution_effect_state_is_managed_correctness_exception(self):
        managed_patch = ROOT / "patches" / "0011-execution-outbox-effect-state.patch"
        self.assertTrue(managed_patch.is_file())
        self.assertFalse(
            (ROOT / "candidates" / "execution_plane" / "outbox_effect_state.patch").exists()
        )

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review_id = "patch:0011-execution-outbox-effect-state.patch"
        self.assertIn(review_id, by_id)
        self.assertEqual(by_id[review_id]["status"], "approved")

        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        managed = {item["file"] for item in series["patches"]}
        self.assertIn("0011-execution-outbox-effect-state.patch", managed)

        exceptions = json.loads(
            (
                ROOT
                / "governance"
                / "core_patch_correctness_exceptions_v1.json"
            ).read_text(encoding="utf-8-sig")
        )
        exception_files = {item["file"] for item in exceptions["exceptions"]}
        self.assertIn("0011-execution-outbox-effect-state.patch", exception_files)

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "Prepare managed N.E.K.O product worktree",
            "git -C _neko_product apply --check",
            "verify_execution_effect_state_candidate.py --neko-root _neko_product",
            "Verify managed effect-state patch in product worktree",
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

    def test_github_gate_requires_product_main_current_at_agent_commit_boundary(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        required = (
            "Require product main current at agent commit boundary",
            "github.event_name == 'push'",
            "refs/heads/agent/",
            "refs/heads/private/neko-overlay-v1:refs/remotes/origin/private/neko-overlay-v1",
            "AGENT_COMMIT_TIME",
            'git rev-list --first-parent -1 --before="$AGENT_COMMIT_TIME"',
            'git merge-base --is-ancestor "$PRODUCT_MAIN_REQUIRED" HEAD',
            "BLOCK_AGENT_STALE_BASE",
            "PASS_RACE: product main advanced after agent HEAD",
            "next agent push must resync",
        )
        for item in required:
            self.assertIn(item, workflow)
        freshness = workflow.index("Require product main current at agent commit boundary")
        reuse = workflow.index("Reuse-first hard gate")
        self.assertLess(freshness, reuse)


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
            "test_native_realtime_loud_ingress_publishes_activity_before_worker",
            "test_teardown_outliving_its_connection_does_not_touch_the_replacement",
            "test_retired_teardown_does_not_shut_the_replacements_arbiter_down",
            "test_retired_receive_loop_cannot_condemn_or_report_the_replacement",
            "test_late_failure_from_a_retired_generation_cannot_recover_the_successor",
            "test_neither_hook_runs_once_the_host_is_on_a_new_turn",
            "test_the_rotation_stands_down_when_a_turn_starts_during_response_done",
            "test_old_runtime_audio_waiting_for_frame_lock_is_not_sent",
            "test_runtime_handoff_drains_status_blocked_inside_websocket_send",
            "test_a_superseded_flow_cannot_release_the_newer_starts_slot",
            "test_the_automatic_restart_stands_down_at_every_resumption_point",
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
        prepare_gate = workflow.index("Prepare managed N.E.K.O product worktree")
        product_gate = workflow.index(
            "Exercise patched companion switch/audio ownership regression"
        )
        clean_candidate_gate = workflow.index("Verify pinned native Execution Plane seams")
        self.assertLess(prepare_gate, product_gate)
        self.assertLess(product_gate, clean_candidate_gate)
        self.assertIn('PRODUCT_WORKTREE="$GITHUB_WORKSPACE/_neko_product"', workflow[product_gate:clean_candidate_gate])
        self.assertIn('git -C _neko_product apply -- "$PATCH_PATH"', workflow[prepare_gate:product_gate])
        self.assertNotIn(
            'git -C _neko_upstream apply -- "$PATCH_PATH"',
            workflow[prepare_gate:clean_candidate_gate],
            "managed product patches must stay in the product worktree",
        )

    def test_xiaoyu_owned_console_launches_remain_hidden(self):
        shortcuts = (ROOT / "tools" / "install_xiaoyu_shortcuts.ps1").read_text(
            encoding="utf-8-sig"
        )
        oneclick = (ROOT / "tools" / "start_xiaoyu_oneclick.ps1").read_text(
            encoding="utf-8-sig"
        )
        startup = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn(
            '-ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"',
            shortcuts,
        )

        backend_start = oneclick.index(
            'Start-Process -FilePath "powershell.exe" -ArgumentList @('
        )
        backend_ready = oneclick.index(
            '$deadline = (Get-Date).AddSeconds(180)',
            backend_start,
        )
        backend_segment = oneclick[backend_start:backend_ready]
        self.assertIn(") -WindowStyle Hidden -PassThru", backend_segment)
        self.assertNotIn("WindowStyle Normal", backend_segment)
        self.assertNotIn("WindowStyle Minimized", backend_segment)

        restore_args = startup.index('$RestoreArgs = @(')
        launcher_start = startup.index(
            'Write-Host "== Start original N.E.K.O with XiaoYu private state =="',
            restore_args,
        )
        restore_segment = startup[restore_args:launcher_start]
        self.assertIn(
            'Start-Process -FilePath $Python -ArgumentList $RestoreArgs -WindowStyle Hidden | Out-Null',
            restore_segment,
        )

    def test_github_gate_runs_native_embedding_asset_reuse_regression(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        overlay_start = workflow.index("- name: Overlay contract tests")
        compile_start = workflow.index("- name: Compile overlay control plane")
        overlay_segment = workflow[overlay_start:compile_start]
        self.assertIn(
            "private_overlay.tests.test_native_embedding_assets",
            overlay_segment,
        )

    def test_github_gate_runs_bootstrap_runtime_helper_regressions(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        overlay_start = workflow.index("- name: Overlay contract tests")
        compile_start = workflow.index("- name: Compile overlay control plane")
        overlay_segment = workflow[overlay_start:compile_start]
        self.assertIn('python -m pip install -q "httpx[socks]>=0.28.1"', overlay_segment)
        for module in (
            "private_overlay.tests.test_ensure_private_plugin",
            "private_overlay.tests.test_ensure_xiaoyu_activity_preferences",
            "private_overlay.tests.test_reconcile_neko_plugin_runtime",
            "private_overlay.tests.test_xiaoyu_interaction_policy_plugin",
        ):
            self.assertIn(module, overlay_segment)

    def test_github_gate_replays_patched_startup_regression(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        product_gate = workflow.index(
            "Exercise patched companion switch/audio ownership regression"
        )
        clean_candidate_gate = workflow.index("Verify pinned native Execution Plane seams")
        product_segment = workflow[product_gate:clean_candidate_gate]
        required = (
            "test_xiaoyu_startup_performance.py",
            "test_token_tracker_install_hooks_idempotent.py",
            "test_cloudsave_lifecycle_flow.py",
            "test_live2d_model_config_write_locking.py",
        )
        for item in required:
            self.assertIn(item, product_segment)
        self.assertIn(
            'uv run --project "$GITHUB_WORKSPACE/_neko_upstream" --locked --group dev',
            product_segment,
        )
        self.assertIn('PYTHONPATH="$PRODUCT_WORKTREE"', product_segment)

    def test_managed_execution_regression_is_paired_with_clean_native_baseline(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "Capture clean native Execution Plane regression baseline",
            "execution-native-tests.txt",
            "execution-native-baseline.xml",
            "execution-native-managed.xml",
            "BLOCK_EXECUTION_REGRESSION_TESTSET_DRIFT",
            "BLOCK_EXECUTION_MANAGED_REGRESSION",
            "managed_failures - baseline_failures",
        ):
            self.assertIn(required, workflow)
        baseline = workflow.index(
            "Capture clean native Execution Plane regression baseline"
        )
        candidate = workflow.index("Verify managed effect-state patch in product worktree")
        patched = workflow.index("Regress managed native Execution Plane")
        self.assertLess(baseline, candidate)
        self.assertLess(candidate, patched)
        self.assertIn("cd _neko_upstream", workflow[baseline:candidate])
        self.assertIn("cd _neko_product", workflow[patched:workflow.index("Exercise report-wait host-restart candidate")])
        self.assertEqual(
            workflow.count('mapfile -t EXECUTION_NATIVE_TESTS < "$RUNNER_TEMP/execution-native-tests.txt"'),
            2,
        )

    def test_native_delivery_receipt_is_managed_correctness_exception(self):
        managed_patch = ROOT / "patches" / "0012-native-delivery-receipt.patch"
        self.assertTrue(managed_patch.is_file())
        self.assertFalse(
            (
                ROOT
                / "candidates"
                / "execution_plane"
                / "native_delivery_receipt.patch"
            ).exists()
        )

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review_id = "patch:0012-native-delivery-receipt.patch"
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
        self.assertIn("0012-native-delivery-receipt.patch", managed)

        exceptions = json.loads(
            (
                ROOT
                / "governance"
                / "core_patch_correctness_exceptions_v1.json"
            ).read_text(encoding="utf-8-sig")
        )
        exception_files = {item["file"] for item in exceptions["exceptions"]}
        self.assertIn("0012-native-delivery-receipt.patch", exception_files)

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for required in (
            "Prepare managed N.E.K.O product worktree",
            "verify_native_delivery_receipt_candidate.py --neko-root _neko_product",
            "Verify managed native delivery receipt in product worktree",
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
        self.assertIn("run_companion_performance.ps1", script)
        self.assertIn("$CompanionPerformance", script)
        self.assertTrue((ROOT / "release" / "COMPANION_PERFORMANCE_BUDGETS.json").is_file())


    def test_github_gate_runs_bounded_companion_micro_soak(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("soak_rounds:", workflow)
        self.assertIn('default: "12"', workflow)
        self.assertIn("SOAK_ROUNDS=3", workflow)
        self.assertIn(
            "private_overlay.tests.test_companion_performance_budget", workflow
        )
        self.assertIn(
            "private_overlay.tests.test_run_companion_performance_gate", workflow
        )
        self.assertGreaterEqual(
            workflow.count('for round in $(seq 1 "$SOAK_ROUNDS")'),
            2,
        )
        self.assertGreaterEqual(
            workflow.count('"$SOAK_ROUNDS" -gt 50'),
            2,
        )
        for required in (
            "Companion Runtime soak round",
            "QQ Runtime soak round",
            "test_character_switch_queue.py",
            "test_character_runtime_voice_identity.py",
            "test_model_switch_keeps_live_budget.py",
            "test_native_realtime_loud_ingress_publishes_activity_before_worker",
            "test_teardown_outliving_its_connection_does_not_touch_the_replacement",
            "test_retired_receive_loop_cannot_condemn_or_report_the_replacement",
            "test_the_rotation_stands_down_when_a_turn_starts_during_response_done",
            "test_old_runtime_audio_waiting_for_frame_lock_is_not_sent",
            "test_xiaoyu_plugin_visible_final_admission.py",
            "test_qq_connection_status_refresh.py",
            "test_qq_runtime_transition_lock.py",
            "test_qq_catchup.py",
            "test_live_inbound_idempotency_faults.py",
        ):
            self.assertIn(required, workflow)

        companion_soak = workflow[
            workflow.index("Companion Runtime soak round"):
            workflow.index("Verify pinned native Execution Plane seams")
        ]
        for required in (
            "test_retired_teardown_does_not_shut_the_replacements_arbiter_down",
            "test_repeated_close_runs_the_teardown_once",
            "test_close_inside_the_connect_window_does_not_latch_the_new_socket_shut",
            "test_audio_processor_is_not_released_after_a_replacement_adopts_it",
            "test_retired_receive_loop_drops_buffered_frame_before_dispatch",
            "test_retired_handler_exception_cannot_close_the_replacement",
            "test_late_failure_from_a_retired_generation_cannot_recover_the_successor",
            "test_neither_hook_runs_once_the_host_is_on_a_new_turn",
            "test_runtime_handoff_drains_status_blocked_inside_websocket_send",
            "test_old_ready_waiting_for_cache_lock_cannot_publish_to_new_runtime",
            "test_clear_pipeline_waiting_for_lock_preserves_replacement_cache",
            "test_fallback_cannot_create_third_worker",
            "test_retirement_during_audio_frame_keeps_header_and_payload_together",
            "test_fallback_timeout_reserves_recovery_for_only_its_session",
            "test_a_superseded_flow_cannot_release_the_newer_starts_slot",
            "test_every_point_a_flow_resumes_from_an_await_stands_down",
            "test_standing_down_stops_committed_capture_before_it_unwinds",
            "test_the_mic_failure_cleanup_stands_down_before_ending_the_session",
            "test_the_automatic_restart_stands_down_at_every_resumption_point",
            "test_qwen_voice_bundle.py",
            "test_character_card_manager_renders_and_opens_cards_when_model_scan_never_resolves",
            "test_character_card_manager_saved_new_field_survives_immediate_reopen_with_stale_reload",
            "test_character_card_manager_cancels_stale_live2d_when_switching_to_3d_preview",
            "test_character_card_manager_panel_close_recreates_live2d_preview_context",
            "test_model_binding_waits_for_renderer_and_rejects_a_newer_unbind_race",
            "test_cloud_choice_retries_the_same_revision_after_a_renderer_failure",
            "test_selection_changes_during_pending_requests_use_the_current_model_next",
            "chat_avatar_integration.test.cjs",
            "voice_preview_races.cjs",
            "test_windows_notification_block_preserves_activity_but_closes_propensity",
            "test_nonblocking_windows_notification_state_keeps_native_propensity",
            "test_maybe_deliver_is_leisure_only",
            "test_maybe_deliver_allows_explicit_leisure_states",
            "test_maybe_deliver_aborts_when_user_engages_during_phase2_transition",
            "test_maybe_deliver_pass_when_user_takes_over_before_finish",
            "test_voice_session_still_gated_by_lock_and_suspend",
            "test_voice_session_ignores_display_off_and_return_quiet",
            "test_voice_gate_sees_arbiter_busyness_not_just_the_responding_flag",
            "test_voice_callback_defers_when_microphone_activity_arrived_first",
            "test_user_input_between_claim_and_lock_is_detected",
            "test_user_input_during_agent_delivery_sets_preempted",
            "test_work_break_pending_armed_at_threshold",
            "test_work_break_pending_persists_until_cleared",
            "test_break_acc_extends_through_transitioning_when_already_started",
            "test_break_acc_resets_on_any_other_state",
            "test_long_gap_clears_work_break_pending_too",
            "test_anti_slack_pending_fires_on_focus_to_leisure",
            "test_anti_slack_skipped_when_focus_too_short",
            "test_anti_slack_skipped_for_idle_target",
            "test_anti_slack_respects_cooldown",
            "test_anti_slack_pending_cleared_on_return_to_focus",
            "test_focused_video_fires_after_sustained_dwell",
            "test_focused_video_dwell_resets_on_window_switch",
            "test_repeat_suppressed_break_reminder_consumes_pending_source",
            "test_all_break_reminder_branches_consume_repeat_suppression",
            "test_break_reminder_respects_round_ownership",
            "test_break_reminder_stops_when_round_retires_during_generation",
            "test_work_break_theater_prompt_invites_from_the_frozen_public_opening",
        ):
            self.assertIn(required, companion_soak)

        qq_soak = workflow[
            workflow.index("QQ Runtime soak round"):
            workflow.index("Probe plugin-visible delivery-floor native gap")
        ]
        for required in (
            "test_qq_outbound_guard.py",
            "test_group_send_safety.py",
            "test_proactive_budget_integration.py",
            "test_qq_proactive_initiative.py",
            "test_qq_auto_reply_forward_client.py",
            "test_qq_buffer_no_append_after_delivery.py",
            "test_qq_buffer_send_time_floor.py",
            "test_qq_reply_buffer_switch.py",
            "test_live_inbound_idempotency_faults.py",
        ):
            self.assertIn(required, qq_soak)

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review = by_id["governance:companion-runtime-micro-soak-v1"]
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["decision"], "reuse_native")
        self.assertTrue(
            (
                ROOT
                / "evals"
                / "evidence"
                / "2026-11-23-companion-runtime-soak-reuse.json"
            ).is_file()
        )

    def test_native_plugin_crash_recovery_remains_probe_only(self):
        probe = (
            ROOT
            / "candidates"
            / "plugin_lifecycle"
            / "probe_native_crash_recovery_gap.py"
        )
        evidence_path = (
            ROOT
            / "evals"
            / "evidence"
            / "2026-11-23-native-plugin-crash-recovery-gap.json"
        )
        self.assertTrue(probe.is_file())
        self.assertTrue(evidence_path.is_file())

        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
        self.assertTrue(evidence["product_policy"]["promotion_prohibited"])
        for forbidden in (
            "new_daemon",
            "new_watchdog",
            "new_state_store",
            "new_router",
            "new_managed_patch",
        ):
            self.assertFalse(evidence["product_policy"][forbidden])
        self.assertEqual(
            evidence["product_policy"]["current_recovery"],
            "explicit/startup native reconcile only",
        )

        reviews = json.loads(
            (ROOT / "governance" / "reuse_reviews.json").read_text(
                encoding="utf-8-sig"
            )
        )
        by_id = {item["id"]: item for item in reviews["reviews"]}
        review = by_id["runtime:plugin-crash-recovery"]
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["decision"], "reuse_native")
        self.assertEqual(
            review["machine_probe"],
            "candidates/plugin_lifecycle/probe_native_crash_recovery_gap.py",
        )
        self.assertTrue(review["retirement_condition"])
        self.assertTrue(
            all(
                layer["status"] == "checked"
                for layer in review["search_layers"].values()
            )
        )

        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        exception_policy = json.loads(
            (
                ROOT
                / "governance"
                / "core_patch_correctness_exceptions_v1.json"
            ).read_text(encoding="utf-8-sig")
        )
        exception_files = {item["file"] for item in exception_policy["exceptions"]}
        self.assertFalse(
            any(
                "crash" in item["file"].lower()
                or "watchdog" in item["file"].lower()
                for item in series["patches"]
            )
        )
        self.assertFalse(
            any(
                "crash" in filename.lower() or "watchdog" in filename.lower()
                for filename in exception_files
            )
        )

        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("Probe native plugin crash-recovery gap", workflow)
        self.assertIn(
            "private_overlay/candidates/plugin_lifecycle/"
            "probe_native_crash_recovery_gap.py --neko-root _neko_upstream",
            workflow,
        )

    def test_fac795_execution_migration_probe_is_agent_scoped_and_pinned(self):
        workflow = (
            ROOT.parent / ".github" / "workflows" / "private-overlay-gate.yml"
        ).read_text(encoding="utf-8-sig")
        for marker in (
            "Checkout fixed fac795 NekoPower execution migration candidate",
            "Probe fixed fac795 NekoPower execution migration boundary",
            "refs/heads/agent/execution-continuity-v2",
            "fac795091e33cd92a6604d14ac242510944badac",
            "probe_neko_fac795_execution_migration.py",
            "_neko_execution_migration_candidate",
        ):
            self.assertIn(marker, workflow)

        probe = (
            ROOT
            / "candidates"
            / "execution_plane"
            / "probe_neko_fac795_execution_migration.py"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("promotion_forbidden", probe)
        self.assertIn("MIGRATION_BLOCKED_RESIDUALS", probe)
        self.assertNotIn("NEKO_UPSTREAM.lock.json\").write", probe)

if __name__ == "__main__":
    unittest.main()
