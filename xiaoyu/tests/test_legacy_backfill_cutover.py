from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.backfill import (
    LegacyBackfillOrderConflict,
    LegacyShadowBackfill,
)
from xiaoyu.persistence.repositories.events import LegacyEventShadowWriter
from xiaoyu.release.migration import (
    AuthorityCutoverEvidence,
    AuthorityCutoverGate,
    MigrationRollbackPolicy,
)


class LegacyShadowBackfillTests(unittest.TestCase):
    def _db(self, path: Path) -> Database:
        db = Database(path)
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS events(
                       event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       at TEXT NOT NULL,kind TEXT NOT NULL,actor TEXT NOT NULL,
                       content TEXT NOT NULL,extra TEXT NOT NULL DEFAULT '{}'
                   )"""
            )
        apply_migrations(db)
        return db

    def _legacy(self, db: Database, content: str) -> int:
        with db.transaction(immediate=True) as conn:
            cur = conn.execute(
                """INSERT INTO events(at,kind,actor,content,extra)
                   VALUES(?,?,?,?,?)""",
                (
                    "2026-11-18T00:00:00+00:00",
                    "conversation.user",
                    "user",
                    content,
                    json.dumps({"turn_id": "turn-" + content}),
                ),
            )
            return int(cur.lastrowid)

    def test_backfill_crash_after_commit_restarts_without_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "identity.sqlite3")
            self._legacy(db, "one")
            self._legacy(db, "two")
            backfill = LegacyShadowBackfill(db)
            backfill.start("fish-1")

            def crash(phase, event_id):
                if phase == "before_progress":
                    raise RuntimeError("synthetic crash after DB commit")

            with self.assertRaises(RuntimeError):
                backfill.run_batch("fish-1", limit=2, fault_hook=crash)

            # Progress sidecar is deliberately stale, but canonical writes committed.
            self.assertEqual(
                backfill.progress_store.load().last_processed_event_id, 0
            )
            report = backfill.run_batch("fish-1", limit=2)
            self.assertTrue(report.converged)
            self.assertTrue(report.source_order_ok)
            self.assertEqual(report.progress.state, "CAUGHT_UP")

            with db.transaction() as conn:
                count = conn.execute(
                    """SELECT COUNT(*) FROM canonical_events
                       WHERE identity_id='fish-1'
                         AND source_namespace='legacy'"""
                ).fetchone()[0]
            self.assertEqual(count, 2)

    def test_backfill_then_incremental_converges_in_source_order(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "identity.sqlite3")
            self._legacy(db, "one")
            self._legacy(db, "two")
            backfill = LegacyShadowBackfill(db)
            report = backfill.run_batch("fish-1", limit=20)
            self.assertTrue(report.converged)
            self.assertTrue(report.source_order_ok)

            with db.transaction(immediate=True) as conn:
                cur = conn.execute(
                    """INSERT INTO events(at,kind,actor,content,extra)
                       VALUES(?,?,?,?,?)""",
                    (
                        "2026-11-18T00:01:00+00:00",
                        "conversation.user",
                        "user",
                        "three",
                        "{}",
                    ),
                )
                LegacyEventShadowWriter().write(
                    conn,
                    "fish-1",
                    int(cur.lastrowid),
                    "2026-11-18T00:01:00+00:00",
                    "conversation.user",
                    "user",
                    "three",
                    {},
                )

            self.assertTrue(backfill.source_order_ok("fish-1"))
            backfill.require_cutover_ready("fish-1")

    def test_incremental_overtakes_backfill_and_blocks_cutover(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "identity.sqlite3")
            self._legacy(db, "one")
            self._legacy(db, "two")
            backfill = LegacyShadowBackfill(db)
            progress = backfill.start("fish-1")
            self.assertEqual(progress.snapshot_high_watermark, 2)

            with db.transaction(immediate=True) as conn:
                cur = conn.execute(
                    """INSERT INTO events(at,kind,actor,content,extra)
                       VALUES(?,?,?,?,?)""",
                    (
                        "2026-11-18T00:01:00+00:00",
                        "conversation.user",
                        "user",
                        "three",
                        "{}",
                    ),
                )
                LegacyEventShadowWriter().write(
                    conn,
                    "fish-1",
                    int(cur.lastrowid),
                    "2026-11-18T00:01:00+00:00",
                    "conversation.user",
                    "user",
                    "three",
                    {},
                )

            report = backfill.run_batch("fish-1", limit=20)
            self.assertTrue(report.converged)
            self.assertFalse(report.source_order_ok)
            with self.assertRaises(LegacyBackfillOrderConflict):
                backfill.require_cutover_ready("fish-1")


class AuthorityCutoverGateTests(unittest.TestCase):
    def test_all_required_evidence_is_needed_for_single_authority_switch(self):
        good = AuthorityCutoverEvidence(
            shadow_caught_up=True,
            rebuild_equal=True,
            unresolved_conflicts=0,
            erasure_generation_source=7,
            erasure_generation_shadow=7,
            source_order_ok=True,
            old_writer_fenced=True,
        )
        decision = AuthorityCutoverGate.evaluate(good)
        self.assertTrue(decision.ready)
        self.assertEqual(decision.blockers, ())
        self.assertEqual(
            decision.rollback_policy, MigrationRollbackPolicy.FORWARD_ONLY
        )

        blocked = AuthorityCutoverGate.evaluate(
            AuthorityCutoverEvidence(
                shadow_caught_up=False,
                rebuild_equal=False,
                unresolved_conflicts=2,
                erasure_generation_source=8,
                erasure_generation_shadow=7,
                source_order_ok=False,
                old_writer_fenced=False,
            )
        )
        self.assertFalse(blocked.ready)
        self.assertEqual(
            set(blocked.blockers),
            {
                "SHADOW_NOT_CAUGHT_UP",
                "REBUILD_MISMATCH",
                "UNRESOLVED_CONFLICTS",
                "ERASURE_GENERATION_MISMATCH",
                "SOURCE_ORDER_MISMATCH",
                "OLD_WRITER_NOT_FENCED",
            },
        )
        self.assertEqual(
            blocked.rollback_policy, MigrationRollbackPolicy.FORWARD_ONLY
        )


if __name__ == "__main__":
    unittest.main()
