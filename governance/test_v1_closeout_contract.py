# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path

G=Path(__file__).resolve().parent
ROOT=G.parent

class V1CloseoutContractTests(unittest.TestCase):
    def test_policy_capacity_and_phase(self):
        policy=json.loads((G/"policy.json").read_text(encoding="utf-8"))
        self.assertEqual("ACTIVE",policy["v1_closeout"]["status"])
        self.assertEqual(4,policy["startup"]["dynamic_capacity"]["hard_max_research_engineers"])
        self.assertEqual(1,policy["startup"]["dynamic_capacity"]["hard_max_auditors"])
        self.assertEqual(5,policy["startup"]["dynamic_capacity"]["hard_max_total"])
        self.assertFalse(policy["phase_priority_guard"]["continuous_research_exception"]["enabled"])
        self.assertTrue(policy["v1_closeout"]["codex_for_lead_forbidden"])

    def test_release_gates_are_explicit(self):
        obj=json.loads((G/"V1_RELEASE_CRITERIA_20261102.json").read_text(encoding="utf-8"))
        ids={x["id"] for x in obj["gates"]}
        self.assertEqual({
            "V1G-RETRIEVAL","V1G-STATE-IDENTITY","V1G-CROSS-MODEL",
            "V1G-CONSOLIDATION-SCALE","V1G-RELIABILITY","V1G-FINAL-RELEASE"
        },ids)

    def test_backlog_routes_only_four_closeout_lanes(self):
        b=json.loads((G/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        phase=b["phase_policy"]
        self.assertEqual("V1_PRODUCT_CLOSEOUT",phase["current_phase"])
        self.assertTrue(phase["closeout_mode"])
        self.assertEqual(
            {"V1C-STATE","V1C-CONSOLIDATION","V1C-INTEGRATION"},
            set(phase["closeout_required_backlog"])
        )
        release_ids={
            x["id"] for x in json.loads(
                (G/"V1_RELEASE_CRITERIA_20261102.json").read_text(encoding="utf-8")
            )["gates"]
        }
        rows={x["id"]:x for x in b["candidates"] if x.get("id") in phase["closeout_required_backlog"]}
        self.assertEqual(3,len(rows))
        for row in rows.values():
            self.assertEqual("V1_PRODUCT_CLOSEOUT",row["plan"])
            self.assertIn(row["release_gate"],release_ids)
            self.assertGreaterEqual(int(row["task_deadline_hours"]),1)
            self.assertLessEqual(int(row["task_deadline_hours"]),48)

    def test_old_fast_multi_slot_does_not_refill(self):
        b=json.loads((G/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        old=[x for x in b["candidates"] if str(x.get("id","")).startswith("FASTRET-")]
        self.assertTrue(old)
        self.assertFalse(any(x.get("status")=="active" for x in old))

    def test_role_prompts_have_closeout_override(self):
        for name in [
            "LEAD_PROMPT.md","MAINLINE_RESEARCH_AGENT_PROMPT.md",
            "DIVERGENT_RESEARCH_AGENT_PROMPT.md","INDEPENDENT_AUDITOR_PROMPT.md"
        ]:
            text=(G/"agent_prompts"/name).read_text(encoding="utf-8",errors="replace")
            self.assertTrue(text.startswith("## V1_PRODUCT_CLOSEOUT_OVERRIDE_20261102"),name)
        lead=(G/"agent_prompts"/"LEAD_PROMPT.md").read_text(encoding="utf-8",errors="replace")
        self.assertIn("Do NOT start or use Codex.",lead)

    def test_first_external_e0_is_bound_to_retrieval_gate(self):
        crit=json.loads((G/"V1_RELEASE_CRITERIA_20261102.json").read_text(encoding="utf-8"))
        gate=next(x for x in crit["gates"] if x["id"]=="V1G-RETRIEVAL")
        ev=gate["current_evidence"]
        eid=ev.get("winner_e0_id") or ev.get("e0_id")
        self.assertTrue(eid)
        ep=G/"fastlane"/"e0_candidates"/f"{eid}.json"
        self.assertTrue(ep.is_file())
        e0=json.loads(ep.read_text(encoding="utf-8"))
        self.assertEqual("xiaoyu-fast-retrieval-e0-v4",e0["schema"])
        self.assertEqual("E0_EXTERNAL_DEV_QUALIFIED",e0["status"])
        if ev.get("candidate_freeze"):
            self.assertTrue((G.parent/ev["candidate_freeze"]).is_file())
        if gate.get("status")=="FROZEN_TEST_COMPLETE_PENDING_INDEPENDENT_AUDIT":
            self.assertTrue((G/"V1_FAST_WINNER_AUDIT_HANDOFF_20261102.json").is_file())

if __name__=="__main__":
    unittest.main(verbosity=2)
