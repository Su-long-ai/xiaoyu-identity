from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from .db import Database
from .erasure import ExternalErasureFenceStore, ErasureWatermarkError
from .schema import apply_migrations, applied_versions, verify_schema


class RestoreMode(str, Enum):
    PORTABLE_IMPORT = "PORTABLE_IMPORT"
    MANAGED = "MANAGED"
    DISASTER_RECOVERY = "DISASTER_RECOVERY"
    ROLLBACK = "ROLLBACK"


class RecoveryError(RuntimeError):
    pass


class BackupError(RecoveryError):
    pass


class MissingErasureWatermark(RecoveryError):
    pass


class RestoreInvariantError(RecoveryError):
    pass


@dataclass(frozen=True)
class RestoreReport:
    mode: RestoreMode
    identity_id: str
    erasure_generation: int
    quarantined_outbox: int
    quarantined_effects: int
    quarantined_delivery_attempts: int
    revoked_delegations: int
    degraded_providers: int
    invalidated_execution_authorizations: int
    quarantined_purposes: int
    quarantined_occurrences: int
    quarantined_deliveries: int
    cleared_projections: int
    rebuilt_projections: int


class RecoveryQuarantineStore:
    VERSION = 1

    def __init__(self, db_path) -> None:
        self.path = Path(str(Path(db_path)) + ".restore-quarantine.json")

    def activate(self, *, identity_id: str, mode: RestoreMode, created_at: str) -> None:
        payload = {
            "version": self.VERSION,
            "identity_id": identity_id,
            "mode": mode.value,
            "created_at": created_at,
            "state": "ACTIVE",
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def is_active(self) -> bool:
        if not self.path.exists():
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return True
        return payload.get("state") == "ACTIVE"

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class RecoveryManager:
    """Fail-closed backup/restore boundary for the single SQLite authority."""

    @staticmethod
    def create_backup(
        *,
        source_path,
        backup_path,
        identity_id: str,
        release_version: str,
        release_digest: str,
        created_at: Optional[datetime] = None,
    ) -> Path:
        source = Database(source_path)
        RecoveryManager._require_healthy(source, "source")
        apply_migrations(source)
        verify_schema(source)

        fence = ExternalErasureFenceStore(source.path)
        identity_fence = fence.sync_from_db(source, identity_id)

        backup = Path(backup_path)
        stage = backup.with_name(backup.name + ".partial")
        stage_manifest = Path(str(stage) + ".manifest.json")
        stage_fence = ExternalErasureFenceStore(stage).path
        for candidate in (stage, stage_manifest, stage_fence):
            if candidate.exists():
                candidate.unlink()

        try:
            source.backup_to(stage)
            backup_db = Database(stage)
            RecoveryManager._require_healthy(backup_db, "backup")
            backup_fence = ExternalErasureFenceStore(stage)
            fence.copy_to(backup_fence)

            with source.transaction() as conn:
                source_revision = conn.execute(
                    """SELECT COALESCE(MAX(ingest_revision),0)
                       FROM canonical_event_ingest WHERE identity_id=?""",
                    (identity_id,),
                ).fetchone()[0]
            versions = applied_versions(source)
            now = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
            manifest = {
                "version": 1,
                "identity_id": identity_id,
                "schema_version": max(versions, default=0),
                "migration_version": max(versions, default=0),
                "erasure_generation": int(identity_fence["erasure_generation"]),
                "source_revision_watermark": int(source_revision),
                "creation_time": now.isoformat(timespec="microseconds"),
                "release_version": release_version,
                "release_digest": release_digest,
                "db_sha256": RecoveryManager._sha256(stage),
            }
            RecoveryManager._write_json(stage_manifest, manifest)

            # The manifest is the commit marker and is replaced last. A crash
            # between file replacements leaves either no manifest or a digest
            # mismatch, both rejected by validation.
            final_manifest = Path(str(backup) + ".manifest.json")
            final_fence = ExternalErasureFenceStore(backup).path
            os.replace(stage, backup)
            os.replace(stage_fence, final_fence)
            os.replace(stage_manifest, final_manifest)
            return backup
        except Exception as exc:
            for candidate in (stage, stage_manifest, stage_fence):
                if candidate.exists():
                    candidate.unlink()
            if isinstance(exc, RecoveryError):
                raise
            raise BackupError("backup creation failed: %s" % exc) from exc

    @staticmethod
    def restore(
        *,
        candidate_path,
        target_path,
        identity_id: str,
        mode: RestoreMode,
        watermark_path: Optional[Path] = None,
        activated_at: Optional[datetime] = None,
    ) -> RestoreReport:
        candidate_path = Path(candidate_path)
        target_path = Path(target_path)
        if candidate_path.resolve() == target_path.resolve():
            raise ValueError("restore candidate must differ from active target")

        manifest = RecoveryManager.validate_backup_manifest(
            candidate_path, expected_identity_id=identity_id
        )
        if (
            mode in (RestoreMode.MANAGED, RestoreMode.ROLLBACK)
            and manifest is None
        ):
            raise BackupError(
                "managed/rollback restore requires a XiaoYu backup manifest; "
                "use explicit disaster recovery or migration for raw snapshots"
            )
        source_candidate = Database(candidate_path)
        RecoveryManager._require_healthy(source_candidate, "candidate")

        RecoveryManager._reject_stale_authority_restore(
            target_path=target_path,
            identity_id=identity_id,
            mode=mode,
            manifest=manifest,
        )

        fence_store, fence_identity = RecoveryManager._trusted_fence(
            candidate_path=candidate_path,
            target_path=target_path,
            identity_id=identity_id,
            mode=mode,
            watermark_path=watermark_path,
        )
        stamp = (activated_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(timespec="microseconds")

        work_path = target_path.with_name(target_path.name + ".restore-work")
        stage_path = target_path.with_name(target_path.name + ".restore-stage")
        RecoveryManager._cleanup_sqlite_artifact(work_path)
        RecoveryManager._cleanup_sqlite_artifact(stage_path)
        try:
            # Restore candidates are immutable evidence. All migration,
            # tombstone replay, and quarantine changes happen on a working copy.
            source_candidate.backup_to(work_path)
            candidate = Database(work_path)
            RecoveryManager._require_healthy(candidate, "candidate working copy")
            apply_migrations(candidate)
            verify_schema(candidate)

            counts = RecoveryManager._prepare_candidate(
                candidate,
                identity_id=identity_id,
                fence_identity=fence_identity,
                restored_at=stamp,
            )
            RecoveryManager._verify_candidate(candidate, identity_id, fence_identity)

            # Materialize committed WAL state into a clean activation image.
            candidate.backup_to(stage_path)
            stage = Database(stage_path)
            RecoveryManager._require_healthy(stage, "staged restore")

            if target_path.exists():
                RecoveryManager._checkpoint(target_path)
            for suffix in ("-wal", "-shm"):
                p = Path(str(target_path) + suffix)
                if p.exists():
                    p.unlink()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage_path, target_path)

            target_fence = ExternalErasureFenceStore(target_path)
            payload = fence_store.load()
            if payload is None:
                raise MissingErasureWatermark(
                    "trusted erasure watermark disappeared"
                )
            target_fence._write(payload)

            RecoveryQuarantineStore(target_path).activate(
                identity_id=identity_id, mode=mode, created_at=stamp
            )
        finally:
            RecoveryManager._cleanup_sqlite_artifact(work_path)
            RecoveryManager._cleanup_sqlite_artifact(stage_path)
        return RestoreReport(
            mode=mode,
            identity_id=identity_id,
            erasure_generation=int(fence_identity["erasure_generation"]),
            quarantined_outbox=counts["outbox"],
            quarantined_effects=counts["effects"],
            quarantined_delivery_attempts=counts["attempts"],
            revoked_delegations=counts["delegations"],
            degraded_providers=counts["providers"],
            invalidated_execution_authorizations=counts["execution_auth"],
            quarantined_purposes=counts["purposes"],
            quarantined_occurrences=counts["occurrences"],
            quarantined_deliveries=counts["deliveries"],
            cleared_projections=counts["projections"],
            rebuilt_projections=counts["rebuilt_projections"],
        )

    @staticmethod
    def clear_execution_quarantine(*, target_path, identity_id: str) -> None:
        store = RecoveryQuarantineStore(target_path)
        if not store.is_active():
            return
        db = Database(target_path)
        RecoveryManager._verify_no_replayable_restore_work(db, identity_id)
        store.clear()

    @staticmethod
    def validate_backup_manifest(
        candidate_path,
        *,
        expected_identity_id: Optional[str] = None,
    ) -> Optional[dict]:
        candidate = Path(candidate_path)
        manifest_path = Path(str(candidate) + ".manifest.json")
        if not manifest_path.exists():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackupError("backup manifest is unreadable") from exc
        if int(payload.get("version", 0)) != 1:
            raise BackupError("unsupported backup manifest version")
        if expected_identity_id is not None and str(
            payload.get("identity_id")
        ) != str(expected_identity_id):
            raise BackupError("backup identity does not match restore target")
        expected_digest = str(payload.get("db_sha256") or "")
        if not expected_digest or expected_digest != RecoveryManager._sha256(candidate):
            raise BackupError("backup manifest digest mismatch")
        return payload

    @staticmethod
    def _source_revision_watermark(
        db: Database,
        identity_id: str,
    ) -> int:
        with db.transaction() as conn:
            table = conn.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='canonical_event_ingest'"""
            ).fetchone()
            if table is None:
                return 0
            row = conn.execute(
                """SELECT COALESCE(MAX(ingest_revision),0)
                   FROM canonical_event_ingest
                   WHERE identity_id=?""",
                (identity_id,),
            ).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _reject_stale_authority_restore(
        *,
        target_path: Path,
        identity_id: str,
        mode: RestoreMode,
        manifest: Optional[dict],
    ) -> None:
        """Never let an older snapshot replace newer healthy authority.

        Delete continuity has the external erasure fence because deletion must
        survive even disaster recovery. Other authoritative edits remain in
        the single SQLite authority, so managed/rollback restore must fail
        closed instead of copying those edits into a second journal.
        """
        if mode == RestoreMode.PORTABLE_IMPORT or not target_path.exists():
            return

        target = Database(target_path)
        try:
            healthy = target.is_healthy()
        except sqlite3.DatabaseError:
            healthy = False

        if not healthy:
            if mode in (RestoreMode.MANAGED, RestoreMode.ROLLBACK):
                raise RestoreInvariantError(
                    "managed/rollback restore requires a healthy active target; "
                    "use explicit disaster recovery for a corrupt target"
                )
            return

        if manifest is None:
            # Only explicit disaster-recovery paths may reach this point.
            # They do not claim managed backup provenance.
            return

        try:
            candidate_revision = int(
                manifest["source_revision_watermark"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(
                "backup manifest source revision watermark is missing or invalid"
            ) from exc
        if candidate_revision < 0:
            raise BackupError(
                "backup manifest source revision watermark is invalid"
            )

        active_revision = RecoveryManager._source_revision_watermark(
            target, identity_id
        )
        if active_revision > candidate_revision:
            raise RestoreInvariantError(
                "restore candidate predates active authority "
                "(candidate source revision %d, active %d)"
                % (candidate_revision, active_revision)
            )

    @staticmethod
    def _trusted_fence(
        *,
        candidate_path: Path,
        target_path: Path,
        identity_id: str,
        mode: RestoreMode,
        watermark_path: Optional[Path],
    ):
        if watermark_path is not None:
            store = ExternalErasureFenceStore(target_path, path=watermark_path)
        elif mode == RestoreMode.PORTABLE_IMPORT:
            if target_path.exists():
                raise RecoveryError("portable import requires a new target")
            store = ExternalErasureFenceStore(candidate_path)
        else:
            store = ExternalErasureFenceStore(target_path)

        identity = store.identity(identity_id)
        if identity is None:
            raise MissingErasureWatermark(
                "managed/disaster/rollback restore requires a trusted latest erasure watermark"
            )
        return store, identity

    @staticmethod
    def _prepare_candidate(
        db: Database,
        *,
        identity_id: str,
        fence_identity: dict,
        restored_at: str,
    ) -> dict:
        counts = {
            "outbox": 0,
            "effects": 0,
            "attempts": 0,
            "delegations": 0,
            "providers": 0,
            "execution_auth": 0,
            "purposes": 0,
            "occurrences": 0,
            "deliveries": 0,
            "projections": 0,
            "rebuilt_projections": 0,
        }
        with db.transaction(immediate=True) as conn:
            for tombstone in fence_identity.get("tombstones", []):
                fact_key = str(tombstone["target_id"])
                generation = int(tombstone["erasure_generation"])
                result_revision = tombstone.get("result_revision")
                current = conn.execute(
                    """SELECT current_revision,last_source_ingest_revision
                       FROM fact_authority_revisions
                       WHERE identity_id=? AND fact_key=?""",
                    (identity_id, fact_key),
                ).fetchone()
                current_revision = 0 if current is None else int(current[0])
                current_source_revision = (
                    0 if current is None else int(current[1])
                )
                current_erasure_generation = (
                    0
                    if current is None
                    else int(
                        conn.execute(
                            """SELECT erasure_generation
                               FROM fact_authority_revisions
                               WHERE identity_id=? AND fact_key=?""",
                            (identity_id, fact_key),
                        ).fetchone()[0]
                    )
                )
                source_revision = int(tombstone.get("source_ingest_revision") or 0)
                must_reapply_delete = (
                    current is None
                    or current_erasure_generation < generation
                    or current_source_revision <= source_revision
                )
                revision = (
                    max(
                        current_revision + 1,
                        int(result_revision)
                        if result_revision is not None
                        else 0,
                    )
                    if must_reapply_delete
                    else current_revision
                )
                conn.execute(
                    """INSERT OR IGNORE INTO erasure_tombstones(
                           erasure_id,identity_id,target_type,target_id,
                           erasure_generation,requested_at,applied_at,source_event_id,
                           source_ingest_revision,mutation_id
                       ) VALUES(?,?,'fact_key',?,?,?,?,?,?,?)""",
                    (
                        str(tombstone["erasure_id"]),
                        identity_id,
                        fact_key,
                        generation,
                        str(tombstone["requested_at"]),
                        str(tombstone.get("applied_at") or tombstone["requested_at"]),
                        str(tombstone["source_event_id"]),
                        source_revision,
                        str(tombstone["mutation_id"]),
                    ),
                )
                if must_reapply_delete:
                    conn.execute(
                        """UPDATE temporal_facts SET status='DELETED'
                           WHERE identity_id=? AND fact_key=? AND status!='DELETED'""",
                        (identity_id, fact_key),
                    )
                    RecoveryManager._propagate_restored_erasure(
                        conn,
                        identity_id=identity_id,
                        fact_key=fact_key,
                    )
                conn.execute(
                    """INSERT INTO fact_authority_revisions(
                           identity_id,fact_key,current_revision,
                           last_source_ingest_revision,erasure_generation,updated_at
                       ) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(identity_id,fact_key) DO UPDATE SET
                         current_revision=MAX(current_revision,excluded.current_revision),
                         last_source_ingest_revision=MAX(last_source_ingest_revision,excluded.last_source_ingest_revision),
                         erasure_generation=MAX(erasure_generation,excluded.erasure_generation),
                         updated_at=excluded.updated_at""",
                    (
                        identity_id,
                        fact_key,
                        revision,
                        source_revision,
                        generation,
                        restored_at,
                    ),
                )
                mutation_present = conn.execute(
                    "SELECT 1 FROM fact_mutations WHERE mutation_id=?",
                    (str(tombstone["mutation_id"]),),
                ).fetchone()
                if must_reapply_delete and mutation_present is not None:
                    conn.execute(
                        """INSERT OR IGNORE INTO projection_invalidations(
                               identity_id,fact_key,source_revision,erasure_generation,
                               mutation_id,invalidated_at
                           ) VALUES(?,?,?,?,?,?)""",
                        (
                            identity_id,
                            fact_key,
                            revision,
                            generation,
                            str(tombstone["mutation_id"]),
                            restored_at,
                        ),
                    )

            cur = conn.execute(
                """UPDATE outbox SET state='NEEDS_RECONCILIATION',next_attempt_at=NULL,
                                     updated_at=?
                   WHERE identity_id=? AND state IN
                     ('PENDING','CLAIMED','FAILED_RETRYABLE','DISPATCHING')""",
                (restored_at, identity_id),
            )
            counts["outbox"] = int(cur.rowcount)
            cur = conn.execute(
                """UPDATE effects SET dispatch_state='NEEDS_RECONCILIATION',updated_at=?
                   WHERE identity_id=? AND dispatch_state IN
                     ('PROPOSED','AUTHORIZED','QUEUED','DISPATCHING','FAILED_RETRYABLE')""",
                (restored_at, identity_id),
            )
            counts["effects"] = int(cur.rowcount)

            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "delivery_attempts" in tables:
                cur = conn.execute(
                    """UPDATE delivery_attempts
                       SET state='NEEDS_RECONCILIATION',updated_at=?
                       WHERE identity_id=? AND state IN
                         ('QUEUED','CLAIMED','DISPATCHING','UNKNOWN','FAILED_RETRYABLE')""",
                    (restored_at, identity_id),
                )
                counts["attempts"] = int(cur.rowcount)

            cur = conn.execute(
                """UPDATE delegations SET revoked_at=?
                   WHERE identity_id=? AND revoked_at IS NULL""",
                (restored_at, identity_id),
            )
            counts["delegations"] = int(cur.rowcount)
            cur = conn.execute(
                "DELETE FROM execution_authorizations WHERE identity_id=?",
                (identity_id,),
            )
            counts["execution_auth"] = int(cur.rowcount)
            cur = conn.execute(
                """UPDATE purposes
                   SET state='NEEDS_RECONCILIATION',updated_at=?,
                       last_evaluated_at=?
                   WHERE identity_id=? AND state IN
                     ('SCHEDULED','ACTIVE','WAITING')""",
                (restored_at, restored_at, identity_id),
            )
            counts["purposes"] = int(cur.rowcount)
            if "purpose_occurrences" in tables:
                cur = conn.execute(
                    """UPDATE purpose_occurrences
                       SET state='NEEDS_RECONCILIATION',updated_at=?
                       WHERE identity_id=? AND state IN ('READY','CLAIMED')""",
                    (restored_at, identity_id),
                )
                counts["occurrences"] = int(cur.rowcount)
            cur = conn.execute(
                """UPDATE deliveries
                   SET state='NEEDS_RECONCILIATION',updated_at=?
                   WHERE identity_id=? AND state IN ('PENDING','FAILED')""",
                (restored_at, identity_id),
            )
            counts["deliveries"] = int(cur.rowcount)
            cur = conn.execute(
                """UPDATE provider_registry SET lifecycle_state='DEGRADED',updated_at=?
                   WHERE lifecycle_state NOT IN ('DISABLED','SHUTDOWN')""",
                (restored_at,),
            )
            counts["providers"] = int(cur.rowcount)
            cur = conn.execute(
                "DELETE FROM projections WHERE identity_id=?", (identity_id,)
            )
            counts["projections"] = int(cur.rowcount)
            counts["rebuilt_projections"] = RecoveryManager._rebuild_projections(
                conn, identity_id=identity_id, built_at=restored_at
            )
        return counts

    @staticmethod
    def _propagate_restored_erasure(
        conn,
        *,
        identity_id: str,
        fact_key: str,
    ) -> None:
        rows = conn.execute(
            """SELECT fact_id,claim_id FROM temporal_facts
               WHERE identity_id=? AND fact_key=?""",
            (identity_id, fact_key),
        ).fetchall()
        fact_ids = {str(row["fact_id"]) for row in rows}
        claim_ids = {str(row["claim_id"]) for row in rows}
        if claim_ids:
            placeholders = ",".join("?" for _ in claim_ids)
            conn.execute(
                """UPDATE claims SET status='ERASED'
                   WHERE identity_id=? AND claim_id IN (%s)
                     AND status!='ERASED'""" % placeholders,
                (identity_id, *sorted(claim_ids)),
            )
        if fact_ids:
            relationships = conn.execute(
                """SELECT principal_id,source_fact_ids_json
                   FROM relationship_state WHERE identity_id=?""",
                (identity_id,),
            ).fetchall()
            for row in relationships:
                try:
                    sources = {
                        str(value)
                        for value in json.loads(str(row["source_fact_ids_json"]))
                    }
                except (TypeError, ValueError):
                    sources = fact_ids
                if sources & fact_ids:
                    conn.execute(
                        """DELETE FROM relationship_state
                           WHERE identity_id=? AND principal_id=?""",
                        (identity_id, str(row["principal_id"])),
                    )

    @staticmethod
    def _rebuild_projections(conn, *, identity_id: str, built_at: str) -> int:
        rows = conn.execute(
            """SELECT tf.fact_id,tf.fact_key,tf.subject,tf.predicate,
                      tf.value_json,tf.cardinality,tf.revision,
                      far.current_revision,far.erasure_generation
               FROM temporal_facts tf
               JOIN fact_authority_revisions far
                 ON far.identity_id=tf.identity_id
                AND far.fact_key=tf.fact_key
               WHERE tf.identity_id=? AND tf.status='CURRENT'
               ORDER BY tf.fact_key,tf.revision,tf.fact_id""",
            (identity_id,),
        ).fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(str(row["fact_key"]), []).append(row)

        inserted = 0
        for fact_key in sorted(grouped):
            group = grouped[fact_key]
            last = group[-1]
            source_ids = [str(row["fact_id"]) for row in group]
            value = {
                "subject": str(last["subject"]),
                "predicate": str(last["predicate"]),
                "cardinality": str(last["cardinality"]),
                "values": [json.loads(str(row["value_json"])) for row in group],
            }
            conn.execute(
                """INSERT INTO projections(
                       identity_id,projection_key,projection_type,value_json,
                       source_fact_ids_json,builder_version,built_at,
                       source_revision,erasure_generation
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    identity_id,
                    fact_key,
                    "CURRENT_FACT",
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        source_ids,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "recovery-current-fact-v1",
                    built_at,
                    int(last["current_revision"]),
                    int(last["erasure_generation"]),
                ),
            )
            inserted += 1
        return inserted

    @staticmethod
    def _verify_candidate(db: Database, identity_id: str, fence_identity: dict) -> None:
        RecoveryManager._require_healthy(db, "candidate after prepare")
        verify_schema(db)
        with db.transaction() as conn:
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                raise RestoreInvariantError("candidate foreign_key_check failed")
            identities = set()
            for table in ("canonical_events", "temporal_facts", "effects", "outbox"):
                for row in conn.execute(
                    "SELECT DISTINCT identity_id FROM %s" % table
                ).fetchall():
                    if row[0] is not None:
                        identities.add(str(row[0]))
            if identities and identity_id not in identities:
                raise RestoreInvariantError("identity continuity smoke failed")
            for tombstone in fence_identity.get("tombstones", []):
                fact_key = str(tombstone["target_id"])
                authority = conn.execute(
                    """SELECT last_source_ingest_revision,erasure_generation
                       FROM fact_authority_revisions
                       WHERE identity_id=? AND fact_key=?""",
                    (identity_id, fact_key),
                ).fetchone()
                tombstone_generation = int(tombstone["erasure_generation"])
                tombstone_source = int(
                    tombstone.get("source_ingest_revision") or 0
                )
                if authority is None:
                    raise RestoreInvariantError(
                        "erasure fence authority revision is missing"
                    )
                if int(authority["erasure_generation"]) < tombstone_generation:
                    raise RestoreInvariantError(
                        "erasure generation is behind trusted fence"
                    )
                # Active state is valid only when the DB has already processed
                # this erasure generation and then consumed a newer source.
                if int(authority["last_source_ingest_revision"]) <= tombstone_source:
                    resurrected = conn.execute(
                        """SELECT 1 FROM temporal_facts
                           WHERE identity_id=? AND fact_key=? AND status!='DELETED'
                           LIMIT 1""",
                        (identity_id, fact_key),
                    ).fetchone()
                    if resurrected is not None:
                        raise RestoreInvariantError(
                            "erasure fence was not applied"
                        )
        RecoveryManager._verify_no_replayable_restore_work(db, identity_id)

    @staticmethod
    def _verify_no_replayable_restore_work(db: Database, identity_id: str) -> None:
        with db.transaction() as conn:
            row = conn.execute(
                """SELECT 1 FROM outbox WHERE identity_id=? AND state IN
                   ('PENDING','CLAIMED','FAILED_RETRYABLE','DISPATCHING') LIMIT 1""",
                (identity_id,),
            ).fetchone()
            if row is not None:
                raise RestoreInvariantError("restored executable outbox work remains")
            purpose = conn.execute(
                """SELECT 1 FROM purposes WHERE identity_id=? AND state IN
                   ('SCHEDULED','ACTIVE','WAITING') LIMIT 1""",
                (identity_id,),
            ).fetchone()
            if purpose is not None:
                raise RestoreInvariantError("restored executable purpose remains")
            auth = conn.execute(
                """SELECT 1 FROM execution_authorizations
                   WHERE identity_id=? LIMIT 1""",
                (identity_id,),
            ).fetchone()
            if auth is not None:
                raise RestoreInvariantError("restored execution authorization remains reusable")

    @staticmethod
    def _require_healthy(db: Database, label: str) -> None:
        try:
            healthy = db.is_healthy()
        except sqlite3.DatabaseError as exc:
            raise RestoreInvariantError(
                "%s integrity_check failed: %s" % (label, exc)
            ) from exc
        if not healthy:
            raise RestoreInvariantError("%s integrity_check failed" % label)

    @staticmethod
    def _cleanup_sqlite_artifact(path: Path) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()

    @staticmethod
    def _checkpoint(path: Path) -> None:
        db = Database(path)
        conn = db.connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
