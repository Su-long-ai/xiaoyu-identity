# -*- coding: utf-8 -*-
"""Focused shape tests for E2 freeze semantics; no model/network."""
import json,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
import freeze_e2_protocol as fz


class E2FreezeShapeTests(unittest.TestCase):
    def test_atomic_write_replaces_complete_json(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x.json"
            fz.atomic_write(p,b'{"ok":true}\n')
            self.assertEqual(json.loads(p.read_text()),{"ok":True})

    def test_protocol_freeze_is_separate_from_phase_switch_by_contract(self):
        p=json.loads((HERE/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json").read_text(encoding="utf-8"))
        self.assertEqual(p["schema"],"xiaoyu-e2-pilot-protocol-v2")
        self.assertIn(p["status"],("DRAFT_PRE_FREEZE","FROZEN_BEFORE_EXECUTION"))
        self.assertEqual(p["protocol_role"],"NONPROMOTIONAL_PILOT")
        self.assertEqual(p["claim_eligibility"],"NONE")
        self.assertFalse(p["scope"]["private_identity_data"])
        self.assertFalse(p["scope"]["confirmatory_calls_allowed"])
        self.assertTrue(p["execution_rules"]["freeze_before_any_benchmark_paid_call"])
        self.assertTrue(all(x["ready_to_freeze"] for x in p["required_tracks"]))
        self.assertTrue(any("phase" in x.lower() or "P2" in x for x in p["freeze_blockers"]))


if __name__=="__main__":
    unittest.main(verbosity=2)
