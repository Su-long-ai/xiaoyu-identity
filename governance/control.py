# -*- coding: utf-8 -*-
"""小鱼科学研究池：轻量治理，不执行模型、不启动 Agent、不修改身份数据库。
Python 3.11 stdlib only. All writes confined to <project>/governance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

POLICY_FILE = "policy.json"
REUSE_CATALOG_FILE = "REUSE_CATALOG.json"
ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{4,63}$")
FAMILY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,80}$")
ROLE_LIMITS = {"research_engineer": "research_engineers", "auditor": "auditors"}
ROLES = set(ROLE_LIMITS) | {"lead"}

class GovernanceError(Exception):
    pass

def canonical(value):
    value = str(value).strip().lower()
    if not FAMILY_PATTERN.fullmatch(value):
        raise GovernanceError("family key must match [a-z0-9_.-] and length 3..81")
    return value

def jsonload(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def rel_artifact(workspace, filename):
    path = Path(filename)
    if path.is_absolute() or ".." in path.parts or any(x in ("", ".") for x in path.parts):
        raise GovernanceError("artifact path is not workspace-relative")
    workspace = workspace.resolve(strict=True)
    unchecked = workspace / path
    if any(part.is_symlink() for part in [unchecked] + list(unchecked.parents)
           if part != workspace.parent and part.is_relative_to(workspace)):
        raise GovernanceError("symlinked artifact path forbidden")
    dest = unchecked.resolve(strict=True)
    if not dest.is_relative_to(workspace):
        raise GovernanceError("artifact escapes worker workspace")
    if dest.is_symlink() or not dest.is_file():
        raise GovernanceError("artifact missing/symlink/directory: " + str(filename))
    if dest.stat().st_nlink > 1:
        raise GovernanceError("hardlinked evidence forbidden")
    if dest.stat().st_size > 2_000_000:
        raise GovernanceError("artifact exceeds 2 MiB cap")
    return dest

class Governance:
    def __init__(self, root, clock=None):
        self.root = Path(root).resolve()
        self.home = self.root / "governance"
        self.home.mkdir(parents=True, exist_ok=True)
        self.policy = jsonload(self.home / POLICY_FILE)
        self.clock = clock or time.time
        self.workspace_dir = self.home / "workspaces"
        self.workspace_dir.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.home / "registry.sqlite3", timeout=30,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def close(self):
        self.db.close()

    def _schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS agents(
                agent_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                joined_at REAL NOT NULL,
                last_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases(
                lease_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                role TEXT NOT NULL,
                family TEXT NOT NULL,
                lineage TEXT NOT NULL DEFAULT '',
                capability TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                lane TEXT NOT NULL,
                tier TEXT NOT NULL,
                workspace TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                ttl_end REAL NOT NULL,
                state TEXT NOT NULL,
                reopen_basis TEXT NOT NULL DEFAULT '',
                reuse_plan_json TEXT NOT NULL DEFAULT '{}',
                reuse_guard_version INTEGER NOT NULL DEFAULT 0,
                reuse_catalog_sha TEXT NOT NULL DEFAULT '',
                reuse_decision_sha TEXT NOT NULL DEFAULT '',
                backlog_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
            );
            CREATE INDEX IF NOT EXISTS idx_leases_live ON leases(state,role,heartbeat_at);
            CREATE TABLE IF NOT EXISTS submissions(
                submission_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL UNIQUE,
                at REAL NOT NULL,
                evidence_label TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                manifest_sha TEXT NOT NULL,
                receipt_sha TEXT NOT NULL,
                baseline TEXT NOT NULL,
                metric TEXT NOT NULL,
                delta REAL,
                decision TEXT NOT NULL DEFAULT 'PENDING',
                decided_by TEXT,
                decision_reason TEXT,
                FOREIGN KEY(lease_id) REFERENCES leases(lease_id)
            );
            CREATE INDEX IF NOT EXISTS idx_submission_state ON submissions(decision,at);
            CREATE TABLE IF NOT EXISTS reviews(
                review_id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                at REAL NOT NULL,
                findings_json TEXT NOT NULL DEFAULT '[]',
                material_count INTEGER NOT NULL DEFAULT 0,
                advisory_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(submission_id) REFERENCES submissions(submission_id)
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        columns={r["name"] for r in self.db.execute("PRAGMA table_info(leases)")}
        if "lineage" not in columns:
            self.db.execute("ALTER TABLE leases ADD COLUMN lineage TEXT NOT NULL DEFAULT ''")
        columns={r["name"] for r in self.db.execute("PRAGMA table_info(leases)")}
        for column,ddl in (
            ("reuse_plan_json","TEXT NOT NULL DEFAULT '{}'"),
            ("reuse_guard_version","INTEGER NOT NULL DEFAULT 0"),
            ("reuse_catalog_sha","TEXT NOT NULL DEFAULT ''"),
            ("reuse_decision_sha","TEXT NOT NULL DEFAULT ''"),
            ("backlog_id","TEXT NOT NULL DEFAULT ''"),
            ("worker_instance_id","TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in columns:
                self.db.execute(f"ALTER TABLE leases ADD COLUMN {column} {ddl}")
        columns={r["name"] for r in self.db.execute("PRAGMA table_info(submissions)")}
        if "receipt_sha" not in columns:
            self.db.execute("ALTER TABLE submissions ADD COLUMN receipt_sha TEXT NOT NULL DEFAULT ''")
        columns={r["name"] for r in self.db.execute("PRAGMA table_info(submissions)")}
        if "snapshot_dir" not in columns:
            self.db.execute("ALTER TABLE submissions ADD COLUMN snapshot_dir TEXT NOT NULL DEFAULT ''")
        review_columns={r["name"] for r in self.db.execute("PRAGMA table_info(reviews)")}
        for column,ddl in (
            ("findings_json","TEXT NOT NULL DEFAULT '[]'"),
            ("material_count","INTEGER NOT NULL DEFAULT 0"),
            ("advisory_count","INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in review_columns:
                self.db.execute(f"ALTER TABLE reviews ADD COLUMN {column} {ddl}")
        self.db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('paused','false')")

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _worker_instance_guard_config(self):
        cfg=self.policy.get("worker_instance_guard",{})
        return cfg if isinstance(cfg,dict) else {}

    def _worker_instance_guard_active(self, at=None):
        cfg=self._worker_instance_guard_config()
        now=self.clock() if at is None else float(at)
        return bool(cfg.get("enabled",False)) and now >= float(cfg.get("effective_after_epoch",0))

    @staticmethod
    def _validate_worker_instance_id(worker_instance_id):
        value=str(worker_instance_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,95}",value):
            raise GovernanceError(
                "worker_instance_id must be a per-chat id of 8-96 letters/digits/_/- "
                "(example: chat-7f3a91c2d4e8)")
        return value

    def _assert_worker_instance(self, lease, worker_instance_id):
        cfg=self._worker_instance_guard_config()
        effective=float(cfg.get("effective_after_epoch",0))
        if not bool(cfg.get("enabled",False)) or float(lease["claimed_at"]) < effective:
            return
        owner=str(lease["worker_instance_id"] or "")
        if not owner:
            raise GovernanceError("Active post-fix lease is missing worker_instance_id; release and re-claim")
        supplied=str(worker_instance_id or "").strip()
        if supplied != owner:
            raise GovernanceError(
                "WORKER_INSTANCE_CONFLICT: this active lease/workspace belongs to another "
                "ChatGPT worker instance. Do not reuse the same agent_id from a parallel chat; "
                "use that chat's original --worker-instance-id or a different agent_id.")

    def paused(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        return row["value"] == "true"

    def pause(self, enabled, reason):
        if not reason or len(reason.strip()) < 8:
            raise GovernanceError("Pause/resume needs a concrete reason (>=8 chars)")
        with self.tx():
            self.db.execute("UPDATE settings SET value=? WHERE key='paused'",
                            ("true" if enabled else "false",))
            self.db.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                ("last_control_action", json.dumps(
                    {"paused":enabled,"reason":reason,"at":self.clock()},
                    ensure_ascii=False)))
        return {"paused":self.paused(),"reason":reason}

    def _reap(self, at):
        lease_config = self.policy["leases"]
        stale_sec = float(lease_config["stale_seconds"])
        self.db.execute(
            "UPDATE leases SET state='STALE' WHERE state='ACTIVE' "
            "AND ? - heartbeat_at >= ? AND ? < ttl_end",
            (at,stale_sec,at))
        self.db.execute(
            "UPDATE leases SET state='TTL_EXPIRED' WHERE state='ACTIVE' AND ? >= ttl_end",
            (at,))

    def reap(self):
        with self.tx():
            self._reap(self.clock())
        return self.status()

    def _dynamic_capacity(self):
        """Return adaptive role/total upper bounds. These are ceilings, never occupancy targets."""
        startup=self.policy.get("startup",{})
        cfg=startup.get("dynamic_capacity",{})
        if not isinstance(cfg,dict) or not cfg.get("enabled",False):
            research=int(startup.get("research_engineers",0))
            auditors=int(startup.get("auditors",0))
            total=int(startup.get("max_total",research+auditors))
            return {
                "enabled":False,
                "research_engineers":research,
                "auditors":auditors,
                "total":total,
                "hard_max_total":total,
                "reason":{"mode":"legacy_fixed"},
            }

        active_research=int(self.db.execute(
            "SELECT count(*) FROM leases WHERE state='ACTIVE' AND role='research_engineer'"
        ).fetchone()[0])
        active_auditors=int(self.db.execute(
            "SELECT count(*) FROM leases WHERE state='ACTIVE' AND role='auditor'"
        ).fetchone()[0])
        pending_e1=int(self.db.execute(
            "SELECT count(*) FROM submissions WHERE decision='PENDING'"
        ).fetchone()[0])

        base_r=max(0,int(cfg.get("base_research_engineers",3)))
        headroom=max(1,int(cfg.get("research_join_headroom",2)))
        hard_r=max(base_r,int(cfg.get("hard_max_research_engineers",9)))
        research=min(hard_r,max(base_r,active_research+headroom))

        base_a=max(0,int(cfg.get("base_auditors",1)))
        per_a=max(1,int(cfg.get("pending_e1_per_auditor",2)))
        hard_a=max(base_a,int(cfg.get("hard_max_auditors",2)))
        audit_demand=(pending_e1+per_a-1)//per_a if pending_e1 else 0
        auditors=min(hard_a,max(base_a,active_auditors,audit_demand))

        hard_total=max(1,int(cfg.get(
            "hard_max_total",startup.get("max_total_future_without_policy_review",10))))
        total=min(hard_total,research+auditors)
        # Never report/admit below already-active occupancy if policy is edited live.
        active_total=active_research+active_auditors
        total=max(active_total,total)
        return {
            "enabled":True,
            "research_engineers":research,
            "auditors":auditors,
            "total":total,
            "hard_max_total":hard_total,
            "reason":{
                "active_research":active_research,
                "research_headroom":headroom,
                "pending_e1":pending_e1,
                "pending_e1_per_auditor":per_a,
                "active_auditors":active_auditors,
            },
        }

    def _limit(self, role):
        caps=self._dynamic_capacity()
        return int(caps[ROLE_LIMITS[role]])

    def _streak(self, family, field="family"):
        """Scientific stop-loss only; non-scientific gate failures do not kill a family."""
        if field not in ("family","lineage"):
            raise GovernanceError("Invalid streak field")
        rows = self.db.execute(
            "SELECT s.delta,s.evidence_label,s.manifest_path FROM submissions s "
            "JOIN leases l ON l.lease_id=s.lease_id "
            f"WHERE l.{field}=? ORDER BY s.at DESC LIMIT 30", (family,)).fetchall()
        n = 0
        for row in rows:
            manifest={}
            try:
                path=Path(row["manifest_path"])
                if path.is_file():
                    manifest=json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                manifest={}
            scientific=manifest.get("scientific_outcome")
            scope=manifest.get("falsification_scope")
            gate=manifest.get("gate_stratification") or {}
            blocker=gate.get("primary_blocker_class")

            # New multidimensional results: implementation/performance/admin/env/
            # safety/release failures do not consume the scientific stop-loss budget.
            if blocker and blocker!="SCIENTIFIC":
                continue

            if scientific:
                if scientific=="POSITIVE":
                    break
                if scientific!="NEGATIVE":
                    continue
                # Exact/implementation-scoped negatives may stop that exact attempt,
                # but they must not accumulate into lineage death.
                if field=="lineage" and scope!="FAMILY_LEVEL":
                    continue
                if row["delta"] is not None and float(row["delta"])>0 and scope!="FAMILY_LEVEL":
                    continue
                n+=1
                continue

            # Legacy evidence had no explicit dimensions. Be conservative:
            # positive-delta NONPASS is partial progress, and legacy results cannot
            # establish lineage-wide death without an explicit FAMILY_LEVEL scope.
            if row["delta"] is not None and float(row["delta"])>0:
                break
            is_bad = row["evidence_label"] in ("NONPASS","INCONCLUSIVE")
            if row["delta"] is not None:
                is_bad = is_bad or float(row["delta"]) <= 0
            if row["delta"] is None and row["evidence_label"] == "EVIDENCE_ONLY":
                continue
            if not is_bad:
                break
            n+=1
        return n


    def _phase_guard_config(self):
        return self.policy.get("phase_priority_guard",{})

    def _phase_guard_active(self):
        cfg=self._phase_guard_config()
        return bool(cfg.get("enabled",False)) and self.clock() >= float(cfg.get("effective_after_epoch",0))

    def _current_root_rc_mainline_freeze(self):
        """Reuse the Lead routing record to block only new self-directed mainline work
        while the current product release candidate still lacks independent closure.
        Existing leases, backlog-bound work, exact recovery and explorers are unaffected.
        """
        path=self.home/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json"
        if not path.is_file():
            return None
        try:
            data=jsonload(path)
        except Exception as exc:
            raise GovernanceError(
                "Current-root routing record unreadable; new self-directed mainline fails closed"
            ) from exc
        rc=(((data.get("current_routing") or {}).get("product_root") or {})
            .get("release_candidate") or {})
        status=str(rc.get("status") or "")
        if (status.startswith("FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_")
                and status.endswith("AUDIT")):
            return {
                "status":status,
                "freeze_record":str(rc.get("freeze_record") or
                    "governance/CURRENT_PRODUCT_RC_FREEZE_20261031.json"),
                "bundle":str(rc.get("bundle") or ""),
                "audit_handoff":str(rc.get("audit_handoff") or ""),
            }
        return None

    def _v1_release_gate_ids(self):
        path=self.home/"V1_RELEASE_CRITERIA_20261102.json"
        if not path.is_file():
            return set()
        try:
            data=jsonload(path)
        except Exception:
            return set()
        return {
            str(g.get("id") or "")
            for g in (data.get("gates") or [])
            if isinstance(g,dict) and str(g.get("id") or "")
        }

    def _preflight_backlog_contract(self, row):
        """Return empty string when a backlog row is actually claimable by the control plane.

        Invalid Lead/backlog metadata must be visible, but must never become a
        global self-directed-work blocker. This catches schema/reuse-plan drift
        before phase-priority can deadlock the pool.
        """
        try:
            family=canonical(row["family"])
            lineage=canonical(row.get("lineage") or row["family"])
            capability=row["capability"]
            lane=row["lane"]
            hypothesis=row["hypothesis"]
            backlog_id=str(row.get("id") or "")
            if not backlog_id:
                return "backlog row missing id"
            if str(row.get("plan") or "")=="V1_PRODUCT_CLOSEOUT":
                gate=str(row.get("release_gate") or "")
                valid_gates=self._v1_release_gate_ids()
                if not gate:
                    return "V1 closeout backlog row missing release_gate"
                if gate not in valid_gates:
                    return "V1 closeout backlog row has unknown release_gate: "+gate
                try:
                    deadline=int(row.get("task_deadline_hours") or 0)
                except Exception:
                    deadline=0
                if deadline<=0 or deadline>48:
                    return "V1 closeout backlog row task_deadline_hours must be 1..48"
            if capability not in self.policy["capabilities"]:
                return "unknown capability: "+str(capability)
            if lane not in self.policy["research_lane_weights_advisory"]:
                return "unknown research lane: "+str(lane)
            self.reuse_check(
                "research_engineer",family,capability,hypothesis,lane,
                lineage=lineage,reuse_plan=row.get("reuse_plan"),
                backlog_id=backlog_id)
            return ""
        except (GovernanceError,KeyError,TypeError,ValueError) as exc:
            return str(exc)

    def phase_priority_status(self):
        """Return current auto-assign backlog availability without claiming work."""
        cfg=self._phase_guard_config()
        result={
            "active":self._phase_guard_active(),
            "available_unclaimed":[],
            "invalid_backlog":[],
            "auto_assign_plans":[],
            "current_phase":None,
            "self_directed_active":[],
            "closeout_mode":False,
            "closeout_required_backlog":[],
            "closeout_reason":"",
            "p1_research_closeout_complete":False,
        }
        path=self.home/"RESEARCH_BACKLOG.json"
        if not path.is_file():
            result["error"]="RESEARCH_BACKLOG.json missing"
            return result
        data=jsonload(path)
        phase=data.get("phase_policy",{})
        plans=list(phase.get("auto_assign_plans",[]))
        result["auto_assign_plans"]=plans
        result["current_phase"]=phase.get("current_phase")
        result["closeout_mode"]=bool(phase.get("closeout_mode",False))
        result["closeout_required_backlog"]=list(phase.get("closeout_required_backlog",[]))
        result["closeout_reason"]=str(phase.get("closeout_reason",""))
        result["p1_research_closeout_complete"]=bool(
            phase.get("p1_research_closeout_complete",False))
        allowed=set(plans)
        candidates=[]
        for row in sorted(data.get("candidates",[]),
                          key=lambda r:(r.get("priority",99),r.get("id",""))):
            if row.get("status","active")!="active":
                continue
            if allowed and row.get("plan") not in allowed:
                continue
            preflight_error=self._preflight_backlog_contract(row)
            if preflight_error:
                result["invalid_backlog"].append({
                    "id":row.get("id"),
                    "family":row.get("family"),
                    "capability":row.get("capability"),
                    "priority":row.get("priority",99),
                    "error":preflight_error,
                    "blocking":False,
                })
                continue
            # Normal tasks are consumed once claimed. An active backlog task
            # whose newest exact backlog lease was independently NEEDS_WORK is
            # a formal remediation target, not a permanently consumed task.
            prior=self.db.execute(
                "SELECT lease_id,agent_id,state,backlog_id,workspace FROM leases "
                "WHERE backlog_id=? ORDER BY claimed_at DESC LIMIT 1",
                (str(row.get("id") or ""),)).fetchone()
            remediation=False
            followup=False
            if prior:
                sub=self.db.execute(
                    "SELECT submission_id,decision FROM submissions WHERE lease_id=? "
                    "ORDER BY at DESC LIMIT 1",(prior["lease_id"],)).fetchone()
                remediation=bool(
                    prior["state"]=="SUBMITTED" and sub
                    and sub["decision"]=="NEEDS_WORK"
                    and str(prior["backlog_id"] or "")==str(row.get("id") or ""))
                # Keep phase-priority availability consistent with continuation:
                # a released/stale/expired exact backlog lease that never submitted
                # did not consume the scientific task. Likewise, a non-single-pass
                # active backlog may deliberately continue after an intermediate
                # ACCEPT_E1/EVIDENCE_ONLY boundary while Lead leaves it incomplete.
                followup_no_submission=bool(
                    prior["state"] in ("RELEASED","STALE","TTL_EXPIRED")
                    and sub is None
                    and str(prior["backlog_id"] or "")==str(row.get("id") or "")
                )
                followup_intermediate=bool(
                    not row.get("single_pass")
                    and not row.get("completion_level")
                    and not row.get("completion_submission")
                    and prior["state"]!="ACTIVE"
                    and sub is not None
                    and sub["decision"] in ("ACCEPT_E1","EVIDENCE_ONLY")
                    and str(prior["backlog_id"] or "")==str(row.get("id") or "")
                )
                followup=followup_no_submission or followup_intermediate
                if not remediation and not followup:
                    continue
            else:
                # Legacy rows without backlog_id retain the prior family/capability
                # consumption rule; they are never auto-classified as remediation.
                legacy=self.db.execute(
                    "SELECT lease_id FROM leases WHERE family=? AND capability=? "
                    "ORDER BY claimed_at DESC LIMIT 1",
                    (canonical(row["family"]),row["capability"])).fetchone()
                if legacy:
                    continue
            # Explicitly adopted self-directed work also consumes the backlog row even
            # when the family differs in legacy rows.
            adopted=row.get("adopted_lease_id")
            if adopted and self.db.execute(
                "SELECT 1 FROM leases WHERE lease_id=?",(adopted,)).fetchone():
                continue
            priority=row.get("priority",99)
            item={
                "id":row.get("id"),"plan":row.get("plan"),
                "task_pool":row.get("task_pool"),
                "priority":priority,
                "family":canonical(row["family"]),
                "capability":row["capability"],
                # Negative-priority / explicit observed-blocker backlog is a
                # product-correctness interrupt and must preempt new
                # self-directed work even across advisory task-pool pins.
                "global_preempt_self_directed":bool(
                    (isinstance(priority,(int,float)) and priority < 0)
                    or row.get("observed_blocker")
                ),
            }
            if prior and remediation:
                item.update(remediation=True,
                            previous_lease_id=prior["lease_id"],
                            previous_agent_id=prior["agent_id"],
                            previous_workspace=prior["workspace"])
            elif prior and followup:
                item.update(followup=True,
                            previous_lease_id=prior["lease_id"],
                            previous_agent_id=prior["agent_id"],
                            previous_workspace=prior["workspace"])
            candidates.append(item)
        result["available_unclaimed"]=candidates
        effective=float(cfg.get("effective_after_epoch",0))
        rows=self.db.execute(
            """SELECT lease_id,agent_id,family,capability,claimed_at
                 FROM leases
                WHERE state='ACTIVE' AND role='research_engineer'
                  AND (backlog_id IS NULL OR backlog_id='')
                  AND claimed_at>=?
                ORDER BY claimed_at""",(effective,)).fetchall()
        result["self_directed_active"]=[dict(r) for r in rows]
        cr=dict(cfg.get("continuous_research_exception") or {})
        allowed_phases=list(cr.get("allowed_phases") or [])
        allowed_lanes=list(cr.get("allowed_lanes") or [])
        product_mainline_exempt=bool(
            cr.get("product_mainline_never_blocked_by_research_quota",True)
        )
        quota_active=[
            r for r in result["self_directed_active"]
            if not (product_mainline_exempt
                    and str(r.get("family") or "").startswith("portfolio.mainline."))
        ]
        active_count=len(quota_active)
        max_active=max(0,int(cr.get("max_active_self_directed",0) or 0))
        phase_allowed=(
            not allowed_phases
            or str(result.get("current_phase") or "") in set(map(str,allowed_phases))
        )
        blockers_clear=(
            not bool(cr.get("requires_no_closeout_backlog",True))
            or not result["closeout_required_backlog"]
        )
        result["continuous_research"]={
            "enabled":bool(cr.get("enabled",False)),
            "phase_allowed":phase_allowed,
            "blockers_clear":blockers_clear,
            "allowed_lanes":allowed_lanes,
            "active_count":active_count,
            "active_total_count":len(result["self_directed_active"]),
            "product_mainline_active_count":(
                len(result["self_directed_active"])-active_count
                if product_mainline_exempt else 0
            ),
            "max_active":max_active,
            "slots_available":max(0,max_active-active_count),
            "soft_budget_only":bool(cr.get("soft_budget_only",True)),
            "product_share_target":cr.get("product_share_target"),
            "research_share_target":cr.get("research_share_target"),
            "research_mix":cr.get("research_mix") or {},
            "product_mainline_never_blocked_by_research_quota":bool(
                cr.get("product_mainline_never_blocked_by_research_quota",True)
            ),
        }
        return result

    def _reuse_guard_config(self):
        return self.policy.get("reuse_guard",{})

    def _reuse_guard_active(self):
        cfg=self._reuse_guard_config()
        return bool(cfg.get("enabled",False)) and self.clock() >= float(cfg.get("effective_after_epoch",0))

    def _lease_requires_reuse_guard(self, lease):
        cfg=self._reuse_guard_config()
        return (bool(cfg.get("enabled",False))
                and lease["role"] in cfg.get("required_roles",["research_engineer"])
                and float(lease["claimed_at"]) >= float(cfg.get("effective_after_epoch",0)))

    def reuse_coverage(self):
        cfg=self._reuse_guard_config()
        effective=float(cfg.get("effective_after_epoch",0))
        roles=tuple(cfg.get("required_roles",["research_engineer"]))
        if not roles:
            return {"eligible":0,"guarded":0,"unguarded":0,"active_unguarded":[],"submitted_unguarded":[]}
        marks=",".join("?" for _ in roles)
        rows=self.db.execute(
            f"""SELECT lease_id,state,reuse_guard_version FROM leases
                 WHERE claimed_at>=? AND role IN ({marks}) ORDER BY claimed_at""",
            (effective,*roles)).fetchall()
        unguarded=[r["lease_id"] for r in rows if int(r["reuse_guard_version"] or 0)<=0]
        active_unguarded=[r["lease_id"] for r in rows
                          if int(r["reuse_guard_version"] or 0)<=0 and r["state"]=="ACTIVE"]
        submitted=self.db.execute(
            f"""SELECT l.lease_id,s.submission_id,s.evidence_label,s.decision
                  FROM leases l JOIN submissions s ON s.lease_id=l.lease_id
                 WHERE l.claimed_at>=? AND l.role IN ({marks})
                   AND coalesce(l.reuse_guard_version,0)<=0 ORDER BY s.at""",
            (effective,*roles)).fetchall()
        detail=[dict(r) for r in submitted]
        pending_e1=[r for r in detail
                    if r["evidence_label"]=="LEAD_READY" and r["decision"]=="PENDING"]
        return {
            "eligible":len(rows),
            "guarded":len(rows)-len(unguarded),
            "unguarded":len(unguarded),
            "active_unguarded":active_unguarded,
            "submitted_unguarded":[r["lease_id"] for r in submitted],
            "unguarded_submission_details":detail,
            "pending_unguarded_e1":pending_e1,
            "enforcement_clean":not active_unguarded and not pending_e1,
        }

    def _reuse_catalog(self):
        cfg=self._reuse_guard_config()
        name=str(cfg.get("catalog") or REUSE_CATALOG_FILE)
        path=self.home/name
        raw=path.read_bytes()
        data=json.loads(raw.decode("utf-8"))
        if data.get("schema") not in ("xiaoyu-reuse-catalog-v1","xiaoyu-reuse-catalog-v2"):
            raise GovernanceError("Unsupported reuse catalog schema")
        return data,sha(raw),path

    @staticmethod
    def _prior_tokens(text):
        text=str(text or "").lower()
        out=set(re.findall(r"[a-z0-9_]{2,}",text))
        for chunk in re.findall(r"[\u3400-\u9fff]+",text):
            if len(chunk)==1:
                out.add(chunk)
            else:
                out.update(chunk[i:i+2] for i in range(len(chunk)-1))
        return out

    @staticmethod
    def _norm_hypothesis(text):
        return " ".join(str(text or "").strip().lower().split())

    def prior_work(self, family, capability, hypothesis, lineage="", limit=8):
        """Cheap local prior-work search over the existing registry; no new search service."""
        family=canonical(family)
        lineage=canonical(lineage) if lineage else family
        try:limit=max(1,min(30,int(limit)))
        except Exception:limit=8
        q=self._prior_tokens(hypothesis)
        norm=self._norm_hypothesis(hypothesis)
        rows=self.db.execute(
            """SELECT l.lease_id,l.family,l.lineage,l.capability,l.hypothesis,l.state,
                      l.claimed_at,s.submission_id,s.evidence_label,s.decision,s.delta
                 FROM leases l LEFT JOIN submissions s ON s.lease_id=l.lease_id
                WHERE l.capability=? ORDER BY l.claimed_at DESC""",(capability,)).fetchall()
        matches=[]
        for row in rows:
            t=self._prior_tokens(row["hypothesis"])
            union=q|t
            jac=(len(q&t)/len(union)) if union else 0.0
            score=0.70*jac
            if row["family"]==family:score+=0.15
            if row["lineage"]==lineage:score+=0.15
            exact=self._norm_hypothesis(row["hypothesis"])==norm
            matches.append({
                "lease_id":row["lease_id"],
                "submission_id":row["submission_id"],
                "family":row["family"],"lineage":row["lineage"],
                "state":row["state"],"evidence_label":row["evidence_label"],
                "decision":row["decision"],"delta":row["delta"],
                "similarity":round(score,4),"hypothesis_jaccard":round(jac,4),
                "exact_hypothesis":exact,
                "hypothesis":row["hypothesis"],
            })
        matches.sort(key=lambda x:(x["exact_hypothesis"],x["similarity"],
                                   bool(x["submission_id"])),reverse=True)
        return {"family":family,"lineage":lineage,"capability":capability,
                "query_hypothesis":hypothesis,"matches":matches[:limit]}

    def reuse_doctor(self):
        """Local catalog/decision/prior-work health audit. No web/API calls."""
        catalog,catalog_sha,_=self._reuse_catalog()
        now_date=time.strftime("%Y-%m-%d",time.gmtime(self.clock()))
        issues=[]
        components=catalog.get("components",[])
        ids=[c.get("id") for c in components if isinstance(c,dict)]
        if len(ids)!=len(set(ids)):
            issues.append({"severity":"error","type":"duplicate_component_id"})
        by={c.get("id"):c for c in components if isinstance(c,dict)}
        meta=catalog.get("metadata_policy",{})
        blocked=set(meta.get("new_use_blocked_lifecycles",["hold","deprecated"]))
        ext_required=meta.get("external_component_required_fields",[])
        external_types={"pypi","github","external_repo","local_external_checkout"}
        stale=[]
        for cid,c in by.items():
            lifecycle=c.get("lifecycle")
            if lifecycle not in set(meta.get("lifecycles",[])):
                issues.append({"severity":"error","type":"invalid_lifecycle","component":cid,
                               "value":lifecycle})
            if c.get("source",{}).get("type") in external_types:
                missing=[x for x in ext_required if x not in c or c.get(x) in (None,"","unknown")]
                if missing:
                    issues.append({"severity":"warning","type":"external_metadata_missing",
                                   "component":cid,"fields":missing})
            ref=c.get("decision_ref")
            if isinstance(ref,str) and ref and not (self.home/"decisions"/(ref+".md")).is_file():
                issues.append({"severity":"warning","type":"decision_record_missing",
                               "component":cid,"decision_ref":ref})
            review=c.get("review_after")
            if isinstance(review,str) and review < now_date:
                stale.append(cid)
                issues.append({"severity":"warning","type":"component_review_stale",
                               "component":cid,"review_after":review})
        backlog=jsonload(self.home/"RESEARCH_BACKLOG.json")
        phase_policy=backlog.get("phase_policy",{})
        allowed_plans=set(phase_policy.get("auto_assign_plans",[]))
        require_phase_hold=bool(phase_policy.get("require_hold_outside_auto_assign",False))
        backlog_refs=[]
        for row in backlog.get("candidates",[]):
            is_active=row.get("status","active")=="active"
            if (require_phase_hold and allowed_plans and is_active
                    and row.get("plan") not in allowed_plans):
                issues.append({
                    "severity":"error","type":"active_backlog_outside_phase",
                    "backlog_id":row.get("id"),"plan":row.get("plan"),
                    "current_phase":phase_policy.get("current_phase"),
                    "allowed_plans":sorted(allowed_plans),
                })
            for cid in row.get("reuse_plan",{}).get("components",[]):
                backlog_refs.append((row.get("id"),cid))
                if not is_active:
                    continue
                if cid not in by:
                    issues.append({"severity":"error","type":"backlog_unknown_component",
                                   "backlog_id":row.get("id"),"component":cid})
                elif by[cid].get("lifecycle") in blocked:
                    issues.append({"severity":"error","type":"backlog_blocked_component",
                                   "backlog_id":row.get("id"),"component":cid,
                                   "lifecycle":by[cid].get("lifecycle")})
        active=[]
        for row in self.db.execute(
            "SELECT lease_id,family,capability,reuse_plan_json,reuse_catalog_sha,"
            "reuse_guard_version FROM leases WHERE state='ACTIVE' AND role='research_engineer'"):
            try:plan=json.loads(row["reuse_plan_json"] or "{}")
            except Exception:plan={}
            refs=plan.get("components",[])
            drift=bool(row["reuse_catalog_sha"] and row["reuse_catalog_sha"]!=catalog_sha)
            blocked_refs=[cid for cid in refs if cid in by and by[cid].get("lifecycle") in blocked]
            active.append({"lease_id":row["lease_id"],"family":row["family"],
                           "guard_version":int(row["reuse_guard_version"] or 0),
                           "catalog_drift":drift,"blocked_components":blocked_refs})
            if drift:
                issues.append({"severity":"warning","type":"active_catalog_revision_drift",
                               "lease_id":row["lease_id"],
                               "note":"Current lease remains bound to its stored decision; revalidate only for a new lease."})
            if blocked_refs:
                issues.append({"severity":"error","type":"active_component_now_blocked",
                               "lease_id":row["lease_id"],"components":blocked_refs})
        # Advisory semantic-near-duplicate clusters; never auto-reject old evidence.
        rows=[dict(r) for r in self.db.execute(
            """SELECT l.lease_id,l.family,l.lineage,l.capability,l.hypothesis,l.state,
                      s.submission_id,s.decision
                 FROM leases l LEFT JOIN submissions s ON s.lease_id=l.lease_id
                ORDER BY l.claimed_at""")]
        clusters=[]
        for i,a in enumerate(rows):
            at=self._prior_tokens(a["hypothesis"])
            for b in rows[i+1:]:
                if a["capability"]!=b["capability"]:continue
                bt=self._prior_tokens(b["hypothesis"]);u=at|bt
                jac=(len(at&bt)/len(u)) if u else 0.0
                score=0.70*jac+0.15*(a["family"]==b["family"])+0.15*(a["lineage"]==b["lineage"])
                if score>=0.86:
                    clusters.append({"a":a["lease_id"],"b":b["lease_id"],
                                     "capability":a["capability"],
                                     "similarity":round(score,4)})
        clusters=sorted(clusters,key=lambda x:x["similarity"],reverse=True)[:20]
        coverage=self.reuse_coverage()
        errors=sum(x["severity"]=="error" for x in issues)
        return {"schema":"xiaoyu-reuse-doctor-v1",
                "catalog_version":catalog.get("version"),
                "catalog_sha256":catalog_sha,"checked_at":self.clock(),
                "components":len(by),"stale_reviews":stale,
                "coverage":coverage,"active_decisions":active,
                "near_duplicate_prior_work":clusters,
                "issues":issues,"error_count":errors,
                "warning_count":sum(x["severity"]=="warning" for x in issues),
                "healthy":errors==0 and coverage.get("enforcement_clean",False)}

    def backlog_task(self, backlog_id):
        if not backlog_id:
            return None
        path=self.home/"RESEARCH_BACKLOG.json"
        data=jsonload(path)
        rows=[r for r in data.get("candidates",[]) if r.get("id")==backlog_id]
        if len(rows)!=1:
            raise GovernanceError("Unknown or ambiguous backlog_id")
        return rows[0]

    def _assert_backlog_lease_still_active(self, lease):
        backlog_id=lease["backlog_id"] if "backlog_id" in lease.keys() else ""
        if not backlog_id:
            return
        row=self.backlog_task(backlog_id)
        status=row.get("status","active")
        if status!="active":
            raise GovernanceError(
                f"Backlog-bound lease is no longer active: {backlog_id} status={status}; "
                "release this lease and claim the current successor")

    def _backlog_reuse_plan(self, backlog_id, family, lineage, capability, hypothesis):
        path=self.home/"RESEARCH_BACKLOG.json"
        data=jsonload(path)
        rows=[r for r in data.get("candidates",[]) if r.get("id")==backlog_id]
        if len(rows)!=1:
            raise GovernanceError("Unknown or ambiguous backlog_id for reuse gate")
        row=rows[0]
        if row.get("status","active") != "active":
            raise GovernanceError("Backlog task is not active: "+str(row.get("status")))
        expected=(canonical(row["family"]),canonical(row.get("lineage") or row["family"]),
                  row["capability"],row["hypothesis"])
        actual=(family,lineage,capability,hypothesis)
        if expected!=actual:
            raise GovernanceError("Backlog task differs from Lead-vetted reuse plan")
        plan=row.get("reuse_plan")
        if not isinstance(plan,dict):
            raise GovernanceError("Backlog task missing machine-vetted reuse_plan")
        return plan

    def _phase_claimable_for_agent(self, phase_status, agent_id):
        """Return only auto-assign backlog this stable agent can actually claim.

        Portfolio workers are pinned to task pools by phase_policy.agent_task_pools.
        Backlog in another pool must not globally block self-directed work.
        NEEDS_WORK remediation also preserves author continuity, matching
        continuation.assign_next().
        """
        available=list(phase_status.get("available_unclaimed") or [])
        path=self.home/"RESEARCH_BACKLOG.json"
        agent_pool=None
        if path.is_file():
            try:
                phase=(jsonload(path).get("phase_policy") or {})
                agent_pool=(phase.get("agent_task_pools") or {}).get(agent_id)
            except Exception:
                agent_pool=None
        out=[]
        for item in available:
            if agent_pool and item.get("task_pool")!=agent_pool:
                continue
            if (item.get("remediation")
                    and item.get("previous_agent_id")
                    and item.get("previous_agent_id")!=agent_id):
                continue
            out.append(item)
        return out

    def reuse_check(self, role, family, capability, hypothesis, lane,
                    lineage="", reuse_plan=None, backlog_id="", recovery_of=""):
        """Fail-closed build-vs-reuse gate for every new research lease."""
        family=canonical(family)
        lineage=canonical(lineage) if lineage else family
        cfg=self._reuse_guard_config()
        if role not in cfg.get("required_roles",["research_engineer"]):
            return {"status":"NOT_REQUIRED","source":"role_exempt","plan":{},
                    "matched_rules":[],"catalog_sha256":"","guard_version":int(cfg.get("version",0))}
        if not self._reuse_guard_active():
            return {"status":"GRANDFATHERED_PRE_GUARD","source":"pre_guard","plan":{},
                    "matched_rules":[],"catalog_sha256":"","guard_version":int(cfg.get("version",0))}

        catalog,catalog_sha,catalog_path=self._reuse_catalog()
        source="self_directed"
        if recovery_of:
            old=self.db.execute("SELECT * FROM leases WHERE lease_id=?",(recovery_of,)).fetchone()
            if not old:
                raise GovernanceError("reuse recovery references unknown prior lease")
            if (old["family"],old["lineage"],old["capability"],old["hypothesis"]) != (
                    family,lineage,capability,hypothesis):
                raise GovernanceError("reuse recovery scope differs from prior lease")
            if old["reuse_plan_json"] and old["reuse_plan_json"]!="{}":
                reuse_plan=json.loads(old["reuse_plan_json"])
                source="recovery_inherit"
            elif float(old["claimed_at"]) < float(cfg.get("effective_after_epoch",0)):
                reuse_plan={
                    "mode":"grandfathered_recovery",
                    "components":["xiaoyu_existing_core"],
                    "gap":"Exact recovery of a lease created before the reuse guard; no new subsystem or infrastructure may be introduced during recovery.",
                    "no_new_infrastructure":True,
                }
                source="grandfathered_recovery"
            else:
                raise GovernanceError("Prior lease has no valid reuse decision to inherit")
        elif backlog_id:
            vetted=self._backlog_reuse_plan(backlog_id,family,lineage,capability,hypothesis)
            if reuse_plan not in (None,"",{}):
                supplied=json.loads(reuse_plan) if isinstance(reuse_plan,str) else reuse_plan
                if supplied!=vetted:
                    raise GovernanceError("Caller reuse plan differs from Lead-vetted backlog plan")
            reuse_plan=vetted
            source="backlog_vetted"
        elif reuse_plan in (None,"",{}):
            raise GovernanceError(
                "Reuse gate requires --reuse-plan-json for self-directed research; "
                "run control.py reuse-check before claiming")

        if isinstance(reuse_plan,str):
            try:
                reuse_plan=json.loads(reuse_plan)
            except json.JSONDecodeError as exc:
                raise GovernanceError("reuse_plan must be valid JSON object") from exc
        if not isinstance(reuse_plan,dict):
            raise GovernanceError("reuse_plan must be a JSON object")

        req=catalog.get("universal_requirements",{})
        allowed_modes=set(req.get("allowed_modes",[]))
        mode=reuse_plan.get("mode")
        if mode not in allowed_modes:
            raise GovernanceError("reuse_plan mode is not allowed")
        components=reuse_plan.get("components")
        if not isinstance(components,list) or not components or len(components)>int(req.get("max_components",8)):
            raise GovernanceError("reuse_plan components must be a nonempty bounded list")
        if len(set(components))!=len(components) or not all(isinstance(x,str) for x in components):
            raise GovernanceError("reuse_plan components must be unique string IDs")
        known={c.get("id") for c in catalog.get("components",[]) if isinstance(c,dict)}
        unknown=sorted(set(components)-known)
        if req.get("known_component_ids_only",True) and unknown:
            raise GovernanceError("Unknown reuse component(s): "+", ".join(unknown))
        component_map={c.get("id"):c for c in catalog.get("components",[]) if isinstance(c,dict)}
        blocked_lifecycle=set(catalog.get("metadata_policy",{}).get(
            "new_use_blocked_lifecycles",["hold","deprecated"]))
        blocked=[cid for cid in components
                 if component_map.get(cid,{}).get("lifecycle") in blocked_lifecycle]
        if blocked and mode not in ("falsification","legacy_compat","grandfathered_recovery"):
            raise GovernanceError("Reuse component lifecycle blocks new normal use: "+", ".join(
                cid+"="+str(component_map[cid].get("lifecycle")) for cid in blocked))
        if mode!="grandfathered_recovery":
            cap_rule=catalog.get("capability_requirements",{}).get(capability,{})
            cap_any=set(cap_rule.get("required_any_components",[]))
            if cap_any and not (cap_any & set(components)):
                raise GovernanceError(cap_rule.get(
                    "message","Reuse plan does not anchor this capability to a retained mechanism"))
        gap=reuse_plan.get("gap")
        if not isinstance(gap,str) or len(gap.strip())<int(req.get("min_gap_chars",40)):
            raise GovernanceError("reuse_plan gap must concretely explain the missing capability")
        no_new_infra=reuse_plan.get("no_new_infrastructure")
        infra_exception=reuse_plan.get("lead_infrastructure_exception")
        exception_allowed=bool(
            cfg.get("lead_vetted_infrastructure_exception",False)
            and source=="backlog_vetted"
            and isinstance(infra_exception,dict)
            and infra_exception.get("approved") is True
            and isinstance(infra_exception.get("reason"),str)
            and len(infra_exception.get("reason").strip())>=40
        )
        if req.get("no_new_infrastructure_must_be_true",True) and no_new_infra is not True and not exception_allowed:
            raise GovernanceError(
                "reuse_plan must commit no_new_infrastructure=true; only a Lead-vetted backlog may carry an explicit infrastructure exception")
        new_deps=reuse_plan.get("new_dependencies",[])
        if not isinstance(new_deps,list):
            raise GovernanceError("new_dependencies must be a list")
        if new_deps and not exception_allowed:
            raise GovernanceError(
                "New external dependencies/frameworks require Lead catalog review via an explicit Lead-vetted backlog infrastructure exception")
        if new_deps:
            required_dep=set(cfg.get("external_dependency_required_fields",["id","source","version","license","reason"]))
            for dep in new_deps:
                if not isinstance(dep,dict) or not required_dep.issubset(dep) or any(dep.get(k) in (None,"") for k in required_dep):
                    raise GovernanceError(
                        "Lead-vetted new dependency missing exact id/source/version/license/reason metadata")

        matched=[]
        target_family=family+" "+lineage
        for rule in catalog.get("rules",[]):
            if not isinstance(rule,dict):
                continue
            fp=rule.get("family_regex")
            hp=rule.get("hypothesis_regex")
            if fp and re.search(fp,target_family) is None:
                continue
            if hp and re.search(hp,hypothesis) is None:
                continue
            required=set(rule.get("required_components",[]))
            if required and not required.issubset(set(components)):
                raise GovernanceError(rule.get("message","Reuse rule failed")+
                                      "; required="+",".join(sorted(required)))
            any_req=set(rule.get("required_any_components",[]))
            if any_req and not (any_req & set(components)):
                raise GovernanceError(rule.get("message","Reuse rule failed")+
                                      "; requires one of="+",".join(sorted(any_req)))
            allowed=set(rule.get("allowed_modes",[]))
            if allowed and mode not in allowed:
                raise GovernanceError(rule.get("message","Reuse rule failed")+
                                      "; mode="+str(mode))
            matched.append(rule.get("id","unnamed"))

        prior_summary=self.prior_work(family,capability,hypothesis,lineage=lineage,limit=8)
        prior_plan=None
        v2_active=(int(cfg.get("version",1))>=2 and
                   self.clock()>=float(cfg.get("v2_effective_after_epoch",0)))
        if source=="self_directed" and v2_active:
            prior_plan=reuse_plan.get("prior_work")
            if not isinstance(prior_plan,dict):
                raise GovernanceError(
                    "Reuse Guard V2 requires prior_work review for self-directed research; "
                    "run control.py prior-work and include reviewed + novelty")
            reviewed=prior_plan.get("reviewed")
            novelty=prior_plan.get("novelty")
            replication_of=prior_plan.get("replication_of")
            if not isinstance(reviewed,list) or not all(isinstance(x,str) for x in reviewed):
                raise GovernanceError("prior_work.reviewed must be a list of lease IDs")
            if not isinstance(novelty,str) or len(novelty.strip())<50:
                raise GovernanceError("prior_work.novelty must explain the material difference (>=50 chars)")
            threshold=float(cfg.get("prior_work_similarity_threshold",0.58))
            material=[x for x in prior_summary["matches"]
                      if (x["exact_hypothesis"] or x["similarity"]>=threshold
                          or x["family"]==family or x["lineage"]==lineage)][:3]
            missing=[x["lease_id"] for x in material if x["lease_id"] not in reviewed]
            if missing:
                raise GovernanceError("Prior-work review missing similar lease(s): "+", ".join(missing))
            exact=[x for x in material if x["exact_hypothesis"] and x["submission_id"]]
            if exact and cfg.get("prior_work_exact_block",True):
                ids={x["lease_id"] for x in exact}
                allowed=(mode=="falsification" or
                         (isinstance(replication_of,str) and replication_of in ids))
                if not allowed:
                    raise GovernanceError(
                        "Exact prior submitted hypothesis already exists; change the hypothesis "
                        "materially or declare falsification/replication_of")
            prior_plan={"reviewed":reviewed,"novelty":novelty.strip(),
                        "replication_of":replication_of or None}
        plan={
            "mode":mode,
            "components":components,
            "gap":gap.strip(),
            "no_new_infrastructure":bool(no_new_infra is True),
            "new_dependencies":new_deps,
        }
        if exception_allowed:
            plan["lead_infrastructure_exception"]={
                "approved":True,
                "reason":infra_exception["reason"].strip(),
            }
        if prior_plan is not None:
            plan["prior_work"]=prior_plan
        return {
            "status":"PASS","source":source,"plan":plan,
            "matched_rules":matched,"catalog_sha256":catalog_sha,
            "catalog_version":int(catalog.get("version",1)),
            "policy_revision":str(cfg.get("policy_revision","reuse-v"+str(cfg.get("version",1)))),
            "catalog":str(catalog_path),"guard_version":int(cfg.get("version",1)),
            "prior_work":prior_summary,
        }

    def join(self, agent_id, role, family, capability, hypothesis, lane,
             reopen_basis="", lineage="", reuse_plan=None, backlog_id="", recovery_of="",
             worker_instance_id=""):
        if not ID_PATTERN.fullmatch(agent_id):
            raise GovernanceError("agent_id must be stable 5-64 letters/digits/_/-")
        if role not in ROLE_LIMITS:
            raise GovernanceError("Only research_engineer or auditor can lease work. Lead uses review.")
        family=canonical(family)
        lineage=canonical(lineage) if lineage else family
        if capability not in self.policy["capabilities"]:
            raise GovernanceError("Unknown capability")
        if lane not in self.policy["research_lane_weights_advisory"]:
            raise GovernanceError("Unknown research lane")
        hypothesis_len=len(hypothesis.strip())
        if hypothesis_len < 12:
            raise GovernanceError("Hypothesis must be at least 12 chars")
        if hypothesis_len > 600 and not backlog_id:
            raise GovernanceError("Self-directed hypothesis must be at most 600 chars")
        if len(reopen_basis)>1000:
            raise GovernanceError("reopen basis too long")
        now=self.clock()
        if self._worker_instance_guard_active(now):
            worker_instance_id=self._validate_worker_instance_id(worker_instance_id)
        else:
            worker_instance_id=str(worker_instance_id or "").strip()
        with self.tx():
            self._reap(now)
            if self.paused():
                raise GovernanceError("Research pool paused")
            identity=self.db.execute(
                "SELECT role FROM agents WHERE agent_id=?",(agent_id,)).fetchone()
            if identity and identity["role"]!=role:
                raise GovernanceError("Stable agent_id cannot switch role")
            active=self.db.execute(
                "SELECT * FROM leases WHERE agent_id=? AND state='ACTIVE'",
                (agent_id,)).fetchone()
            if active:
                self._assert_worker_instance(active,worker_instance_id)
                if active["family"] != family or active["capability"] != capability:
                    raise GovernanceError("Existing active lease: release before new claim")
                return {"lease_id":active["lease_id"],
                        "workspace":active["workspace"],"resumed":True,
                        "state":"ACTIVE",
                        "reuse_guard_version":int(active["reuse_guard_version"] or 0),
                        "backlog_id":active["backlog_id"]}
            if (role=="research_engineer" and not backlog_id and not recovery_of
                    and (family.startswith("portfolio.mainline.")
                         or lineage.startswith("portfolio.mainline."))):
                rc_hold=self._current_root_rc_mainline_freeze()
                if rc_hold:
                    raise GovernanceError(
                        "Current-root mainline freeze: independent RC audit is pending; "
                        "new self-directed portfolio.mainline work is not claimable"
                    )
            phase_cfg=self._phase_guard_config()
            if (role==phase_cfg.get("required_role","research_engineer")
                    and self._phase_guard_active()
                    and phase_cfg.get("block_self_directed_when_auto_assign_available",True)
                    and not backlog_id and not recovery_of):
                phase_status=self.phase_priority_status()
                cr=phase_status.get("continuous_research") or {}
                is_product_mainline=(
                    family.startswith("portfolio.mainline.")
                    or lineage.startswith("portfolio.mainline.")
                )
                # Capability-ceiling routing is authoritative for new
                # self-directed exploration in normal portfolio mode too.
                # Product mainline, backlog-bound and recovery work remain
                # exempt so real product work can preempt the research quota.
                if (not is_product_mainline
                        and cr.get("enabled")
                        and cr.get("phase_allowed")
                        and cr.get("blockers_clear")
                        and cr.get("allowed_lanes")
                        and lane not in set(cr.get("allowed_lanes") or [])):
                    raise GovernanceError(
                        "Phase-priority gate: self-directed lane is not allowed "
                        "by the current continuous-research policy"
                    )
                if (not phase_status.get("closeout_mode")
                        and not is_product_mainline
                        and cr.get("enabled")
                        and cr.get("phase_allowed")
                        and cr.get("blockers_clear")
                        and int(cr.get("max_active") or 0)>0
                        and int(cr.get("active_count") or 0)>=int(cr.get("max_active") or 0)):
                    raise GovernanceError(
                        "Phase-priority gate: continuous-research capacity reached"
                    )
                if phase_status.get("closeout_mode"):
                    targets=",".join(str(x) for x in phase_status.get("closeout_required_backlog",[])[:8])
                    lane_allowed=(
                        not cr.get("allowed_lanes")
                        or lane in set(cr.get("allowed_lanes") or [])
                    )
                    # During closeout with no required blocker backlog, keep the
                    # bounded continuous-research exception alive even when the
                    # synthetic/current phase name is outside allowed_phases.
                    # Any required blocker still fails closed via blockers_clear.
                    no_required_closeout=not bool(phase_status.get("closeout_required_backlog"))
                    continuous_allowed=bool(
                        cr.get("enabled")
                        and (cr.get("phase_allowed") or no_required_closeout)
                        and cr.get("blockers_clear")
                        and int(cr.get("slots_available") or 0)>0
                        and lane_allowed
                    )
                    if not continuous_allowed:
                        raise GovernanceError(
                            "Phase-priority gate: phase closeout mode is active"
                            +((" ("+targets+")") if targets else "")
                            +"; only the bounded continuous-research exception may run")
                urgent=[
                    x for x in (phase_status.get("available_unclaimed") or [])
                    if x.get("global_preempt_self_directed")
                ]
                if urgent:
                    ids=",".join(str(x.get("id")) for x in urgent[:8])
                    raise GovernanceError(
                        "Phase-priority gate: global product blocker backlog exists ("+ids+
                        "); new self-directed research must yield to the blocker")
                available=self._phase_claimable_for_agent(phase_status,agent_id)
                if available:
                    ids=",".join(str(x.get("id")) for x in available[:8])
                    raise GovernanceError(
                        "Phase-priority gate: claimable auto-assign backlog exists ("+ids+
                        "); use control.py next/backlog claim before self-directed research")
            reuse_decision=self.reuse_check(
                role,family,capability,hypothesis,lane,lineage=lineage,
                reuse_plan=reuse_plan,backlog_id=backlog_id,recovery_of=recovery_of)
            active_n=self.db.execute(
                "SELECT count(*) FROM leases WHERE state='ACTIVE' AND role=?",(role,)
            ).fetchone()[0]
            caps=self._dynamic_capacity()
            if active_n >= int(caps[ROLE_LIMITS[role]]):
                raise GovernanceError("Role dynamic capacity full")
            if self.db.execute(
                "SELECT count(*) FROM leases WHERE state='ACTIVE'"
            ).fetchone()[0] >= int(caps["total"]):
                raise GovernanceError("Pool dynamic capacity full")
            duplicated=self.db.execute(
                "SELECT lease_id FROM leases WHERE state='ACTIVE' AND family=? AND capability=?",
                (family,capability)).fetchone()
            if duplicated:
                raise GovernanceError("Duplicate active family/capability claim")
            streak=max(self._streak(family),self._streak(lineage,"lineage"))
            if streak>=int(self.policy["stop_loss"]["pause_after_nonimproving"]):
                if len(reopen_basis.strip())<30:
                    raise GovernanceError("Family/lineage paused after repeated NONPASS; meaningful reopen_basis required")
            lease_id="fish-"+uuid.uuid4().hex[:16]
            workspace=(self.workspace_dir / lease_id).resolve()
            if not workspace.is_relative_to(self.home.resolve()):
                raise GovernanceError("workspace outside governance root")
            workspace.mkdir(parents=True,exist_ok=False)
            if not identity:
                self.db.execute(
                    "INSERT INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
                    (agent_id,role,now,now))
            else:
                self.db.execute("UPDATE agents SET last_seen=? WHERE agent_id=?",
                                (now,agent_id))
            decision_bytes=json.dumps(
                {"schema":"xiaoyu-reuse-decision-v2" if int(reuse_decision.get("guard_version",0))>=2 else "xiaoyu-reuse-decision-v1","lease_id":lease_id,
                 "agent_id":agent_id,"family":family,"lineage":lineage,
                 "capability":capability,"hypothesis":hypothesis,
                 "backlog_id":backlog_id,"decision":reuse_decision,
                 "created_at":now},ensure_ascii=False,indent=2,sort_keys=True
            ).encode("utf-8")
            decision_path=workspace/"REUSE_DECISION.json"
            decision_path.write_bytes(decision_bytes)
            decision_sha=sha(decision_bytes)
            self.db.execute(
                "INSERT INTO leases(lease_id,agent_id,role,family,lineage,capability,hypothesis,"
                "lane,tier,workspace,claimed_at,heartbeat_at,ttl_end,state,reopen_basis,"
                "reuse_plan_json,reuse_guard_version,reuse_catalog_sha,reuse_decision_sha,backlog_id,"
                "worker_instance_id)"
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lease_id,agent_id,role,family,lineage,capability,hypothesis,lane,"E0",
                 str(workspace),now,now,now+int(self.policy["leases"]["ttl_seconds"]),
                 "ACTIVE",reopen_basis,json.dumps(reuse_decision.get("plan",{}),
                 ensure_ascii=False,sort_keys=True),int(reuse_decision.get("guard_version",0)),
                 reuse_decision.get("catalog_sha256",""),decision_sha,backlog_id,
                 worker_instance_id))
        return {"lease_id":lease_id,"workspace":str(workspace),
                "resumed":False,"state":"ACTIVE",
                "research_stop_loss_warning":streak>=2,
                "worker_instance_bound":bool(worker_instance_id),
                "reuse_guard":reuse_decision}

    def retrofit_reuse(self, lease_id, reuse_plan, reason):
        """Lead repair for a post-epoch lease created by an older control process."""
        if not isinstance(reason,str) or len(reason.strip())<20:
            raise GovernanceError("reuse retrofit requires a concrete reason (>=20 chars)")
        row=self.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease_id,)).fetchone()
        if not row or row["state"]!="ACTIVE":
            raise GovernanceError("reuse retrofit requires an ACTIVE lease")
        if not self._lease_requires_reuse_guard(row):
            raise GovernanceError("reuse retrofit is only for post-epoch guarded research leases")
        if int(row["reuse_guard_version"] or 0)>0:
            raise GovernanceError("lease already has a reuse decision")
        if isinstance(reuse_plan,str):
            try: retrofit_plan=json.loads(reuse_plan)
            except json.JSONDecodeError as exc:
                raise GovernanceError("reuse retrofit plan must be valid JSON") from exc
        else:
            retrofit_plan=dict(reuse_plan) if isinstance(reuse_plan,dict) else reuse_plan
        cfg=self._reuse_guard_config()
        if (isinstance(retrofit_plan,dict) and int(cfg.get("version",1))>=2
                and self.clock()>=float(cfg.get("v2_effective_after_epoch",0))):
            prior=dict(retrofit_plan.get("prior_work") or {})
            reviewed=list(prior.get("reviewed") or [])
            if lease_id not in reviewed: reviewed.append(lease_id)
            prior["reviewed"]=reviewed
            prior["novelty"]=prior.get("novelty") or (
                "Lead retrofit preserves the exact already-running scientific scope; it adds only "
                "the missing governance decision and does not create a new experiment or subsystem.")
            prior.setdefault("replication_of",None)
            retrofit_plan["prior_work"]=prior
        decision=self.reuse_check(
            row["role"],row["family"],row["capability"],row["hypothesis"],row["lane"],
            lineage=row["lineage"],reuse_plan=retrofit_plan)
        decision=dict(decision)
        decision["source"]="lead_retrofit"
        decision["retrofit_reason"]=reason.strip()
        workspace=Path(row["workspace"])
        decision_path=workspace/"REUSE_DECISION.json"
        if decision_path.exists() or decision_path.is_symlink():
            raise GovernanceError("retrofit refuses an existing REUSE_DECISION.json; inspect manually")
        now=self.clock()
        body=json.dumps(
            {"schema":"xiaoyu-reuse-decision-v2" if int(decision.get("guard_version",0))>=2 else "xiaoyu-reuse-decision-v1","lease_id":lease_id,
             "agent_id":row["agent_id"],"family":row["family"],"lineage":row["lineage"],
             "capability":row["capability"],"hypothesis":row["hypothesis"],
             "backlog_id":row["backlog_id"],"decision":decision,
             "created_at":now},ensure_ascii=False,indent=2,sort_keys=True
        ).encode("utf-8")
        tmp=decision_path.with_name("REUSE_DECISION.json.tmp."+uuid.uuid4().hex)
        created=False
        try:
            with self.tx():
                current=self.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease_id,)).fetchone()
                if not current or current["state"]!="ACTIVE" or int(current["reuse_guard_version"] or 0)>0:
                    raise GovernanceError("lease changed during reuse retrofit")
                with tmp.open("xb") as stream:
                    stream.write(body);stream.flush();os.fsync(stream.fileno())
                os.replace(tmp,decision_path);created=True
                self.db.execute(
                    """UPDATE leases SET reuse_plan_json=?,reuse_guard_version=?,
                       reuse_catalog_sha=?,reuse_decision_sha=? WHERE lease_id=?""",
                    (json.dumps(decision["plan"],ensure_ascii=False,sort_keys=True),
                     int(decision["guard_version"]),decision["catalog_sha256"],
                     sha(body),lease_id))
        except Exception:
            tmp.unlink(missing_ok=True)
            if created:
                decision_path.unlink(missing_ok=True)
            raise
        return {"lease_id":lease_id,"status":"RETROFIT_PASS",
                "reuse_guard_version":int(decision["guard_version"]),
                "reuse_decision_sha256":sha(body),"decision":decision}

    def continue_agent(self, agent_id, worker_instance_id=""):
        """Same ChatGPT turn handoff; claims work, never invokes an LLM."""
        from continuation import assign_next
        return assign_next(self, agent_id, GovernanceError, worker_instance_id)

    def _owner_active(self, lease_id, agent_id, worker_instance_id=""):
        row=self.db.execute(
            "SELECT * FROM leases WHERE lease_id=? AND agent_id=?",
            (lease_id,agent_id)).fetchone()
        if not row or row["state"]!="ACTIVE":
            raise GovernanceError("Not an active lease owned by agent_id")
        self._assert_worker_instance(row,worker_instance_id)
        return row

    def heartbeat(self, lease_id, agent_id, worker_instance_id=""):
        now=self.clock()
        with self.tx():
            self._reap(now)
            row=self._owner_active(lease_id,agent_id,worker_instance_id)
            if self._lease_requires_reuse_guard(row) and int(row["reuse_guard_version"] or 0)<=0:
                raise GovernanceError(
                    "Post-epoch lease missing reuse decision; heartbeat refused until Lead retrofit")
            self._assert_backlog_lease_still_active(row)
            lease_cfg=self.policy.get("leases",{})
            new_ttl=float(row["ttl_end"])
            if lease_cfg.get("sliding_ttl_on_heartbeat",False):
                renew=float(lease_cfg.get("ttl_renew_seconds",lease_cfg.get("ttl_seconds",0)) or 0)
                if renew>0:
                    new_ttl=now+renew
            self.db.execute("UPDATE leases SET heartbeat_at=?,ttl_end=? WHERE lease_id=?",
                            (now,new_ttl,lease_id))
            self.db.execute("UPDATE agents SET last_seen=? WHERE agent_id=?",
                            (now,agent_id))
        return {"lease_id":lease_id,"ttl_end":new_ttl,
                "lease_remaining_seconds":max(0,int(new_ttl-now))}

    def release(self, lease_id, agent_id, worker_instance_id=""):
        with self.tx():
            self._reap(self.clock())
            self._owner_active(lease_id,agent_id,worker_instance_id)
            self.db.execute(
                "UPDATE leases SET state='RELEASED' WHERE lease_id=?",(lease_id,))
        return {"lease_id":lease_id,"state":"RELEASED"}

    def _paid_evidence_required(self, lease):
        """E1 claims using the governed paid gateway need ledger-bound call provenance."""
        try:
            plan=json.loads(lease["reuse_plan_json"] or "{}")
        except Exception:
            plan={}
        components=set(plan.get("components") or [])
        paid=self.policy.get("budget",{}).get("paid_research",{})
        guard=paid.get("runtime_guard",{}) if isinstance(paid,dict) else {}
        effective=float(guard.get("effective_after_epoch") or 0.0)
        return (
            "research_api_gateway" in components
            and bool(guard.get("enabled",False))
            and bool(guard.get("require_proxy_tag",False))
            and float(lease["claimed_at"])>=effective
        )

    def _prefrozen_paid_requirement(self, lease):
        """Return the Lead-vetted paid-evidence contract for a backlog-bound lease."""
        backlog_id=str(lease["backlog_id"] or "")
        if not backlog_id:
            return None
        path=self.home/"RESEARCH_BACKLOG.json"
        if not path.is_file():
            raise GovernanceError("Backlog-bound paid claim has no RESEARCH_BACKLOG.json")
        data=jsonload(path)
        rows=[r for r in data.get("candidates",[]) if r.get("id")==backlog_id]
        if len(rows)!=1:
            raise GovernanceError("Backlog-bound paid claim has unknown/ambiguous backlog_id")
        req=rows[0].get("paid_evidence_requirement")
        return req if isinstance(req,dict) else None

    def _verify_paid_evidence(self, lease, manifest):
        """Bind LEAD_READY paid-model evidence to durable proxy usage rows."""
        if manifest.get("evidence_label")!="LEAD_READY" or not self._paid_evidence_required(lease):
            return {"required":False}
        pe=manifest.get("paid_evidence")
        if not isinstance(pe,dict):
            raise GovernanceError(
                "LEAD_READY claim using research_api_gateway requires paid_evidence ledger binding")
        call_ids=pe.get("call_ids")
        if (not isinstance(call_ids,list) or not call_ids or len(call_ids)>500
                or not all(isinstance(x,str) and re.fullmatch(r"api-[0-9a-f]{32}",x) for x in call_ids)
                or len(set(call_ids))!=len(call_ids)):
            raise GovernanceError("paid_evidence.call_ids must be 1-500 unique api-<hex32> IDs")
        scope=pe.get("budget_scope")
        if not isinstance(scope,str) or not scope.startswith("proxy:"):
            raise GovernanceError("paid_evidence.budget_scope must be an explicit proxy:<tag> scope")
        paid=self.policy.get("budget",{}).get("paid_research",{})
        guard=paid.get("runtime_guard",{}) if isinstance(paid,dict) else {}
        allowed_tags={str(x) for x in (guard.get("allowed_proxy_tags") or [])}
        tail=scope.split(":",1)[1] if scope.startswith("proxy:") else ""
        base_tag=tail.split(":",1)[0]
        if allowed_tags and base_tag not in allowed_tags:
            raise GovernanceError("paid_evidence budget scope base tag is not currently allowlisted")
        phase=pe.get("phase")
        if phase not in ("smoke","benchmark"):
            raise GovernanceError("paid_evidence.phase must be smoke or benchmark")
        max_raw=pe.get("max_raw_tokens")
        if (not isinstance(max_raw,int) or isinstance(max_raw,bool) or max_raw<=0
                or max_raw>int(paid.get("max_total_tokens") or 100_000_000)):
            raise GovernanceError("paid_evidence.max_raw_tokens must be a positive bounded integer")

        # Freeze the paid-evidence contract at backlog/lease planning time.
        # A result may not rewrite scope/phase/cap after observing actual usage.
        frozen=self._prefrozen_paid_requirement(lease)
        if frozen is not None:
            expected_scope=frozen.get("budget_scope")
            expected_phase=frozen.get("phase")
            expected_cap=frozen.get("max_raw_tokens")
            if expected_scope is not None and scope!=expected_scope:
                raise GovernanceError(
                    f"paid_evidence.budget_scope differs from pre-frozen backlog requirement: "
                    f"{scope!r} != {expected_scope!r}")
            if expected_phase is not None and phase!=expected_phase:
                raise GovernanceError(
                    f"paid_evidence.phase differs from pre-frozen backlog requirement: "
                    f"{phase!r} != {expected_phase!r}")
            if expected_cap is not None and max_raw!=expected_cap:
                raise GovernanceError(
                    f"paid_evidence.max_raw_tokens differs from pre-frozen backlog requirement: "
                    f"{max_raw!r} != {expected_cap!r}")

        db_path=self.home/"research_api_usage.sqlite3"
        if not db_path.is_file():
            raise GovernanceError("Paid evidence ledger is missing")
        con=sqlite3.connect(db_path,timeout=10)
        con.row_factory=sqlite3.Row
        try:
            marks=",".join("?" for _ in call_ids)
            rows=con.execute(
                f"""SELECT call_id,created_at,finished_at,phase,purpose,provider,model,status,
                           actual_tokens,budget_scope,gateway_origin
                      FROM calls WHERE call_id IN ({marks})""", tuple(call_ids)
            ).fetchall()
        finally:
            con.close()
        got={r["call_id"]:r for r in rows}
        missing=[x for x in call_ids if x not in got]
        if missing:
            raise GovernanceError("paid_evidence references unknown call IDs: "+", ".join(missing[:5]))
        now=float(self.clock())
        total=0
        provider=str(paid.get("provider") or "")
        for cid in call_ids:
            row=got[cid]
            if row["status"]!="COMMITTED":
                raise GovernanceError(f"paid_evidence call {cid} is not COMMITTED")
            if row["budget_scope"]!=scope:
                raise GovernanceError(f"paid_evidence call {cid} scope mismatch")
            if row["gateway_origin"]!="http_proxy":
                raise GovernanceError(
                    f"paid_evidence call {cid} lacks authenticated HTTP proxy provenance")
            if row["phase"]!=phase:
                raise GovernanceError(f"paid_evidence call {cid} phase mismatch")
            if provider and row["provider"]!=provider:
                raise GovernanceError(f"paid_evidence call {cid} provider mismatch")
            if float(row["created_at"]) < float(lease["claimed_at"]):
                raise GovernanceError(f"paid_evidence call {cid} predates the research lease")
            if row["finished_at"] is None or float(row["finished_at"])>now:
                raise GovernanceError(f"paid_evidence call {cid} has invalid completion time")
            actual=int(row["actual_tokens"] or 0)
            if actual<=0:
                raise GovernanceError(f"paid_evidence call {cid} has no positive committed usage")
            total+=actual
        if total>max_raw:
            raise GovernanceError(
                f"paid_evidence committed raw tokens {total} exceed declared cap {max_raw}")
        promotion=self.policy.get("paid_evidence_promotion",{}) or {}
        if promotion.get("authenticated_transport_attestation_required",False):
            raise GovernanceError(
                "paid LEAD_READY promotion blocked: authenticated transport attestation unavailable; "
                "gateway_origin=http_proxy is not sufficient provenance")
        return {"required":True,"calls":len(call_ids),"raw_tokens":total,
                "budget_scope":scope,"phase":phase}

    def _validate_scientific_evidence_separation(self, lease, manifest):
        """Keep science, engineering, administration, environment, safety and release distinct."""
        cfg=self.policy.get("scientific_evidence_separation",{})
        if not cfg.get("enabled",False):
            return
        claimed=float(lease["claimed_at"] or 0)
        effective=float(cfg.get("effective_after_epoch",0) or 0)
        if claimed < effective:
            return
        label=manifest.get("evidence_label")
        required_labels=set(cfg.get("required_for_evidence_labels",["LEAD_READY","NONPASS"]))
        if label not in required_labels:
            return
        required={"scientific_outcome","promotion_evidence_status","scientific_falsifier_observed"}
        missing=sorted(required-set(manifest))
        if missing:
            raise GovernanceError("Scientific/evidence separation missing manifest fields: "+str(missing))
        scientific=manifest.get("scientific_outcome")
        promotion=manifest.get("promotion_evidence_status")
        observed=manifest.get("scientific_falsifier_observed")
        if scientific not in set(cfg.get("scientific_outcomes",[])):
            raise GovernanceError("Unknown scientific_outcome")
        if promotion not in set(cfg.get("promotion_evidence_statuses",[])):
            raise GovernanceError("Unknown promotion_evidence_status")
        if not isinstance(observed,bool):
            raise GovernanceError("scientific_falsifier_observed must be boolean")

        gate_cfg=self.policy.get("multidimensional_gate_stratification",{}) or {}
        backlog_id=""
        try:
            backlog_id=str(lease["backlog_id"] or "")
        except (KeyError,IndexError,TypeError):
            backlog_id=""
        backlog_gate_required=True
        if backlog_id:
            try:
                backlog_gate_required=bool(
                    self.backlog_task(backlog_id).get("gate_stratification_required",False))
            except Exception:
                backlog_gate_required=False
        gate_active=bool(
            gate_cfg.get("enabled",False)
            and claimed>=float(gate_cfg.get("effective_after_epoch",0) or 0)
            and label in set(gate_cfg.get("required_for_evidence_labels",["LEAD_READY","NONPASS"]))
            and backlog_gate_required
        )
        gate=None
        if gate_active:
            gate=manifest.get("gate_stratification")
            if not isinstance(gate,dict):
                raise GovernanceError("Post-repair LEAD_READY/NONPASS requires gate_stratification")
            required_gate={
                "primary_blocker_class","implementation_outcome","safety_outcome",
                "release_outcome","administrative_outcome","environment_outcome"
            }
            miss=sorted(required_gate-set(gate))
            if miss:
                raise GovernanceError("gate_stratification missing fields: "+str(miss))
            checks=(
                ("primary_blocker_class","primary_blocker_classes"),
                ("implementation_outcome","implementation_outcomes"),
                ("safety_outcome","safety_outcomes"),
                ("release_outcome","release_outcomes"),
                ("administrative_outcome","administrative_outcomes"),
                ("environment_outcome","environment_outcomes"),
            )
            for field,allowed_key in checks:
                if gate[field] not in set(gate_cfg.get(allowed_key,[])):
                    raise GovernanceError("Unknown gate_stratification "+field)

        if label=="LEAD_READY":
            if scientific!="POSITIVE" or promotion!="VALID" or observed:
                raise GovernanceError(
                    "LEAD_READY requires POSITIVE scientific outcome, VALID promotion evidence, and no observed scientific falsifier")
            if gate_active:
                if gate["primary_blocker_class"]!="NO_BLOCKER":
                    raise GovernanceError("LEAD_READY gate_stratification requires NO_BLOCKER")
                promotion_gate_requirements=(
                    ("implementation_outcome",{"PASS","NOT_APPLICABLE"}),
                    ("safety_outcome",{"PASS","NOT_APPLICABLE"}),
                    ("release_outcome",{"PASS","NOT_APPLICABLE"}),
                    ("administrative_outcome",{"VALID","NOT_APPLICABLE"}),
                    ("environment_outcome",{"READY","NOT_APPLICABLE"}),
                )
                for field,allowed in promotion_gate_requirements:
                    if gate[field] not in allowed:
                        raise GovernanceError(
                            "LEAD_READY requires tested/applicable promotion gates; "
                            f"{field}={gate[field]} is not promotable")
                if self.policy.get("productization_debt",{}).get("future_lead_ready_requires_intent",False):
                    intent=manifest.get("productization_intent")
                    if not isinstance(intent,dict):
                        raise GovernanceError("Post-repair LEAD_READY requires productization_intent")
                    action=intent.get("action")
                    allowed=set(gate_cfg.get("productization_intent_actions",[]))
                    if action not in allowed:
                        raise GovernanceError("Unknown productization_intent action")
                    reason=intent.get("reason")
                    if not isinstance(reason,str) or len(reason.strip())<20:
                        raise GovernanceError("productization_intent requires concrete reason >=20 chars")

        if label=="NONPASS":
            rescue_cfg=self.policy.get("historical_rescue",{}) or {}
            if gate_active:
                blocker=gate["primary_blocker_class"]
                if blocker=="SCIENTIFIC":
                    if scientific!="NEGATIVE" or observed is not True:
                        raise GovernanceError(
                            "Scientific NONPASS requires NEGATIVE outcome and observed scientific falsifier")
                elif blocker in set(gate_cfg.get("nonpass_allowed_nonscientific_blockers",[])):
                    if observed:
                        raise GovernanceError(
                            "Non-scientific NONPASS must not claim scientific_falsifier_observed=true")
                    if blocker=="IMPLEMENTATION_CORRECTNESS" and gate["implementation_outcome"]!="FAIL":
                        raise GovernanceError("IMPLEMENTATION_CORRECTNESS NONPASS requires implementation_outcome=FAIL")
                    if blocker=="IMPLEMENTATION_PERFORMANCE":
                        if gate["implementation_outcome"]!="FAIL":
                            raise GovernanceError("IMPLEMENTATION_PERFORMANCE NONPASS requires implementation_outcome=FAIL")
                        role=manifest.get("performance_gate_role")
                        if role not in set(gate_cfg.get("performance_gate_roles",[])):
                            raise GovernanceError("Performance NONPASS requires valid performance_gate_role")
                        if role=="SCIENTIFIC_COST_HYPOTHESIS":
                            raise GovernanceError(
                                "SCIENTIFIC_COST_HYPOTHESIS must use primary_blocker_class=SCIENTIFIC when its scientific cost hypothesis is falsified")
                    if blocker=="SAFETY_BOUNDARY" and gate["safety_outcome"]!="FAIL":
                        raise GovernanceError("SAFETY_BOUNDARY NONPASS requires safety_outcome=FAIL")
                    if blocker=="RELEASE_INTEGRATION" and gate["release_outcome"]!="FAIL":
                        raise GovernanceError("RELEASE_INTEGRATION NONPASS requires release_outcome=FAIL")
                else:
                    raise GovernanceError(
                        "Administrative/environment/no-blocker conditions cannot create NONPASS; preserve evidence as EVIDENCE_ONLY/NOT_TESTED")
            else:
                if scientific!="NEGATIVE" or observed is not True:
                    raise GovernanceError(
                        "NONPASS requires NEGATIVE scientific outcome and an observed scientific falsifier; budget/scope/token-cap invalidity alone must not create NONPASS")

            rescue_effective=float(rescue_cfg.get("effective_after_epoch",0) or 0)
            if rescue_cfg.get("enabled",False) and claimed >= rescue_effective:
                scope=manifest.get("falsification_scope")
                allowed=set(rescue_cfg.get("allowed_falsification_scopes",[]))
                if rescue_cfg.get("nonpass_scope_required",False):
                    if not isinstance(scope,str) or scope not in allowed:
                        raise GovernanceError(
                            "Post-rescue-policy NONPASS requires falsification_scope in "
                            +str(sorted(allowed))+
                            "; exact candidate failure must not silently imply broader family falsification")
                preserved=manifest.get("preserved_signal")
                if rescue_cfg.get("preserved_signal_required",False):
                    if not isinstance(preserved,str) or len(preserved.strip())<12:
                        raise GovernanceError(
                            "Post-rescue-policy NONPASS requires preserved_signal describing measured capability that remains valid, or an explicit statement that none remains")


    def _manifest_check(self, lease, filename):
        workspace=Path(lease["workspace"])
        if self._lease_requires_reuse_guard(lease) and int(lease["reuse_guard_version"] or 0)<=0:
            raise GovernanceError("Post-epoch lease is missing a reuse decision; Lead retrofit required before submit")
        self._assert_backlog_lease_still_active(lease)
        if lease["reuse_decision_sha"]:
            decision_path=workspace/"REUSE_DECISION.json"
            if (not decision_path.is_file() or decision_path.is_symlink() or
                    sha(decision_path.read_bytes())!=lease["reuse_decision_sha"]):
                raise GovernanceError("Reuse decision missing or altered after claim")
        manifest_path=rel_artifact(workspace,filename)
        raw=manifest_path.read_bytes()
        if re.search(rb"(?i)(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|secret|bearer)[ :=]+[A-Za-z0-9_-]{18,})",raw):
            raise GovernanceError("Possible credential detected in research manifest")
        if len(raw)>100_000:
            raise GovernanceError("manifest exceeds 100 KB")
        manifest=json.loads(raw.decode("utf-8"))
        required={"hypothesis","falsifier","baseline","metric","delta",
                  "limitations","evidence_label","artifacts","method"}
        guarded=bool(int(lease["reuse_guard_version"] or 0) and lease["reuse_plan_json"]!="{}")
        if guarded:
            required.add("reuse_compliance")
        if not required.issubset(manifest):
            raise GovernanceError("Missing manifest fields: "+str(sorted(required-set(manifest))))
        if guarded:
            compliance=manifest.get("reuse_compliance")
            if not isinstance(compliance,dict):
                raise GovernanceError("reuse_compliance must be an object")
            expected=json.loads(lease["reuse_plan_json"])
            considered=compliance.get("components_considered")
            if considered!=expected.get("components"):
                raise GovernanceError("reuse_compliance components differ from claimed reuse plan")
            if compliance.get("new_dependencies")!=[]:
                raise GovernanceError("reuse_compliance cannot add undeclared dependencies")
            if compliance.get("new_infrastructure") is not False:
                raise GovernanceError("reuse_compliance must confirm new_infrastructure=false")
            deviation=compliance.get("deviation","none")
            if not isinstance(deviation,str) or not deviation.strip():
                raise GovernanceError("reuse_compliance deviation must be explicit")
            if deviation.strip().lower()!="none" and expected.get("mode") not in ("falsification","legacy_compat"):
                raise GovernanceError("Reuse-plan deviation requires a new Lead-reviewed claim")
        if manifest["hypothesis"] != lease["hypothesis"]:
            raise GovernanceError("Manifest hypothesis differs from claim")
        if manifest["evidence_label"] not in self.policy["evidence_labels"]:
            raise GovernanceError("Unknown evidence label")
        self._validate_scientific_evidence_separation(lease,manifest)
        paid_check=self._verify_paid_evidence(lease,manifest)
        if paid_check.get("required"):
            manifest["_paid_evidence_verified"]=paid_check
        if not isinstance(manifest["artifacts"],list) or len(manifest["artifacts"])>30:
            raise GovernanceError("artifacts must be list up to 30")
        for field in ("baseline","metric","falsifier","method","limitations"):
            if not isinstance(manifest[field],str) or len(manifest[field].strip()) < 4:
                raise GovernanceError("Missing/short field: "+field)
        delta=manifest["delta"]
        if delta is not None and (not isinstance(delta,(int,float)) or
                                  isinstance(delta,bool) or not -1e100 < float(delta) < 1e100):
            raise GovernanceError("delta must be finite numeric or null")
        if manifest["evidence_label"]=="LEAD_READY":
            if lease["backlog_id"]:
                try:
                    btask=self.backlog_task(lease["backlog_id"])
                except Exception:
                    btask={}
                if btask.get("task_pool")=="exploration":
                    raise GovernanceError("Exploration evidence cannot directly become LEAD_READY; reproduce it on the mainline and pass independent audit")
            if not manifest["artifacts"] or delta is None or float(delta)<=0:
                raise GovernanceError("Lead-ready requires an artifact and positive measured improvement")
        record=[]
        if len(set(manifest["artifacts"]))!=len(manifest["artifacts"]):
            raise GovernanceError("Duplicate artifact")
        for a in manifest["artifacts"]:
            if not isinstance(a,str):raise GovernanceError("artifact path must be string")
            p=rel_artifact(workspace,a)
            if p == manifest_path:
                raise GovernanceError("manifest cannot be its own evidence artifact")
            b=p.read_bytes()
            record.append({"path":a,"sha256":sha(b),"bytes":len(b)})
        return manifest_path,raw,manifest,record

    def _write_submission_snapshot(self, submission_id, lease, raw, record, receipt_bytes):
        root=(self.home/"submission_snapshots").resolve()
        root.mkdir(parents=True,exist_ok=True)
        snapshot=(root/submission_id).resolve()
        if not snapshot.is_relative_to(root):
            raise GovernanceError("submission snapshot escapes governance root")
        snapshot.mkdir(parents=False,exist_ok=False)
        try:
            (snapshot/"manifest.bin").write_bytes(raw)
            workspace=Path(lease["workspace"])
            for idx,obj in enumerate(record):
                data=rel_artifact(workspace,obj["path"]).read_bytes()
                (snapshot/f"artifact_{idx:03d}.bin").write_bytes(data)
            if lease["reuse_decision_sha"]:
                decision_path=workspace/"REUSE_DECISION.json"
                (snapshot/"reuse_decision.bin").write_bytes(decision_path.read_bytes())
            (snapshot/"receipt.json").write_bytes(receipt_bytes)
            index={
                "schema":"fish-submission-snapshot-v1",
                "submission_id":submission_id,
                "lease_id":lease["lease_id"],
                "manifest_sha256":sha(raw),
                "artifacts":record,
                "reuse_decision_sha256":lease["reuse_decision_sha"],
                "receipt_sha256":sha(receipt_bytes),
            }
            (snapshot/"SNAPSHOT_INDEX.json").write_text(
                json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            for child in snapshot.iterdir():
                if child.is_file():
                    try: os.chmod(child,0o444)
                    except OSError: pass
            return snapshot
        except Exception:
            shutil.rmtree(snapshot,ignore_errors=True)
            raise

    def submit(self, lease_id, agent_id, manifest_name, worker_instance_id=""):
        with self.tx():
            self._reap(self.clock())
            lease=self._owner_active(lease_id,agent_id,worker_instance_id)
            path,raw,manifest,record=self._manifest_check(lease,manifest_name)
            backlog_id=str(lease["backlog_id"] or "") if "backlog_id" in lease.keys() else ""
            if backlog_id and manifest.get("evidence_label")=="LEAD_READY":
                task=self.backlog_task(backlog_id)
                boundary=task.get("current_active_lease_evidence_boundary")
                if (str(task.get("current_active_lease") or "")==str(lease_id)
                        and isinstance(boundary,dict)
                        and str(boundary.get("promotion_evidence_status") or "") not in ("","VALID","NOT_APPLICABLE")):
                    raise GovernanceError(
                        "Backlog-bound current lease is explicitly non-promotable: "
                        f"promotion_evidence_status={boundary.get('promotion_evidence_status')}; "
                        "submit supporting evidence only or claim the frozen successor")
            sid="sub-"+uuid.uuid4().hex[:16]
            receipt={
                "schema":"fish-evidence-receipt-v2",
                "lease_id":lease_id,
                "submission_id":sid,
                "manifest_relative":manifest_name,
                "manifest_sha256":sha(raw),
                "artifacts":record,
                "submitted_at":self.clock(),
                "tier":"E1" if manifest["evidence_label"]=="LEAD_READY" else "E0",
                "reuse_decision_sha256":lease["reuse_decision_sha"],
                "paid_evidence_verified":manifest.get("_paid_evidence_verified"),
                "snapshot_version":1
            }
            receipt_path=Path(lease["workspace"])/"receipt.json"
            if receipt_path.exists() or receipt_path.is_symlink():
                if receipt_path.is_symlink() or not receipt_path.is_file():
                    raise GovernanceError("Untrusted orphan receipt path")
                try:
                    old_receipt=jsonload(receipt_path)
                except (OSError,ValueError) as exc:
                    raise GovernanceError("Unreadable orphan receipt") from exc
                stable_fields=("lease_id","manifest_relative","manifest_sha256","artifacts",
                               "tier","reuse_decision_sha256","paid_evidence_verified")
                if any(old_receipt.get(key)!=receipt.get(key) for key in stable_fields):
                    raise GovernanceError("Orphan receipt evidence differs; manual review required")
                receipt_bytes=receipt_path.read_bytes()
            else:
                receipt_bytes=json.dumps(receipt,indent=2,ensure_ascii=False).encode("utf-8")
                tmp=receipt_path.with_name("receipt.json.tmp."+uuid.uuid4().hex)
                try:
                    with tmp.open("xb") as stream:
                        stream.write(receipt_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(tmp,receipt_path)
                finally:
                    tmp.unlink(missing_ok=True)
            receipt_bytes=receipt_path.read_bytes()
            receipt_sha=sha(receipt_bytes)
            snapshot=self._write_submission_snapshot(sid,lease,raw,record,receipt_bytes)
            decision="PENDING" if receipt["tier"]=="E1" else "EVIDENCE_ONLY"
            self.db.execute(
                "INSERT INTO submissions(submission_id,lease_id,at,evidence_label,"
                "manifest_path,manifest_sha,receipt_sha,baseline,metric,delta,decision,snapshot_dir) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid,lease_id,self.clock(),manifest["evidence_label"],
                 str(path),sha(raw),receipt_sha,manifest["baseline"],manifest["metric"],
                 manifest["delta"],decision,str(snapshot)))
            self.db.execute(
                "UPDATE leases SET state='SUBMITTED',tier=? WHERE lease_id=?",
                (receipt["tier"],lease_id))
        seal_path=Path(lease["workspace"])/"WORKSPACE_SEALED.json"
        if not seal_path.exists():
            seal={
                "schema":"xiaoyu-workspace-seal-v1",
                "lease_id":lease_id,
                "submission_id":sid,
                "sealed_at":self.clock(),
                "policy":"Historical workspace is read-only after submission. Continue only in the next lease workspace."
            }
            try:
                seal_path.write_text(json.dumps(seal,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            except OSError:
                pass
        outcome = {"submission_id":sid,"evidence_label":manifest["evidence_label"],
                   "lead_decision":decision,"receipt":str(receipt_path),
                   "immutable_snapshot":str(snapshot)}
        outcome["submission_committed"] = True
        if self.policy.get("continuation",{}).get("enabled",False):
            try:
                outcome.update(self.continue_agent(agent_id,worker_instance_id))
            except Exception as exc:
                outcome.update(continue_research=False, next_task=None,
                               next_step="RETRY_NEXT",
                               continuation_error=type(exc).__name__,
                               continuation_hint="Submission saved and verified by ID; "
                               "repair task handoff then run next --agent-id "
                               + agent_id + " --worker-instance-id <this-chat-id>. "
                               "Do not resubmit this lease.")
        return outcome

    def verify_receipt(self, submission_id):
        row=self.db.execute(
            "SELECT s.*,l.workspace,l.agent_id FROM submissions s JOIN leases l "
            "ON s.lease_id=l.lease_id WHERE s.submission_id=?",
            (submission_id,)).fetchone()
        if not row:raise GovernanceError("Unknown submission")
        snapshot_dir=str(row["snapshot_dir"] or "") if "snapshot_dir" in row.keys() else ""
        if snapshot_dir:
            root=(self.home/"submission_snapshots").resolve()
            snapshot=Path(snapshot_dir).resolve(strict=True)
            if not snapshot.is_relative_to(root) or snapshot.name!=submission_id:
                raise GovernanceError("Untrusted submission snapshot path")
            p=snapshot/"receipt.json"
            if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=row["receipt_sha"]:
                raise GovernanceError("Immutable evidence receipt altered")
            receipt=jsonload(p)
            raw=(snapshot/"manifest.bin").read_bytes()
            if sha(raw)!=receipt["manifest_sha256"] or sha(raw)!=row["manifest_sha"]:
                raise GovernanceError("Immutable manifest snapshot drift")
            reuse_sha=receipt.get("reuse_decision_sha256","")
            if reuse_sha:
                decision_path=snapshot/"reuse_decision.bin"
                if not decision_path.is_file() or sha(decision_path.read_bytes())!=reuse_sha:
                    raise GovernanceError("Immutable reuse decision snapshot drift")
            for idx,obj in enumerate(receipt["artifacts"]):
                artifact_path=snapshot/f"artifact_{idx:03d}.bin"
                b=artifact_path.read_bytes()
                if len(b)!=obj["bytes"] or sha(b)!=obj["sha256"]:
                    raise GovernanceError("Immutable artifact snapshot drift")
            return {"submission_id":submission_id,"integrity":"PASS",
                    "integrity_source":"IMMUTABLE_SUBMISSION_SNAPSHOT",
                    "agent_id":row["agent_id"],"evidence_label":row["evidence_label"],
                    "decision":row["decision"]}
        workspace=Path(row["workspace"])
        p=workspace/"receipt.json"
        if sha(p.read_bytes())!=row["receipt_sha"]:
            raise GovernanceError("Evidence receipt altered after submission")
        receipt=jsonload(p)
        reuse_sha=receipt.get("reuse_decision_sha256","")
        if reuse_sha:
            decision_path=workspace/"REUSE_DECISION.json"
            if (not decision_path.is_file() or sha(decision_path.read_bytes())!=reuse_sha):
                raise GovernanceError("Reuse decision drift")
        raw=rel_artifact(workspace,receipt["manifest_relative"]).read_bytes()
        if sha(raw)!=receipt["manifest_sha256"] or sha(raw)!=row["manifest_sha"]:
            raise GovernanceError("Manifest content changed")
        for obj in receipt["artifacts"]:
            b=rel_artifact(workspace,obj["path"]).read_bytes()
            if len(b)!=obj["bytes"] or sha(b)!=obj["sha256"]:
                raise GovernanceError("Artifact content drift")
        return {"submission_id":submission_id,
                "integrity":"PASS","integrity_source":"LEGACY_MUTABLE_WORKSPACE",
                "agent_id":row["agent_id"],
                "evidence_label":row["evidence_label"],"decision":row["decision"]}

    @staticmethod
    def classify_findings(findings):
        """P0/P1 need a concrete observed material impact; P2/P3 are nonblocking."""
        if not isinstance(findings,list) or len(findings)>8:
            raise GovernanceError("findings must be a list of up to 8 concrete issues")
        results=[]
        for item in findings:
            if not isinstance(item,dict):
                raise GovernanceError("finding must be an object")
            severity=item.get("severity")
            if severity not in ("P0","P1","P2","P3"):
                raise GovernanceError("Finding severity must be P0/P1/P2/P3")
            for field,min_len in (("issue",8),("impact",10),("fix",8)):
                if not isinstance(item.get(field),str) or len(item[field].strip())<min_len:
                    raise GovernanceError("Specific "+field+" required for each finding")
            record={k:item[k].strip() for k in ("severity","issue","impact","fix")}
            record["blocking"]=severity in ("P0","P1")
            if record["blocking"]:
                if item.get("observed") is not True:
                    raise GovernanceError("Material blocker requires observed=true")
                for field in ("reproduction","evidence"):
                    if not isinstance(item.get(field),str) or len(item[field].strip())<12:
                        raise GovernanceError("Material blocker requires specific "+field)
                    record[field]=item[field].strip()
                record["observed"]=True
            else:
                for field in ("reproduction","evidence"):
                    if isinstance(item.get(field),str):
                        record[field]=item[field].strip()
                record["observed"]=bool(item.get("observed",False))
            results.append(record)
        return results

    def review(self, submission_id, reviewer_id, decision, reason, findings=None):
        """E1 candidate review only. Small issues never block; nothing freezes the pool."""
        released_audit_leases=[]
        if decision not in ("ACCEPT_E1","REJECT","NEEDS_WORK"):
            raise GovernanceError("E2/E3 approval not implemented; only E1 candidate review")
        if not ID_PATTERN.fullmatch(reviewer_id):
            raise GovernanceError("reviewer_id invalid")
        if not isinstance(reason,str) or len(reason.strip())<15:
            raise GovernanceError("Reason must describe the actual outcome (at least 15 chars)")
        classified=self.classify_findings(findings if findings is not None else [])
        material=sum(int(x["blocking"]) for x in classified)
        advisory=len(classified)-material
        if material and decision=="ACCEPT_E1":
            raise GovernanceError("Cannot accept a candidate with verified P0/P1 material findings")
        if not material and decision!="ACCEPT_E1":
            raise GovernanceError("P2/P3 advice or vague risk cannot REJECT/NEEDS_WORK a candidate")
        with self.tx():
            row=self.db.execute(
                "SELECT s.*,l.agent_id AS author,l.role,l.claimed_at,l.reuse_guard_version,"
                "l.reuse_plan_json,l.workspace,l.backlog_id "
                "FROM submissions s JOIN leases l "
                "ON l.lease_id=s.lease_id WHERE s.submission_id=?",
                (submission_id,)).fetchone()
            if not row or row["decision"]!="PENDING":
                raise GovernanceError("No pending E1 submission")
            if row["author"]==reviewer_id:
                raise GovernanceError("Author cannot review own E1 submission")
            reviewer=self.db.execute(
                "SELECT role FROM agents WHERE agent_id=?", (reviewer_id,)).fetchone()
            if not reviewer or reviewer["role"]!="auditor":
                raise GovernanceError("Only distinct registered auditor may review")
            if decision=="ACCEPT_E1":
                if self._lease_requires_reuse_guard(row) and int(row["reuse_guard_version"] or 0)<=0:
                    raise GovernanceError(
                        "Post-epoch unguarded submission cannot be ACCEPT_E1; "
                        "repeat the claim under the Build-vs-Reuse guard")
                self.verify_receipt(submission_id)
                if row["evidence_label"]!="LEAD_READY":
                    raise GovernanceError("Only LEAD_READY may be accepted E1")
                raw_manifest=json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
                self._verify_paid_evidence(row,raw_manifest)
            self.db.execute(
                "UPDATE submissions SET decision=?,decided_by=?,decision_reason=? "
                "WHERE submission_id=?", (decision,reviewer_id,reason,submission_id))
            self.db.execute(
                "INSERT INTO reviews(review_id,submission_id,reviewer_id,decision,reason,at,"
                "findings_json,material_count,advisory_count) VALUES(?,?,?,?,?,?,?,?,?)",
                ("review-"+uuid.uuid4().hex[:16],submission_id,reviewer_id,
                 decision,reason,self.clock(),json.dumps(classified,ensure_ascii=False),
                 material,advisory))
            # A completed E1 decision finishes the auditor's current review lease.
            # Keep the stable auditor identity registered, but free the single auditor
            # capacity immediately so the next pending candidate can receive its own
            # scope-specific audit lease instead of waiting for TTL expiry.
            active_audits=self.db.execute(
                "SELECT lease_id FROM leases WHERE agent_id=? AND role='auditor' AND state='ACTIVE'",
                (reviewer_id,)).fetchall()
            released_audit_leases=[x["lease_id"] for x in active_audits]
            if released_audit_leases:
                marks=",".join("?" for _ in released_audit_leases)
                self.db.execute(
                    f"UPDATE leases SET state='RELEASED' WHERE lease_id IN ({marks})",
                    tuple(released_audit_leases))
        next_pending=self.db.execute(
            "SELECT submission_id FROM submissions WHERE decision='PENDING' "
            "ORDER BY at LIMIT 1").fetchone()
        return {"submission_id":submission_id,"decision":decision,
                "material_blockers":material,"nonblocking_advice":advisory,
                "scope":"THIS_E1_CANDIDATE_ONLY",
                "global_research_blocked":False,
                "scientific_claim":"NOT_GRANTED","product_promotion":"NOT_GRANTED",
                "continue_audit":True,
                "released_audit_leases":released_audit_leases,
                "next_submission":next_pending["submission_id"] if next_pending else None,
                "next_step":"REVIEW_PENDING_E1" if next_pending else "INDEPENDENT_E0_WORK"}

    def audit_stats(self):
        """Queue throughput/latency + material/advisory counts; no automatic 'quality' claim."""
        totals=self.db.execute(
            "SELECT count(*) AS n,coalesce(sum(material_count),0) AS m,"
            "coalesce(sum(advisory_count),0) AS a FROM reviews").fetchone()
        decisions={x["decision"]:x["n"] for x in self.db.execute(
            "SELECT decision,count(*) AS n FROM submissions GROUP BY decision")}
        waiting=self.db.execute(
            "SELECT min(at) FROM submissions WHERE decision='PENDING'").fetchone()[0]
        latencies=[max(0,float(x[0])-float(x[1])) for x in self.db.execute(
            "SELECT r.at,s.at FROM reviews r JOIN submissions s "
            "ON r.submission_id=s.submission_id")]
        return {
            "reviewed":int(totals["n"]),
            "pending":decisions.get("PENDING",0),
            "accept_e1":decisions.get("ACCEPT_E1",0),
            "rejected":decisions.get("REJECT",0),
            "needs_work":decisions.get("NEEDS_WORK",0),
            "material_findings":int(totals["m"]),
            "advisory_findings":int(totals["a"]),
            "avg_queue_wait_seconds":round(sum(latencies)/len(latencies),1) if latencies else None,
            "oldest_pending_age_seconds":max(0,round(self.clock()-waiting,1)) if waiting is not None else None,
            "queue_blocks_exploration":False,
            "false_blocker_rate":"NOT_MEASURED_REQUIRES_REVERSAL_PROCESS"
        }

    def status(self):
        active=[dict(x) for x in self.db.execute(
            "SELECT lease_id,agent_id,role,capability,family,lineage,hypothesis,lane,"
            "workspace,claimed_at,heartbeat_at,ttl_end,state,reuse_guard_version,backlog_id "
            "FROM leases WHERE state='ACTIVE' ORDER BY claimed_at")]
        role_counts={role:sum(x["role"]==role for x in active) for role in ROLE_LIMITS}
        counts={x["state"]:x["cnt"] for x in self.db.execute(
            "SELECT state,count(*) AS cnt FROM leases GROUP BY state")}
        awaiting=self.db.execute(
            "SELECT count(*) FROM submissions WHERE decision='PENDING'").fetchone()[0]
        dynamic_capacity=self._dynamic_capacity()
        current_root_rc_audit=self._current_root_rc_mainline_freeze()
        capacity_reason={**dynamic_capacity["reason"],
                         "pending_current_root_rc_audit":bool(current_root_rc_audit)}
        return {"governance":"E0_E1_OPERATIONAL",
                "paused":self.paused(),
                "active_total":len(active),
                "capacity":dynamic_capacity["total"],
                "capacity_mode":"DYNAMIC_UPPER_BOUND" if dynamic_capacity["enabled"] else "LEGACY_FIXED",
                "capacity_hard_ceiling":dynamic_capacity["hard_max_total"],
                "capacity_by_role":{
                    "research_engineer":dynamic_capacity["research_engineers"],
                    "auditor":dynamic_capacity["auditors"],
                },
                "capacity_reason":capacity_reason,
                "current_root_rc_audit_pending":current_root_rc_audit,
                "active_by_role":role_counts,
                "lease_states":counts,
                "pending_e1_audit":awaiting,
                "audit_stats":self.audit_stats(),
                "active":active,
                "declared_paid_budget_usd_per_day":self.policy["budget"].get("max_paid_usd_per_day"),
                "paid_research_token_budget":self.policy["budget"].get("paid_research",{}),
                "runtime_api_gateway_enabled":bool(self.policy["budget"].get("paid_research",{}).get("enabled",False)),
                "reuse_guard":{"active":self._reuse_guard_active(),
                               "coverage":self.reuse_coverage(),
                               **self._reuse_guard_config()},
                "phase_priority_guard":{**self._phase_guard_config(),
                                        "status":self.phase_priority_status()},
                "formal_claim_enabled":False,
                "identity_data_access":False}

    def queue(self):
        return [dict(r) for r in self.db.execute(
            "SELECT s.submission_id,s.at,s.evidence_label,s.decision,"
            "l.agent_id,l.capability,l.family,l.hypothesis FROM submissions s "
            "JOIN leases l ON l.lease_id=s.lease_id ORDER BY s.at DESC LIMIT 100")]

def cli(root, args):
    g=Governance(root)
    try:
        if args.command=="status":return g.status()
        if args.command=="reap":return g.reap()
        if args.command=="pause":return g.pause(True,args.reason)
        if args.command=="resume":return g.pause(False,args.reason)
        if args.command=="join":
            return g.join(args.agent_id,args.role,args.family,args.capability,
                          args.hypothesis,args.lane,args.reopen_basis,args.lineage,
                          args.reuse_plan_json,args.backlog_id,args.recovery_of,
                          args.worker_instance_id)
        if args.command=="reuse-check":
            return g.reuse_check(args.role,args.family,args.capability,args.hypothesis,
                                 args.lane,args.lineage,args.reuse_plan_json,
                                 args.backlog_id,args.recovery_of)
        if args.command=="reuse-audit":return g.reuse_coverage()
        if args.command=="reuse-doctor":return g.reuse_doctor()
        if args.command=="phase-priority":return g.phase_priority_status()
        if args.command=="prior-work":
            return g.prior_work(args.family,args.capability,args.hypothesis,
                                args.lineage,args.limit)
        if args.command=="reuse-retrofit":
            return g.retrofit_reuse(args.lease_id,args.reuse_plan_json,args.reason)
        if args.command=="heartbeat":return g.heartbeat(args.lease_id,args.agent_id,args.worker_instance_id)
        if args.command=="release":return g.release(args.lease_id,args.agent_id,args.worker_instance_id)
        if args.command=="submit":return g.submit(args.lease_id,args.agent_id,args.manifest,args.worker_instance_id)
        if args.command=="next":return g.continue_agent(args.agent_id,args.worker_instance_id)
        if args.command=="review":return g.review(args.submission_id,args.reviewer_id,
                                                   args.decision,args.reason,
                                                   json.loads(args.findings_json))
        if args.command=="verify":return g.verify_receipt(args.submission_id)
        if args.command=="queue":return g.queue()
        if args.command=="audit-stats":return g.audit_stats()
        raise GovernanceError("Unknown command")
    finally:g.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="command",required=True)
    for c in ("status","reap","queue","audit-stats","reuse-audit","reuse-doctor","phase-priority"):subs.add_parser(c)
    for c in ("pause","resume"):
        pp=subs.add_parser(c);pp.add_argument("--reason",required=True)
    pp=subs.add_parser("join")
    for a in ("agent-id","role","family","capability","hypothesis","lane"):
        pp.add_argument("--"+a,required=True)
    pp.add_argument("--reopen-basis",default="")
    pp.add_argument("--lineage",default="",help="stable architecture-lineage key; cannot reset stop-loss by family rename")
    pp.add_argument("--reuse-plan-json",default="",help="machine-readable build-vs-reuse plan for self-directed research")
    pp.add_argument("--backlog-id",default="",help="Lead-vetted backlog candidate id")
    pp.add_argument("--recovery-of",default="",help="exact prior lease id for stale/TTL recovery")
    pp.add_argument("--worker-instance-id",default="",help="per-chat worker instance id; required for post-fix leases")
    pp=subs.add_parser("reuse-check")
    for a in ("role","family","capability","hypothesis","lane"):
        pp.add_argument("--"+a,required=True)
    pp.add_argument("--lineage",default="")
    pp.add_argument("--reuse-plan-json",default="")
    pp.add_argument("--backlog-id",default="")
    pp.add_argument("--recovery-of",default="")
    pp=subs.add_parser("prior-work")
    pp.add_argument("--family",required=True)
    pp.add_argument("--lineage",default="")
    pp.add_argument("--capability",required=True)
    pp.add_argument("--hypothesis",required=True)
    pp.add_argument("--limit",type=int,default=8)
    pp=subs.add_parser("reuse-retrofit")
    pp.add_argument("--lease-id",required=True)
    pp.add_argument("--reuse-plan-json",required=True)
    pp.add_argument("--reason",required=True)
    pp=subs.add_parser("next")
    pp.add_argument("--agent-id",required=True,
                    help="resume active work or claim the next eligible task with the same agent identity")
    pp.add_argument("--worker-instance-id",default="",
                    help="per-chat worker instance id; required for post-fix leases")
    for c in ("heartbeat","release","submit"):
        pp=subs.add_parser(c)
        pp.add_argument("--lease-id",required=True)
        pp.add_argument("--agent-id",required=True)
        pp.add_argument("--worker-instance-id",default="",
                        help="per-chat worker instance id; required for post-fix leases")
        if c=="submit":pp.add_argument("--manifest",required=True)
    pp=subs.add_parser("review")
    pp.add_argument("--submission-id",required=True)
    pp.add_argument("--reviewer-id",required=True)
    pp.add_argument("--decision",required=True,choices=["ACCEPT_E1","REJECT","NEEDS_WORK"])
    pp.add_argument("--reason",required=True)
    pp.add_argument("--findings-json",default="[]",
                    help="JSON list of material or advisory findings; P0/P1 require reproducible impact")
    pp=subs.add_parser("verify");pp.add_argument("--submission-id",required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    try:
        result=cli(root,args)
        print(json.dumps({"ok":True,"result":result},ensure_ascii=False,indent=2))
    except (GovernanceError,ValueError,FileNotFoundError,json.JSONDecodeError,
            sqlite3.Error,OSError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False))
        return 2
    return 0

if __name__=="__main__":sys.exit(main())
