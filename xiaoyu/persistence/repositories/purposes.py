from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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


class PurposeRepository:
    def insert(
        self,
        conn: sqlite3.Connection,
        purpose: Purpose,
        created_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO purposes(
                   purpose_id,identity_id,owner_type,owner_id,state,kind,source_event_id,
                   payload_json,scheduled_wall_time,timezone,resolved_utc_time,miss_policy,
                   created_at,updated_at,last_evaluated_at,quiet_class,duplicate_key
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                None
                if purpose.resolved_utc_time is None
                else datetime_to_text(
                    purpose.resolved_utc_time, "resolved_utc_time"
                ),
                purpose.miss_policy.value,
                timestamp,
                timestamp,
                None
                if purpose.last_evaluated_at is None
                else datetime_to_text(
                    purpose.last_evaluated_at, "last_evaluated_at"
                ),
                purpose.quiet_class,
                purpose.duplicate_key,
            ),
        )

    def get(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
    ) -> Optional[Purpose]:
        row = conn.execute(
            "SELECT * FROM purposes WHERE purpose_id=?",
            (purpose_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def transition(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        from_states: tuple[PurposeState, ...],
        to_state: PurposeState,
        updated_at: datetime,
        *,
        resolved_utc_time: Optional[datetime] = None,
        scheduled_wall_time: Optional[str] = None,
    ) -> bool:
        placeholders = ",".join("?" for _ in from_states)
        assignments = ["state=?", "updated_at=?", "last_evaluated_at=?"]
        values: list[object] = [
            to_state.value,
            datetime_to_text(updated_at, "updated_at"),
            datetime_to_text(updated_at, "last_evaluated_at"),
        ]
        if resolved_utc_time is not None:
            assignments.append("resolved_utc_time=?")
            values.append(
                datetime_to_text(
                    resolved_utc_time, "resolved_utc_time"
                )
            )
        if scheduled_wall_time is not None:
            assignments.append("scheduled_wall_time=?")
            values.append(scheduled_wall_time)
        values.append(purpose_id)
        values.extend(state.value for state in from_states)
        cur = conn.execute(
            "UPDATE purposes SET %s WHERE purpose_id=? AND state IN (%s)"
            % (",".join(assignments), placeholders),
            tuple(values),
        )
        return cur.rowcount == 1

    def cancel(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        updated_at: datetime,
    ) -> bool:
        return self.transition(
            conn,
            purpose_id,
            (
                PurposeState.CONFIRMED,
                PurposeState.SCHEDULED,
                PurposeState.ACTIVE,
                PurposeState.WAITING,
            ),
            PurposeState.CANCELLED,
            updated_at,
        )

    def complete(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        updated_at: datetime,
    ) -> bool:
        return self.transition(
            conn,
            purpose_id,
            (PurposeState.ACTIVE, PurposeState.WAITING),
            PurposeState.COMPLETED,
            updated_at,
        )

    def reschedule(
        self,
        conn: sqlite3.Connection,
        purpose_id: str,
        scheduled_wall_time: str,
        timezone_name: str,
        resolved_utc_time: datetime,
        updated_at: datetime,
    ) -> bool:
        cur = conn.execute(
            """UPDATE purposes
               SET state='SCHEDULED',scheduled_wall_time=?,timezone=?,resolved_utc_time=?,
                   updated_at=?,last_evaluated_at=?
               WHERE purpose_id=? AND state IN ('CONFIRMED','SCHEDULED','ACTIVE','WAITING')""",
            (
                scheduled_wall_time,
                timezone_name,
                datetime_to_text(
                    resolved_utc_time, "resolved_utc_time"
                ),
                datetime_to_text(updated_at, "updated_at"),
                datetime_to_text(updated_at, "last_evaluated_at"),
                purpose_id,
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
                datetime_to_text(now, "now"),
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
        )
