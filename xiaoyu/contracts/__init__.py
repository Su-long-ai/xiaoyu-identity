"""Stable public contracts for the XiaoYu semantic/runtime boundary."""
from .actor import ActorContext, Delegation
from .authorization import (
    ActionRequest,
    AuthorizationContext,
    AuthorizationDecision,
    ResourceRef,
    RiskTier,
)
from .capability import (
    CapabilityDescriptor,
    IsolationMode,
    ProviderHealth,
    ProviderLifecycle,
)
from .effects import EffectIntent, EffectState
from .envelopes import InputSourceEnvelope, Taint, TrustClass
from .errors import ContractError, ContractFieldError, ContractTimeError
from .multimodal import MultimodalEvidenceRef
from .principal import PrincipalContext
from .receipts import ActionReceipt
from .surface import DeliveryReceipt, SurfaceAdapter, SurfaceHealth

__all__ = [
    "ActionReceipt", "ActionRequest", "ActorContext", "AuthorizationContext",
    "AuthorizationDecision", "CapabilityDescriptor", "ContractError",
    "ContractFieldError", "ContractTimeError", "Delegation", "EffectIntent",
    "EffectState", "InputSourceEnvelope", "IsolationMode", "MultimodalEvidenceRef",
    "PrincipalContext", "ProviderHealth", "ProviderLifecycle", "ResourceRef", "RiskTier",
    "SurfaceAdapter", "SurfaceHealth", "DeliveryReceipt", "Taint", "TrustClass",
]
