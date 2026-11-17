from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    Delegation,
    PrincipalContext,
    ResourceRef,
)
from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.core.authorization import AuthorizationResult


class AuthorizationDecisionRepository:
    def record(
        self,
        conn: sqlite3.Connection,
        decision_id: str,
        identity_id: str,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        result: AuthorizationResult,
        created_at: Optional[datetime] = None,
        purpose_id_override: Optional[str] = None,
    ) -> None:
        at = created_at or datetime.now(timezone.utc)
        audit_resource = {
            "resource": resource.to_dict(),
            "risk_tier": action.risk_tier.value,
            "surface": context.surface,
            "context_space": context.context_space,
            "audience_scope": context.audience_scope,
            "delegation_id": None if delegation is None else delegation.delegation_id,
            "matched_delegation_id": result.matched_delegation_id,
        }
        conn.execute(
            """INSERT INTO authorization_decisions(
                   decision_id,identity_id,principal_id,actor_id,purpose_id,
                   action_class,resource_json,decision,reason_code,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                decision_id,
                identity_id,
                principal.principal_id,
                actor.actor_id,
                purpose_id_override if purpose_id_override is not None else (
                    None if delegation is None else delegation.purpose_id
                ),
                action.action_class,
                canonical_json(audit_resource),
                result.decision.value,
                result.reason_code,
                datetime_to_text(at, "created_at"),
            ),
        )
