from __future__ import annotations


class ContractError(ValueError):
    """Base error for invalid XiaoYu public-contract data."""


class ContractFieldError(ContractError):
    """Raised when required/unknown contract fields do not match the schema."""


class ContractTimeError(ContractError):
    """Raised when a persisted timestamp is missing timezone information."""
