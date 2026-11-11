# -*- coding: utf-8 -*-
"""Same-turn research handoff. Never starts a model or a background task."""
from __future__ import annotations
import json
from pathlib import Path
from recovery import attach_files, recent_unfinished

AUDITOR_TASKS = [
    dict(family="audit.fastlane.e0_advantage_reproduction", capability="memory_retrieval",
         lineage="audit.fastlane", lane="evaluation_data",
         hypothesis="Light-audit only positive fast-lane E0 candidates: reproduce the same matched local end-to-end advantage once, verify component SHA/context cap/no obvious external200 leakage, then mark PASS so the fixed external200 may run. Do not apply release-grade audit to fast E0. Material P0/P1 product/release audits still preempt.")
]

def _specs(g, role, agent_id=None):
    if role == "auditor":
        rc=g._current_root_rc_mainline_freeze()
        if rc:
            bundle=str(rc.get("bundle") or "")
            base=Path(bundle).name or "current_root"
            slug="".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in base)
            freeze_record=str(rc.get("freeze_record") or "")
            audit_handoff=str(rc.get("audit_handoff") or "")
            return [dict(
                family="audit.current_root.release_candidate."+slug,
                capability="cost_reliability",
                lineage="audit.current_root.release_candidate",
                lane="evaluation_data",
                hypothesis=(
                    "Independently audit frozen current-root release candidate "+bundle+
                    " from "+freeze_record+
                    (" following "+audit_handoff if audit_handoff else "")+
                    " against exact live-root membership and hashes; run only its frozen release and specialty gates, attack stale-byte substitution and tamper fail-closed, and report current-root closure separately from E2/E3."))]
        return AUDITOR_TASKS
    path = g.home / "RESEARCH_BACKLOG.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("candidates", [])
    phase_policy=data.get("phase_policy",{})
    allowed_plans=set(phase_policy.get("auto_assign_plans",[]))
    agent_pool=(phase_policy.get("agent_task_pools") or {}).get(agent_id) if agent_id else None
    rows = [r for r in rows
            if r.get("status","active") == "active"
            and (not allowed_plans or r.get("plan") in allowed_plans)
            and (not agent_pool or r.get("task_pool")==agent_pool)]
    return [dict(family=r["family"], capability=r["capability"],
                 lineage=r.get("lineage") or r["family"],
                 lane=r["lane"], hypothesis=r["hypothesis"],
                 backlog_id=r.get("id"), reuse_plan=r.get("reuse_plan"),
                 priority=r.get("priority",99))
            for r in sorted(rows, key=lambda r:(r.get("priority",99),r.get("id","")))]

def _spec_matches_lease(spec,row):
    return (spec.get("family")==row["family"]
            and spec.get("capability")==row["capability"]
            and spec.get("lineage")==row["lineage"]
            and spec.get("hypothesis")==row["hypothesis"])

def _prior_assignment(g,spec):
    """Return the newest lease/submission/review for this exact backlog task.

    Historical family/capability matches still consume legacy rows, but only an
    exact backlog-bound NEEDS_WORK submission is eligible for automatic
    remediation. This prevents an E1-rejected active backlog item from becoming
    permanently unclaimable while avoiding cross-task family reuse.
    """
    backlog_id=str(spec.get("backlog_id") or "")
    lease=None
    if backlog_id:
        lease=g.db.execute(
            "SELECT * FROM leases WHERE backlog_id=? ORDER BY claimed_at DESC LIMIT 1",
            (backlog_id,)).fetchone()
    if lease is None:
        # Preserve compatibility with pre-backlog/legacy claims that used the
        # same formal family+capability but had no backlog_id recorded.
        lease=g.db.execute(
            "SELECT * FROM leases WHERE family=? AND capability=? "
            "ORDER BY claimed_at DESC LIMIT 1",
            (spec["family"],spec["capability"])).fetchone()
    if not lease:
        return None
    sub=g.db.execute(
        "SELECT * FROM submissions WHERE lease_id=? ORDER BY at DESC LIMIT 1",
        (lease["lease_id"],)).fetchone()
    review=None
    if sub:
        review=g.db.execute(
            "SELECT * FROM reviews WHERE submission_id=? ORDER BY at DESC LIMIT 1",
            (sub["submission_id"],)).fetchone()
    return {"lease":lease,"submission":sub,"review":review}

def _is_needs_work_remediation(prior,spec):
    if not prior or not spec.get("backlog_id"):
        return False
    lease=prior["lease"]; sub=prior["submission"]
    return (str(lease["backlog_id"] or "")==str(spec["backlog_id"])
            and sub is not None and sub["decision"]=="NEEDS_WORK"
            and lease["state"]=="SUBMITTED")


def _active_backlog_incomplete(g,spec):
    """Lead-owned backlog lifecycle, not prior lease existence, decides completion."""
    backlog_id=str(spec.get("backlog_id") or "")
    if not backlog_id:
        return False
    try:
        row=g.backlog_task(backlog_id)
    except Exception:
        return False
    return (row.get("status","active")=="active"
            and not row.get("completion_level")
            and not row.get("completion_submission"))


def _is_active_backlog_followup(g,prior,spec):
    """Permit same-author continuation when an active backlog remains incomplete.

    This covers two legitimate E2/P2 patterns:
    - a lease was RELEASED/STALE without a submission; or
    - an intermediate ACCEPT_E1/EVIDENCE_ONLY boundary was accepted while the
      Lead deliberately kept the backlog item active for the next bounded stage.

    NEEDS_WORK has its own remediation path. A done/completed backlog never
    reopens through this helper.
    """
    if not prior or not _active_backlog_incomplete(g,spec):
        return False
    lease=prior["lease"]; sub=prior["submission"]
    try:
        backlog_row=g.backlog_task(str(spec.get("backlog_id") or ""))
    except Exception:
        backlog_row={}
    if backlog_row.get("single_pass") and sub is not None:
        return False
    if str(lease["backlog_id"] or "")!=str(spec.get("backlog_id") or ""):
        return False
    if lease["state"]=="ACTIVE":
        return False
    if sub is None:
        return lease["state"] in ("RELEASED","STALE","TTL_EXPIRED")
    return sub["decision"] in ("ACCEPT_E1","EVIDENCE_ONLY")


def _unclaimed_specs(g,role,agent_id=None):
    out=[]
    for spec in _specs(g,role,agent_id):
        prior=_prior_assignment(g,spec)
        if (prior is None or _is_needs_work_remediation(prior,spec)
                or _is_active_backlog_followup(g,prior,spec)):
            out.append(spec)
    return out

def _lease_payload(row, resumed, g=None):
    task = dict(agent_id=row["agent_id"], lease_id=row["lease_id"],
                workspace=row["workspace"], family=row["family"],
                lineage=row["lineage"], capability=row["capability"],
                hypothesis=row["hypothesis"], lane=row["lane"],
                role=row["role"], backlog_id=row["backlog_id"],
                reuse_guard_version=int(row["reuse_guard_version"] or 0))
    if g is not None and row["backlog_id"]:
        b=g.backlog_task(row["backlog_id"])
        task["task_contract"]={k:b.get(k) for k in (
            "falsifier","baseline","cost_rule","required_attacks",
            "promotion_exclusions","supporting_lead_e0","note","task_pool",
            "anti_local_contract","single_pass") if b.get(k) is not None}
    return dict(continue_research=True, next_task=task, next_workspace=row["workspace"],
                next_lease_id=row["lease_id"], resumed=resumed, next_step="WORK_IN_ASSIGNED_WORKSPACE")

def assign_next(g, agent_id, governance_error, worker_instance_id=''):
    """Claim a new nonduplicated task with the same agent_id, or resume an active lease.

    A depleted static backlog is NOT scientific project saturation. In that case
    the worker is instructed to discover a fresh falsifiable hypothesis, join
    explicitly, and continue in the SAME ChatGPT turn.
    """
    row = g.db.execute("SELECT role FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if row is None:
        raise ValueError("Registered stable agent_id required")
    role = row["role"]
    # Reclassify expired/stale leases before reporting an ACTIVE task.
    g.reap()
    active = g.db.execute("SELECT * FROM leases WHERE agent_id=? AND state='ACTIVE'",
                          (agent_id,)).fetchone()
    if active:
        try:
            g._assert_worker_instance(active,worker_instance_id)
        except governance_error as e:
            return dict(continue_research=False,next_task=None,
                        next_workspace=None,next_lease_id=None,
                        next_step="WORKER_INSTANCE_CONFLICT",
                        reason=str(e))
        # A newly re-opened product-correctness blocker must not be hidden by
        # an already-active unmanaged/self-directed lease. We do not auto-release
        # or mutate that workspace; instead force an explicit safe checkpoint/
        # release decision before the worker may resume lower-priority work.
        if role=="research_engineer" and not str(active["backlog_id"] or ""):
            try:
                ps=g.phase_priority_status()
                interrupts=[
                    x for x in (ps.get("available_unclaimed") or [])
                    if x.get("global_preempt_self_directed")
                ]
            except Exception:
                interrupts=[]
            if interrupts:
                # Preempt only for a blocker/remediation that became actionable
                # *after* this active lease was claimed. Existing backlog that
                # predated the lease must not break idempotent active re-entry.
                fresh_interrupts=[]
                claimed_at=float(active["claimed_at"] or 0)
                for item in interrupts:
                    if not item.get("remediation"):
                        continue
                    backlog_id=str(item.get("id") or "")
                    verdict=g.db.execute(
                        """SELECT r.at
                             FROM reviews r
                             JOIN submissions s ON s.submission_id=r.submission_id
                             JOIN leases l ON l.lease_id=s.lease_id
                            WHERE l.backlog_id=? AND r.decision='NEEDS_WORK'
                            ORDER BY r.at DESC LIMIT 1""",
                        (backlog_id,)).fetchone()
                    if verdict and float(verdict["at"] or 0)>claimed_at:
                        fresh_interrupts.append(item)
                if fresh_interrupts:
                    fresh_interrupts=sorted(
                        fresh_interrupts,
                        key=lambda x:(x.get("priority",99),str(x.get("id") or "")))
                    target=fresh_interrupts[0]
                    return attach_files(
                        dict(
                            continue_research=False,
                            next_task=None,
                            next_workspace=active["workspace"],
                            next_lease_id=active["lease_id"],
                            next_step="HIGH_PRIORITY_BACKLOG_PREEMPT_REQUIRED",
                            reason=(
                                "A product-correctness remediation became actionable after "
                                "this self-directed lease was claimed. Checkpoint the current "
                                "bounded work if scientifically valid, otherwise release it; "
                                "then call next again and claim the higher-priority blocker."
                            ),
                            active_lease_id=active["lease_id"],
                            active_family=active["family"],
                            preempt_target=target,
                        ),
                        active["workspace"])
        try:
            g._assert_backlog_lease_still_active(active)
        except governance_error as e:
            return attach_files(
                dict(continue_research=False,next_task=None,
                     next_step="BACKLOG_TASK_NO_LONGER_ACTIVE",
                     reason=str(e),lease_id=active["lease_id"],
                     workspace=active["workspace"]),
                active["workspace"])
        if (g._lease_requires_reuse_guard(active)
                and int(active["reuse_guard_version"] or 0)<=0):
            return attach_files(
                dict(continue_research=False,next_task=None,
                     next_step="REUSE_RETROFIT_REQUIRED",
                     reason="Post-epoch active lease has no Build-vs-Reuse decision; "
                            "Lead retrofit or release is required before work continues.",
                     lease_id=active["lease_id"],workspace=active["workspace"]),
                active["workspace"])
        return attach_files(_lease_payload(active, resumed=True, g=g), active["workspace"])
    if g.paused():
        return dict(continue_research=False, next_task=None, next_step="PAUSED")
    interrupted = recent_unfinished(g,agent_id)
    deferred_interrupted=None
    if interrupted:
        # During a frozen phase (currently P1), a stale self-directed task that
        # is not itself part of the auto-assign set must not steal a slot from
        # a still-unclaimed formal blocker. Preserve its workspace/evidence,
        # but defer automatic recovery until the formal queue is exhausted.
        unclaimed=_unclaimed_specs(g,role,agent_id) if role=="research_engineer" else []
        interrupted_is_formal=any(_spec_matches_lease(spec,interrupted)
                                  for spec in _specs(g,role,agent_id))
        if unclaimed and not interrupted_is_formal:
            deferred_interrupted=interrupted
            interrupted=None
    if interrupted:
        # Never mutate the stale/expired lease or its historic workspace.
        # Claim a *new* lease with the original stable scientific hypothesis.
        try:
            reuse_plan=None
            if interrupted["reuse_plan_json"]:
                try:
                    reuse_plan=json.loads(interrupted["reuse_plan_json"])
                except Exception:
                    reuse_plan=None
            new_lease=g.join(agent_id,role,interrupted["family"],
                             interrupted["capability"],interrupted["hypothesis"],
                             interrupted["lane"],lineage=interrupted["lineage"],
                             reuse_plan=reuse_plan,
                             backlog_id=str(interrupted["backlog_id"] or ""),
                             recovery_of=interrupted["lease_id"],
                             worker_instance_id=worker_instance_id)
        except governance_error as e:
            data=dict(continue_research=False,next_task=None,next_step="RECOVERY_CLAIM_BLOCKED",
                      reason=str(e),previous_lease_id=interrupted["lease_id"],
                      previous_workspace=interrupted["workspace"])
            return attach_files(data,interrupted["workspace"],
                                recovery_state="OLD_LEASE_NOT_WRITABLE")
        fresh=g.db.execute("SELECT * FROM leases WHERE lease_id=?",
                           (new_lease["lease_id"],)).fetchone()
        data=_lease_payload(fresh,resumed=False,g=g)
        data.update(next_step="RECOVER_FROM_PREVIOUS_WORKSPACE",
                    previous_lease_id=interrupted["lease_id"],
                    previous_workspace=interrupted["workspace"],
                    previous_lease_state=interrupted["state"])
        return attach_files(data,interrupted["workspace"],
                            recovery_state="NEW_LEASE_WRITE_ONLY_OLD_WORKSPACE_READ_ONLY")
    errors=[]
    for spec in _specs(g, role, agent_id):
        prior=_prior_assignment(g,spec)
        remediation=_is_needs_work_remediation(prior,spec)
        followup=_is_active_backlog_followup(g,prior,spec)
        if prior is not None and not remediation and not followup:
            continue
        if (remediation or followup) and prior["lease"]["agent_id"]!=agent_id:
            # Preserve author continuity for remediation and active-backlog
            # follow-up. Lead may explicitly reassign by changing the contract.
            continue
        try:
            if remediation:
                review=prior.get("review")
                reason=(review["reason"] if review else
                        prior["submission"]["decision_reason"] or "Independent E1 NEEDS_WORK")
                reopen=("Independent E1 NEEDS_WORK remediation for backlog "
                        +str(spec.get("backlog_id"))+": "+str(reason))[:1000]
                lease = g.join(agent_id,role,spec["family"],spec["capability"],
                               spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
                               reopen_basis=reopen,
                               reuse_plan=spec.get("reuse_plan"),
                               backlog_id=spec.get("backlog_id") or "",
                               recovery_of=prior["lease"]["lease_id"],
                               worker_instance_id=worker_instance_id)
            elif followup:
                sub=prior.get("submission")
                boundary=(sub["decision"] if sub is not None else prior["lease"]["state"])
                reopen=("Active backlog "+str(spec.get("backlog_id"))
                        +" remains incomplete after prior "+str(boundary)
                        +"; continue the same Lead-vetted task without opening a new hypothesis.")[:1000]
                lease = g.join(agent_id,role,spec["family"],spec["capability"],
                               spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
                               reopen_basis=reopen,
                               reuse_plan=spec.get("reuse_plan"),
                               backlog_id=spec.get("backlog_id") or "",
                               recovery_of=prior["lease"]["lease_id"],
                               worker_instance_id=worker_instance_id)
            else:
                lease = g.join(agent_id,role,spec["family"],spec["capability"],
                               spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
                               reuse_plan=spec.get("reuse_plan"),
                               backlog_id=spec.get("backlog_id") or "",
                               worker_instance_id=worker_instance_id)
        except governance_error as e:
            # Concurrent worker, capacity or stop-loss may reject this candidate.
            errors.append(str(e))
            if str(e) in ("Pool capacity full","Role capacity full"):
                break
            continue
        fresh = g.db.execute("SELECT * FROM leases WHERE lease_id=?",
                             (lease["lease_id"],)).fetchone()
        data=_lease_payload(fresh,resumed=bool(lease.get("resumed")),g=g)
        if followup:
            sub=prior.get("submission")
            data.update(
                next_step="CONTINUE_ACTIVE_BACKLOG",
                previous_lease_id=prior["lease"]["lease_id"],
                previous_workspace=prior["lease"]["workspace"],
                previous_submission_id=(sub["submission_id"] if sub is not None else None),
                previous_decision=(sub["decision"] if sub is not None else None),
                continuation_reason="Lead backlog remains active without a completion marker.")
        if remediation:
            review=prior.get("review")
            findings=[]
            if review and review["findings_json"]:
                try: findings=json.loads(review["findings_json"])
                except Exception: findings=[]
            data.update(
                next_step="REMEDIATE_NEEDS_WORK",
                previous_lease_id=prior["lease"]["lease_id"],
                previous_workspace=prior["lease"]["workspace"],
                previous_submission_id=prior["submission"]["submission_id"],
                previous_decision="NEEDS_WORK",
                remediation_findings=findings,
                remediation_reason=(review["reason"] if review else
                                    prior["submission"]["decision_reason"]))
            return attach_files(
                data,prior["lease"]["workspace"],
                recovery_state="NEW_REMEDIATION_LEASE_OLD_WORKSPACE_READ_ONLY")
        if deferred_interrupted is not None:
            data["deferred_recovery"]={
                "lease_id":deferred_interrupted["lease_id"],
                "workspace":deferred_interrupted["workspace"],
                "state":deferred_interrupted["state"],
                "reason":"Formal current-phase backlog preempts unmanaged stale self-directed recovery."
            }
        return data
    if errors and errors[-1] in ("Pool capacity full","Role capacity full"):
        return dict(continue_research=False, next_task=None,
                    next_step="POOL_CAPACITY_FULL", reason=errors[-1])
    if role=="research_engineer":
        phase_status=g.phase_priority_status()
        if phase_status.get("active") and phase_status.get("closeout_mode"):
            required=phase_status.get("closeout_required_backlog",[])
            if required:
                phase_name=phase_status.get("current_phase")
                return dict(
                    continue_research=False,next_task=None,next_workspace=None,
                    next_step=("P1_CLOSEOUT_GATES_IN_FLIGHT" if phase_name=="P1"
                               else "PHASE_CLOSEOUT_GATES_IN_FLIGHT"),
                    current_phase=phase_name,
                    closeout_required_backlog=required,
                    reason=phase_status.get("closeout_reason") or
                           "Current phase closeout has known direct gates; do not invent self-directed research.")
            if phase_status.get("p1_research_closeout_complete"):
                return dict(
                    continue_research=False,next_task=None,next_workspace=None,
                    next_step="P1_RESEARCH_CLOSEOUT_COMPLETE",
                    closeout_required_backlog=[],
                    reason=phase_status.get("closeout_reason") or
                           "P1 research closeout is complete. Do not auto-open later phases until Lead explicitly changes phase policy.")
            return dict(
                continue_research=False,next_task=None,next_workspace=None,
                next_step="PHASE_CLOSEOUT_NO_ASSIGNABLE_WORK",
                current_phase=phase_status.get("current_phase"),
                closeout_required_backlog=[],
                reason=phase_status.get("closeout_reason") or
                       "Current phase closeout is active with no assignable formal task.")
    if role=="research_engineer":
        try:
            pdata=json.loads((g.home/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8")).get("phase_policy",{})
            agent_pool=(pdata.get("agent_task_pools") or {}).get(agent_id)
            current_phase=pdata.get("current_phase")
        except Exception:
            agent_pool=None
            current_phase=None
        if current_phase=="FAST_RESEARCH_LOOP":
            if agent_pool=="exploration":
                return dict(continue_research=True,next_task=None,next_workspace=None,
                            next_step="FAST_RETRIEVAL_COMPONENT_LOOP",
                            instruction="Stay in the long-lived fast retrieval lane. Reuse research_components/retrieval/candidate_template.py and run_local_e2e.py. Iterate multiple component versions inside the same ACTIVE workspace; failed local E2E versions need no submission or audit. Only a real matched local end-to-end win may be promoted to governance/fastlane/e0_candidates, then light-audited. Do not use the external200 before audit PASS.")
            if agent_pool=="mainline":
                return dict(continue_research=True,next_task=None,next_workspace=None,
                            next_step="SELF_DIRECTED_MAINLINE_OTHER_CAPABILITY",
                            instruction="Mainline is intentionally not assigned to retrieval fast-lane experiments. Continue the next real product/capability bottleneck outside retrieval: accepted-byte integration, semantic ingress, identity/persona/relationship continuity, state/update behavior, or an observed material P0/P1. Skip pure governance/documentation/promotion-evidence hygiene and micro-performance unless it truly blocks the product. Use a matched end-to-end baseline and keep work product-shaped.")
        if current_phase=="CAPABILITY_RETRIEVAL_SPRINT":
            if agent_pool=="exploration":
                return dict(continue_research=True,next_task=None,next_workspace=None,
                            next_step="FAST_RETRIEVAL_COMPONENT_LOOP",
                            instruction="Retrieval sprint is superseded by the fast research loop. Use the reusable component API, local E2E first, positive-only E0, light audit, then external200.")
            if agent_pool=="mainline":
                return dict(continue_research=True,next_task=None,next_workspace=None,
                            next_step="SELF_DIRECTED_MAINLINE_OTHER_CAPABILITY",
                            instruction="Retrieval sprint is superseded for mainline. Continue other real product/capability bottlenecks; do not spend mainline on fast retrieval component trials.")
        if agent_pool=="exploration":
            return dict(continue_research=True,next_task=None,next_workspace=None,
                        next_step="SELF_DIRECTED_DIVERGENT_HYPOTHESIS",
                        instruction="In this same ChatGPT turn open a materially different, nonduplicate exploratory hypothesis. "
                        "It must target at least three independent failure families, compare at least two mechanism paradigms, "
                        "avoid tuning the same exposed cases, include a kill condition, and remain E0/exploratory. "
                        "Run prior-work and reuse-check, then join with the SAME agent_id. Prefer a new causal mechanism or cross-domain transfer over parameter/prompt tweaks.")
        if agent_pool=="mainline":
            rc_hold=g._current_root_rc_mainline_freeze()
            if rc_hold:
                return dict(
                    continue_research=False,next_task=None,next_workspace=None,
                    next_step="CURRENT_ROOT_RC_AUDIT_PENDING",
                    current_root_rc=rc_hold,
                    reason="Independent current-root RC audit is pending; do not open a new self-directed mainline hypothesis.")
            return dict(continue_research=True,next_task=None,next_workspace=None,
                        next_step="SELF_DIRECTED_MAINLINE_BOTTLENECK",
                        instruction="In this same ChatGPT turn take the next practical mainline bottleneck from current accepted bytes/product regressions. "
                        "Require a matched baseline, no oracle fields, and either measurable integration value or deletion/simplification value. "
                        "Run prior-work and reuse-check, then join with the SAME agent_id. Do not open benchmark-specific answerer tuning.")
    return dict(continue_research=True, next_task=None, next_workspace=None,
                next_step="SELF_DIRECTED_NEW_HYPOTHESIS",
                instruction="Discover a nonduplicate falsifiable task, pass prior-work/reuse-check, and continue with the same agent_id.")
