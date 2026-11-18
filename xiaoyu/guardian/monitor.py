from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Optional, Protocol, Sequence

from xiaoyu.runtime.resource_broker import HostResourceSnapshot


class GuardianSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class GuardianFinding:
    code: str
    severity: GuardianSeverity
    component: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.component:
            raise ValueError("guardian finding requires code and component")
        # Telemetry metadata must stay scalar and bounded. Raw content,
        # request payloads, prompts, memory text and user messages do not belong
        # in Guardian findings.
        clean = {}
        for key, value in dict(self.attributes).items():
            if value is None:
                continue
            if not isinstance(value, (str, int, float, bool)):
                raise TypeError(
                    "guardian attributes must be scalar metadata"
                )
            text = str(value)
            if isinstance(value, str) and len(text) > 256:
                raise ValueError(
                    "guardian string attributes are limited to 256 chars"
                )
            clean[str(key)] = value
        object.__setattr__(self, "attributes", clean)


@dataclass(frozen=True)
class GuardianReport:
    observed_at: datetime
    findings: tuple[GuardianFinding, ...]

    def __post_init__(self) -> None:
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("guardian report time must be timezone-aware")

    @property
    def healthy(self) -> bool:
        return not any(
            finding.severity is GuardianSeverity.CRITICAL
            for finding in self.findings
        )


@dataclass(frozen=True)
class GuardianThresholds:
    heartbeat_timeout_s: float = 60.0
    restart_window_s: float = 300.0
    max_restarts_in_window: int = 4
    backup_max_age_s: float = 24 * 3600.0
    denied_window_s: float = 300.0
    denied_effect_threshold: int = 8
    cpu_fraction: float = 0.98
    gpu_fraction: float = 0.98
    min_ram_available_mb: float = 256.0
    min_vram_available_mb: float = 128.0

    def __post_init__(self) -> None:
        positive = (
            self.heartbeat_timeout_s,
            self.restart_window_s,
            self.backup_max_age_s,
            self.denied_window_s,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("guardian time thresholds must be positive")
        if self.max_restarts_in_window < 1:
            raise ValueError("max_restarts_in_window must be positive")
        if self.denied_effect_threshold < 1:
            raise ValueError("denied_effect_threshold must be positive")


@dataclass(frozen=True)
class GuardianInputs:
    identity_db_path: Path
    identity_id: Optional[str] = None
    backup_path: Optional[Path] = None
    expected_provider_digests: Mapping[str, str] = field(
        default_factory=dict
    )
    release_authority_path: Optional[Path] = None
    resource_snapshot: Optional[HostResourceSnapshot] = None
    state_path: Optional[Path] = None


class GuardianSink(Protocol):
    def emit(self, report: GuardianReport) -> None:
        ...


class GuardianStateStore:
    """Independent non-authority sidecar for liveness/restart metadata."""

    VERSION = 1

    def __init__(self, path) -> None:
        self.path = Path(path)

    def heartbeat(
        self,
        component_id: str,
        *,
        observed_at: Optional[datetime] = None,
    ) -> None:
        current = observed_at or datetime.now(timezone.utc)
        payload = self._load()
        payload["heartbeats"][str(component_id)] = current.astimezone(
            timezone.utc
        ).isoformat(timespec="microseconds")
        self._write(payload)

    def record_restart(
        self,
        component_id: str,
        *,
        observed_at: Optional[datetime] = None,
        keep: int = 64,
    ) -> None:
        current = observed_at or datetime.now(timezone.utc)
        payload = self._load()
        values = payload["restarts"].setdefault(
            str(component_id), []
        )
        values.append(
            current.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            )
        )
        payload["restarts"][str(component_id)] = values[-max(1, keep):]
        self._write(payload)

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                "version": self.VERSION,
                "heartbeats": {},
                "restarts": {},
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "version": self.VERSION,
                "heartbeats": {},
                "restarts": {},
                "corrupt": True,
            }
        if not isinstance(payload, dict):
            return {
                "version": self.VERSION,
                "heartbeats": {},
                "restarts": {},
                "corrupt": True,
            }
        if int(payload.get("version", 0)) != self.VERSION:
            return {
                "version": self.VERSION,
                "heartbeats": {},
                "restarts": {},
                "corrupt": True,
            }
        if not isinstance(payload.get("heartbeats"), dict):
            payload["heartbeats"] = {}
        if not isinstance(payload.get("restarts"), dict):
            payload["restarts"] = {}
        return payload

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)


class IndependentGuardian:
    """Independent read-only observer over XiaoYu authority/runtime metadata."""

    def __init__(
        self,
        *,
        thresholds: GuardianThresholds = GuardianThresholds(),
        sinks: Sequence[GuardianSink] = (),
    ) -> None:
        self.thresholds = thresholds
        self.sinks = tuple(sinks)

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _readonly_connection(path: Path) -> sqlite3.Connection:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=2.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    @staticmethod
    def _table_exists(
        conn: sqlite3.Connection,
        table: str,
    ) -> bool:
        return (
            conn.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name=?""",
                (table,),
            ).fetchone()
            is not None
        )

    def _database_findings(
        self,
        inputs: GuardianInputs,
        now: datetime,
    ) -> list[GuardianFinding]:
        path = Path(inputs.identity_db_path)
        if not path.exists():
            return [
                GuardianFinding(
                    "DB_MISSING",
                    GuardianSeverity.CRITICAL,
                    "sqlite-authority",
                )
            ]
        conn = None
        try:
            conn = self._readonly_connection(path)
            result = conn.execute("PRAGMA quick_check").fetchone()
            if result is None or str(result[0]).lower() != "ok":
                return [
                    GuardianFinding(
                        "DB_INTEGRITY_FAILED",
                        GuardianSeverity.CRITICAL,
                        "sqlite-authority",
                    )
                ]
        except sqlite3.DatabaseError:
            return [
                GuardianFinding(
                    "DB_INTEGRITY_FAILED",
                    GuardianSeverity.CRITICAL,
                    "sqlite-authority",
                )
            ]
        finally:
            if conn is not None:
                conn.close()
        return []

    def _release_provider_digests(
        self,
        inputs: GuardianInputs,
    ) -> tuple[dict[str, str], list[GuardianFinding]]:
        explicit = dict(inputs.expected_provider_digests)
        if explicit:
            return explicit, []
        if inputs.release_authority_path is None:
            return {}, []
        try:
            from xiaoyu.release.authority import ReleaseAuthority
            current = ReleaseAuthority(
                inputs.release_authority_path
            ).current()
        except Exception:
            return {}, [
                GuardianFinding(
                    "RELEASE_AUTHORITY_UNREADABLE",
                    GuardianSeverity.CRITICAL,
                    "release-authority",
                )
            ]
        if current is None:
            return {}, [
                GuardianFinding(
                    "CURRENT_RELEASE_MISSING",
                    GuardianSeverity.WARNING,
                    "release-authority",
                )
            ]
        blockers = current.binding_blockers()
        findings = []
        if blockers:
            findings.append(
                GuardianFinding(
                    "CURRENT_RELEASE_BINDINGS_INCOMPLETE",
                    GuardianSeverity.WARNING,
                    "release-authority",
                    {"count": len(blockers)},
                )
            )
        return dict(current.provider_digests), findings

    def _provider_findings(
        self,
        inputs: GuardianInputs,
    ) -> list[GuardianFinding]:
        expected_provider_digests, findings = (
            self._release_provider_digests(inputs)
        )
        if not expected_provider_digests:
            return findings
        conn = None
        try:
            conn = self._readonly_connection(
                Path(inputs.identity_db_path)
            )
            if not self._table_exists(conn, "provider_registry"):
                return findings + [
                    GuardianFinding(
                        "PROVIDER_REGISTRY_MISSING",
                        GuardianSeverity.CRITICAL,
                        "provider-registry",
                    )
                ]
            for provider_id, expected in sorted(
                expected_provider_digests.items()
            ):
                row = conn.execute(
                    """SELECT descriptor_digest,lifecycle_state
                       FROM provider_registry WHERE provider_id=?""",
                    (provider_id,),
                ).fetchone()
                if row is None:
                    findings.append(
                        GuardianFinding(
                            "PROVIDER_MISSING",
                            GuardianSeverity.WARNING,
                            "provider-registry",
                            {"provider_id": provider_id},
                        )
                    )
                    continue
                actual = str(row["descriptor_digest"])
                if actual != str(expected):
                    findings.append(
                        GuardianFinding(
                            "PROVIDER_DIGEST_DRIFT",
                            GuardianSeverity.CRITICAL,
                            "provider-registry",
                            {
                                "provider_id": provider_id,
                                "lifecycle": str(
                                    row["lifecycle_state"]
                                ),
                            },
                        )
                    )
        except sqlite3.DatabaseError:
            # Integrity checker emits the DB finding. Avoid duplicate content.
            pass
        finally:
            if conn is not None:
                conn.close()
        return findings

    def _denied_effect_findings(
        self,
        inputs: GuardianInputs,
        now: datetime,
    ) -> list[GuardianFinding]:
        conn = None
        try:
            conn = self._readonly_connection(
                Path(inputs.identity_db_path)
            )
            if not self._table_exists(
                conn, "authorization_decisions"
            ):
                return []
            rows = conn.execute(
                """SELECT decision,created_at,action_class
                   FROM authorization_decisions
                   WHERE decision='DENY'
                   ORDER BY created_at DESC
                   LIMIT 1000"""
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            if conn is not None:
                conn.close()

        cutoff = now - timedelta(
            seconds=self.thresholds.denied_window_s
        )
        recent = [
            row
            for row in rows
            if (
                (stamp := self._parse_time(row["created_at"]))
                is not None
                and stamp >= cutoff
            )
        ]
        if len(recent) < self.thresholds.denied_effect_threshold:
            return []
        action_counts: dict[str, int] = {}
        for row in recent:
            action = str(row["action_class"])
            action_counts[action] = action_counts.get(action, 0) + 1
        top_action = max(
            action_counts,
            key=lambda value: (
                action_counts[value],
                value,
            ),
        )
        return [
            GuardianFinding(
                "REPEATED_DENIED_EFFECTS",
                GuardianSeverity.WARNING,
                "authorization",
                {
                    "count": len(recent),
                    "window_s": self.thresholds.denied_window_s,
                    "top_action_class": top_action,
                },
            )
        ]

    def _backup_findings(
        self,
        inputs: GuardianInputs,
        now: datetime,
    ) -> list[GuardianFinding]:
        if inputs.backup_path is None:
            return []
        backup = Path(inputs.backup_path)
        manifest_path = Path(str(backup) + ".manifest.json")
        if not backup.exists() or not manifest_path.exists():
            return [
                GuardianFinding(
                    "BACKUP_MISSING",
                    GuardianSeverity.WARNING,
                    "backup",
                )
            ]
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception:
            return [
                GuardianFinding(
                    "BACKUP_MANIFEST_UNREADABLE",
                    GuardianSeverity.CRITICAL,
                    "backup",
                )
            ]
        if not isinstance(manifest, dict):
            return [
                GuardianFinding(
                    "BACKUP_MANIFEST_INVALID",
                    GuardianSeverity.CRITICAL,
                    "backup",
                )
            ]
        created = self._parse_time(manifest.get("creation_time"))
        if created is None:
            return [
                GuardianFinding(
                    "BACKUP_MANIFEST_TIME_INVALID",
                    GuardianSeverity.CRITICAL,
                    "backup",
                )
            ]
        age = max(0.0, (now - created).total_seconds())
        findings = []
        if age > self.thresholds.backup_max_age_s:
            findings.append(
                GuardianFinding(
                    "BACKUP_STALE",
                    GuardianSeverity.WARNING,
                    "backup",
                    {"age_s": round(age, 3)},
                )
            )
        if (
            inputs.identity_id is not None
            and str(manifest.get("identity_id"))
            != str(inputs.identity_id)
        ):
            findings.append(
                GuardianFinding(
                    "BACKUP_IDENTITY_MISMATCH",
                    GuardianSeverity.CRITICAL,
                    "backup",
                )
            )
        expected = str(manifest.get("db_sha256") or "")
        if expected:
            digest = hashlib.sha256()
            try:
                with backup.open("rb") as handle:
                    for chunk in iter(
                        lambda: handle.read(1024 * 1024),
                        b"",
                    ):
                        digest.update(chunk)
            except OSError:
                findings.append(
                    GuardianFinding(
                        "BACKUP_UNREADABLE",
                        GuardianSeverity.CRITICAL,
                        "backup",
                    )
                )
            else:
                actual = "sha256:" + digest.hexdigest()
                if actual != expected:
                    findings.append(
                        GuardianFinding(
                            "BACKUP_DIGEST_MISMATCH",
                            GuardianSeverity.CRITICAL,
                            "backup",
                        )
                    )
        return findings

    def _resource_findings(
        self,
        inputs: GuardianInputs,
    ) -> list[GuardianFinding]:
        snapshot = inputs.resource_snapshot
        if snapshot is None:
            return []
        findings = []
        if (
            snapshot.cpu_fraction is not None
            and snapshot.cpu_fraction >= self.thresholds.cpu_fraction
        ):
            findings.append(
                GuardianFinding(
                    "CPU_RUNAWAY",
                    GuardianSeverity.WARNING,
                    "resources",
                    {"cpu_fraction": round(snapshot.cpu_fraction, 4)},
                )
            )
        if (
            snapshot.gpu_fraction is not None
            and snapshot.gpu_fraction >= self.thresholds.gpu_fraction
        ):
            findings.append(
                GuardianFinding(
                    "GPU_RUNAWAY",
                    GuardianSeverity.WARNING,
                    "resources",
                    {"gpu_fraction": round(snapshot.gpu_fraction, 4)},
                )
            )
        if (
            snapshot.ram_available_mb is not None
            and snapshot.ram_available_mb
            <= self.thresholds.min_ram_available_mb
        ):
            findings.append(
                GuardianFinding(
                    "RAM_PRESSURE",
                    GuardianSeverity.WARNING,
                    "resources",
                    {
                        "ram_available_mb": round(
                            snapshot.ram_available_mb, 3
                        )
                    },
                )
            )
        if (
            snapshot.vram_available_mb is not None
            and snapshot.vram_available_mb
            <= self.thresholds.min_vram_available_mb
        ):
            findings.append(
                GuardianFinding(
                    "VRAM_PRESSURE",
                    GuardianSeverity.WARNING,
                    "resources",
                    {
                        "vram_available_mb": round(
                            snapshot.vram_available_mb, 3
                        )
                    },
                )
            )
        return findings

    def _sidecar_findings(
        self,
        inputs: GuardianInputs,
        now: datetime,
    ) -> list[GuardianFinding]:
        path = inputs.state_path
        if path is None:
            return []
        state = GuardianStateStore(path)._load()
        if state.get("corrupt"):
            return [
                GuardianFinding(
                    "GUARDIAN_STATE_CORRUPT",
                    GuardianSeverity.WARNING,
                    "guardian-sidecar",
                )
            ]
        findings = []
        for component, value in sorted(
            state.get("heartbeats", {}).items()
        ):
            stamp = self._parse_time(value)
            if (
                stamp is None
                or (now - stamp).total_seconds()
                > self.thresholds.heartbeat_timeout_s
            ):
                findings.append(
                    GuardianFinding(
                        "COMPONENT_HEARTBEAT_STALE",
                        GuardianSeverity.CRITICAL,
                        str(component),
                    )
                )
        cutoff = now - timedelta(
            seconds=self.thresholds.restart_window_s
        )
        for component, values in sorted(
            state.get("restarts", {}).items()
        ):
            recent = 0
            for value in values:
                stamp = self._parse_time(value)
                if stamp is not None and stamp >= cutoff:
                    recent += 1
            if recent >= self.thresholds.max_restarts_in_window:
                findings.append(
                    GuardianFinding(
                        "RESTART_LOOP",
                        GuardianSeverity.CRITICAL,
                        str(component),
                        {
                            "restart_count": recent,
                            "window_s": self.thresholds.restart_window_s,
                        },
                    )
                )
        return findings

    def check(
        self,
        inputs: GuardianInputs,
        *,
        observed_at: Optional[datetime] = None,
    ) -> GuardianReport:
        now = (
            observed_at or datetime.now(timezone.utc)
        ).astimezone(timezone.utc)
        findings = []
        findings.extend(self._database_findings(inputs, now))
        findings.extend(self._backup_findings(inputs, now))
        findings.extend(self._provider_findings(inputs))
        findings.extend(self._resource_findings(inputs))
        findings.extend(self._denied_effect_findings(inputs, now))
        findings.extend(self._sidecar_findings(inputs, now))
        report = GuardianReport(now, tuple(findings))
        sink_failures = []
        for sink in self.sinks:
            try:
                sink.emit(report)
            except Exception:
                sink_failures.append(
                    GuardianFinding(
                        "TELEMETRY_SINK_FAILED",
                        GuardianSeverity.WARNING,
                        type(sink).__name__,
                    )
                )
        if sink_failures:
            report = GuardianReport(
                now,
                report.findings + tuple(sink_failures),
            )
        return report
