from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from identity_core import IdentityStore


class IdentityShadowIntegrationTests(unittest.TestCase):
    def test_default_path_does_not_create_v1_authority_tables(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td))
            try:
                tables = {
                    str(row[0])
                    for row in store.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertNotIn("canonical_events", tables)
                self.assertNotIn("schema_migrations", tables)
            finally:
                store.close()

    def test_opt_in_shadow_mirrors_record_in_same_database(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td), enable_v1_shadow=True)
            try:
                legacy_id = store.record(
                    "conversation.user",
                    "user",
                    "hello canonical shadow",
                    {
                        "surface": "desktop",
                        "principal_id": "owner",
                        "turn_id": "turn-shadow-1",
                    },
                )
                row = store.conn.execute(
                    """SELECT event_id,identity_id,turn_id,event_type,surface,
                              principal_id,eligible_for_memory,payload_json
                       FROM canonical_events WHERE event_id=?""",
                    ("legacy:%d" % legacy_id,),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["identity_id"], store.persona()["id"])
                self.assertEqual(row["turn_id"], "turn-shadow-1")
                self.assertEqual(row["event_type"], "conversation.user")
                self.assertEqual(row["surface"], "desktop")
                self.assertEqual(row["principal_id"], "owner")
                self.assertEqual(int(row["eligible_for_memory"]), 1)
                self.assertIn("hello canonical shadow", row["payload_json"])
            finally:
                store.close()

    def test_stable_source_key_dedupes_canonical_replay(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td), enable_v1_shadow=True)
            try:
                extra = {
                    "surface": "qq",
                    "principal_id": "owner",
                    "source_namespace": "qq",
                    "source_event_key": "message-123",
                }
                store.record(
                    "conversation.user",
                    "user",
                    "same upstream message",
                    extra,
                )
                store.record(
                    "conversation.user",
                    "user",
                    "same upstream message",
                    extra,
                )
                canonical_count = store.conn.execute(
                    """SELECT COUNT(*) FROM canonical_events
                       WHERE identity_id=? AND source_namespace='qq'
                         AND source_event_key='message-123'""",
                    (store.persona()["id"],),
                ).fetchone()[0]
                ingest_count = store.conn.execute(
                    """SELECT COUNT(*) FROM canonical_event_ingest cei
                       JOIN canonical_events ce ON ce.event_id=cei.event_id
                       WHERE ce.identity_id=? AND ce.source_namespace='qq'
                         AND ce.source_event_key='message-123'""",
                    (store.persona()["id"],),
                ).fetchone()[0]
                legacy_count = store.conn.execute(
                    """SELECT COUNT(*) FROM events
                       WHERE content='same upstream message'"""
                ).fetchone()[0]
                self.assertEqual(canonical_count, 1)
                self.assertEqual(ingest_count, 1)
                self.assertEqual(legacy_count, 2)
            finally:
                store.close()

    def test_shadow_failure_rolls_back_legacy_event(self):
        class BrokenShadow:
            def write(self, *args, **kwargs):
                raise RuntimeError("synthetic shadow failure")

        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td), enable_v1_shadow=True)
            try:
                store._canonical_shadow = BrokenShadow()
                with self.assertRaisesRegex(RuntimeError, "synthetic shadow failure"):
                    store.record(
                        "conversation.user",
                        "user",
                        "must rollback",
                        {"surface": "desktop"},
                    )
                count = store.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE content='must rollback'"
                ).fetchone()[0]
                self.assertEqual(count, 0)
            finally:
                store.close()

    def test_add_memory_auto_source_is_shadowed_as_user_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td), enable_v1_shadow=True)
            try:
                memory_id = store.add_memory(
                    "I prefer local-first tools",
                    category="preference",
                    priority=5,
                )
                legacy_source = store.conn.execute(
                    "SELECT source_event FROM memories WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()[0]
                row = store.conn.execute(
                    """SELECT event_type,eligible_for_memory
                       FROM canonical_events WHERE event_id=?""",
                    ("legacy:%d" % int(legacy_source),),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["event_type"], "memory.saved")
                self.assertEqual(int(row["eligible_for_memory"]), 1)
            finally:
                store.close()

    def test_reopen_with_shadow_is_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            first = IdentityStore(home, enable_v1_shadow=True)
            identity_id = first.persona()["id"]
            first.close()

            second = IdentityStore(home, enable_v1_shadow=True)
            try:
                self.assertEqual(second.persona()["id"], identity_id)
                versions = [
                    int(row[0])
                    for row in second.conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ]
                self.assertEqual(versions, [1, 2, 3, 4, 5])
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
