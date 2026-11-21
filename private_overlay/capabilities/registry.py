from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]*\.v[1-9][0-9]*$")

Handler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]
HealthCheck = Callable[[], bool | Awaitable[bool]]


class CapabilityRegistrationError(ValueError):
    pass


class CapabilityUnavailable(RuntimeError):
    def __init__(self, capability: str, attempts: tuple["ProviderAttempt", ...]):
        self.capability = capability
        self.attempts = attempts
        details = ", ".join(
            f"{item.provider_id}:{item.status}" for item in attempts
        ) or "no providers"
        super().__init__(f"{capability} unavailable ({details})")


@dataclass(frozen=True)
class ProviderAttempt:
    provider_id: str
    status: str
    error: str | None = None


@dataclass(frozen=True)
class ShadowResult:
    provider_id: str
    status: str
    value: Any = None
    error: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    capability: str
    provider_id: str
    value: Any
    attempts: tuple[ProviderAttempt, ...] = ()
    shadows: tuple[ShadowResult, ...] = ()


@dataclass(frozen=True)
class CapabilityProvider:
    capability: str
    provider_id: str
    handler: Handler = field(compare=False, repr=False)
    priority: int = 0
    health: HealthCheck | None = field(default=None, compare=False, repr=False)
    shadow: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if not _CAPABILITY_RE.fullmatch(self.capability):
            raise CapabilityRegistrationError(
                "capability must be a versioned id such as interruptibility.v1"
            )
        if not self.provider_id or self.provider_id.strip() != self.provider_id:
            raise CapabilityRegistrationError("provider_id must be non-empty and trimmed")
        if not callable(self.handler):
            raise CapabilityRegistrationError("handler must be callable")
        if self.health is not None and not callable(self.health):
            raise CapabilityRegistrationError("health must be callable")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class CapabilityRegistry:
    """Small routing layer over N.E.K.O-owned capability implementations.

    This object owns no product state and starts no runtime. Providers remain
    responsible for their own lifecycle (normally N.E.K.O plugins/native code).
    """

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, CapabilityProvider]] = {}

    def register(self, provider: CapabilityProvider) -> None:
        bucket = self._providers.setdefault(provider.capability, {})
        if provider.provider_id in bucket:
            raise CapabilityRegistrationError(
                f"duplicate provider {provider.provider_id!r} for {provider.capability}"
            )
        bucket[provider.provider_id] = provider

    def unregister(self, capability: str, provider_id: str) -> bool:
        bucket = self._providers.get(capability)
        if not bucket or provider_id not in bucket:
            return False
        del bucket[provider_id]
        if not bucket:
            self._providers.pop(capability, None)
        return True

    def providers(self, capability: str) -> tuple[CapabilityProvider, ...]:
        bucket = self._providers.get(capability, {})
        return tuple(
            sorted(
                bucket.values(),
                key=lambda item: (-item.priority, item.provider_id),
            )
        )

    async def dispatch(
        self,
        capability: str,
        payload: Mapping[str, Any],
        *,
        include_shadow: bool = True,
    ) -> DispatchResult:
        attempts: list[ProviderAttempt] = []
        winner: CapabilityProvider | None = None
        value: Any = None

        active = [
            item
            for item in self.providers(capability)
            if item.enabled and not item.shadow
        ]
        shadows = [
            item
            for item in self.providers(capability)
            if item.enabled and item.shadow
        ]

        for provider in active:
            if not await self._healthy(provider):
                attempts.append(ProviderAttempt(provider.provider_id, "unhealthy"))
                continue
            try:
                value = await _maybe_await(provider.handler(payload))
            except Exception as exc:
                attempts.append(
                    ProviderAttempt(
                        provider.provider_id,
                        "failed",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            winner = provider
            attempts.append(ProviderAttempt(provider.provider_id, "selected"))
            break

        if winner is None:
            raise CapabilityUnavailable(capability, tuple(attempts))

        shadow_results: tuple[ShadowResult, ...] = ()
        if include_shadow and shadows:
            evaluated: list[ShadowResult] = []
            for provider in shadows:
                if not await self._healthy(provider):
                    evaluated.append(ShadowResult(provider.provider_id, "unhealthy"))
                    continue
                try:
                    shadow_value = await _maybe_await(provider.handler(payload))
                except Exception as exc:
                    evaluated.append(
                        ShadowResult(
                            provider.provider_id,
                            "failed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                else:
                    evaluated.append(
                        ShadowResult(provider.provider_id, "observed", value=shadow_value)
                    )
            shadow_results = tuple(evaluated)

        return DispatchResult(
            capability=capability,
            provider_id=winner.provider_id,
            value=value,
            attempts=tuple(attempts),
            shadows=shadow_results,
        )

    async def _healthy(self, provider: CapabilityProvider) -> bool:
        if provider.health is None:
            return True
        try:
            return bool(await _maybe_await(provider.health()))
        except Exception:
            return False
