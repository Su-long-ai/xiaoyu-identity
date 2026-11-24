from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "NEKO_UPSTREAM.lock.json"
MATRIX = ROOT / "evals" / "execution_plane_acceptance_v1.json"

CORE_TESTS = (
    "tests/unit/nekoclaw/test_host_ledger.py",
    "tests/unit/nekoclaw/test_host_delivery.py",
    "tests/unit/nekoclaw/test_host_robustness.py",
    "tests/unit/nekoclaw/test_host_plugin_runs.py",
    "tests/unit/nekoclaw/test_host_gateway.py",
    "tests/unit/nekoclaw/test_execution_audit.py",
    "tests/unit/nekoclaw/test_host_preferences_permissions.py",
    "tests/unit/nekoclaw/test_host_runtimes.py",
    "tests/unit/nekoclaw/test_dsh_acp.py",
    "tests/unit/nekoclaw/test_dsh_driver.py",
    "tests/unit/nekoclaw/test_dsh_grant_wire.py",
    "tests/unit/nekoclaw/test_dsh_host_tools.py",
)

FULL_TESTS = CORE_TESTS + (
    "tests/unit/nekoclaw/test_agent_wiring.py",
    "tests/unit/nekoclaw/test_host_task_brain.py",
    "tests/unit/nekoclaw/test_host_task_agents.py",
    "tests/unit/nekoclaw/test_runtime_process.py",
    "tests/unit/nekoclaw/test_runtime_gateway_tools.py",
    "tests/unit/nekoclaw/test_runtime_tools_fs.py",
)

SOURCE_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "atomic_terminal_result_outbox": (
        "nekoclaw/host/ledger.py",
        (
            "async def transition(",
            "outbox: Iterable[tuple[str, dict[str, Any]]]",
            "self._outbox_insert(",
        ),
    ),
    "reporter_uses_atomic_transition": (
        "nekoclaw/host/reports.py",
        (
            "def task_result_report(",
            "async def transition(",
            "await self._ledger.transition(",
        ),
    ),
    "direct_plugin_permission_revocation": (
        "nekoclaw/host/task_brain.py",
        (
            "def still_wanted() -> bool:",
            "self._permissions.grant_active(",
            "async def abort(",
            "await self._reporter.transition(",
        ),
    ),
    "gateway_permission_revocation": (
        "nekoclaw/host/gateway.py",
        (
            "self._permissions.grant_active(",
            "still_wanted=lambda:",
            "audited_run_entry(",
        ),
    ),
    "durable_result_outbox": (
        "nekoclaw/host/outbox.py",
        (
            "class OutboxSender:",
            "outbox_pending(",
            "outbox_mark_sent(",
            "outbox_mark_failed(",
        ),
    ),
    "dsh_optional_runtime_seam": (
        "nekoclaw/host/runtimes.py",
        (
            "dsh",
            "builtin",
        ),
    ),
    "agent_master_native_preflight_switches": (
        "app/agent_server/api_runtime.py",
        (
            "def _check_agent_api_gate()",
            "async def _console_switches()",
            '"gate": _agent_server_facade._check_agent_api_gate()',
            '"capabilities": dict(Modules.capability_cache or {})',
        ),
    ),
    "agent_master_native_runtime_permissions": (
        "app/agent_server/api_console.py",
        (
            '@router.get("/switches")',
            '@router.get("/runtime")',
            '@router.get("/permissions")',
            '@router.post("/runtime/dsh/install")',
        ),
    ),
    "agent_master_restart_intent_reuses_native_enable_paths": (
        "app/agent_runtime_intent.py",
        (
            "INTENT_KEYS:",
            "def set_intent(",
            "def load_intent(",
            "set_agent_enabled",
            "set_agent_flags",
        ),
    ),
    "agent_master_power_routes_through_main": (
        "plugin/server/routes/console_proxy.py",
        (
            '@router.post("/switch"',
            '"command": "set_agent_enabled"',
            'f"{_main_base()}/api/agent/command"',
            '"switch_failed"',
        ),
    ),
    "agent_master_failure_reason_is_user_visible": (
        "frontend/plugin-manager/src/components/power/home/PowerBar.vue",
        (
            "await setPower(enabled)",
            "flipError.value = describeConsoleError(failure, t, te)",
            "now.gate?.ready !== false",
            "now.gate.reasons",
        ),
    ),
}

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _git(neko_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=neko_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()

def _host_relpath(relpath: str, host_package: str) -> str:
    if host_package not in {"nekoclaw", "nekopower"}:
        raise ValueError(f"unsupported host package: {host_package}")
    return relpath.replace("nekoclaw", host_package)

def _source_contract_results(
    neko_root: Path, host_package: str = "nekoclaw"
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, (relpath, needles) in SOURCE_CONTRACTS.items():
        resolved_relpath = _host_relpath(relpath, host_package)
        path = neko_root / resolved_relpath
        if not path.is_file():
            results.append(
                {
                    "name": name,
                    "path": resolved_relpath,
                    "ok": False,
                    "missing": ["<file>"],
                }
            )
            continue
        text = _read(path)
        missing = [needle for needle in needles if needle not in text]
        results.append(
            {
                "name": name,
                "path": resolved_relpath,
                "ok": not missing,
                "missing": missing,
            }
        )
    return results

def _acceptance_matrix_summary() -> dict[str, Any]:
    data = json.loads(MATRIX.read_text(encoding="utf-8-sig"))
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    cases = list(data.get("cases") or [])
    ids = [str(item.get("id") or "") for item in cases]
    duplicate_ids = sorted({case_id for case_id in ids if case_id and ids.count(case_id) > 1})
    malformed = [
        str(item.get("id") or "<missing-id>")
        for item in cases
        if item.get("status") not in {"native_covered", "acceptance_gap"}
    ]
    blockers = [
        {
            "id": str(item.get("id") or ""),
            "domain": str(item.get("domain") or ""),
            "reason": str(item.get("reason") or ""),
        }
        for item in cases
        if item.get("status") == "acceptance_gap" and item.get("severity") == "blocker"
    ]
    pinned = str(lock.get("tested_commit") or "")
    matrix_pin = str(data.get("pinned_commit") or "")
    ok = (
        bool(cases)
        and not duplicate_ids
        and not malformed
        and bool(pinned)
        and matrix_pin == pinned
    )
    return {
        "ok": ok,
        "case_count": len(cases),
        "native_covered": sum(item.get("status") == "native_covered" for item in cases),
        "acceptance_gap_count": sum(item.get("status") == "acceptance_gap" for item in cases),
        "blockers": blockers,
        "duplicate_ids": duplicate_ids,
        "malformed": malformed,
        "pinned_commit": matrix_pin,
        "lock_commit": pinned,
    }


def _delivery_receipt_probe(
    neko_root: Path, host_package: str = "nekoclaw"
) -> dict[str, Any]:
    if host_package not in {"nekoclaw", "nekopower"}:
        raise ValueError(f"unsupported host package: {host_package}")
    mount = neko_root / f"app/agent_server/{host_package}_mount.py"
    bus = neko_root / "main_logic/agent_event_bus.py"
    main = neko_root / "app/main_server/character_runtime.py"
    runtime = neko_root / "app/agent_server/api_runtime.py"
    texts = {
        "mount": _read(mount) if mount.is_file() else "",
        "bus": _read(bus) if bus.is_file() else "",
        "main": _read(main) if main.is_file() else "",
        "runtime": _read(runtime) if runtime.is_file() else "",
    }
    stable_identity = (
        ("item.id" in texts["mount"] or "delivery_id" in texts["mount"])
        and ("delivery_id" in texts["mount"] or "report_id" in texts["mount"])
    )
    legacy_ack_protocol = (
        ("delivery_ack" in texts["bus"] or "report_ack" in texts["bus"])
        and ("delivery_ack" in texts["runtime"] or "report_ack" in texts["runtime"])
        and ("delivery_ack" in texts["main"] or "report_ack" in texts["main"])
    )
    barrier_ack = f"{host_package}_delivery_barrier_ack"
    native_barrier_protocol = (
        barrier_ack in texts["bus"]
        and barrier_ack in texts["runtime"]
        and barrier_ack in texts["main"]
        and "DELIVERY_ACK_FUTURE_KEY" in texts["main"]
    )
    ack_protocol = legacy_ack_protocol or native_barrier_protocol
    return {
        "ok": bool(stable_identity and ack_protocol),
        "stable_report_identity": stable_identity,
        "cross_process_delivery_ack": ack_protocol,
        "note": (
            "PASS only when the durable host outbox has a stable report identity and "
            "main-server delivery acknowledgement is wired back to agent_server. "
            "A ZeroMQ PUSH.send success alone is transport acceptance, not effect receipt."
        ),
    }

def _resolve_python(neko_root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    candidates = (
        neko_root / ".venv" / "Scripts" / "python.exe",
        neko_root / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable

def _run_tests(
    neko_root: Path, python: str, full: bool, host_package: str = "nekoclaw"
) -> dict[str, Any]:
    raw_selection = FULL_TESTS if full else CORE_TESTS
    selection = tuple(_host_relpath(item, host_package) for item in raw_selection)
    cmd = [python, "-m", "pytest", "-q", *selection]
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=neko_root,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "command": cmd,
        "stdout_tail": proc.stdout[-12000:],
        "stderr_tail": proc.stderr[-12000:],
        "selection": list(selection),
    }

def build_report(
    neko_root: Path,
    *,
    python: str | None = None,
    run_pytest: bool = True,
    full: bool = False,
    strict_delivery_receipt: bool = False,
    strict_product_gaps: bool = False,
    host_package: str = "nekoclaw",
) -> tuple[dict[str, Any], bool]:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    pinned = str(lock.get("tested_commit") or "")
    head = _git(neko_root, "rev-parse", "HEAD")
    source_contracts = _source_contract_results(neko_root, host_package)
    delivery_receipt = _delivery_receipt_probe(neko_root, host_package)
    acceptance_matrix = _acceptance_matrix_summary()
    tests: dict[str, Any] | None = None
    if run_pytest:
        tests = _run_tests(
            neko_root, _resolve_python(neko_root, python), full, host_package
        )
    ok = (
        bool(pinned)
        and head == pinned
        and all(item["ok"] for item in source_contracts)
        and (tests is None or bool(tests["ok"]))
        and bool(acceptance_matrix["ok"])
        and (not strict_delivery_receipt or bool(delivery_receipt["ok"]))
        and (not strict_product_gaps or not acceptance_matrix["blockers"])
    )
    report = {
        "schema_version": 1,
        "kind": "xiaoyu_execution_plane_native_acceptance",
        "neko_root": str(neko_root),
        "pinned_commit": pinned,
        "observed_head": head,
        "head_matches_pin": head == pinned,
        "working_tree_status": _git(neko_root, "status", "--porcelain"),
        "host_package": host_package,
        "source_contracts": source_contracts,
        "delivery_receipt": delivery_receipt,
        "acceptance_matrix": acceptance_matrix,
        "pytest": tests,
        "strict_delivery_receipt": strict_delivery_receipt,
        "strict_product_gaps": strict_product_gaps,
        "ok": ok,
    }
    return report, ok

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise XiaoYu's Execution Plane against the pinned native N.E.K.O runtime. "
            "This tool reuses native tests and source contracts; it does not create a second runtime."
        )
    )
    parser.add_argument("--neko-root", required=True, type=Path)
    parser.add_argument("--python")
    parser.add_argument("--no-pytest", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--strict-delivery-receipt", action="store_true")
    parser.add_argument("--strict-product-gaps", action="store_true")
    parser.add_argument(
        "--host-package",
        choices=("nekoclaw", "nekopower"),
        default="nekoclaw",
        help="Native N.E.K.O execution authority package to validate.",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    neko_root = args.neko_root.resolve()
    report, ok = build_report(
        neko_root,
        python=args.python,
        run_pytest=not args.no_pytest,
        full=args.full,
        strict_delivery_receipt=args.strict_delivery_receipt,
        strict_product_gaps=args.strict_product_gaps,
        host_package=args.host_package,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
