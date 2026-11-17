from __future__ import annotations

import json
import sqlite3
from typing import List, Optional

from xiaoyu.contracts import Taint, TrustClass
from xiaoyu.contracts.common import datetime_from_text, datetime_to_text
from xiaoyu.core.events import (
    CanonicalEvent,
    legacy_event_to_envelope,
    stable_event_id,
)


class CanonicalEventConflict(RuntimeError):
    """Stable source/event identity was reused with different semantics."""


_COLUMNS = (
    "event_id,identity_id,turn_id,event_type,surface,source_type,principal_id,"
    "audience_scope,context_space,trust_class,taint_json,eligible_for_memory,"
    "payload_type,payload_json,observed_at,recorded_at,correlation_id,schema_version,"
    "source_namespace,source_event_key,semantic_digest"
)


class CanonicalEventRepository:
    def append(self, conn: sqlite3.Connection, event: CanonicalEvent) -> bool:
        existing = self._find_existing_identity(conn, event)
        if existing is not None:
            if existing.semantic_digest == event.semantic_digest:
                return False
            raise CanonicalEventConflict(
                "canonical source identity reused with different semantics: %s"
                % (event.source_event_key or event.event_id)
            )

        try:
            conn.execute(
                "INSERT INTO canonical_events(%s) VALUES(%s)"
                % (
                    _COLUMNS,
                    ",".join("?" for _ in range(21)),
                ),
                event.storage_tuple(),
            )
        except sqlite3.IntegrityError as exc:
            existing = self._find_existing_identity(conn, event)
            if (
                existing is not None
                and existing.semantic_digest == event.semantic_digest
            ):
                return False
            raise CanonicalEventConflict(
                "canonical event conflicts with persisted identity: %s"
                % event.event_id
            ) from exc

        conn.execute(
            """INSERT INTO canonical_event_ingest(
                   event_id,identity_id,inserted_at
               ) VALUES(?,?,?)""",
            (
                event.event_id,
                event.identity_id,
                datetime_to_text(event.recorded_at, "recorded_at"),
            ),
        )
        return True

    def append_or_get(
        self,
        conn: sqlite3.Connection,
        event: CanonicalEvent,
    ) -> CanonicalEvent:
        if self.append(conn, event):
            return event
        if event.source_event_key is not None:
            persisted = self.get_by_source(
                conn,
                event.identity_id,
                event.source_namespace,
                event.source_event_key,
            )
        else:
            persisted = self.get(conn, event.event_id)
        if persisted is None:
            raise RuntimeError("idempotent canonical event disappeared")
        return persisted

    def _find_existing_identity(
        self,
        conn: sqlite3.Connection,
        event: CanonicalEvent,
    ) -> Optional[CanonicalEvent]:
        if event.source_event_key is not None:
            found = self.get_by_source(
                conn,
                event.identity_id,
                event.source_namespace,
                event.source_event_key,
            )
            if found is not None:
                return found
        return self.get(conn, event.event_id)

    def get(
        self,
        conn: sqlite3.Connection,
        event_id: str,
    ) -> Optional[CanonicalEvent]:
        row = conn.execute(
            "SELECT %s FROM canonical_events WHERE event_id=?"
            % _COLUMNS,
            (event_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def get_by_source(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        source_namespace: str,
        source_event_key: str,
    ) -> Optional[CanonicalEvent]:
        row = conn.execute(
            """SELECT %s FROM canonical_events
               WHERE identity_id=? AND source_namespace=? AND source_event_key=?"""
            % _COLUMNS,
            (identity_id, source_namespace, source_event_key),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def get_ingest_revision(
        self,
        conn: sqlite3.Connection,
        event_id: str,
    ) -> int:
        row = conn.execute(
            """SELECT ingest_revision FROM canonical_event_ingest
               WHERE event_id=?""",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError("missing ingest revision for event %s" % event_id)
        return int(row[0])

    def list_turn(
        self,
        conn: sqlite3.Connection,
        turn_id: str,
    ) -> List[CanonicalEvent]:
        rows = conn.execute(
            "SELECT %s FROM canonical_events "
            "WHERE turn_id=? ORDER BY recorded_at,event_id"
            % _COLUMNS,
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
            taint=tuple(
                Taint(value)
                for value in json.loads(row["taint_json"])
            ),
            eligible_for_memory=bool(
                row["eligible_for_memory"]
            ),
            payload_type=str(row["payload_type"]),
            payload=json.loads(row["payload_json"]),
            observed_at=datetime_from_text(
                str(row["observed_at"]),
                "observed_at",
            ),
            recorded_at=datetime_from_text(
                str(row["recorded_at"]),
                "recorded_at",
            ),
            correlation_id=str(row["correlation_id"]),
            schema_version=int(row["schema_version"]),
            source_namespace=str(
                row["source_namespace"] or "legacy"
            ),
            source_event_key=row["source_event_key"],
            semantic_digest=str(
                row["semantic_digest"] or ""
            ),
        )


class LegacyEventShadowWriter:
    """Writes a V1 canonical mirror using the caller's SQLite transaction."""

    def __init__(
        self,
        repository: Optional[CanonicalEventRepository] = None,
    ) -> None:
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
        metadata = dict(extra or {})
        envelope = legacy_event_to_envelope(
            legacy_event_id=legacy_event_id,
            at=at,
            kind=kind,
            actor=actor,
            content=content,
            extra=metadata,
        )

        explicit_source_key = metadata.get("source_event_key")
        if explicit_source_key is None:
            source_namespace = "legacy"
            source_event_key = str(int(legacy_event_id))
            event_id_override = envelope.event_id
        else:
            source_namespace = str(
                metadata.get("source_namespace")
                or envelope.surface
                or "surface"
            )
            source_event_key = str(explicit_source_key)
            event_id_override = stable_event_id(
                identity_id,
                source_namespace,
                source_event_key,
            )

        event = CanonicalEvent.from_envelope(
            identity_id=identity_id,
            event_type=kind,
            envelope=envelope,
            principal_id=envelope.principal_hint,
            turn_id=turn_id,
            recorded_at=envelope.observed_at,
            source_namespace=source_namespace,
            source_event_key=source_event_key,
            event_id_override=event_id_override,
        )
        return self.repository.append_or_get(conn, event)
