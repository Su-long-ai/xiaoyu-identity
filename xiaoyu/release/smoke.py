from __future__ import annotations

import tempfile
from pathlib import Path

from xiaoyu.persistence import (
    Database,
    ExternalErasureFenceStore,
    RecoveryManager,
    RestoreMode,
    apply_migrations,
    assert_schema_compatible,
    verify_schema,
)

from .authority import ReleaseManifest, ReleaseSmokeEvidence


class ReleaseSmokeRunner:
    """Offline, non-activating candidate checks used by Release Authority."""

    @staticmethod
    def run(
        *,
        db_path,
        identity_id: str,
        manifest: ReleaseManifest,
    ) -> ReleaseSmokeEvidence:
        source = Database(db_path)
        schema_ok = True
        migration_ok = True
        restore_ok = True
        identity_ok = True

        try:
            assert_schema_compatible(
                source, max_supported_version=manifest.max_schema_version
            )
        except Exception:
            schema_ok = False

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            migration_copy = root / "migration-smoke.sqlite3"
            try:
                source.backup_to(migration_copy)
                migration_db = Database(migration_copy)
                apply_migrations(migration_db)
                verify_schema(migration_db)
            except Exception:
                migration_ok = False

            backup = root / "restore-smoke.sqlite3"
            restored = root / "restored.sqlite3"
            try:
                RecoveryManager.create_backup(
                    source_path=source.path,
                    backup_path=backup,
                    identity_id=identity_id,
                    release_version=manifest.release_id,
                    release_digest=manifest.release_digest,
                )
                RecoveryManager.restore(
                    candidate_path=backup,
                    target_path=restored,
                    identity_id=identity_id,
                    mode=RestoreMode.PORTABLE_IMPORT,
                )
            except Exception:
                restore_ok = False
                identity_ok = False
            else:
                source_identity = ExternalErasureFenceStore(
                    source.path
                ).identity(identity_id)
                restored_identity = ExternalErasureFenceStore(
                    restored
                ).identity(identity_id)
                identity_ok = (
                    source_identity is not None
                    and restored_identity is not None
                    and int(source_identity["erasure_generation"])
                    == int(restored_identity["erasure_generation"])
                )

        return ReleaseSmokeEvidence(
            schema_compatibility=schema_ok,
            migration_smoke=migration_ok,
            restore_smoke=restore_ok,
            identity_continuity_smoke=identity_ok,
        )
