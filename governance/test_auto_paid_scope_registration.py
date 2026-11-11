from __future__ import annotations
import hashlib, importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

class TestAutoPaidScopeRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.gov=self.root/"governance"; self.gov.mkdir()
        self.ws=self.gov/"workspaces"/"fish-testauto123456"; self.ws.mkdir(parents=True)
        (self.root/"provider.json").write_text(json.dumps({
            "provider":"deepseek","model":"deepseek-flash",
            "url":"https://example.invalid","key_env":"NO_KEY"
        }),encoding="utf-8")
        auth=self.gov/"AUTH.json"
        auth.write_text(json.dumps({"status":"ACTIVE"}),encoding="utf-8")
        freeze=self.ws/"FREEZE.json"
        freeze.write_text(json.dumps({
            "schema":"test-freeze","status":"FROZEN_BEFORE_PROVIDER_ACCESS",
            "frozen_before_provider_execution":True
        }),encoding="utf-8")
        self.scope="proxy:xiaoyu:test-auto-paid-v1"
        self.case_id="auto:C001"
        self.prefix="1"*64
        policy={
          "budget":{"max_paid_api_calls_per_day":1000,"paid_research":{
            "enabled":True,"provider":"deepseek","active_phase":"benchmark",
            "benchmark_unlocked":True,"max_total_tokens":1000000,
            "smoke_max_tokens":10000,"benchmark_max_tokens":1000000,
            "thinking":"disabled","reasoning_effort":"none","temperature":0,"top_p":1,
            "estimated_remaining_project_budget_cny":50,
            "pricing_cny_per_million":{
              "cache_hit":{"peak":0.04,"off_peak":0.02},
              "cache_miss":{"peak":2.0,"off_peak":1.0},
              "output":{"peak":8.0,"off_peak":4.0}
            },
            "auto_scope_authorization":{
              "enabled":True,"record":"governance/AUTH.json",
              "threshold_cny":10.0,"strict_less_than":True
            },
            "prefrozen_mainline_execution_manifests":[],
            "runtime_guard":{
              "enabled":True,"effective_after_epoch":0,"rolling_window_seconds":900,
              "scope_raw_token_cap":200000,"scope_cache_miss_cap":200000,
              "scope_output_token_cap":50000,"scope_call_cap":100,
              "scope_epoch_raw_token_cap":200000,"scope_epoch_cache_miss_cap":200000,
              "scope_epoch_output_token_cap":50000,"scope_epoch_call_cap":100,
              "max_single_reservation_tokens":50000,"require_proxy_tag":True,
              "allowed_proxy_tags":["xiaoyu"],"block_benchmark_weekday_peak":False,
              "scope_overrides":{}
            }
          }},
          "e2_transition":{"current_stage":"E2_CONFIRMATORY","confirmatory_calls_allowed":False}
        }
        (self.gov/"policy.json").write_text(json.dumps(policy),encoding="utf-8")
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({"candidates":[]}),encoding="utf-8")
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.executescript("""
        create table leases(lease_id text primary key,agent_id text,role text,family text,lineage text,
        capability text,hypothesis text,lane text,tier text,workspace text,claimed_at real,
        heartbeat_at real,ttl_end real,state text,reopen_basis text,reuse_plan_json text,
        reuse_guard_version integer,reuse_catalog_sha text,reuse_decision_sha text,backlog_id text);
        """)
        con.execute("""insert into leases values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
          "fish-testauto123456","xy-test-agent","research_engineer","portfolio.explore.test","portfolio.explore.test",
          "memory_evidence","test","alternative_architecture","E0",str(self.ws),1,1,9999999999,"ACTIVE","",
          "{}" ,2,"","",""
        ))
        con.commit();con.close()
        req={
          "schema":"xiaoyu-auto-paid-scope-request-v1","status":"FROZEN_REQUEST",
          "lease_id":"fish-testauto123456","agent_id":"xy-test-agent",
          "scope":self.scope,"phase":"benchmark","provider":"deepseek","model":"deepseek-flash",
          "thinking":"disabled","reasoning_effort":"none","temperature":0,"top_p":1,
          "max_raw_tokens":10000,"max_case_calls":1,"max_completion_tokens":100,
          "response_format":{"type":"json_object"},"case_ids":[self.case_id],
          "case_prefix_sha256":{"auto:":self.prefix},
          "conservative_peak_hard_bound_cny":0.03,
          "freeze":{"path":"governance/workspaces/fish-testauto123456/FREEZE.json","sha256":sha(freeze)},
          "boundaries":{"private_identity_data":False,"blind_or_formal_data":False,"product_mutation":False}
        }
        self.req=self.ws/"AUTO_PAID_SCOPE_REQUEST.json"
        self.req.write_text(json.dumps(req),encoding="utf-8")
        spec=importlib.util.spec_from_file_location("registrar",HERE/"register_auto_paid_scope.py")
        self.reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.reg)
        self.reg.ROOT=self.root;self.reg.GOV=self.gov;self.reg.POLICY=self.gov/"policy.json"
        self.reg.BACKLOG=self.gov/"RESEARCH_BACKLOG.json";self.reg.REG_DIR=self.gov/"auto_paid_scopes"
        self.reg.USAGE_DB=self.gov/"research_api_usage.sqlite3";self.reg.LEASE_DB=self.gov/"registry.sqlite3"

    def tearDown(self): self.tmp.cleanup()

    def test_apply_registers_exact_scope_and_existing_gateway_accepts_it(self):
        preview=self.reg.apply(self.req,False)
        self.assertFalse(preview["apply"])
        result=self.reg.apply(self.req,True)
        self.assertTrue(result["registered"])
        policy=json.loads((self.gov/"policy.json").read_text())
        rows=policy["budget"]["paid_research"]["prefrozen_mainline_execution_manifests"]
        self.assertEqual([x["scope"] for x in rows],[self.scope])

        from research_api import ResearchApiBudget, ResearchBudgetError, _PROXY_AUTH_SENTINEL
        b=ResearchApiBudget(self.root,clock=lambda:10000)
        try:
            messages=[{"role":"system","content":"frozen"},{"role":"user","content":"case"}]
            cid,_,_=b.reserve(
              messages,100,self.scope,phase="benchmark",
              response_format={"type":"json_object"},budget_scope=self.scope,
              case_id=self.case_id,prompt_prefix_sha256=self.prefix,
              _proxy_auth=_PROXY_AUTH_SENTINEL)
            self.assertTrue(cid)
            with self.assertRaises(ResearchBudgetError):
                b.reserve(
                  messages,100,"other",phase="benchmark",
                  response_format={"type":"json_object"},budget_scope="proxy:xiaoyu:unregistered",
                  case_id="other:C001",prompt_prefix_sha256=self.prefix,
                  _proxy_auth=_PROXY_AUTH_SENTINEL)
        finally:b.close()

    def test_rejects_at_or_above_owner_threshold(self):
        req=json.loads(self.req.read_text())
        req["max_raw_tokens"]=1_000_000
        req["max_case_calls"]=1000
        req["max_completion_tokens"]=1000
        req["conservative_peak_hard_bound_cny"]=10
        self.req.write_text(json.dumps(req),encoding="utf-8")
        with self.assertRaisesRegex(self.reg.AdmissionError,"strictly below"):
            self.reg.apply(self.req,False)

    def test_bound_active_backlog_may_register(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set backlog_id='RC8M2'")
        con.commit();con.close()
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[{"id":"RC8M2","status":"active"}]
        }),encoding="utf-8")
        preview=self.reg.apply(self.req,False)
        self.assertFalse(preview["apply"])

    def test_bound_held_backlog_cannot_register(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set backlog_id='RC8M2'")
        con.commit();con.close()
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[{"id":"RC8M2","status":"hold_material_p1"}]
        }),encoding="utf-8")
        with self.assertRaisesRegex(self.reg.AdmissionError,"bound backlog to remain active"):
            self.reg.apply(self.req,False)

    def test_rejects_nonactive_lease(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set state='SUBMITTED'");con.commit();con.close()
        with self.assertRaisesRegex(self.reg.AdmissionError,"ACTIVE lease"):
            self.reg.apply(self.req,False)

    def test_apply_does_not_write_research_backlog_admin_row(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set backlog_id='RC8M2'")
        con.commit();con.close()
        original={"candidates":[{"id":"RC8M2","status":"active"}]}
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps(original),encoding="utf-8")
        result=self.reg.apply(self.req,True)
        self.assertTrue(result["registered"])
        self.assertEqual(
            json.loads((self.gov/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8")),
            original,
        )
        manifest=json.loads((self.root/result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["auto_registration"]["schema"],"xiaoyu-auto-paid-scope-registration-v2")
        self.assertEqual(manifest["auto_registration"]["bound_backlog_id"],"RC8M2")

    def test_validation_to_apply_race_fails_without_overwriting_hold(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set backlog_id='RC8M2'")
        con.commit();con.close()
        (self.gov/"RESEARCH_BACKLOG.json").write_text(
            json.dumps({"candidates":[{"id":"RC8M2","status":"active"}]}),encoding="utf-8")
        original_validate=self.reg.validate_request
        def raced(req):
            values=original_validate(req)
            (self.gov/"RESEARCH_BACKLOG.json").write_text(
                json.dumps({"candidates":[{"id":"RC8M2","status":"hold_material_p1"}]}),encoding="utf-8")
            con=sqlite3.connect(self.gov/"registry.sqlite3")
            con.execute("update leases set state='RELEASED' where lease_id='fish-testauto123456'")
            con.commit();con.close()
            return values
        self.reg.validate_request=raced
        with self.assertRaisesRegex(self.reg.AdmissionError,"ACTIVE lease"):
            self.reg.apply(self.req,True)
        self.assertEqual(
            json.loads((self.gov/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8")),
            {"candidates":[{"id":"RC8M2","status":"hold_material_p1"}]},
        )
        policy=json.loads((self.gov/"policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["budget"]["paid_research"]["prefrozen_mainline_execution_manifests"],[])

    def test_runtime_revocation_checks_live_source_lease_and_backlog(self):
        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set backlog_id='RC8M2'")
        con.commit();con.close()
        (self.gov/"RESEARCH_BACKLOG.json").write_text(
            json.dumps({"candidates":[{"id":"RC8M2","status":"active"}]}),encoding="utf-8")
        result=self.reg.apply(self.req,True)
        self.assertTrue(result["registered"])

        con=sqlite3.connect(self.gov/"registry.sqlite3")
        con.execute("update leases set state='RELEASED' where lease_id='fish-testauto123456'")
        con.commit();con.close()
        (self.gov/"RESEARCH_BACKLOG.json").write_text(
            json.dumps({"candidates":[{"id":"RC8M2","status":"hold_material_p1"}]}),encoding="utf-8")

        from research_api import ResearchApiBudget,ResearchBudgetError,_PROXY_AUTH_SENTINEL
        b=ResearchApiBudget(self.root,clock=lambda:10000)
        try:
            with self.assertRaisesRegex(ResearchBudgetError,"source lease is not ACTIVE"):
                b.reserve(
                  [{"role":"system","content":"frozen"},{"role":"user","content":"case"}],
                  100,self.scope,phase="benchmark",
                  response_format={"type":"json_object"},budget_scope=self.scope,
                  case_id=self.case_id,prompt_prefix_sha256=self.prefix,
                  _proxy_auth=_PROXY_AUTH_SENTINEL)
        finally:
            b.close()

if __name__=="__main__": unittest.main()
