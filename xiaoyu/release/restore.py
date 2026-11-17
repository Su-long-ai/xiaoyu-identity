from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from identity_core import IdentityStore
from xiaoyu.persistence import Database, apply_migrations


class ManagedRestoreError(RuntimeError):
    pass


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name=?""",
        (table,),
    ).fetchone() is not None


def _identity_id(conn: sqlite3.Connection) -> str:
    row=conn.execute(
        "SELECT value FROM settings WHERE key='persona'"
    ).fetchone()
    if row is None:
        raise ManagedRestoreError("identity persona is missing")
    value=json.loads(row[0])
    identity_id=str(value.get("id") or "").strip()
    if not identity_id:
        raise ManagedRestoreError("identity id is missing")
    return identity_id


def _setting_int(
    conn: sqlite3.Connection,
    key: str,
    default: int = 0,
) -> int:
    row=conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()
    if row is None:
        return default
    try:
        return int(json.loads(row[0]))
    except (TypeError,ValueError, json.JSONDecodeError):
        return default


def _set_setting_int(
    conn: sqlite3.Connection,
    key: str,
    value: int,
) -> None:
    conn.execute(
        """INSERT INTO settings(key,value) VALUES(?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key,json.dumps(int(value))),
    )


def _apply_live_erasure_fences(
    live: sqlite3.Connection,
    restored: sqlite3.Connection,
    identity_id: str,
) -> int:
    live_rows=live.execute(
        """SELECT * FROM erasure_tombstones
           WHERE identity_id=?
           ORDER BY erasure_generation,erasure_id""",
        (identity_id,),
    ).fetchall()
    restored_max=restored.execute(
        """SELECT COALESCE(MAX(erasure_generation),0)
           FROM erasure_tombstones WHERE identity_id=?""",
        (identity_id,),
    ).fetchone()[0]
    applied=0
    for row in live_rows:
        generation=int(row["erasure_generation"])
        if generation<=int(restored_max or 0):
            continue
        target_type=str(row["target_type"])
        target_id=str(row["target_id"])

        if target_type=="memory":
            restored.execute(
                "DELETE FROM memories WHERE memory_id=?",
                (int(target_id),),
            )
        elif target_type=="fact_key":
            restored.execute(
                """UPDATE temporal_facts SET status='DELETED'
                   WHERE identity_id=? AND fact_key=?""",
                (identity_id,target_id),
            )
            live_revision=live.execute(
                """SELECT * FROM fact_authority_revisions
                   WHERE identity_id=? AND fact_key=?""",
                (identity_id,target_id),
            ).fetchone()
            if live_revision is not None:
                restored.execute(
                    """INSERT INTO fact_authority_revisions(
                           identity_id,fact_key,current_revision,
                           last_source_ingest_revision,erasure_generation,updated_at
                       ) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(identity_id,fact_key) DO UPDATE SET
                           current_revision=excluded.current_revision,
                           last_source_ingest_revision=excluded.last_source_ingest_revision,
                           erasure_generation=excluded.erasure_generation,
                           updated_at=excluded.updated_at""",
                    (
                        identity_id,
                        target_id,
                        int(live_revision["current_revision"]),
                        int(live_revision["last_source_ingest_revision"]),
                        int(live_revision["erasure_generation"]),
                        str(live_revision["updated_at"]),
                    ),
                )
        else:
            raise ManagedRestoreError(
                "unsupported erasure target_type: %s" % target_type
            )

        restored.execute(
            """INSERT OR IGNORE INTO erasure_tombstones(
                   erasure_id,identity_id,target_type,target_id,
                   erasure_generation,requested_at,applied_at,source_event_id,
                   source_ingest_revision,mutation_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                row["erasure_id"],
                row["identity_id"],
                row["target_type"],
                row["target_id"],
                row["erasure_generation"],
                row["requested_at"],
                row["applied_at"],
                row["source_event_id"],
                row["source_ingest_revision"],
                row["mutation_id"],
            ),
        )
        restored_max=generation
        applied+=1

    # Keep legacy freshness monotonic relative to the live authority.
    _set_setting_int(
        restored,
        "memory_change_seq",
        max(
            _setting_int(restored,"memory_change_seq",0),
            _setting_int(live,"memory_change_seq",0),
        ),
    )
    return applied


def _quarantine_restored_execution(
    conn: sqlite3.Connection,
    restored_at: str,
) -> Dict[str,int]:
    counts={}

    cur=conn.execute(
        """UPDATE effects
           SET dispatch_state='NEEDS_RECONCILIATION',
               verifier_state='RESTORED_REQUIRES_RECONCILIATION',
               updated_at=?
           WHERE dispatch_state NOT IN ('SUCCEEDED','FAILED','VERIFIED')""",
        (restored_at,),
    )
    counts["effects"]=int(cur.rowcount)

    cur=conn.execute(
        """UPDATE outbox
           SET state='NEEDS_RECONCILIATION',updated_at=?
           WHERE state IN ('PENDING','CLAIMED','FAILED_RETRYABLE')""",
        (restored_at,),
    )
    counts["outbox"]=int(cur.rowcount)

    if _table_exists(conn,"delivery_attempts"):
        cur=conn.execute(
            """UPDATE delivery_attempts
               SET state='UNKNOWN',updated_at=?
               WHERE state IN ('QUEUED','DISPATCHING')""",
            (restored_at,),
        )
        counts["delivery_attempts"]=int(cur.rowcount)
        conn.execute(
            """UPDATE deliveries
               SET state='NEEDS_RECONCILIATION',updated_at=?
               WHERE state IN ('PENDING','ATTEMPTING')""",
            (restored_at,),
        )

    if _table_exists(conn,"purpose_occurrences"):
        cur=conn.execute(
            """UPDATE purpose_occurrences
               SET state='NEEDS_RECONCILIATION',updated_at=?
               WHERE state IN ('READY','CLAIMED')""",
            (restored_at,),
        )
        counts["purpose_occurrences"]=int(cur.rowcount)

    cur=conn.execute(
        """UPDATE delegations
           SET revoked_at=?
           WHERE revocable=1 AND revoked_at IS NULL""",
        (restored_at,),
    )
    counts["delegations_revoked"]=int(cur.rowcount)
    return counts


def managed_restore(
    archive,
    current_home,
    new_home,
) -> Dict[str,Any]:
    """Restore an older managed backup without reviving newer deletions/effects.

    This is intentionally distinct from portable import.  A managed rollback
    requires the current live authority so newer erasure fences cannot disappear
    with the old backup.
    """
    current_home=Path(current_home)
    live_path=current_home/"identity.sqlite3"
    if not live_path.is_file():
        raise ManagedRestoreError(
            "current managed authority database is required"
        )

    live=sqlite3.connect(str(live_path),timeout=30)
    live.row_factory=sqlite3.Row
    try:
        if live.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ManagedRestoreError(
                "current managed authority failed integrity_check"
            )
        if not _table_exists(live,"erasure_tombstones"):
            raise ManagedRestoreError(
                "current managed authority has no erasure fence ledger"
            )
        live_identity=_identity_id(live)

        restored_home=IdentityStore.import_to_new_home(
            archive,
            new_home,
        )
        restored_db=Database(
            Path(restored_home)/"identity.sqlite3"
        )
        apply_migrations(restored_db)

        restored=restored_db.connect()
        try:
            if restored.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]!="ok":
                raise ManagedRestoreError(
                    "restored database failed integrity_check"
                )
            restored_identity=_identity_id(restored)
            if restored_identity!=live_identity:
                raise ManagedRestoreError(
                    "archive identity does not match current authority"
                )

            restored.execute("BEGIN IMMEDIATE")
            try:
                applied=_apply_live_erasure_fences(
                    live,
                    restored,
                    live_identity,
                )
                at=datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                )
                quarantined=_quarantine_restored_execution(
                    restored,
                    at,
                )
                restored.commit()
            except Exception:
                restored.rollback()
                raise

            if restored.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]!="ok":
                raise ManagedRestoreError(
                    "post-reconciliation integrity_check failed"
                )
        finally:
            restored.close()

        return {
            "home":str(restored_home),
            "identity_id":live_identity,
            "erasure_fences_applied":applied,
            "quarantined":quarantined,
            "activation_ready":True,
        }
    finally:
        live.close()
