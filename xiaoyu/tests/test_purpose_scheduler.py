from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from xiaoyu.core.purpose import (
    MissPolicy, Purpose, PurposeKind, PurposeOwner, PurposeState, resolve_wall_time,
)
from xiaoyu.persistence import Database, apply_migrations, applied_versions
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import PowerLifecycle, PurposeScheduler

UTC = timezone.utc
NOW = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)


class PurposeSchedulerTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _insert(self, db, *, purpose_id, due, policy, payload=None):
        wall = due.astimezone(ZoneInfo("Asia/Shanghai"))
        purpose = Purpose(
            purpose_id=purpose_id,
            identity_id="fish-1",
            owner_type=PurposeOwner.USER,
            owner_id="owner",
            state=PurposeState.SCHEDULED,
            kind=PurposeKind.REMINDER,
            source_event_id="source-event",
            payload=payload or {},
            scheduled_wall_time=wall.isoformat(timespec="minutes"),
            timezone_name="Asia/Shanghai",
            resolved_utc_time=due,
            miss_policy=policy,
            duplicate_key="dup:" + purpose_id,
        )
        with db.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO canonical_events(
                       event_id,identity_id,turn_id,event_type,surface,source_type,principal_id,
                       audience_scope,context_space,trust_class,taint_json,eligible_for_memory,
                       payload_type,payload_json,observed_at,recorded_at,correlation_id,schema_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "source-event","fish-1",None,"conversation.user","desktop","text",
                    "owner","PRIVATE","PERSONAL","OWNER_DIRECT","[]",1,
                    "text/plain","{}",NOW.isoformat(),NOW.isoformat(),"corr-source",1,
                ),
            )
            PurposeRepository().insert(conn, purpose, NOW - timedelta(hours=1))

    def test_schema_v3_applied(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(applied_versions(self._db(td)), [1, 2, 3, 4, 5, 6, 7, 8, 9])

    def test_dst_fold_resolves_to_distinct_instants(self):
        zone = ZoneInfo("America/Los_Angeles")
        first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
        self.assertEqual(
            (resolve_wall_time(second, "America/Los_Angeles") -
             resolve_wall_time(first, "America/Los_Angeles")).total_seconds(),
            3600,
        )

    def test_late_delivery_and_skip_policy(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert(db, purpose_id="late", due=NOW-timedelta(hours=3), policy=MissPolicy.DELIVER_LATE)
            self._insert(db, purpose_id="skip", due=NOW-timedelta(hours=3), policy=MissPolicy.SKIP_IF_MISSED, payload={"miss_after_seconds":120})
            got = {d.purpose_id:d.new_state for d in PurposeScheduler(db,"fish-1").reconcile_due(NOW)}
            self.assertEqual(got["late"], PurposeState.ACTIVE)
            self.assertEqual(got["skip"], PurposeState.EXPIRED)

    def test_ask_reconcile_and_reschedule_are_non_blind(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert(db,purpose_id="ask",due=NOW-timedelta(minutes=5),policy=MissPolicy.ASK)
            self._insert(db,purpose_id="rec",due=NOW-timedelta(minutes=5),policy=MissPolicy.RECONCILE)
            self._insert(db,purpose_id="res",due=NOW-timedelta(minutes=5),policy=MissPolicy.RESCHEDULE,payload={"reschedule_seconds":600})
            got={d.purpose_id:d.new_state for d in PurposeScheduler(db,"fish-1").reconcile_due(NOW)}
            self.assertEqual(got["ask"], PurposeState.WAITING)
            self.assertEqual(got["rec"], PurposeState.NEEDS_RECONCILIATION)
            self.assertEqual(got["res"], PurposeState.SCHEDULED)
            conn=db.connect()
            try:
                row=conn.execute("SELECT scheduled_wall_time,timezone,resolved_utc_time FROM purposes WHERE purpose_id='res'").fetchone()
                self.assertEqual(row["timezone"], "Asia/Shanghai")
                self.assertTrue(row["scheduled_wall_time"].endswith("+08:00"))
                self.assertEqual(row["resolved_utc_time"], (NOW+timedelta(minutes=10)).isoformat(timespec="microseconds"))
            finally:
                conn.close()

    def test_cancel_prevents_activation(self):
        with tempfile.TemporaryDirectory() as td:
            db=self._db(td)
            self._insert(db,purpose_id="cancel",due=NOW-timedelta(minutes=1),policy=MissPolicy.DELIVER_LATE)
            with db.transaction() as conn:
                self.assertTrue(PurposeRepository().cancel(conn,"cancel",NOW))
            self.assertEqual(PurposeScheduler(db,"fish-1").reconcile_due(NOW),[])

    def test_explicit_reschedule_preserves_named_timezone(self):
        with tempfile.TemporaryDirectory() as td:
            db=self._db(td)
            self._insert(db,purpose_id="move",due=NOW+timedelta(hours=1),policy=MissPolicy.DELIVER_LATE)
            zone=ZoneInfo("America/Los_Angeles")
            local=datetime(2026,11,18,9,45,tzinfo=zone)
            utc=resolve_wall_time(local,"America/Los_Angeles")
            with db.transaction() as conn:
                self.assertTrue(PurposeRepository().reschedule(
                    conn,"move",local.isoformat(timespec="minutes"),"America/Los_Angeles",utc,NOW
                ))
            conn=db.connect()
            try:
                row=conn.execute("SELECT scheduled_wall_time,timezone,resolved_utc_time,state FROM purposes WHERE purpose_id='move'").fetchone()
                self.assertEqual(row["scheduled_wall_time"],local.isoformat(timespec="minutes"))
                self.assertEqual(row["timezone"],"America/Los_Angeles")
                self.assertEqual(row["resolved_utc_time"],utc.isoformat(timespec="microseconds"))
                self.assertEqual(row["state"],"SCHEDULED")
            finally:
                conn.close()

    def test_resume_reconciles_once(self):
        with tempfile.TemporaryDirectory() as td:
            db=self._db(td)
            self._insert(db,purpose_id="wake",due=NOW+timedelta(minutes=30),policy=MissPolicy.DELIVER_LATE)
            scheduler=PurposeScheduler(db,"fish-1")
            power=PowerLifecycle(scheduler)
            power.suspend(NOW)
            report=power.resume(NOW+timedelta(hours=3))
            self.assertEqual(report.reconciled_purposes,1)
            self.assertEqual(scheduler.reconcile_due(NOW+timedelta(hours=3,seconds=1)),[])


if __name__ == "__main__":
    unittest.main()
