from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ErasureWatermarkError(RuntimeError):
    pass


class ExternalErasureFenceStore:
    """Append-only privacy fence kept outside the restorable SQLite snapshot.

    Managed restore treats this sibling file as the latest-known deletion
    authority. It intentionally survives replacement of the database file.
    """

    VERSION = 1

    def __init__(self, db_path, path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path)
        self.path = Path(path) if path is not None else Path(
            str(self.db_path) + ".erasure-watermark.json"
        )

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != self.VERSION:
            raise ErasureWatermarkError("unsupported erasure watermark version")
        identities = payload.get("identities")
        if not isinstance(identities, dict):
            raise ErasureWatermarkError("invalid erasure watermark identities")
        return payload

    def identity(self, identity_id: str) -> Optional[Dict[str, Any]]:
        payload = self.load()
        if payload is None:
            return None
        value = payload["identities"].get(identity_id)
        return None if value is None else dict(value)

    def ensure_identity(self, identity_id: str) -> Dict[str, Any]:
        payload = self.load() or {"version": self.VERSION, "identities": {}}
        identities = payload["identities"]
        if identity_id not in identities:
            identities[identity_id] = {
                "erasure_generation": 0,
                "tombstones": [],
            }
            self._write(payload)
        return dict(identities[identity_id])

    def sync_from_db(self, db, identity_id: str) -> Dict[str, Any]:
        with db.transaction() as conn:
            return self.sync_from_connection(conn, identity_id)

    def sync_from_connection(self, conn, identity_id: str) -> Dict[str, Any]:
        rows = conn.execute(
            """SELECT erasure_id,target_id,erasure_generation,requested_at,
                      applied_at,source_event_id,source_ingest_revision,mutation_id
               FROM erasure_tombstones
               WHERE identity_id=? AND target_type='fact_key'
               ORDER BY erasure_generation,target_id""",
            (identity_id,),
        ).fetchall()
        revisions = {
            str(row["fact_key"]): int(row["current_revision"])
            for row in conn.execute(
                """SELECT fact_key,current_revision
                   FROM fact_authority_revisions WHERE identity_id=?""",
                (identity_id,),
            ).fetchall()
        }
        payload = self.load() or {"version": self.VERSION, "identities": {}}
        existing = payload["identities"].get(
            identity_id, {"erasure_generation": 0, "tombstones": []}
        )
        by_key = {
            (int(item["erasure_generation"]), str(item["target_id"])): dict(item)
            for item in existing.get("tombstones", [])
        }
        generation = int(existing.get("erasure_generation", 0))
        for row in rows:
            item = dict(row)
            item["result_revision"] = revisions.get(str(row["target_id"]))
            by_key[(int(row["erasure_generation"]), str(row["target_id"]))] = item
            generation = max(generation, int(row["erasure_generation"]))
        payload["identities"][identity_id] = {
            "erasure_generation": generation,
            "tombstones": [
                by_key[key] for key in sorted(by_key)
            ],
        }
        self._write(payload)
        return dict(payload["identities"][identity_id])

    def record_fact_delete(
        self,
        *,
        identity_id: str,
        fact_key: str,
        generation: int,
        source_event_id: str,
        source_ingest_revision: int,
        mutation_id: str,
        requested_at: str,
        result_revision: Optional[int] = None,
    ) -> None:
        payload = self.load() or {"version": self.VERSION, "identities": {}}
        identity = payload["identities"].setdefault(
            identity_id, {"erasure_generation": 0, "tombstones": []}
        )
        current_generation = int(identity.get("erasure_generation", 0))
        if int(generation) < current_generation:
            raise ErasureWatermarkError(
                "erasure generation cannot move backwards"
            )
        item = {
            "erasure_id": "erasure:" + mutation_id,
            "target_id": fact_key,
            "erasure_generation": int(generation),
            "requested_at": requested_at,
            "applied_at": requested_at,
            "source_event_id": source_event_id,
            "source_ingest_revision": int(source_ingest_revision),
            "mutation_id": mutation_id,
            "result_revision": result_revision,
        }
        tombstones = [
            dict(value) for value in identity.get("tombstones", [])
            if str(value.get("mutation_id")) != mutation_id
        ]
        tombstones.append(item)
        tombstones.sort(
            key=lambda value: (
                int(value["erasure_generation"]),
                str(value["target_id"]),
            )
        )
        identity["erasure_generation"] = max(current_generation, int(generation))
        identity["tombstones"] = tombstones
        self._write(payload)

    def copy_to(self, other: "ExternalErasureFenceStore") -> None:
        payload = self.load()
        if payload is None:
            raise ErasureWatermarkError("source erasure watermark is missing")
        other._write(payload)

    def _write(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        data = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
