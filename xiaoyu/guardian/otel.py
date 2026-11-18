from __future__ import annotations

from importlib import metadata
from typing import Any, Optional

from .monitor import GuardianReport


class OpenTelemetryUnavailable(RuntimeError):
    pass


class OpenTelemetryGuardianSink:
    """Privacy-safe OpenTelemetry metadata exporter.

    The sink uses only the OpenTelemetry API. A host application may configure
    any SDK/exporter it wants; XiaoYu does not own another telemetry backend.
    """

    REVIEWED_API_VERSION = "1.45.2"
    SAFE_ATTRIBUTE_KEYS = {
        "provider_id",
        "lifecycle",
        "count",
        "window_s",
        "top_action_class",
        "age_s",
        "cpu_fraction",
        "gpu_fraction",
        "ram_available_mb",
        "vram_available_mb",
        "restart_count",
    }

    def __init__(
        self,
        *,
        meter: Optional[Any] = None,
        tracer: Optional[Any] = None,
        required_api_version: Optional[str] = REVIEWED_API_VERSION,
    ) -> None:
        if meter is None or tracer is None:
            try:
                from opentelemetry import metrics, trace  # type: ignore
            except ImportError as exc:
                raise OpenTelemetryUnavailable(
                    "opentelemetry-api is not installed"
                ) from exc
            if required_api_version is not None:
                try:
                    installed = metadata.version("opentelemetry-api")
                except metadata.PackageNotFoundError as exc:
                    raise OpenTelemetryUnavailable(
                        "opentelemetry-api metadata unavailable"
                    ) from exc
                if installed != required_api_version:
                    raise OpenTelemetryUnavailable(
                        "opentelemetry-api version %s is not the reviewed %s"
                        % (installed, required_api_version)
                    )
            meter = meter or metrics.get_meter("xiaoyu.guardian")
            tracer = tracer or trace.get_tracer("xiaoyu.guardian")

        self.meter = meter
        self.tracer = tracer
        self._finding_counter = meter.create_counter(
            "xiaoyu.guardian.findings",
            unit="1",
            description="Guardian findings by code/severity/component",
        )
        self._check_counter = meter.create_counter(
            "xiaoyu.guardian.checks",
            unit="1",
            description="Independent Guardian checks",
        )

    @classmethod
    def _attributes(cls, finding) -> dict[str, Any]:
        result = {
            "guardian.code": finding.code,
            "guardian.severity": finding.severity.value,
            "guardian.component": finding.component,
        }
        for key, value in finding.attributes.items():
            if key not in cls.SAFE_ATTRIBUTE_KEYS:
                continue
            result["guardian." + key] = value
        return result

    def emit(self, report: GuardianReport) -> None:
        self._check_counter.add(
            1,
            {
                "guardian.healthy": bool(report.healthy),
                "guardian.finding_count": len(report.findings),
            },
        )
        with self.tracer.start_as_current_span(
            "xiaoyu.guardian.check"
        ) as span:
            span.set_attribute("guardian.healthy", bool(report.healthy))
            span.set_attribute(
                "guardian.finding_count",
                len(report.findings),
            )
            for finding in report.findings:
                attributes = self._attributes(finding)
                self._finding_counter.add(1, attributes)
                span.add_event(
                    "guardian.finding",
                    attributes=attributes,
                )
