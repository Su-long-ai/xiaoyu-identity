from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.schema import MIGRATIONS
from xiaoyu.release.authority import (
    ReleaseActivationError,
    ReleaseAuthority,
    ReleaseManifest,
    ReleaseRollbackPolicy,
    ReleaseSmokeEvidence,
    ReleaseState,
)
from xiaoyu.release.smoke import ReleaseSmokeRunner


def manifest(release_id: str, schema: int, max_schema: int) -> ReleaseManifest:
    return ReleaseManifest(
        release_id=release_id,
        core_commit="commit-" + release_id,
        schema_version=schema,
        max_schema_version=max_schema,
        migration_version=schema,
        contract_digest="sha256:contract-" + release_id,
        release_digest="sha256:release-" + release_id,
    )


GOOD = ReleaseSmokeEvidence(True, True, True, True)


class ReleaseAuthorityTests(unittest.TestCase):
    def test_candidate_activation_lkg_rejection_and_forward_fix_policy(self):
        with tempfile.TemporaryDirectory() as td:
            authority = ReleaseAuthority(Path(td) / "release-authority.json")
            old = manifest("r-old", 5, 5)
            new = manifest("r-new", 7, 7)
            bad = manifest("r-bad", 7, 7)

            authority.register_candidate(old)
            authority.activate(old.release_id, GOOD)
            self.assertEqual(authority.state("r-old"), ReleaseState.CURRENT)

            authority.register_candidate(bad)
            with self.assertRaises(ReleaseActivationError):
                authority.activate(
                    bad.release_id,
                    ReleaseSmokeEvidence(True, True, False, True),
                )
            self.assertEqual(authority.state("r-bad"), ReleaseState.REJECTED)
            self.assertEqual(authority.state("r-old"), ReleaseState.CURRENT)

            authority.register_candidate(new)
            authority.activate(new.release_id, GOOD)
            self.assertEqual(authority.state("r-new"), ReleaseState.CURRENT)
            self.assertEqual(
                authority.state("r-old"), ReleaseState.LAST_KNOWN_GOOD
            )
            self.assertEqual(authority.last_known_good().release_id, "r-old")
            self.assertEqual(
                authority.rollback_policy(
                    current_release_id="r-new",
                    target_release_id="r-old",
                ),
                ReleaseRollbackPolicy.FORWARD_FIX_REQUIRED,
            )

    def test_release_smoke_runs_migration_restore_and_identity_checks(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            latest = max(migration.version for migration in MIGRATIONS)
            evidence = ReleaseSmokeRunner.run(
                db_path=db.path,
                identity_id="fish-1",
                manifest=manifest("candidate", latest, latest),
            )
            self.assertEqual(evidence, GOOD)


if __name__ == "__main__":
    unittest.main()
