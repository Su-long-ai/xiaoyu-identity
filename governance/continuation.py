# -*- coding: utf-8 -*-
"""Same-turn research handoff. Never starts a model or a background task."""
from __future__ import annotations
import json
from pathlib import Path
from recovery import attach_files, recent_unfinished

AUDITOR_TASKS = [
    dict(family="audit.temporal.ood", capability="memory_evidence",
         lineage="audit.temporal", lane="evaluation_data",
         hypothesis="Independent blinded Mandarin paraphrase set checks temporal correction and stale preference false assertions."),
    dict(family="audit.erasure.replay", capability="privacy_erasure",
         lineage="audit.erasure", lane="safety_privacy",
         hypothesis="Synthetic archive restore and evidence replay reveal whether erased memory is recoverable in recalled state."),
    dict(family="audit.persona.continuity", capability="persona_growth",
         lineage="audit.persona", lane="evaluation_data",
         hypothesis="Independent fixed synthetic identity swap probes identify fabricated growth and unsupported shared experiences."),
]

def _specs(g, role):
    if role == "auditor":
        return AUDITOR_TASKS
    path = g.home / "RESEARCH_BACKLOG.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("candidates", [])
    phase_policy=data.get("phase_policy",{})
    allowed_plans=set(phase_policy.get("auto_assign_plans",[]))
    rows = [r for r in rows
            if r.get("status","active") == "active"
            and (not allowed_plans or r.get("plan") in allowed_plans)]
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

def _unclaimed_specs(g,role):
    out=[]
    for spec in _specs(g,role):
        prior=_prior_assignment(g,spec)
        if prior is None or _is_needs_work_remediation(prior,spec):
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
            "promotion_exclusions","supporting_lead_e0","note") if b.get(k) is not None}
    return dict(continue_research=True, next_task=task, next_workspace=row["workspace"],
                next_lease_id=row["lease_id"], resumed=resumed, next_step="WORK_IN_ASSIGNED_WORKSPACE")

def assign_next(g, agent_id, governance_error):
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
        unclaimed=_unclaimed_specs(g,role) if role=="research_engineer" else []
        interrupted_is_formal=any(_spec_matches_lease(spec,interrupted)
                                  for spec in _specs(g,role))
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
                             recovery_of=interrupted["lease_id"])
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
    for spec in _specs(g, role):
        prior=_prior_assignment(g,spec)
        remediation=_is_needs_work_remediation(prior,spec)
        if prior is not None and not remediation:
            continue
        if remediation and prior["lease"]["agent_id"]!=agent_id:
            # Preserve author continuity for automatic remediation. Lead may
            # explicitly reassign by changing the backlog contract if needed.
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
                               recovery_of=prior["lease"]["lease_id"])
            else:
                lease = g.join(agent_id,role,spec["family"],spec["capability"],
                               spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
                               reuse_plan=spec.get("reuse_plan"),
                               backlog_id=spec.get("backlog_id") or "")
        except governance_error as e:
            # Concurrent worker, capacity or stop-loss may reject this candidate.
            errors.append(str(e))
            if str(e) in ("Pool capacity full","Role capacity full"):
                break
            continue
        fresh = g.db.execute("SELECT * FROM leases WHERE lease_id=?",
                             (lease["lease_id"],)).fetchone()
        data=_lease_payload(fresh,resumed=bool(lease.get("resumed")),g=g)
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
            if phase_status.get("p1_research_closeout_complete"):
                return dict(
                    continue_research=False,next_task=None,next_workspace=None,
                    next_step="P1_RESEARCH_CLOSEOUT_COMPLETE",
                    closeout_required_backlog=[],
                    reason=phase_status.get("closeout_reason") or
                           "P1 research closeout is complete. Do not auto-open P2 or self-directed research until Lead explicitly changes phase policy.")
            return dict(
                continue_research=False,next_task=None,next_workspace=None,
                next_step="P1_CLOSEOUT_GATES_IN_FLIGHT",
                closeout_required_backlog=phase_status.get("closeout_required_backlog",[]),
                reason=phase_status.get("closeout_reason") or
                       "P1 closeout mode is active; do not invent new research while known direct gates are active/pending.")
    return dict(continue_research=True, next_task=None, next_workspace=None,
                next_step="SELF_DIRECTED_NEW_HYPOTHESIS",
                instruction="In this ChatGPT turn discover a nonduplicate falsifiable task. "
                "First run control.py prior-work for the proposed family/lineage/capability/hypothesis, "
                "then include prior_work.reviewed and a concrete novelty explanation in the reuse plan. "
                "Run control.py reuse-check with mode, concrete known components, gap, "
                "no_new_infrastructure=true and new_dependencies=[]. Only after PASS join with the SAME agent_id and the "
                "same reuse plan. Do not treat static backlog exhaustion as scientific "
                "saturation. Keep to your own workspace and policy.")
