from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from xiaoyu.persistence import (
    Database,
    UnsupportedSchemaVersion,
    apply_migrations,
    applied_versions,
    assert_schema_compatible,
    verify_schema,
)
from xiaoyu.persistence import schema as schema_module
from xiaoyu.persistence.migrations.v1_authority import REQUIRED_TABLES


class PersistenceMigrationTests(unittest.TestCase):
    def test_empty_database_migrates_to_v1(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            self.assertEqual(apply_migrations(db), [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual(applied_versions(db), [1, 2, 3, 4, 5, 6, 7])
            self.assertTrue(db.is_healthy())

            conn = db.connect()
            try:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                conn.close()
            self.assertTrue(REQUIRED_TABLES.issubset(tables))

    def test_existing_legacy_tables_and_rows_are_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identity.sqlite3"
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute("CREATE TABLE events(event_id INTEGER PRIMARY KEY, content TEXT NOT NULL)")
                conn.execute("CREATE TABLE memories(memory_id INTEGER PRIMARY KEY, text TEXT NOT NULL)")
                conn.execute("INSERT INTO settings VALUES('schema_version','3')")
                conn.execute("INSERT INTO events VALUES(1,'legacy event')")
                conn.execute("INSERT INTO memories VALUES(1,'legacy memory')")
                conn.commit()
            finally:
                conn.close()

            db = Database(path)
            self.assertEqual(apply_migrations(db), [1, 2, 3, 4, 5, 6, 7])
            conn = db.connect()
            try:
                self.assertEqual(conn.execute("SELECT content FROM events WHERE event_id=1").fetchone()[0], "legacy event")
                self.assertEqual(conn.execute("SELECT text FROM memories WHERE memory_id=1").fetchone()[0], "legacy memory")
                self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], "3")
            finally:
                conn.close()

    def test_migration_is_idempotent_and_verifiable(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            self.assertEqual(apply_migrations(db), [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual(apply_migrations(db), [])
            verify_schema(db)
            self.assertEqual(applied_versions(db), [1, 2, 3, 4, 5, 6, 7])

    def test_v1_to_latest_and_explicit_stepwise_chain(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            self.assertEqual(apply_migrations(db, target_version=1), [1])
            self.assertEqual(applied_versions(db), [1])
            for version in range(2, 8):
                self.assertEqual(
                    apply_migrations(db, target_version=version),
                    [version],
                )
            self.assertEqual(applied_versions(db), [1, 2, 3, 4, 5, 6, 7])
            verify_schema(db)

    def test_unknown_future_schema_and_older_binary_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "future.sqlite3")
            apply_migrations(db)
            with self.assertRaises(UnsupportedSchemaVersion):
                assert_schema_compatible(db, max_supported_version=5)

            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO schema_migrations(version,name,applied_at)
                       VALUES(999,'future','2026-11-18T00:00:00+00:00')"""
                )
            with self.assertRaises(UnsupportedSchemaVersion):
                apply_migrations(db)
            with self.assertRaises(UnsupportedSchemaVersion):
                verify_schema(db)

    def test_interrupted_migration_rolls_back_and_can_restart(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            original = schema_module.MIGRATIONS

            def fail_apply(conn):
                conn.execute("CREATE TABLE interrupted_probe(value TEXT)")
                raise RuntimeError("synthetic migration crash")

            def fail_verify(conn):
                return None

            failing = schema_module.Migration(
                8, "synthetic_interrupted_v8", fail_apply, fail_verify
            )
            try:
                schema_module.MIGRATIONS = original + (failing,)
                with self.assertRaises(RuntimeError):
                    apply_migrations(db)
            finally:
                schema_module.MIGRATIONS = original

            with db.transaction() as conn:
                table = conn.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='interrupted_probe'"""
                ).fetchone()
                migration = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=8"
                ).fetchone()
            self.assertIsNone(table)
            self.assertIsNone(migration)
            self.assertEqual(apply_migrations(db), [])
            verify_schema(db)

    def test_mixed_version_reader_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            before = applied_versions(db)
            with self.assertRaises(UnsupportedSchemaVersion):
                assert_schema_compatible(db, max_supported_version=4)
            self.assertEqual(applied_versions(db), before)

    def test_online_backup_preserves_schema_and_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / "identity.sqlite3")
            apply_migrations(db)
            with db.transaction() as conn:
                conn.execute(
                    """INSERT INTO canonical_events(
                        event_id,identity_id,turn_id,event_type,surface,source_type,principal_id,
                        audience_scope,context_space,trust_class,taint_json,eligible_for_memory,
                        payload_type,payload_json,observed_at,recorded_at,correlation_id,schema_version
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "evt-1", "fish-1", "turn-1", "conversation.user", "desktop",
                        "text", "owner", "PRIVATE", "PERSONAL", "OWNER_DIRECT", "[]", 1,
                        "text/plain", '{"text":"hello"}', "2026-11-18T12:00:00+00:00",
                        "2026-11-18T12:00:00+00:00", "corr-1", 1,
                    ),
                )
            backup = db.backup_to(root / "backup.sqlite3")
            restored = Database(backup)
            self.assertTrue(restored.is_healthy())
            self.assertEqual(applied_versions(restored), [1, 2, 3, 4, 5, 6, 7])
            conn = restored.connect()
            try:
                row = conn.execute("SELECT payload_json FROM canonical_events WHERE event_id='evt-1'").fetchone()
                self.assertIsNotNone(row)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
