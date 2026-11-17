from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Set

from .errors import ContractFieldError, ContractTimeError


SCHEMA_VERSION = 1


class StringEnum(str, Enum):
    """Enum that serializes to its string value on every supported Python."""


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractTimeError("%s must be timezone-aware" % field_name)
    return value


def datetime_to_text(value: datetime, field_name: str) -> str:
    return require_aware(value, field_name).isoformat(timespec="microseconds")


def datetime_from_text(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractTimeError("%s must be an ISO-8601 datetime" % field_name) from exc
    return require_aware(parsed, field_name)


def ensure_exact_fields(
    data: Mapping[str, Any],
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_set: Set[str] = set(required)
    allowed = required_set | set(optional)
    actual = set(data)
    missing = required_set - actual
    unknown = actual - allowed
    if missing:
        raise ContractFieldError("missing fields: %s" % ", ".join(sorted(missing)))
    if unknown:
        raise ContractFieldError("unknown fields: %s" % ", ".join(sorted(unknown)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return datetime_to_text(value, "datetime")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON for digests, receipts and persisted contract payloads."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def copy_json_object(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Detach a JSON-shaped mapping from caller mutation without extra deps."""
    return json.loads(canonical_json(value))
