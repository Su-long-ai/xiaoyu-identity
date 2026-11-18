# OpenTelemetry Guardian smoke — 2026-11-18

Status: **R19 OPTIONAL TELEMETRY ADAPTER PASS**

## Reused capability

- OpenTelemetry API: 1.45.2
- OpenTelemetry SDK used only for the local verification smoke: 1.45.2
- Package role: telemetry emission only
- XiaoYu Guardian role: independent detection policy remains XiaoYu-owned
- Export backend: none selected by XiaoYu

Official OpenTelemetry Python documentation treats traces and metrics as stable
and recommends the API for library instrumentation, with the host application
configuring an SDK/exporter.

## Local real-package smoke

A repository-external Python 3.11 venv installed:

- opentelemetry-api==1.45.2
- opentelemetry-sdk==1.45.2

The smoke configured the official SDK in-memory metric reader and in-memory
span exporter, then emitted one Guardian RESTART_LOOP finding.

Observed:

- metric resource count: 1
- finished spans: 1
- span event: guardian.finding
- exported attributes:
  - guardian.code=RESTART_LOOP
  - guardian.severity=CRITICAL
  - guardian.component=provider-worker
  - guardian.restart_count=5
  - guardian.window_s=300

A deliberately supplied `prompt=SECRET` attribute was not exported.

## Privacy boundary

The OTel sink uses an explicit attribute allowlist. It does not export:

- prompt or response text
- memory text
- request/resource JSON
- canonical-event payloads
- user messages
- provider request/result bodies
- raw vision/audio data

Guardian findings contain bounded metadata only.

## Architecture boundary

OpenTelemetry does not become an authority or recovery engine.

Guardian detection remains independent and works without OpenTelemetry installed.
When OpenTelemetry is absent, only export is unavailable; the Guardian checks
still run.

The host application chooses any future SDK/exporter/collector configuration.
XiaoYu does not implement another tracing/metrics backend.
