# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
from control import Governance, GovernanceError

SOURCE=Path(__file__).with_name("policy.json")

class ScientificEvidenceSeparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"
        gov.mkdir()
        (gov/"policy.json").write_bytes(SOURCE.read_bytes())
        effective=json.loads(SOURCE.read_text("utf-8"))["scientific_evidence_separation"]["effective_after_epoch"]
        self.g=Governance(self.root,clock=lambda:float(effective)+10.0)
        self.lease={"claimed_at":float(effective)+1.0}

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def base(self,label):
        return {
            "evidence_label":label,
            "scientific_outcome":"POSITIVE",
            "promotion_evidence_status":"VALID",
            "scientific_falsifier_observed":False,
        }

    def test_lead_ready_requires_positive_and_valid(self):
        self.g._validate_scientific_evidence_separation(self.lease,self.base("LEAD_READY"))
        m=self.base("LEAD_READY")
        m["promotion_evidence_status"]="INVALID_ADMINISTRATIVE"
        with self.assertRaisesRegex(GovernanceError,"LEAD_READY requires"):
            self.g._validate_scientific_evidence_separation(self.lease,m)

    def test_admin_invalidity_cannot_be_nonpass_without_scientific_failure(self):
        m=self.base("NONPASS")
        m["promotion_evidence_status"]="INVALID_ADMINISTRATIVE"
        with self.assertRaisesRegex(GovernanceError,"NONPASS requires"):
            self.g._validate_scientific_evidence_separation(self.lease,m)

    def test_nonpass_requires_observed_negative_falsifier(self):
        m=self.base("NONPASS")
        m["scientific_outcome"]="NEGATIVE"
        m["promotion_evidence_status"]="NOT_APPLICABLE"
        m["scientific_falsifier_observed"]=True
        self.g._validate_scientific_evidence_separation(self.lease,m)

    def test_old_lease_is_grandfathered(self):
        self.g._validate_scientific_evidence_separation({"claimed_at":0.0},{"evidence_label":"NONPASS"})

if __name__=="__main__":
    unittest.main(verbosity=2)
