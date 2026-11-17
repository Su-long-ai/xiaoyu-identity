"""Typed repositories over XiaoYu authority tables."""
from .context import MemoryContextRepository
from .claims import ClaimRepository
from .effects import ClaimedOutbox, EffectRepository, OutboxRepository
from .events import CanonicalEventConflict, CanonicalEventRepository, LegacyEventShadowWriter
from .execution_auth import ActorRegistryRepository, DelegationRepository, DispatchAuthorizationDenied, ExecutionAuthorizationRepository
from .grants import AuthorizationDecisionRepository
from .receipts import ActionReceiptRepository, DeliveryRepository
from .purposes import PurposeRepository
from .profile import ProfileRepository
from .promise import PromiseRepository
from .relationship import RelationshipRepository
from .self_authority import SelfAuthorityRepository
from .temporal import TemporalRepository

__all__ = [
    "ActionReceiptRepository",
    "ActorRegistryRepository",
    "AuthorizationDecisionRepository",
    "DelegationRepository",
    "DispatchAuthorizationDenied",
    "ExecutionAuthorizationRepository",
    "DeliveryRepository",
    "CanonicalEventConflict",
    "CanonicalEventRepository",
    "ClaimedOutbox",
    "ClaimRepository",
    "EffectRepository",
    "LegacyEventShadowWriter",
    "MemoryContextRepository",
    "OutboxRepository",
    "PurposeRepository",
    "ProfileRepository",
    "PromiseRepository",
    "RelationshipRepository",
    "SelfAuthorityRepository",
    "TemporalRepository",
]
