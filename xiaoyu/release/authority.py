from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple


class ReleaseState(str, Enum):
    CURRENT = "CURRENT"
    CANDIDATE = "CANDIDATE"
    LAST_KNOWN_GOOD = "LAST_KNOWN_GOOD"
    REJECTED = "REJECTED"


class ReleaseRollbackPolicy(str, Enum):
    ROLLBACK_ALLOWED = "ROLLBACK_ALLOWED"
    FORWARD_FIX_REQUIRED = "FORWARD_FIX_REQUIRED"


class ReleaseActivationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    core_commit: str
    schema_version: int
    max_schema_version: int
    migration_version: int
    contract_digest: str
    release_digest: str

    def __post_init__(self) -> None:
        if not self.release_id:
            raise ValueError("release_id required")
        if self.schema_version < 0 or self.max_schema_version < self.schema_version:
            raise ValueError("invalid release schema compatibility range")
        if self.migration_version < 0:
            raise ValueError("migration_version cannot be negative")


@dataclass(frozen=True)
class ReleaseSmokeEvidence:
    schema_compatibility: bool
    migration_smoke: bool
    restore_smoke: bool
    identity_continuity_smoke: bool

    def blockers(self) -> Tuple[str, ...]:
        blockers = []
        if not self.schema_compatibility:
            blockers.append("SCHEMA_INCOMPATIBLE")
        if not self.migration_smoke:
            blockers.append("MIGRATION_SMOKE_FAILED")
        if not self.restore_smoke:
            blockers.append("RESTORE_SMOKE_FAILED")
        if not self.identity_continuity_smoke:
            blockers.append("IDENTITY_CONTINUITY_FAILED")
        return tuple(blockers)


class ReleaseAuthority:
    """Small durable release-state authority; not a deployment platform."""

    VERSION = 1

    def __init__(self, path) -> None:
        self.path = Path(path)

    def register_candidate(self, manifest: ReleaseManifest) -> None:
        payload = self._load()
        releases = payload["releases"]
        existing = releases.get(manifest.release_id)
        if existing is not None and existing["manifest"] != asdict(manifest):
            raise ReleaseActivationError("release_id reused with different manifest")
        releases[manifest.release_id] = {
            "state": ReleaseState.CANDIDATE.value,
            "manifest": asdict(manifest),
            "evidence": None,
        }
        self._write(payload)

    def activate(
        self,
        release_id: str,
        evidence: ReleaseSmokeEvidence,
    ) -> None:
        payload = self._load()
        record = payload["releases"].get(release_id)
        if record is None:
            raise ReleaseActivationError("unknown release candidate")
        if record["state"] not in (
            ReleaseState.CANDIDATE.value,
            ReleaseState.REJECTED.value,
        ):
            raise ReleaseActivationError("release is not activatable")

        blockers = evidence.blockers()
        record["evidence"] = asdict(evidence)
        if blockers:
            record["state"] = ReleaseState.REJECTED.value
            record["blockers"] = list(blockers)
            self._write(payload)
            raise ReleaseActivationError(
                "release smoke failed: " + ",".join(blockers)
            )

        old_current = payload.get("current_release_id")
        if old_current is not None and old_current != release_id:
            old = payload["releases"].get(old_current)
            if old is not None:
                previous_lkg = payload.get("last_known_good_release_id")
                if previous_lkg and previous_lkg != old_current:
                    previous = payload["releases"].get(previous_lkg)
                    if previous is not None and previous["state"] == ReleaseState.LAST_KNOWN_GOOD.value:
                        previous["state"] = ReleaseState.REJECTED.value
                        previous["blockers"] = ["SUPERSEDED_LAST_KNOWN_GOOD"]
                old["state"] = ReleaseState.LAST_KNOWN_GOOD.value
                payload["last_known_good_release_id"] = old_current

        record["state"] = ReleaseState.CURRENT.value
        record.pop("blockers", None)
        payload["current_release_id"] = release_id
        self._write(payload)

    def reject(self, release_id: str, reason: str) -> None:
        payload = self._load()
        record = payload["releases"].get(release_id)
        if record is None:
            raise ReleaseActivationError("unknown release")
        if record["state"] == ReleaseState.CURRENT.value:
            raise ReleaseActivationError("cannot reject CURRENT release")
        record["state"] = ReleaseState.REJECTED.value
        record["blockers"] = [str(reason)]
        self._write(payload)

    def state(self, release_id: str) -> Optional[ReleaseState]:
        record = self._load()["releases"].get(release_id)
        return None if record is None else ReleaseState(record["state"])

    def current(self) -> Optional[ReleaseManifest]:
        payload = self._load()
        release_id = payload.get("current_release_id")
        return self._manifest(payload, release_id)

    def last_known_good(self) -> Optional[ReleaseManifest]:
        payload = self._load()
        release_id = payload.get("last_known_good_release_id")
        return self._manifest(payload, release_id)

    def rollback_policy(
        self,
        *,
        current_release_id: str,
        target_release_id: str,
    ) -> ReleaseRollbackPolicy:
        payload = self._load()
        current = self._manifest(payload, current_release_id)
        target = self._manifest(payload, target_release_id)
        if current is None or target is None:
            raise ReleaseActivationError("unknown rollback release")
        if target.max_schema_version < current.schema_version:
            return ReleaseRollbackPolicy.FORWARD_FIX_REQUIRED
        return ReleaseRollbackPolicy.ROLLBACK_ALLOWED

    def _manifest(self, payload: dict, release_id: Optional[str]) -> Optional[ReleaseManifest]:
        if release_id is None:
            return None
        record = payload["releases"].get(release_id)
        if record is None:
            return None
        return ReleaseManifest(**record["manifest"])

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                "version": self.VERSION,
                "current_release_id": None,
                "last_known_good_release_id": None,
                "releases": {},
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != self.VERSION:
            raise ReleaseActivationError("unsupported release authority version")
        if not isinstance(payload.get("releases"), dict):
            raise ReleaseActivationError("invalid release authority")
        return payload

    def _write(self, payload: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
