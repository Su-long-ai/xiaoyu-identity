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


def _authorized_request_digest(
    *,
    identity_id: str,
    principal_id: str,
    principal_session_scope,
    principal_context_digest,
    actor_id: str,
    actor_implementation_digest,
    actor_authorization_digest,
    delegation_id,
    delegation_digest,
    purpose_id,
    purpose_revision,
    purpose_occurrence_id,
    action_class: str,
    action_digest: str,
    resource_digest: str,
    context_digest: str,
    request_digest: str,
    destination: str,
    actor_provider_id,
    provider_artifact_digest,
    provider_descriptor_digest,
    provider_interface_digest,
    provider_tool_schema_digest,
    provider_capability,
) -> str:
    return _digest(
        {
            "identity_id": identity_id,
            "principal_id": principal_id,
            "principal_session_scope": principal_session_scope,
            "principal_context_digest": principal_context_digest,
            "actor_id": actor_id,
            "actor_implementation_digest": actor_implementation_digest,
            "actor_authorization_digest": actor_authorization_digest,
            "delegation_id": delegation_id,
            "delegation_digest": delegation_digest,
            "purpose_id": purpose_id,
            "purpose_revision": purpose_revision,
            "purpose_occurrence_id": purpose_occurrence_id,
            "action_class": action_class,
            "action_digest": action_digest,
            "resource_digest": resource_digest,
            "context_digest": context_digest,
            "request_digest": request_digest,
            "destination": destination,
            "actor_provider_id": actor_provider_id,
            "provider_artifact_digest": provider_artifact_digest,
            "provider_descriptor_digest": provider_descriptor_digest,
            "provider_interface_digest": provider_interface_digest,
            "provider_tool_schema_digest": provider_tool_schema_digest,
            "provider_capability": provider_capability,
        }
    )


class DelegationConflict(RuntimeError):
    pass


class DispatchAuthorizationDenied(PermissionError):
    pass


class DelegationRepository:
    @staticmethod
    def _semantic_payload(
        delegation: Delegation,
        actor: ActorContext,
    ) -> dict:
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
            "actor_implementation_digest": actor.implementation_digest,
            "actor_authorization_digest": actor.authorization_digest,
        }

    def ensure(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        delegation: Delegation,
        actor: ActorContext,
    ) -> str:
        payload = self._semantic_payload(delegation, actor)
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


class PrincipalExecutionRepository:
    def register(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        principal: PrincipalContext,
        updated_at: datetime,
    ) -> str:
        context_digest = _digest(principal.to_dict())
        conn.execute(
            """INSERT INTO execution_principals(
                   identity_id,principal_id,session_scope,
                   authentication_level,context_digest,expires_at,
                   revoked_at,updated_at
               ) VALUES(?,?,?,?,?,?,NULL,?)
               ON CONFLICT(identity_id,principal_id,session_scope)
               DO UPDATE SET
                   authentication_level=excluded.authentication_level,
                   context_digest=excluded.context_digest,
                   expires_at=excluded.expires_at,
                   updated_at=excluded.updated_at""",
            (
                identity_id,
                principal.principal_id,
                principal.session_scope,
                principal.authentication_level,
                context_digest,
                None
                if principal.expires_at is None
                else datetime_to_text(
                    principal.expires_at, "principal_expires_at"
                ),
                datetime_to_text(updated_at, "updated_at"),
            ),
        )
        return context_digest

    def revoke(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        principal_id: str,
        session_scope: str,
        revoked_at: datetime,
    ) -> bool:
        cur = conn.execute(
            """UPDATE execution_principals SET revoked_at=?,updated_at=?
               WHERE identity_id=? AND principal_id=? AND session_scope=?
                 AND revoked_at IS NULL""",
            (
                datetime_to_text(revoked_at, "revoked_at"),
                datetime_to_text(revoked_at, "updated_at"),
                identity_id,
                principal_id,
                session_scope,
            ),
        )
        return cur.rowcount == 1


class ExecutionAuthorizationRepository:
    @staticmethod
    def _provider_snapshot(conn: sqlite3.Connection, provider_id):
        if provider_id is None:
            return None
        return conn.execute(
            """SELECT provider_id,capability,artifact_digest,descriptor_digest,
                      interface_digest,tool_schema_digest,lifecycle_state
               FROM provider_registry WHERE provider_id=?""",
            (provider_id,),
        ).fetchone()

    def record(
        self,
        conn: sqlite3.Connection,
        *,
        decision_id: str,
        identity_id: str,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        delegation_digest: Optional[str],
        purpose_id: Optional[str],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        request: dict,
        destination: str,
        created_at: datetime,
        purpose_revision: Optional[int] = None,
        purpose_occurrence_id: Optional[str] = None,
    ) -> None:
        principal_context_digest = _digest(principal.to_dict())
        action_digest = _digest(action.to_dict())
        resource_digest = _digest(resource.to_dict())
        context_digest = _digest(context.to_dict())
        request_digest = _digest(request)
        provider = self._provider_snapshot(conn, actor.provider_id)
        provider_artifact_digest = None if provider is None else provider["artifact_digest"]
        provider_descriptor_digest = None if provider is None else provider["descriptor_digest"]
        provider_interface_digest = None if provider is None else provider["interface_digest"]
        provider_tool_schema_digest = None if provider is None else provider["tool_schema_digest"]
        provider_capability = None if provider is None else provider["capability"]
        provider_lifecycle_state = None if provider is None else provider["lifecycle_state"]
        authorized_digest = _authorized_request_digest(
            identity_id=identity_id,
            principal_id=principal.principal_id,
            principal_session_scope=principal.session_scope,
            principal_context_digest=principal_context_digest,
            actor_id=actor.actor_id,
            actor_implementation_digest=actor.implementation_digest,
            actor_authorization_digest=actor.authorization_digest,
            delegation_id=None if delegation is None else delegation.delegation_id,
            delegation_digest=delegation_digest,
            purpose_id=purpose_id,
            purpose_revision=purpose_revision,
            purpose_occurrence_id=purpose_occurrence_id,
            action_class=action.action_class,
            action_digest=action_digest,
            resource_digest=resource_digest,
            context_digest=context_digest,
            request_digest=request_digest,
            destination=destination,
            actor_provider_id=actor.provider_id,
            provider_artifact_digest=provider_artifact_digest,
            provider_descriptor_digest=provider_descriptor_digest,
            provider_interface_digest=provider_interface_digest,
            provider_tool_schema_digest=provider_tool_schema_digest,
            provider_capability=provider_capability,
        )
        conn.execute(
            """INSERT INTO execution_authorizations(
                   authorization_decision_id,identity_id,principal_id,
                   principal_expires_at,principal_session_scope,
                   principal_context_digest,actor_id,actor_implementation_digest,
                   actor_authorization_digest,delegation_id,purpose_id,
                   action_class,action_digest,resource_digest,context_digest,
                   request_digest,destination,audience_scope,context_space,
                   created_at,purpose_revision,purpose_occurrence_id,
                   delegation_digest,actor_provider_id,provider_artifact_digest,
                   provider_descriptor_digest,provider_interface_digest,
                   provider_tool_schema_digest,provider_capability,
                   provider_lifecycle_state,authorized_request_digest
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                principal.session_scope,
                principal_context_digest,
                actor.actor_id,
                actor.implementation_digest,
                actor.authorization_digest,
                None
                if delegation is None
                else delegation.delegation_id,
                purpose_id,
                action.action_class,
                action_digest,
                resource_digest,
                context_digest,
                request_digest,
                destination,
                context.audience_scope,
                context.context_space,
                datetime_to_text(created_at, "created_at"),
                purpose_revision,
                purpose_occurrence_id,
                delegation_digest,
                actor.provider_id,
                provider_artifact_digest,
                provider_descriptor_digest,
                provider_interface_digest,
                provider_tool_schema_digest,
                provider_capability,
                provider_lifecycle_state,
                authorized_digest,
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
        effect_request: dict,
        now: datetime,
        purpose_revision: Optional[int] = None,
        purpose_occurrence_id: Optional[str] = None,
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
        if row["purpose_revision"] != purpose_revision:
            raise DispatchAuthorizationDenied(
                "authorization purpose revision changed"
            )
        if row["purpose_occurrence_id"] != purpose_occurrence_id:
            raise DispatchAuthorizationDenied(
                "authorization purpose occurrence changed"
            )
        if str(row["destination"]) != destination:
            raise DispatchAuthorizationDenied(
                "authorization destination changed"
            )
        actual_request_digest = _digest(request)
        if str(row["request_digest"]) != actual_request_digest:
            raise DispatchAuthorizationDenied(
                "authorization outbox request changed"
            )
        if str(row["request_digest"]) != _digest(effect_request):
            raise DispatchAuthorizationDenied(
                "authorization effect request changed"
            )

        principal_expires = row["principal_expires_at"]
        if (
            principal_expires is not None
            and now >= datetime_from_text(
                str(principal_expires), "principal_expires_at"
            )
        ):
            raise DispatchAuthorizationDenied(
                "principal session authorization expired"
            )

        principal_context_digest = row["principal_context_digest"]
        if principal_context_digest is not None:
            principal = conn.execute(
                """SELECT authentication_level,context_digest,expires_at,
                          revoked_at
                   FROM execution_principals
                   WHERE identity_id=? AND principal_id=? AND session_scope=?""",
                (
                    identity_id,
                    row["principal_id"],
                    row["principal_session_scope"],
                ),
            ).fetchone()
            if principal is None:
                raise DispatchAuthorizationDenied(
                    "principal session is no longer registered"
                )
            if principal["context_digest"] != principal_context_digest:
                raise DispatchAuthorizationDenied(
                    "principal session context changed"
                )
            revoked = principal["revoked_at"]
            if (
                revoked is not None
                and now >= datetime_from_text(str(revoked), "revoked_at")
            ):
                raise DispatchAuthorizationDenied(
                    "principal session revoked"
                )
            current_expires = principal["expires_at"]
            if (
                current_expires is not None
                and now >= datetime_from_text(
                    str(current_expires), "principal_expires_at"
                )
            ):
                raise DispatchAuthorizationDenied(
                    "principal session expired"
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
        if actor["provider_id"] != row["actor_provider_id"]:
            raise DispatchAuthorizationDenied(
                "actor provider changed"
            )

        delegation_id = row["delegation_id"]
        if delegation_id is not None:
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
            if delegation["delegation_digest"] != row["delegation_digest"]:
                raise DispatchAuthorizationDenied(
                    "standing delegation semantics changed"
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

        provider_snapshot_present = any(
            row[name] is not None
            for name in (
                "provider_artifact_digest",
                "provider_descriptor_digest",
                "provider_interface_digest",
                "provider_tool_schema_digest",
                "provider_capability",
                "provider_lifecycle_state",
            )
        )
        if provider_snapshot_present:
            provider_id = row["actor_provider_id"]
            provider = self._provider_snapshot(conn, provider_id)
            if provider is None:
                raise DispatchAuthorizationDenied(
                    "authorized provider disappeared"
                )
            comparisons = (
                ("artifact_digest", "provider_artifact_digest"),
                ("descriptor_digest", "provider_descriptor_digest"),
                ("interface_digest", "provider_interface_digest"),
                ("tool_schema_digest", "provider_tool_schema_digest"),
                ("capability", "provider_capability"),
            )
            for current_name, snapshot_name in comparisons:
                if provider[current_name] != row[snapshot_name]:
                    raise DispatchAuthorizationDenied(
                        "provider %s changed" % current_name
                    )
            if str(provider["lifecycle_state"]) != "ACTIVE":
                raise DispatchAuthorizationDenied(
                    "provider lifecycle is not ACTIVE"
                )
            if row["provider_lifecycle_state"] != "ACTIVE":
                raise DispatchAuthorizationDenied(
                    "standing approval was not granted to ACTIVE provider"
                )

        expected = _authorized_request_digest(
            identity_id=identity_id,
            principal_id=str(row["principal_id"]),
            principal_session_scope=row["principal_session_scope"],
            principal_context_digest=row["principal_context_digest"],
            actor_id=actor_id,
            actor_implementation_digest=actor["implementation_digest"],
            actor_authorization_digest=actor["authorization_digest"],
            delegation_id=delegation_id,
            delegation_digest=row["delegation_digest"],
            purpose_id=purpose_id,
            purpose_revision=purpose_revision,
            purpose_occurrence_id=purpose_occurrence_id,
            action_class=action_class,
            action_digest=str(row["action_digest"]),
            resource_digest=str(row["resource_digest"]),
            context_digest=str(row["context_digest"]),
            request_digest=actual_request_digest,
            destination=destination,
            actor_provider_id=actor["provider_id"],
            provider_artifact_digest=row["provider_artifact_digest"],
            provider_descriptor_digest=row["provider_descriptor_digest"],
            provider_interface_digest=row["provider_interface_digest"],
            provider_tool_schema_digest=row["provider_tool_schema_digest"],
            provider_capability=row["provider_capability"],
        )
        if str(row["authorized_request_digest"]) != expected:
            raise DispatchAuthorizationDenied(
                "canonical authorized request changed"
            )
