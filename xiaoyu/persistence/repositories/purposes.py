from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from xiaoyu.contracts.common import (
    canonical_json,
    datetime_from_text,
    datetime_to_text,
)
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


class PurposeRepository:
    def insert(
        self,
        conn: sqlite3.Connection,
        purpose: Purpose,
        created_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(_utc(created_at), "created_at")
        conn.execute(
            """INSERT INTO purposes(
                   purpose_id,identity_id,owner_type,owner_id,state,kind,source_event_id,
                   payload_json,scheduled_wall_time,timezone,resolved_utc_time,miss_policy,
                   created_at,updated_at,last_evaluated_at,quiet_class,duplicate_key,revision
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                purpose.purpose_id,
                purpose.identity_id,
                purpose.owner_type.value,
                purpose.owner_id,
                purpose.state.value,
                purpose.kind.value,
                purpose.source_event_id,
                canonical_json(purpose.payload),
                purpose.scheduled_wall_time,
                purpose.timezone_name,
                None if purpose.resolved_utc_time is None else datetime_to_text(
                    _utc(purpose.resolved_utc_time), "resolved_utc_time"
                ),
                purpose.miss_policy.value,
                timestamp,
                timestamp,
                None if purpose.last_evaluated_at is None else datetime_to_text(
                    _utc(purpose.last_evaluated_at), "last_evaluated_at"
                ),
                purpose.quiet_class,
                purpose.duplicate_key,
                purpose.revision,
            ),
        )

    def get(self, conn: sqlite3.Connection, purpose_id: str) -> Optional[Purpose]:
        row = conn.execute(
            "SELECT * FROM purposes WHERE purpose_id=?", (purpose_id,)
        ).fetchone()
        return None if row is None else self._from_row(row)

    def transition(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        from_states: tuple[PurposeState, ...],
        to_state: PurposeState,
        updated_at: datetime,
    ) -> bool:
        placeholders = ",".join("?" for _ in from_states)
        stamp = datetime_to_text(_utc(updated_at), "updated_at")
        cur = conn.execute(
            "UPDATE purposes SET state=?,updated_at=?,last_evaluated_at=? "
            "WHERE purpose_id=? AND state IN (%s)" % placeholders,
            (
                to_state.value,
                stamp,
                stamp,
                purpose_id,
                *(state.value for state in from_states),
            ),
        )
        return cur.rowcount == 1

    def activate_occurrence(
        self,
        conn: sqlite3.Connection,
        purpose: Purpose,
        activated_at: datetime,
    ) -> str:
        if purpose.resolved_utc_time is None:
            raise ValueError("scheduled purpose needs resolved_utc_time")
        occurrence_id = "%s:r%d" % (
            purpose.purpose_id,
            purpose.revision,
        )
        stamp = datetime_to_text(_utc(activated_at), "activated_at")
        due = datetime_to_text(
            _utc(purpose.resolved_utc_time),
            "scheduled_for_utc",
        )
        conn.execute(
            """INSERT INTO purpose_occurrences(
                   occurrence_id,identity_id,purpose_id,purpose_revision,
                   scheduled_for_utc,state,effect_id,activated_at,updated_at
               ) VALUES(?,?,?,?,?,'READY',NULL,?,?)""",
            (
                occurrence_id,
                purpose.identity_id,
                purpose.purpose_id,
                purpose.revision,
                due,
                stamp,
                stamp,
            ),
        )
        cur = conn.execute(
            """UPDATE purposes
               SET state='ACTIVE',updated_at=?,last_evaluated_at=?
               WHERE purpose_id=? AND state='SCHEDULED' AND revision=?""",
            (
                stamp,
                stamp,
                purpose.purpose_id,
                purpose.revision,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("purpose changed before activation")
        return occurrence_id

    def list_ready_occurrences(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT * FROM purpose_occurrences
               WHERE identity_id=? AND state='READY'
               ORDER BY scheduled_for_utc,occurrence_id""",
            (identity_id,),
        ).fetchall()

    def _uncertain_current_revision(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        revision: int,
    ) -> bool:
        row = conn.execute(
            """SELECT 1 FROM effects
               WHERE purpose_id=? AND purpose_revision=?
                 AND dispatch_state IN (
                     'DISPATCHING','UNKNOWN','NEEDS_RECONCILIATION'
                 )
               LIMIT 1""",
            (purpose_id, revision),
        ).fetchone()
        return row is not None

    def cancel(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        updated_at: datetime,
    ) -> bool:
        row = conn.execute(
            "SELECT state,revision FROM purposes WHERE purpose_id=?",
            (purpose_id,),
        ).fetchone()
        if row is None:
            return False
        state = PurposeState(str(row["state"]))
        revision = int(row["revision"])
        if state not in (
            PurposeState.CONFIRMED,
            PurposeState.SCHEDULED,
            PurposeState.ACTIVE,
            PurposeState.WAITING,
        ):
            return False
        stamp = datetime_to_text(_utc(updated_at), "updated_at")
        if self._uncertain_current_revision(conn, purpose_id, revision):
            conn.execute(
                """UPDATE purposes
                   SET state='NEEDS_RECONCILIATION',updated_at=?,
                       last_evaluated_at=?
                   WHERE purpose_id=? AND revision=?""",
                (stamp, stamp, purpose_id, revision),
            )
            return False
        conn.execute(
            """UPDATE purpose_occurrences
               SET state='CANCELLED',updated_at=?
               WHERE purpose_id=? AND purpose_revision=?
                 AND state='READY'""",
            (stamp, purpose_id, revision),
        )
        cur = conn.execute(
            """UPDATE purposes
               SET state='CANCELLED',revision=revision+1,
                   updated_at=?,last_evaluated_at=?
               WHERE purpose_id=? AND revision=?""",
            (stamp, stamp, purpose_id, revision),
        )
        return cur.rowcount == 1

    def complete(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        updated_at: datetime,
    ) -> bool:
        stamp = datetime_to_text(_utc(updated_at), "updated_at")
        row = conn.execute(
            "SELECT revision FROM purposes WHERE purpose_id=?",
            (purpose_id,),
        ).fetchone()
        if row is None:
            return False
        revision = int(row["revision"])
        conn.execute(
            """UPDATE purpose_occurrences
               SET state='COMPLETED',updated_at=?
               WHERE purpose_id=? AND purpose_revision=?
                 AND state IN ('READY','CLAIMED')""",
            (stamp, purpose_id, revision),
        )
        cur = conn.execute(
            """UPDATE purposes SET state='COMPLETED',updated_at=?,
                      last_evaluated_at=?
               WHERE purpose_id=? AND revision=?
                 AND state IN ('ACTIVE','WAITING')""",
            (stamp, stamp, purpose_id, revision),
        )
        return cur.rowcount == 1

    def reschedule(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        scheduled_wall_time: str,
        timezone_name: str,
        resolved_utc_time: datetime,
        updated_at: datetime,
    ) -> bool:
        row = conn.execute(
            "SELECT state,revision FROM purposes WHERE purpose_id=?",
            (purpose_id,),
        ).fetchone()
        if row is None:
            return False
        state = PurposeState(str(row["state"]))
        revision = int(row["revision"])
        if state not in (
            PurposeState.CONFIRMED,
            PurposeState.SCHEDULED,
            PurposeState.ACTIVE,
            PurposeState.WAITING,
        ):
            return False
        stamp = datetime_to_text(_utc(updated_at), "updated_at")
        if self._dispatching_current_revision(conn, purpose_id, revision):
            conn.execute(
                """UPDATE purposes
                   SET state='NEEDS_RECONCILIATION',updated_at=?,
                       last_evaluated_at=?
                   WHERE purpose_id=? AND revision=?""",
                (stamp, stamp, purpose_id, revision),
            )
            return False
        conn.execute(
            """UPDATE purpose_occurrences
               SET state='SUPERSEDED',updated_at=?
               WHERE purpose_id=? AND purpose_revision=?
                 AND state='READY'""",
            (stamp, purpose_id, revision),
        )
        cur = conn.execute(
            """UPDATE purposes
               SET state='SCHEDULED',scheduled_wall_time=?,timezone=?,
                   resolved_utc_time=?,revision=revision+1,
                   updated_at=?,last_evaluated_at=?
               WHERE purpose_id=? AND revision=?""",
            (
                scheduled_wall_time,
                timezone_name,
                datetime_to_text(_utc(resolved_utc_time), "resolved_utc_time"),
                stamp,
                stamp,
                purpose_id,
                revision,
            ),
        )
        return cur.rowcount == 1

    def list_due(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        now: datetime,
        limit: int = 100,
    ) -> List[Purpose]:
        rows = conn.execute(
            """SELECT * FROM purposes
               WHERE identity_id=? AND state='SCHEDULED'
                 AND resolved_utc_time IS NOT NULL
                 AND resolved_utc_time<=?
               ORDER BY resolved_utc_time,purpose_id LIMIT ?""",
            (
                identity_id,
                datetime_to_text(_utc(now), "now"),
                max(1, min(limit, 500)),
            ),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> Purpose:
        return Purpose(
            purpose_id=str(row["purpose_id"]),
            identity_id=str(row["identity_id"]),
            owner_type=PurposeOwner(str(row["owner_type"])),
            owner_id=row["owner_id"],
            state=PurposeState(str(row["state"])),
            kind=PurposeKind(str(row["kind"])),
            source_event_id=str(row["source_event_id"]),
            payload=json.loads(row["payload_json"]),
            scheduled_wall_time=row["scheduled_wall_time"],
            timezone_name=row["timezone"],
            resolved_utc_time=None
            if row["resolved_utc_time"] is None
            else datetime_from_text(
                row["resolved_utc_time"], "resolved_utc_time"
            ),
            miss_policy=MissPolicy(str(row["miss_policy"])),
            quiet_class=str(row["quiet_class"]),
            duplicate_key=row["duplicate_key"],
            last_evaluated_at=None
            if row["last_evaluated_at"] is None
            else datetime_from_text(
                row["last_evaluated_at"], "last_evaluated_at"
            ),
            revision=int(row["revision"]),
        )
