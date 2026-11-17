from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class MigrationRollbackPolicy(str, Enum):
    FORWARD_ONLY = "FORWARD_ONLY"


@dataclass(frozen=True)
class AuthorityCutoverEvidence:
    shadow_caught_up: bool
    rebuild_equal: bool
    unresolved_conflicts: int
    erasure_generation_source: int
    erasure_generation_shadow: int
    source_order_ok: bool
    old_writer_fenced: bool


@dataclass(frozen=True)
class AuthorityCutoverDecision:
    ready: bool
    blockers: Tuple[str, ...]
    rollback_policy: MigrationRollbackPolicy = MigrationRollbackPolicy.FORWARD_ONLY


class AuthorityCutoverGate:
    """Pure gate for the future single-read-authority switch.

    This intentionally does not flip a production read path. Until a durable
    one-way switch and old-writer fence are wired into the compatibility
    facade, migration remains shadow-only and forward-fix only.
    """

    @staticmethod
    def evaluate(evidence: AuthorityCutoverEvidence) -> AuthorityCutoverDecision:
        blockers = []
        if not evidence.shadow_caught_up:
            blockers.append("SHADOW_NOT_CAUGHT_UP")
        if not evidence.rebuild_equal:
            blockers.append("REBUILD_MISMATCH")
        if int(evidence.unresolved_conflicts) != 0:
            blockers.append("UNRESOLVED_CONFLICTS")
        if int(evidence.erasure_generation_source) != int(
            evidence.erasure_generation_shadow
        ):
            blockers.append("ERASURE_GENERATION_MISMATCH")
        if not evidence.source_order_ok:
            blockers.append("SOURCE_ORDER_MISMATCH")
        if not evidence.old_writer_fenced:
            blockers.append("OLD_WRITER_NOT_FENCED")
        return AuthorityCutoverDecision(
            ready=not blockers,
            blockers=tuple(blockers),
        )
