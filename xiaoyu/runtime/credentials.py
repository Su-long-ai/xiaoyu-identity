from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class OptionalCredentialStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class KeyringCredentialRef:
    service: str
    username: str

    def __post_init__(self) -> None:
        if not self.service.strip():
            raise ValueError("keyring service is required")
        if not self.username.strip():
            raise ValueError("keyring username is required")


class SystemKeyringCredentialStore:
    """Thin adapter over Python keyring / the host OS credential store.

    XiaoYu never persists the returned secret. On Windows, keyring's
    recommended built-in backend is the Windows Credential Locker/Vault.
    """

    def __init__(self, module=None) -> None:
        if module is None:
            try:
                import keyring as module  # type: ignore
            except ImportError as exc:
                raise OptionalCredentialStoreUnavailable(
                    "python-keyring is not installed"
                ) from exc
        self.keyring = module

    def get(self, ref: KeyringCredentialRef) -> Optional[str]:
        value = self.keyring.get_password(
            ref.service,
            ref.username,
        )
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None
