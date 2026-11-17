"""Persistence primitives for XiaoYu authority state."""
from .db import Database
from .erasure import ExternalErasureFenceStore, ErasureWatermarkError
from .recovery import (
    MissingErasureWatermark,
    RecoveryError,
    RecoveryManager,
    RecoveryQuarantineStore,
    RestoreInvariantError,
    RestoreMode,
    RestoreReport,
)
from .schema import (
    UnsupportedSchemaVersion,
    apply_migrations,
    applied_versions,
    assert_schema_compatible,
    verify_schema,
)

__all__ = [
    "Database",
    "ExternalErasureFenceStore",
    "ErasureWatermarkError",
    "MissingErasureWatermark",
    "RecoveryError",
    "RecoveryManager",
    "RecoveryQuarantineStore",
    "RestoreInvariantError",
    "RestoreMode",
    "RestoreReport",
    "UnsupportedSchemaVersion",
    "apply_migrations",
    "applied_versions",
    "assert_schema_compatible",
    "verify_schema",
]
