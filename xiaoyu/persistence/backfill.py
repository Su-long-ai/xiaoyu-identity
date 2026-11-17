from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable, Optional

from .db import Database
from .repositories.events import LegacyEventShadowWriter


class LegacyBackfillError(RuntimeError):
    pass


class LegacyBackfillOrderConflict(LegacyBackfillError):
    pass


@dataclass(frozen=True)
class LegacyBackfillProgress:
    identity_id: str
    snapshot_high_watermark: int
    last_processed_event_id: int
    state: str


@dataclass(frozen=True)
class LegacyBackfillReport:
    progress: LegacyBackfillProgress
    scanned: int
    inserted_or_confirmed: int
    source_order_ok: bool
    converged: bool


class LegacyBackfillProgressStore:
    VERSION = 1

    def __init__(self, db_path) -> None:
        self.path = Path(str(Path(db_path)) + ".legacy-backfill.json")

    def load(self) -> Optional[LegacyBackfillProgress]:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != self.VERSION:
            raise LegacyBackfillError("unsupported legacy backfill progress version")
        return LegacyBackfillProgress(
            identity_id=str(payload["identity_id"]),
            snapshot_high_watermark=int(payload["snapshot_high_watermark"]),
            last_processed_event_id=int(payload["last_processed_event_id"]),
            state=str(payload["state"]),
        )

    def save(self, progress: LegacyBackfillProgress) -> None:
        payload = {
            "version": self.VERSION,
            "identity_id": progress.identity_id,
            "snapshot_high_watermark": progress.snapshot_high_watermark,
            "last_processed_event_id": progress.last_processed_event_id,
            "state": progress.state,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)


class LegacyShadowBackfill:
    """Crash-safe legacy event -> canonical shadow copier.

    Progress is operational metadata outside the authority DB. Losing it is safe:
    stable legacy source keys make a repeated scan idempotent.

    The start high-watermark is frozen so a bounded historical prefix is copied.
    New events after that point belong to the incremental shadow writer.
    """

    def __init__(
        self,
        db: Database,
        *,
        writer=None,
        progress_store=None,
    ) -> None:
        self.db = db
        self.writer = writer or LegacyEventShadowWriter()
        self.progress_store = progress_store or LegacyBackfillProgressStore(db.path)

    def start(self, identity_id: str) -> LegacyBackfillProgress:
        existing = self.progress_store.load()
        if existing is not None:
            if existing.identity_id != identity_id:
                raise LegacyBackfillError("backfill identity mismatch")
            return existing
        with self.db.transaction() as conn:
            high = int(
                conn.execute(
                    "SELECT COALESCE(MAX(event_id),0) FROM events"
                ).fetchone()[0]
            )
        progress = LegacyBackfillProgress(
            identity_id=identity_id,
            snapshot_high_watermark=high,
            last_processed_event_id=0,
            state="RUNNING" if high else "CAUGHT_UP",
        )
        self.progress_store.save(progress)
        return progress

    def run_batch(
        self,
        identity_id: str,
        *,
        limit: int = 200,
        fault_hook: Optional[Callable[[str, int], None]] = None,
    ) -> LegacyBackfillReport:
        progress = self.start(identity_id)
        if progress.identity_id != identity_id:
            raise LegacyBackfillError("backfill identity mismatch")

        scanned = 0
        confirmed = 0
        last = progress.last_processed_event_id
        # A DB restore can roll canonical shadow rows back while leaving this
        # sibling progress sidecar ahead. Detect that divergence and safely
        # replay the prefix from zero; stable source keys make it idempotent.
        scan_after = progress.last_processed_event_id
        if (
            scan_after > 0
            and not self.converged(identity_id, scan_after)
        ):
            scan_after = 0
            last = 0

        rows = []
        with self.db.transaction(immediate=True) as conn:
            rows = conn.execute(
                """SELECT event_id,at,kind,actor,content,extra
                   FROM events
                   WHERE event_id>? AND event_id<=?
                   ORDER BY event_id
                   LIMIT ?""",
                (
                    scan_after,
                    progress.snapshot_high_watermark,
                    max(1, min(int(limit), 5000)),
                ),
            ).fetchall()
            for row in rows:
                try:
                    extra = json.loads(str(row["extra"] or "{}"))
                except ValueError:
                    extra = {"legacy_extra_raw": str(row["extra"])}
                if not isinstance(extra, dict):
                    extra = {"legacy_extra": extra}
                self.writer.write(
                    conn,
                    identity_id,
                    int(row["event_id"]),
                    str(row["at"]),
                    str(row["kind"]),
                    str(row["actor"]),
                    str(row["content"]),
                    extra,
                    turn_id=extra.get("turn_id"),
                )
                scanned += 1
                confirmed += 1
                last = int(row["event_id"])
                if fault_hook is not None:
                    fault_hook("after_event", last)

        # Deliberately after the DB commit. If the process dies here, the
        # sidecar remains behind and the same rows are replayed idempotently.
        if fault_hook is not None:
            fault_hook("before_progress", last)

        with self.db.transaction() as conn:
            source_max = int(
                conn.execute(
                    "SELECT COALESCE(MAX(event_id),0) FROM events"
                ).fetchone()[0]
            )
        caught_up = last >= progress.snapshot_high_watermark
        if source_max < progress.snapshot_high_watermark:
            state = "BLOCKED_SOURCE_GAP"
        else:
            state = "CAUGHT_UP" if caught_up else "RUNNING"
        next_progress = LegacyBackfillProgress(
            identity_id=identity_id,
            snapshot_high_watermark=progress.snapshot_high_watermark,
            last_processed_event_id=last,
            state=state,
        )
        self.progress_store.save(next_progress)
        order_ok = self.source_order_ok(identity_id)
        converged = self.converged(identity_id, next_progress.snapshot_high_watermark)
        return LegacyBackfillReport(
            progress=next_progress,
            scanned=scanned,
            inserted_or_confirmed=confirmed,
            source_order_ok=order_ok,
            converged=converged,
        )

    def source_order_ok(self, identity_id: str) -> bool:
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT ce.source_event_key
                   FROM canonical_event_ingest cei
                   JOIN canonical_events ce ON ce.event_id=cei.event_id
                   WHERE ce.identity_id=? AND ce.source_namespace='legacy'
                     AND ce.source_event_key IS NOT NULL
                   ORDER BY cei.ingest_revision""",
                (identity_id,),
            ).fetchall()
        source_ids = []
        for row in rows:
            try:
                source_ids.append(int(row[0]))
            except (TypeError, ValueError):
                continue
        return source_ids == sorted(source_ids)

    def converged(self, identity_id: str, high_watermark: int) -> bool:
        with self.db.transaction() as conn:
            source_max = int(
                conn.execute(
                    "SELECT COALESCE(MAX(event_id),0) FROM events"
                ).fetchone()[0]
            )
            if source_max < int(high_watermark):
                return False
            missing = conn.execute(
                """SELECT 1
                   FROM events le
                   WHERE le.event_id<=?
                     AND NOT EXISTS (
                       SELECT 1 FROM canonical_events ce
                       WHERE ce.identity_id=?
                         AND ce.source_namespace='legacy'
                         AND ce.source_event_key=CAST(le.event_id AS TEXT)
                     )
                   LIMIT 1""",
                (int(high_watermark), identity_id),
            ).fetchone()
        return missing is None

    def require_cutover_ready(self, identity_id: str) -> LegacyBackfillProgress:
        progress = self.start(identity_id)
        if progress.state != "CAUGHT_UP":
            raise LegacyBackfillError("legacy shadow backfill is not caught up")
        if not self.converged(identity_id, progress.snapshot_high_watermark):
            raise LegacyBackfillError("legacy shadow backfill has source gaps")
        if not self.source_order_ok(identity_id):
            raise LegacyBackfillOrderConflict(
                "canonical ingest order differs from legacy source order; rebuild shadow before authority cutover"
            )
        return progress
