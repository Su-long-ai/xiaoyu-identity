from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from check_execution_plane import _delivery_receipt_probe, _source_contract_results


class ExecutionPlaneAcceptanceToolTests(unittest.TestCase):
    def _write(self, root: Path, relpath: str, content: str) -> None:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_source_contracts_require_native_authority_seams(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "nekoclaw/host/ledger.py",
                """
async def transition(
    outbox: Iterable[tuple[str, dict[str, Any]]],
):
    self._outbox_insert(
""",
            )
            self._write(
                root,
                "nekoclaw/host/reports.py",
                """
def task_result_report(
async def transition(
    await self._ledger.transition(
""",
            )
            self._write(
                root,
                "nekoclaw/host/task_brain.py",
                """
def still_wanted() -> bool:
    self._permissions.grant_active(
async def abort(
    await self._reporter.transition(
""",
            )
            self._write(
                root,
                "nekoclaw/host/gateway.py",
                """
self._permissions.grant_active(
still_wanted=lambda:
audited_run_entry(
""",
            )
            self._write(
                root,
                "nekoclaw/host/outbox.py",
                """
class OutboxSender:
outbox_pending(
outbox_mark_sent(
outbox_mark_failed(
""",
            )
            self._write(root, "nekoclaw/host/runtimes.py", "builtin\ndsh\n")

            results = _source_contract_results(root)
            self.assertTrue(results)
            self.assertTrue(all(item["ok"] for item in results), results)

    def test_transport_acceptance_is_not_delivery_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "app/agent_server/nekoclaw_mount.py",
                """
async def send_report(item):
    return await _send_main_event({"event_type": "task_result"})
""",
            )
            self._write(
                root,
                "main_logic/agent_event_bus.py",
                """
async def emit_to_main(event):
    self.push.send(event)
    return True
""",
            )
            self._write(root, "app/main_server/character_runtime.py", "task_result\n")
            self._write(root, "app/agent_server/api_runtime.py", "turn_check_request\n")

            result = _delivery_receipt_probe(root)
            self.assertFalse(result["ok"])
            self.assertFalse(result["stable_report_identity"])
            self.assertFalse(result["cross_process_delivery_ack"])

    def test_stable_identity_plus_cross_process_ack_is_recognized(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(
                root,
                "app/agent_server/nekoclaw_mount.py",
                """
async def send_report(item):
    delivery_id = item.id
    return await _send_main_event({"delivery_id": delivery_id})
""",
            )
            self._write(
                root,
                "main_logic/agent_event_bus.py",
                """
async def emit_to_main(event):
    delivery_ack = event.get("delivery_ack")
""",
            )
            self._write(
                root,
                "app/main_server/character_runtime.py",
                """
async def handle(event):
    delivery_ack = event.get("delivery_ack")
""",
            )
            self._write(
                root,
                "app/agent_server/api_runtime.py",
                """
async def on_event(event):
    if event.get("event_type") == "delivery_ack":
        return
""",
            )

            result = _delivery_receipt_probe(root)
            self.assertTrue(result["ok"])
            self.assertTrue(result["stable_report_identity"])
            self.assertTrue(result["cross_process_delivery_ack"])


if __name__ == "__main__":
    unittest.main()
