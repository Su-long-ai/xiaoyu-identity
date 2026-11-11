# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from control import Governance

SOURCE=Path(__file__).with_name("policy.json")

class DynamicCapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"; gov.mkdir()
        policy=json.loads(SOURCE.read_text(encoding="utf-8"))
        policy["phase_priority_guard"]["enabled"]=False
        policy["reuse_guard"]["enabled"]=False
        policy["worker_instance_guard"]["enabled"]=False
        (gov/"policy.json").write_text(json.dumps(policy),encoding="utf-8")
        self.g=Governance(self.root,clock=lambda:2000000000.0)

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def add_lease(self,role,index,state="ACTIVE"):
        agent=f"agent-{role}-{index}"
        lease=f"x-{role}-{index}-{state.lower()}"
        self.g.db.execute(
            "INSERT OR IGNORE INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
            (agent,role,2000000000.0,2000000000.0))
        self.g.db.execute(
            """INSERT INTO leases(
            lease_id,agent_id,role,family,lineage,capability,hypothesis,lane,tier,
            workspace,claimed_at,heartbeat_at,ttl_end,state,reopen_basis,
            reuse_plan_json,reuse_guard_version,reuse_catalog_sha,reuse_decision_sha,
            backlog_id,worker_instance_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lease,agent,role,f"fam.{role}.{index}",f"fam.{role}.{index}",
             "memory_retrieval","synthetic","main_bottleneck","E0",
             str(self.root/f"w-{role}-{index}"),2000000000.0,2000000000.0,
             2000010000.0,state,"","{}",0,"","","",""))
        return lease

    def add_active(self,role,n):
        for i in range(n):
            self.add_lease(role,i,"ACTIVE")

    def add_pending_e1(self,index):
        lease=self.add_lease("research_engineer",100+index,"SUBMITTED")
        self.g.db.execute(
            """INSERT INTO submissions(
            submission_id,lease_id,at,evidence_label,manifest_path,manifest_sha,
            receipt_sha,baseline,metric,delta,decision,snapshot_dir)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"sub-{index}",lease,2000000000.0+index,"LEAD_READY",
             "x","a","b","baseline","metric",1.0,"PENDING",""))

    def test_idle_uses_v1_closeout_fixed_upper_bound(self):
        c=self.g._dynamic_capacity()
        self.assertEqual(c["research_engineers"],4)
        self.assertEqual(c["auditors"],1)
        self.assertEqual(c["total"],5)
        self.assertEqual(c["hard_max_total"],5)

    def test_research_capacity_does_not_expand_during_v1_closeout(self):
        self.add_active("research_engineer",3)
        c=self.g._dynamic_capacity()
        self.assertEqual(c["research_engineers"],4)
        self.assertEqual(c["total"],5)
        self.add_lease("research_engineer",3,"ACTIVE")
        self.add_lease("research_engineer",4,"ACTIVE")
        c=self.g._dynamic_capacity()
        self.assertEqual(c["research_engineers"],4)
        # Existing over-cap occupancy is reported, but no new research admission
        # is created by that occupancy.
        self.assertEqual(c["total"],5)

    def test_auditor_capacity_stays_one_during_v1_closeout(self):
        for i in range(3):
            self.add_pending_e1(i)
        c=self.g._dynamic_capacity()
        self.assertEqual(c["auditors"],1)
        self.assertEqual(c["total"],5)

    def test_existing_overage_is_tolerated_without_raising_hard_ceiling(self):
        self.add_active("research_engineer",9)
        self.add_active("auditor",1)
        c=self.g._dynamic_capacity()
        self.assertEqual(c["research_engineers"],4)
        # Status never lies below already-active occupancy, but admission
        # hard ceiling remains the V1 closeout ceiling.
        self.assertEqual(c["total"],10)
        self.assertEqual(c["hard_max_total"],5)

if __name__=="__main__":
    unittest.main(verbosity=2)
