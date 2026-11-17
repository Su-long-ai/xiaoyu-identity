from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    Delegation,
    PrincipalContext,
    ResourceRef,
)
from xiaoyu.contracts.common import canonical_json, datetime_from_text, datetime_to_text


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


class DelegationConflict(RuntimeError):
    pass


class DispatchAuthorizationDenied(PermissionError):
    pass


class DelegationRepository:
    @staticmethod
    def _semantic_payload(delegation: Delegation) -> dict:
        return {
            "delegation_id": delegation.delegation_id,
            "issued_by_principal": delegation.issued_by_principal,
            "issued_to_actor": delegation.issued_to_actor,
            "purpose_id": delegation.purpose_id,
            "action_classes": list(delegation.action_classes),
            "resources": list(delegation.resources),
            "max_effect": delegation.max_effect,
            "valid_from": datetime_to_text(
                delegation.valid_from, "valid_from"
            ),
            "expires_at": None
            if delegation.expires_at is None
            else datetime_to_text(
                delegation.expires_at, "expires_at"
            ),
            "revocable": delegation.revocable,
        }

    def ensure(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        delegation: Delegation,
    ) -> str:
        payload = self._semantic_payload(delegation)
        digest = _digest(payload)
        existing = conn.execute(
            """SELECT delegation_digest FROM delegations
               WHERE delegation_id=?""",
            (delegation.delegation_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["delegation_digest"]) != digest:
                raise DelegationConflict(
                    "delegation id reused with different semantics"
                )
            return digest

        conn.execute(
            """INSERT INTO delegations(
                   delegation_id,identity_id,principal_id,actor_id,purpose_id,
                   scope_json,valid_from,expires_at,revoked_at,
                   delegation_digest,revocable
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                delegation.delegation_id,
                identity_id,
                delegation.issued_by_principal,
                delegation.issued_to_actor,
                delegation.purpose_id,
                canonical_json(payload),
                datetime_to_text(
                    delegation.valid_from, "valid_from"
                ),
                None
                if delegation.expires_at is None
                else datetime_to_text(
                    delegation.expires_at, "expires_at"
                ),
                None
                if delegation.revoked_at is None
                else datetime_to_text(
                    delegation.revoked_at, "revoked_at"
                ),
                digest,
                1 if delegation.revocable else 0,
            ),
        )
        return digest

    def revoke(
        self,
        conn: sqlite3.Connection,
        delegation_id: str,
        revoked_at: datetime,
    ) -> bool:
        row = conn.execute(
            """SELECT revocable,revoked_at FROM delegations
               WHERE delegation_id=?""",
            (delegation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(
                "unknown delegation %s" % delegation_id
            )
        if not bool(row["revocable"]):
            return False
        if row["revoked_at"] is not None:
            return False
        conn.execute(
            """UPDATE delegations SET revoked_at=?
               WHERE delegation_id=?""",
            (
                datetime_to_text(revoked_at, "revoked_at"),
                delegation_id,
            ),
        )
        return True


class ActorRegistryRepository:
    def register(
        self,
        conn: sqlite3.Connection,
        actor: ActorContext,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO actor_registry(
                   actor_id,implementation_digest,authorization_digest,
                   provider_id,updated_at
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(actor_id) DO UPDATE SET
                   implementation_digest=excluded.implementation_digest,
                   authorization_digest=excluded.authorization_digest,
                   provider_id=excluded.provider_id,
                   updated_at=excluded.updated_at""",
            (
                actor.actor_id,
                actor.implementation_digest,
                actor.authorization_digest,
                actor.provider_id,
                datetime_to_text(updated_at, "updated_at"),
            ),
        )


class ExecutionAuthorizationRepository:
    def record(
        self,
        conn: sqlite3.Connection,
        *,
        decision_id: str,
        identity_id: str,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        request: dict,
        destination: str,
        created_at: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO execution_authorizations(
                   authorization_decision_id,identity_id,principal_id,
                   principal_expires_at,actor_id,actor_implementation_digest,
                   actor_authorization_digest,delegation_id,purpose_id,
                   action_class,action_digest,resource_digest,context_digest,
                   request_digest,destination,audience_scope,context_space,
                   created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                decision_id,
                identity_id,
                principal.principal_id,
                None
                if principal.expires_at is None
                else datetime_to_text(
                    principal.expires_at,
                    "principal_expires_at",
                ),
                actor.actor_id,
                actor.implementation_digest,
                actor.authorization_digest,
                None
                if delegation is None
                else delegation.delegation_id,
                None
                if delegation is None
                else delegation.purpose_id,
                action.action_class,
                _digest(action.to_dict()),
                _digest(resource.to_dict()),
                _digest(context.to_dict()),
                _digest(request),
                destination,
                context.audience_scope,
                context.context_space,
                datetime_to_text(created_at, "created_at"),
            ),
        )

    def preflight(
        self,
        conn: sqlite3.Connection,
        *,
        authorization_decision_id: str,
        identity_id: str,
        actor_id: str,
        action_class: str,
        purpose_id: Optional[str],
        destination: str,
        request: dict,
        now: datetime,
    ) -> None:
        row = conn.execute(
            """SELECT * FROM execution_authorizations
               WHERE authorization_decision_id=?""",
            (authorization_decision_id,),
        ).fetchone()
        if row is None:
            raise DispatchAuthorizationDenied(
                "missing execution authorization snapshot"
            )
        if str(row["identity_id"]) != identity_id:
            raise DispatchAuthorizationDenied(
                "authorization identity changed"
            )
        if str(row["actor_id"]) != actor_id:
            raise DispatchAuthorizationDenied(
                "authorization actor changed"
            )
        if str(row["action_class"]) != action_class:
            raise DispatchAuthorizationDenied(
                "authorization action changed"
            )
        if row["purpose_id"] != purpose_id:
            raise DispatchAuthorizationDenied(
                "authorization purpose changed"
            )
        if str(row["destination"]) != destination:
            raise DispatchAuthorizationDenied(
                "authorization destination changed"
            )
        if str(row["request_digest"]) != _digest(request):
            raise DispatchAuthorizationDenied(
                "authorization request changed"
            )

        actor = conn.execute(
            """SELECT implementation_digest,authorization_digest,provider_id
               FROM actor_registry WHERE actor_id=?""",
            (actor_id,),
        ).fetchone()
        if actor is None:
            raise DispatchAuthorizationDenied(
                "actor is no longer registered"
            )
        if actor["implementation_digest"] != row["actor_implementation_digest"]:
            raise DispatchAuthorizationDenied(
                "actor implementation digest changed"
            )
        if actor["authorization_digest"] != row["actor_authorization_digest"]:
            raise DispatchAuthorizationDenied(
                "actor authorization/schema digest changed"
            )

        delegation_id = row["delegation_id"]
        if delegation_id is None:
            expires = row["principal_expires_at"]
            if (
                expires is not None
                and now >= datetime_from_text(
                    str(expires), "principal_expires_at"
                )
            ):
                raise DispatchAuthorizationDenied(
                    "principal session authorization expired"
                )
            return

        delegation = conn.execute(
            """SELECT * FROM delegations WHERE delegation_id=?""",
            (delegation_id,),
        ).fetchone()
        if delegation is None:
            raise DispatchAuthorizationDenied(
                "delegation disappeared"
            )
        if str(delegation["principal_id"]) != str(row["principal_id"]):
            raise DispatchAuthorizationDenied(
                "delegation principal changed"
            )
        if str(delegation["actor_id"]) != actor_id:
            raise DispatchAuthorizationDenied(
                "delegation actor changed"
            )
        revoked = delegation["revoked_at"]
        if (
            revoked is not None
            and now >= datetime_from_text(
                str(revoked), "revoked_at"
            )
        ):
            raise DispatchAuthorizationDenied(
                "delegation revoked"
            )
        valid_from = datetime_from_text(
            str(delegation["valid_from"]), "valid_from"
        )
        if now < valid_from:
            raise DispatchAuthorizationDenied(
                "delegation not yet valid"
            )
        expires = delegation["expires_at"]
        if (
            expires is not None
            and now >= datetime_from_text(
                str(expires), "expires_at"
            )
        ):
            raise DispatchAuthorizationDenied(
                "delegation expired"
            )
