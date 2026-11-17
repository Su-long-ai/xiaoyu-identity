from __future__ import annotations

import json
import sqlite3
from typing import List, Optional

from xiaoyu.contracts import Taint, TrustClass
from xiaoyu.contracts.common import datetime_from_text
from xiaoyu.core.events import CanonicalEvent, legacy_event_to_envelope


class CanonicalEventConflict(RuntimeError):
    """Same canonical event ID was reused with different authoritative content."""


_COLUMNS = (
    "event_id,identity_id,turn_id,event_type,surface,source_type,principal_id,"
    "audience_scope,context_space,trust_class,taint_json,eligible_for_memory,"
    "payload_type,payload_json,observed_at,recorded_at,correlation_id,schema_version"
)


class CanonicalEventRepository:
    def append(self, conn: sqlite3.Connection, event: CanonicalEvent) -> bool:
        try:
            conn.execute(
                "INSERT INTO canonical_events(%s) VALUES(%s)" % (
                    _COLUMNS,
                    ",".join("?" for _ in range(18)),
                ),
                event.storage_tuple(),
            )
            return True
        except sqlite3.IntegrityError as exc:
            row = conn.execute(
                "SELECT %s FROM canonical_events WHERE event_id=?" % _COLUMNS,
                (event.event_id,),
            ).fetchone()
            if row is None:
                raise
            existing = self._from_row(row)
            if existing == event:
                return False
            raise CanonicalEventConflict(
                "canonical event id %s already exists with different content" % event.event_id
            ) from exc

    def get(self, conn: sqlite3.Connection, event_id: str) -> Optional[CanonicalEvent]:
        row = conn.execute(
            "SELECT %s FROM canonical_events WHERE event_id=?" % _COLUMNS,
            (event_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def list_turn(self, conn: sqlite3.Connection, turn_id: str) -> List[CanonicalEvent]:
        rows = conn.execute(
            "SELECT %s FROM canonical_events WHERE turn_id=? ORDER BY recorded_at,event_id" % _COLUMNS,
            (turn_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> CanonicalEvent:
        return CanonicalEvent(
            event_id=str(row["event_id"]),
            identity_id=str(row["identity_id"]),
            turn_id=row["turn_id"],
            event_type=str(row["event_type"]),
            surface=str(row["surface"]),
            source_type=str(row["source_type"]),
            principal_id=row["principal_id"],
            audience_scope=str(row["audience_scope"]),
            context_space=str(row["context_space"]),
            trust_class=TrustClass(str(row["trust_class"])),
            taint=tuple(Taint(value) for value in json.loads(row["taint_json"])),
            eligible_for_memory=bool(row["eligible_for_memory"]),
            payload_type=str(row["payload_type"]),
            payload=json.loads(row["payload_json"]),
            observed_at=datetime_from_text(str(row["observed_at"]), "observed_at"),
            recorded_at=datetime_from_text(str(row["recorded_at"]), "recorded_at"),
            correlation_id=str(row["correlation_id"]),
            schema_version=int(row["schema_version"]),
        )


class LegacyEventShadowWriter:
    """Writes a V1 canonical mirror using the caller's existing SQLite transaction."""

    def __init__(self, repository: Optional[CanonicalEventRepository] = None) -> None:
        self.repository = repository or CanonicalEventRepository()

    def write(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        legacy_event_id: int,
        at: str,
        kind: str,
        actor: str,
        content: str,
        extra=None,
        turn_id: Optional[str] = None,
    ) -> CanonicalEvent:
        envelope = legacy_event_to_envelope(
            legacy_event_id=legacy_event_id,
            at=at,
            kind=kind,
            actor=actor,
            content=content,
            extra=extra,
        )
        event = CanonicalEvent.from_envelope(
            identity_id=identity_id,
            event_type=kind,
            envelope=envelope,
            principal_id=envelope.principal_hint,
            turn_id=turn_id,
            recorded_at=envelope.observed_at,
        )
        self.repository.append(conn, event)
        return event
