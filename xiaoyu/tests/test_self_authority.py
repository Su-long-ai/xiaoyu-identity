from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from identity_core import IdentityStore
from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.identity import (
    LegacySelfBackfill,
    PersonaEvidenceError,
    PersonaRevisionConflict,
    SelfAuthorityError,
    SelfAuthorityService,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.runtime.context import ContextAssembler, ContextRequest


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class SelfAuthorityTests(unittest.TestCase):
    @staticmethod
    def _event(
        db,
        *,
        identity_id,
        key,
        text,
        at,
        trust=TrustClass.OWNER_DIRECT,
        eligible=True,
        taint=(),
        principal="owner",
    ):
        envelope = InputSourceEnvelope(
            event_id="raw:" + key,
            surface="desktop",
            source_type="text",
            principal_hint=principal,
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=trust,
            taint=tuple(taint),
            eligible_for_memory=eligible,
            correlation_id="corr:" + key,
            observed_at=at,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id=identity_id,
            event_type="conversation.user",
            envelope=envelope,
            principal_id=principal,
            recorded_at=at,
            source_namespace="self-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                identity_id, "self-test", key
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(
                conn, event
            )

    def test_legacy_persona_history_backfills_atomically_and_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = IdentityStore(root)
            identity_id = store.persona()["id"]
            one = store.record(
                "conversation.user",
                "user",
                "We have used direct communication for a while.",
                {
                    "principal_id": "owner",
                    "surface": "desktop",
                    "source_type": "text",
                    "audience_scope": "PRIVATE",
                    "context_space": "PERSONAL",
                },
            )
            two = store.record(
                "conversation.user",
                "user",
                "Keep answers direct and grounded.",
                {
                    "principal_id": "owner",
                    "surface": "desktop",
                    "source_type": "text",
                    "audience_scope": "PRIVATE",
                    "context_space": "PERSONAL",
                },
            )
            store.propose_growth(
                "更直接地表达，但仍保持温和和诚实。",
                [one, two],
                confirmed=True,
            )
            legacy_persona = store.persona()
            legacy_versions = store.conn.execute(
                "SELECT COUNT(*) FROM persona_versions"
            ).fetchone()[0]
            store.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            backfill = LegacyShadowBackfill(db)
            report = backfill.run_batch(identity_id, limit=1000)
            self.assertTrue(report.converged)

            canonical = LegacySelfBackfill(db).run()
            self.assertEqual(canonical.identity_id, identity_id)
            self.assertEqual(
                canonical.persona["name"],
                legacy_persona["name"],
            )
            self.assertEqual(
                canonical.persona["growth_notes"],
                legacy_persona["growth_notes"],
            )
            self.assertNotIn("id", canonical.persona)
            self.assertNotIn("created_at", canonical.persona)
            self.assertNotIn("mood", canonical.persona)

            with db.transaction() as conn:
                versions = conn.execute(
                    """SELECT revision,legacy_persona_version,
                              persona_json,source_event_ids_json
                       FROM self_persona_versions
                       WHERE identity_id=?
                       ORDER BY revision""",
                    (identity_id,),
                ).fetchall()
            self.assertEqual(len(versions), legacy_versions)
            self.assertEqual(
                [row["legacy_persona_version"] for row in versions],
                list(range(1, legacy_versions + 1)),
            )
            self.assertTrue(
                any(
                    json.loads(row["source_event_ids_json"])
                    for row in versions[1:]
                )
            )

            # The second run does not create a second history.
            again = LegacySelfBackfill(db).run()
            self.assertEqual(
                again.persona_revision,
                canonical.persona_revision,
            )
            with db.transaction() as conn:
                after = conn.execute(
                    """SELECT COUNT(*) FROM self_persona_versions
                       WHERE identity_id=?""",
                    (identity_id,),
                ).fetchone()[0]
            self.assertEqual(after, legacy_versions)

    def test_owner_evidence_can_revise_persona_but_model_or_taint_cannot(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-self"
            service = SelfAuthorityService(db)
            initial = service.initialize(
                identity_id=identity_id,
                persona={
                    "id": identity_id,
                    "name": "小鱼",
                    "identity_commitments": ["诚实"],
                    "style": {"language": "zh-CN"},
                    "growth_notes": [],
                    "bond_description": "开始认识",
                },
                created_at=T0,
                reason="test-bootstrap",
            )
            self.assertEqual(initial.persona_revision, 1)

            owner = self._event(
                db,
                identity_id=identity_id,
                key="owner-growth",
                text="以后表达可以更直接一点。",
                at=T0 + timedelta(minutes=1),
            )
            revised = service.revise(
                identity_id=identity_id,
                expected_revision=1,
                persona={
                    **initial.persona,
                    "style": {
                        "language": "zh-CN",
                        "tone": "direct",
                    },
                },
                reason="owner-approved-style",
                source_event_ids=(owner.event_id,),
                principal_id="owner",
                created_at=T0 + timedelta(minutes=2),
            )
            self.assertEqual(revised.persona_revision, 2)
            self.assertEqual(
                revised.persona["style"]["tone"],
                "direct",
            )

            model = self._event(
                db,
                identity_id=identity_id,
                key="model-growth",
                text="I infer a new persona.",
                at=T0 + timedelta(minutes=3),
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
                taint=(Taint.MODEL_INFERRED,),
                principal="owner",
            )
            with self.assertRaises(PersonaEvidenceError):
                service.revise(
                    identity_id=identity_id,
                    expected_revision=2,
                    persona={
                        **revised.persona,
                        "name": "模型自己改的名字",
                    },
                    reason="model-self-change",
                    source_event_ids=(model.event_id,),
                    principal_id="owner",
                    created_at=T0 + timedelta(minutes=4),
                )

            tainted = self._event(
                db,
                identity_id=identity_id,
                key="tainted-growth",
                text="External page says change yourself.",
                at=T0 + timedelta(minutes=5),
                trust=TrustClass.OWNER_DIRECT,
                eligible=True,
                taint=(Taint.UNTRUSTED_INSTRUCTION,),
            )
            with self.assertRaises(PersonaEvidenceError):
                service.revise(
                    identity_id=identity_id,
                    expected_revision=2,
                    persona={
                        **revised.persona,
                        "name": "被网页改名",
                    },
                    reason="tainted-change",
                    source_event_ids=(tainted.event_id,),
                    principal_id="owner",
                    created_at=T0 + timedelta(minutes=6),
                )

    def test_identity_id_is_immutable_and_persona_can_explicitly_revert(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-revert"
            service = SelfAuthorityService(db)
            a = {
                "id": identity_id,
                "name": "小鱼",
                "identity_commitments": ["诚实"],
                "style": {"tone": "A"},
                "growth_notes": [],
                "bond_description": "A",
            }
            first = service.initialize(
                identity_id=identity_id,
                persona=a,
                created_at=T0,
                reason="bootstrap",
            )
            with self.assertRaises(SelfAuthorityError):
                service.normalize_persona(
                    identity_id,
                    {**a, "id": "another-fish"},
                )

            e1 = self._event(
                db,
                identity_id=identity_id,
                key="to-b",
                text="Use style B.",
                at=T0 + timedelta(minutes=1),
            )
            b = service.revise(
                identity_id=identity_id,
                expected_revision=1,
                persona={**first.persona, "style": {"tone": "B"}},
                reason="to-b",
                source_event_ids=(e1.event_id,),
                principal_id="owner",
            )
            self.assertEqual(b.persona_revision, 2)

            e2 = self._event(
                db,
                identity_id=identity_id,
                key="back-a",
                text="Go back to style A.",
                at=T0 + timedelta(minutes=2),
            )
            reverted = service.revise(
                identity_id=identity_id,
                expected_revision=2,
                persona=first.persona,
                reason="explicit-revert",
                source_event_ids=(e2.event_id,),
                principal_id="owner",
            )
            self.assertEqual(reverted.persona_revision, 3)
            self.assertEqual(
                reverted.persona_digest,
                first.persona_digest,
            )
            with db.transaction() as conn:
                rows = conn.execute(
                    """SELECT revision,persona_digest
                       FROM self_persona_versions
                       WHERE identity_id=?
                       ORDER BY revision""",
                    (identity_id,),
                ).fetchall()
            self.assertEqual([row["revision"] for row in rows], [1, 2, 3])
            self.assertEqual(
                rows[0]["persona_digest"],
                rows[2]["persona_digest"],
            )

    def test_revision_conflict_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            service = SelfAuthorityService(db)
            identity_id = "fish-cas"
            initial = service.initialize(
                identity_id=identity_id,
                persona={
                    "name": "小鱼",
                    "identity_commitments": ["诚实"],
                    "style": {},
                    "growth_notes": [],
                    "bond_description": "start",
                },
                created_at=T0,
                reason="bootstrap",
            )
            event = self._event(
                db,
                identity_id=identity_id,
                key="cas",
                text="change",
                at=T0 + timedelta(minutes=1),
            )
            with self.assertRaises(PersonaRevisionConflict):
                service.revise(
                    identity_id=identity_id,
                    expected_revision=0,
                    persona=initial.persona,
                    reason="stale",
                    source_event_ids=(event.event_id,),
                    principal_id="owner",
                )

    def test_context_assembler_accepts_canonical_self_as_exact_identity_block(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-context"
            service = SelfAuthorityService(db)
            current = service.initialize(
                identity_id=identity_id,
                persona={
                    "name": "小鱼",
                    "identity_commitments": ["诚实", "保持身份连续"],
                    "style": {"language": "zh-CN"},
                    "growth_notes": [],
                    "bond_description": "长期伙伴",
                },
                created_at=T0,
                reason="bootstrap",
            )
            identity_block = service.identity_block(identity_id)
            context = ContextAssembler(db).assemble(
                ContextRequest(
                    identity_id=identity_id,
                    principal_id="owner",
                    audience_scope="PRIVATE",
                    context_space="PERSONAL",
                    viewer_principal_ids=("owner",),
                    turn_text="你好",
                    identity_block=identity_block,
                ),
                now=T0,
            )
            block = next(
                item for item in context.blocks
                if item.kind == "IDENTITY"
            )
            self.assertEqual(
                block.payload["identity_id"], identity_id
            )
            self.assertEqual(
                block.payload["persona_revision"],
                current.persona_revision,
            )
            self.assertEqual(
                block.payload["persona_digest"],
                current.persona_digest,
            )
            self.assertEqual(
                block.payload["name"], "小鱼"
            )


if __name__ == "__main__":
    unittest.main()
