from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from identity_core import IdentityStore
from xiaoyu.persistence import Database
from xiaoyu.release.readiness import CanonicalCutoverReadiness
from xiaoyu.runtime.product_context import (
    CanonicalReadShadowBootstrap,
)
from xiaoyu.runtime.product_readiness import (
    CanonicalWriteShadowDrill,
)


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class CanonicalCutoverReadinessTests(unittest.TestCase):
    def _legacy(self, root: Path):
        store = IdentityStore(root)
        identity_id = str(store.persona()["id"])
        event_id = store.record(
            "conversation.user",
            "user",
            "我喜欢咖啡",
            {
                "principal_id": "owner",
                "surface": "desktop",
                "source_type": "text",
                "audience_scope": "PRIVATE",
                "context_space": "PERSONAL",
            },
        )
        store.add_memory(
            "我喜欢咖啡",
            category="preference",
            priority=5,
            source_event=event_id,
        )
        store.close()
        return identity_id, event_id

    def _ready(self, root: Path, identity_id: str):
        db = Database(root / "identity" / "identity.sqlite3")
        read_path = root / "read-ready.json"
        write_path = root / "write-ready.json"

        bootstrap = CanonicalReadShadowBootstrap(
            db,
            read_path,
            required_consecutive=2,
        )
        first = bootstrap.prepare(
            identity_id=identity_id,
            observed_at=T0,
        )
        self.assertFalse(first.readiness.candidate_ready)
        second = bootstrap.prepare(
            identity_id=identity_id,
            observed_at=T0 + timedelta(minutes=1),
        )
        self.assertTrue(second.readiness.candidate_ready)

        write = CanonicalWriteShadowDrill(
            db, write_path
        ).run(
            identity_id=identity_id,
            observed_at=T0 + timedelta(minutes=2),
        )
        self.assertTrue(
            write.candidate_ready,
            write.blockers,
        )
        return db, read_path, write_path

    def test_candidate_requires_current_untampered_read_and_write_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_id, _ = self._legacy(root)
            db, read_path, write_path = self._ready(
                root, identity_id
            )

            coordinator = CanonicalCutoverReadiness(
                db,
                read_status_path=read_path,
                write_status_path=write_path,
                max_evidence_age_s=3600,
            )
            candidate = coordinator.evaluate(
                identity_id=identity_id,
                evaluated_at=T0 + timedelta(minutes=3),
            )
            self.assertTrue(
                candidate.ready,
                candidate.blockers,
            )
            self.assertIsNotNone(candidate.evidence)
            self.assertTrue(
                candidate.evidence.canonical_read_path_ready
            )
            self.assertTrue(
                candidate.evidence.canonical_write_path_ready
            )

            # Readiness evaluation itself cannot activate the authority switch.
            with db.transaction() as conn:
                active = conn.execute(
                    """SELECT COUNT(*) FROM authority_cutover_state
                       WHERE mode='CANONICAL'"""
                ).fetchone()[0]
            self.assertEqual(active, 0)

            # Tampering any write evidence bit without recomputing its digest
            # invalidates the candidate.
            payload = json.loads(
                write_path.read_text(encoding="utf-8")
            )
            payload["evidence"]["post_cutover_write"] = False
            write_path.write_text(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            tampered = coordinator.evaluate(
                identity_id=identity_id,
                evaluated_at=T0 + timedelta(minutes=4),
            )
            self.assertFalse(tampered.ready)
            self.assertIn(
                "WRITE_EVIDENCE_DIGEST_INVALID",
                tampered.blockers,
            )

    def test_live_legacy_drift_revokes_old_ready_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_id, source_event = self._legacy(root)
            db, read_path, write_path = self._ready(
                root, identity_id
            )
            coordinator = CanonicalCutoverReadiness(
                db,
                read_status_path=read_path,
                write_status_path=write_path,
                max_evidence_age_s=3600,
            )
            self.assertTrue(
                coordinator.evaluate(
                    identity_id=identity_id,
                    evaluated_at=T0 + timedelta(minutes=3),
                ).ready
            )

            # Legacy remains authority in SHADOW. A new real legacy write after
            # the status files were produced must invalidate cutover now.
            legacy = IdentityStore(root)
            legacy.add_memory(
                "状态文件之后的新记忆",
                category="shared",
                priority=3,
                source_event=source_event,
            )
            legacy.close()

            drift = coordinator.evaluate(
                identity_id=identity_id,
                evaluated_at=T0 + timedelta(minutes=4),
            )
            self.assertFalse(drift.ready)
            self.assertTrue(
                any(
                    blocker.startswith("LIVE_READ_DRIFT:")
                    or blocker.startswith(
                        "LEGACY_BACKFILL_NOT_READY:"
                    )
                    for blocker in drift.blockers
                ),
                drift.blockers,
            )

    def test_stale_or_schema_mismatched_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_id, _ = self._legacy(root)
            db, read_path, write_path = self._ready(
                root, identity_id
            )
            coordinator = CanonicalCutoverReadiness(
                db,
                read_status_path=read_path,
                write_status_path=write_path,
                max_evidence_age_s=300,
            )

            read_payload = json.loads(
                read_path.read_text(encoding="utf-8")
            )
            read_payload["updated_at"] = (
                T0 - timedelta(hours=2)
            ).isoformat(timespec="microseconds")
            read_path.write_text(
                json.dumps(
                    read_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            stale = coordinator.evaluate(
                identity_id=identity_id,
                evaluated_at=T0 + timedelta(minutes=3),
            )
            self.assertFalse(stale.ready)
            self.assertIn(
                "READ_EVIDENCE_STALE",
                stale.blockers,
            )

            # Restore current read evidence, then prove schema mismatch alone
            # also blocks.
            bootstrap = CanonicalReadShadowBootstrap(
                db,
                read_path,
                required_consecutive=2,
            )
            bootstrap.prepare(
                identity_id=identity_id,
                observed_at=T0 + timedelta(minutes=3),
            )
            schema_payload = json.loads(
                write_path.read_text(encoding="utf-8")
            )
            schema_payload["schema_version"] = (
                int(schema_payload["schema_version"]) - 1
            )
            write_path.write_text(
                json.dumps(
                    schema_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            mismatch = coordinator.evaluate(
                identity_id=identity_id,
                evaluated_at=T0 + timedelta(minutes=4),
            )
            self.assertFalse(mismatch.ready)
            self.assertIn(
                "WRITE_SCHEMA_STALE",
                mismatch.blockers,
            )


if __name__ == "__main__":
    unittest.main()
