#!/usr/bin/env python3
"""Materialize existing restart candidate tests for the NekoPower migration.

This is a test-only namespace projection. It does not copy or modify runtime
implementation and keeps the c3 candidate tests as the single semantic source.
"""

from __future__ import annotations

import argparse
from pathlib import Path

FILES = (
    "test_host_restart_report_wait_candidate.py",
    "test_host_restart_permission_wait_candidate.py",
    "test_host_restart_answer_handoff_candidate.py",
    "test_host_restart_working_uncertain_candidate.py",
    "test_host_restart_durable_queue_candidate.py",
    "test_host_restart_fault_matrix_candidate.py",
    "host_restart_fault_child.py",
)


def project(source_dir: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in FILES:
        source = source_dir / name
        if not source.is_file():
            raise FileNotFoundError(source)
        text = source.read_text(encoding="utf-8-sig")
        text = text.replace("nekoclaw", "nekopower").replace("NekoClaw", "NekoPower")
        target = output_dir / name
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    written = project(args.source_dir.resolve(), args.output_dir.resolve())
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
