from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from xiaoyu.persistence import Database, ExternalErasureFenceStore, apply_migrations
from xiaoyu.persistence.recovery import BackupError, RecoveryManager, RestoreInvariantError, RestoreMode


class BackupDurabilityTests(unittest.TestCase):
    def _db(self, path: Path) -> Database:
        db = Database(path)
        apply_migrations(db)
        ExternalErasureFenceStore(path).ensure_identity("fish-1")
        return db

    def test_backup_manifest_is_minimal_and_wal_snapshot_is_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            with source.transaction(immediate=True) as conn:
                conn.execute("CREATE TABLE backup_probe(id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO backup_probe(value) VALUES('ok')")

            backup = RecoveryManager.create_backup(
                source_path=source.path,
                backup_path=root / "backup.sqlite3",
                identity_id="fish-1",
                release_version="test-release",
                release_digest="sha256:test",
            )
            self.assertTrue(Database(backup).is_healthy())
            manifest = json.loads(
                Path(str(backup) + ".manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                {
                    "identity_id",
                    "schema_version",
                    "migration_version",
                    "erasure_generation",
                    "source_revision_watermark",
                    "creation_time",
                    "release_version",
                    "release_digest",
                    "db_sha256",
                }.issubset(manifest)
            )
            self.assertEqual(manifest["identity_id"], "fish-1")
            self.assertEqual(manifest["erasure_generation"], 0)

    def test_online_backup_is_consistent_while_wal_writer_is_open(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            with source.transaction(immediate=True) as conn:
                conn.execute("CREATE TABLE backup_probe(id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO backup_probe(value) VALUES('committed')")

            writer_started = threading.Event()
            release_writer = threading.Event()

            def writer():
                conn = source.connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO backup_probe(value) VALUES('uncommitted')")
                    writer_started.set()
                    release_writer.wait(5)
                    conn.commit()
                finally:
                    conn.close()

            thread = threading.Thread(target=writer)
            thread.start()
            self.assertTrue(writer_started.wait(5))
            try:
                backup = source.backup_to(root / "concurrent.sqlite3")
            finally:
                release_writer.set()
                thread.join(5)

            restored = Database(backup)
            self.assertTrue(restored.is_healthy())
            with restored.transaction() as conn:
                values = [
                    row[0]
                    for row in conn.execute(
                        "SELECT value FROM backup_probe ORDER BY id"
                    ).fetchall()
                ]
            self.assertEqual(values, ["committed"])

    def test_synthetic_disk_full_leaves_existing_backup_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            target = root / "backup.sqlite3"
            target.write_bytes(b"previous-backup")

            original = Database.backup_to

            def fail_with_partial(db, destination):
                partial = Path(destination)
                partial.write_bytes(b"partial")
                raise OSError(28, "No space left on device")

            with mock.patch.object(Database, "backup_to", fail_with_partial):
                with self.assertRaises(BackupError):
                    RecoveryManager.create_backup(
                        source_path=source.path,
                        backup_path=target,
                        identity_id="fish-1",
                        release_version="test-release",
                        release_digest="sha256:test",
                    )

            self.assertEqual(target.read_bytes(), b"previous-backup")
            self.assertFalse(Path(str(target) + ".partial").exists())
            Database.backup_to = original

    def test_manifest_digest_detects_partial_or_post_backup_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            backup = RecoveryManager.create_backup(
                source_path=source.path,
                backup_path=root / "backup.sqlite3",
                identity_id="fish-1",
                release_version="test-release",
                release_digest="sha256:test",
            )
            data = bytearray(backup.read_bytes())
            data[-1] ^= 0x01
            backup.write_bytes(bytes(data))

            with self.assertRaises(BackupError):
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=source.path,
                    identity_id="fish-1",
                    mode=RestoreMode.MANAGED,
                )

    def test_truncated_backup_is_rejected_before_activation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            good = source.backup_to(root / "good.sqlite3")
            truncated = root / "truncated.sqlite3"
            data = good.read_bytes()
            truncated.write_bytes(data[: max(64, len(data) // 4)])

            with self.assertRaises(RestoreInvariantError):
                RecoveryManager.restore(
                    candidate_path=truncated,
                    target_path=source.path,
                    identity_id="fish-1",
                    mode=RestoreMode.MANAGED,
                )

    def test_corrupt_header_is_rejected_before_activation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "identity.sqlite3")
            corrupt = source.backup_to(root / "corrupt.sqlite3")
            data = bytearray(corrupt.read_bytes())
            data[:16] = b"not-a-sqlite-db!"
            corrupt.write_bytes(bytes(data))

            with self.assertRaises(RestoreInvariantError):
                RecoveryManager.restore(
                    candidate_path=corrupt,
                    target_path=source.path,
                    identity_id="fish-1",
                    mode=RestoreMode.MANAGED,
                )


if __name__ == "__main__":
    unittest.main()
