from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories import (
    CanonicalEventConflict,
    CanonicalEventRepository,
    LegacyEventShadowWriter,
)


AT = "2026-11-18T12:00:00+00:00"


class CanonicalEventTests(unittest.TestCase):
    def _db(self, root: str) -> Database:
        db = Database(Path(root) / "identity.sqlite3")
        apply_migrations(db)
        with db.transaction() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    content TEXT NOT NULL,
                    extra TEXT NOT NULL DEFAULT '{}'
                )"""
            )
        return db

    def test_legacy_event_maps_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repo = CanonicalEventRepository()
            writer = LegacyEventShadowWriter(repo)
            with db.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO events(at,kind,actor,content,extra) VALUES(?,?,?,?,?)",
                    (AT, "conversation.user", "user", "hello", "{}"),
                )
                event = writer.write(
                    conn, "fish-1", int(cur.lastrowid), AT,
                    "conversation.user", "user", "hello", {"surface": "desktop"},
                    turn_id="turn-1",
                )
                restored = repo.get(conn, event.event_id)
                self.assertEqual(restored, event)
                self.assertTrue(restored.eligible_for_memory)
                self.assertEqual(restored.surface, "desktop")
                self.assertEqual(repo.list_turn(conn, "turn-1"), [event])

    def test_exact_retry_is_idempotent_but_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repo = CanonicalEventRepository()
            writer = LegacyEventShadowWriter(repo)
            with db.transaction() as conn:
                event = writer.write(
                    conn, "fish-1", 1, AT, "conversation.user", "user", "hello", {}
                )
                self.assertFalse(repo.append(conn, event))
                with self.assertRaises(CanonicalEventConflict):
                    writer.write(
                        conn, "fish-1", 1, AT, "conversation.user", "user", "changed", {}
                    )

    def test_same_transaction_rolls_back_legacy_row_when_shadow_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            writer = LegacyEventShadowWriter()
            with self.assertRaises(ValueError):
                with db.transaction() as conn:
                    cur = conn.execute(
                        "INSERT INTO events(at,kind,actor,content,extra) VALUES(?,?,?,?,?)",
                        (AT, "conversation.user", "user", "hello", "{}"),
                    )
                    writer.write(
                        conn, "fish-1", int(cur.lastrowid), "not-a-time",
                        "conversation.user", "user", "hello", {},
                    )
            conn = db.connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_events").fetchone()[0], 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
