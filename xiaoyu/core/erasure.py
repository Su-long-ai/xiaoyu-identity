from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Set


class ManagedErasurePropagator:
    """Propagate a fact deletion through managed derived/read-side state.

    Canonical events and the erasure tombstone remain auditable authority.
    Claims that solely backed the erased fact are retained but marked ERASED.
    Derived projections are rebuildable and are therefore discarded.
    """

    def apply_fact_delete(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        fact_key: str,
    ) -> dict:
        rows = conn.execute(
            """SELECT fact_id,claim_id
               FROM temporal_facts
               WHERE identity_id=? AND fact_key=?""",
            (identity_id, fact_key),
        ).fetchall()
        fact_ids: Set[str] = {str(row["fact_id"]) for row in rows}
        claim_ids: Set[str] = {str(row["claim_id"]) for row in rows}

        claims_erased = 0
        if claim_ids:
            placeholders = ",".join("?" for _ in claim_ids)
            cur = conn.execute(
                """UPDATE claims SET status='ERASED'
                   WHERE identity_id=? AND claim_id IN (%s)
                     AND status!='ERASED'""" % placeholders,
                (identity_id, *sorted(claim_ids)),
            )
            claims_erased = int(cur.rowcount)

        projections_cleared = int(
            conn.execute(
                "DELETE FROM projections WHERE identity_id=?",
                (identity_id,),
            ).rowcount
        )
        relationships_cleared = self._clear_relationships(
            conn, identity_id=identity_id, fact_ids=fact_ids
        )
        return {
            "claims_erased": claims_erased,
            "projections_cleared": projections_cleared,
            "relationships_cleared": relationships_cleared,
        }

    @staticmethod
    def _clear_relationships(
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        fact_ids: Iterable[str],
    ) -> int:
        fact_ids = set(fact_ids)
        if not fact_ids:
            return 0
        rows = conn.execute(
            """SELECT principal_id,source_fact_ids_json
               FROM relationship_state WHERE identity_id=?""",
            (identity_id,),
        ).fetchall()
        cleared = 0
        for row in rows:
            try:
                source_ids = {
                    str(value)
                    for value in json.loads(str(row["source_fact_ids_json"]))
                }
            except (TypeError, ValueError):
                # A malformed derived row cannot be trusted during erasure.
                source_ids = fact_ids
            if source_ids & fact_ids:
                cleared += int(
                    conn.execute(
                        """DELETE FROM relationship_state
                           WHERE identity_id=? AND principal_id=?""",
                        (identity_id, str(row["principal_id"])),
                    ).rowcount
                )
        return cleared
