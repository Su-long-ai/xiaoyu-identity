from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts.common import (
    canonical_json,
    datetime_to_text,
)


def persona_digest(persona: dict) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(persona).encode("utf-8")
    ).hexdigest()


def authority_digest(
    identity_id: str,
    revision: int,
    persona_hash: str,
) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(
            {
                "identity_id": identity_id,
                "persona_revision": int(revision),
                "persona_digest": persona_hash,
            }
        ).encode("utf-8")
    ).hexdigest()


class SelfAuthorityRepository:
    def get_identity(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT identity_id,created_at,current_persona_revision,
                      authority_digest,namespace
               FROM self_identity WHERE identity_id=?""",
            (identity_id,),
        ).fetchone()

    def current_persona(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT spv.*
               FROM self_identity si
               JOIN self_persona_versions spv
                 ON spv.identity_id=si.identity_id
                AND spv.revision=si.current_persona_revision
               WHERE si.identity_id=?""",
            (identity_id,),
        ).fetchone()

    def persona_revision(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        revision: int,
    ):
        return conn.execute(
            """SELECT * FROM self_persona_versions
               WHERE identity_id=? AND revision=?""",
            (identity_id, int(revision)),
        ).fetchone()

    def find_persona_digest(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        digest: str,
    ):
        return conn.execute(
            """SELECT * FROM self_persona_versions
               WHERE identity_id=? AND persona_digest=?""",
            (identity_id, digest),
        ).fetchone()

    def list_persona_versions(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
    ):
        return conn.execute(
            """SELECT * FROM self_persona_versions
               WHERE identity_id=?
               ORDER BY revision""",
            (identity_id,),
        ).fetchall()

    def initialize(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        created_at: datetime,
        persona: dict,
        reason: str,
        source_event_ids: list[str],
        legacy_persona_version: Optional[int] = None,
    ) -> int:
        digest = persona_digest(persona)
        existing = self.get_identity(conn, identity_id)
        if existing is not None:
            current = self.current_persona(conn, identity_id)
            if (
                current is not None
                and str(current["persona_digest"]) == digest
            ):
                return int(existing["current_persona_revision"])
            raise RuntimeError(
                "self identity already initialized with different persona"
            )

        revision = 1
        conn.execute(
            """INSERT INTO self_identity(
                   identity_id,created_at,current_persona_revision,
                   authority_digest,namespace
               ) VALUES(?,?,?,?,?)""",
            (
                identity_id,
                datetime_to_text(created_at, "created_at"),
                revision,
                authority_digest(identity_id, revision, digest),
                "xiaoyu",
            ),
        )
        conn.execute(
            """INSERT INTO self_persona_versions(
                   identity_id,revision,persona_json,persona_digest,
                   reason,source_event_ids_json,created_at,
                   legacy_persona_version
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                identity_id,
                revision,
                canonical_json(persona),
                digest,
                reason,
                canonical_json(source_event_ids),
                datetime_to_text(created_at, "created_at"),
                legacy_persona_version,
            ),
        )
        return revision

    def append_persona(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        expected_revision: int,
        persona: dict,
        reason: str,
        source_event_ids: list[str],
        created_at: datetime,
        legacy_persona_version: Optional[int] = None,
    ) -> int:
        identity = self.get_identity(conn, identity_id)
        if identity is None:
            raise KeyError("unknown self identity %s" % identity_id)
        current_revision = int(identity["current_persona_revision"])
        if current_revision != int(expected_revision):
            raise RuntimeError(
                "persona revision conflict: expected %d current %d"
                % (expected_revision, current_revision)
            )

        digest = persona_digest(persona)
        revision = current_revision + 1
        conn.execute(
            """INSERT INTO self_persona_versions(
                   identity_id,revision,persona_json,persona_digest,
                   reason,source_event_ids_json,created_at,
                   legacy_persona_version
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                identity_id,
                revision,
                canonical_json(persona),
                digest,
                reason,
                canonical_json(source_event_ids),
                datetime_to_text(created_at, "created_at"),
                legacy_persona_version,
            ),
        )
        cur = conn.execute(
            """UPDATE self_identity
               SET current_persona_revision=?,authority_digest=?
               WHERE identity_id=? AND current_persona_revision=?""",
            (
                revision,
                authority_digest(identity_id, revision, digest),
                identity_id,
                current_revision,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("persona revision changed concurrently")
        return revision

    @staticmethod
    def decode_persona(row) -> dict:
        return json.loads(str(row["persona_json"]))

    @staticmethod
    def decode_sources(row) -> tuple[str, ...]:
        return tuple(
            str(value)
            for value in json.loads(
                str(row["source_event_ids_json"])
            )
        )
