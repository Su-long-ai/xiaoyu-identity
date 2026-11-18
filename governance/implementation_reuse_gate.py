from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "governance" / "IMPLEMENTATION_REUSE_POLICY.json"
DEFAULT_CATALOG = ROOT / "governance" / "REUSE_CATALOG.json"


class ReuseGateError(RuntimeError):
    pass


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ReuseGateError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReuseGateError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReuseGateError(f"expected JSON object: {path}")
    return value


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(
        path.replace("\\", "/"),
        pattern.replace("\\", "/"),
    )


def affected_areas(
    changed_files: Iterable[str],
    policy: dict,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for raw in changed_files:
        path = str(raw).replace("\\", "/")
        for area, spec in policy.get("areas", {}).items():
            patterns = spec.get("paths") or []
            if any(_matches(path, str(pattern)) for pattern in patterns):
                result.setdefault(str(area), []).append(path)
    return result


def unclassified_new_files(
    new_files: Iterable[str],
    policy: dict,
) -> list[str]:
    guard = policy.get("unclassified_new_file_guard") or {}
    prefixes = tuple(str(x) for x in guard.get("prefixes") or ())
    extensions = tuple(str(x) for x in guard.get("extensions") or ())
    if not prefixes or not extensions:
        return []
    result = []
    for raw in new_files:
        path = str(raw).replace("\\", "/")
        if not path.startswith(prefixes):
            continue
        if not path.endswith(extensions):
            continue
        if not affected_areas((path,), policy):
            result.append(path)
    return sorted(set(result))


def _catalog_index(catalog: dict) -> dict[str, dict]:
    result = {}
    for item in catalog.get("components", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        result[str(item["id"])] = item
    return result


def _is_external_or_stdlib(component: dict) -> bool:
    source = component.get("source")
    source_type = ""
    if isinstance(source, dict):
        source_type = str(source.get("type") or "")
    return source_type not in {"", "internal", "internal_alias"}


def _decision_entries(payload: dict, path: str) -> list[dict]:
    if payload.get("schema") != "xiaoyu-product-reuse-decision-v1":
        raise ReuseGateError(
            f"{path}: schema must be xiaoyu-product-reuse-decision-v1"
        )
    if not str(payload.get("change_id") or "").strip():
        raise ReuseGateError(f"{path}: change_id is required")
    entries = payload.get("areas")
    if not isinstance(entries, list) or not entries:
        raise ReuseGateError(f"{path}: areas must be a non-empty list")
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReuseGateError(
                f"{path}: each area decision must be an object"
            )
        result.append(entry)
    return result


def validate(
    *,
    changed_files: Iterable[str],
    decision_payloads: Iterable[tuple[str, dict]],
    policy: dict,
    catalog: dict,
    new_files: Iterable[str] = (),
) -> list[str]:
    errors: list[str] = []
    areas = affected_areas(changed_files, policy)
    unclassified = unclassified_new_files(new_files, policy)
    for path in unclassified:
        errors.append(
            f"{path}: new product capability file is not classified by "
            "IMPLEMENTATION_REUSE_POLICY.json; classify it as a commodity "
            "reuse area or explicitly record an authority exception"
        )
    if not areas:
        return errors

    allowed_modes = set(policy.get("allowed_modes") or [])
    blocked = set(policy.get("blocked_component_lifecycles") or [])
    catalog_by_id = _catalog_index(catalog)
    decisions: dict[str, tuple[str, dict]] = {}

    for path, payload in decision_payloads:
        try:
            entries = _decision_entries(payload, path)
        except ReuseGateError as exc:
            errors.append(str(exc))
            continue
        for entry in entries:
            area = str(entry.get("area") or "")
            if area not in policy.get("areas", {}):
                errors.append(f"{path}: unknown area {area!r}")
                continue
            if area in decisions:
                errors.append(
                    f"{path}: duplicate decision for area {area}; "
                    f"already declared in {decisions[area][0]}"
                )
                continue
            decisions[area] = (path, entry)

    for area, touched in sorted(areas.items()):
        declared = decisions.get(area)
        if declared is None:
            errors.append(
                f"{area}: commodity capability changed without a reuse "
                f"decision; touched={','.join(sorted(touched))}"
            )
            continue

        path, entry = declared
        mode = str(entry.get("mode") or "")
        if mode not in allowed_modes:
            errors.append(f"{path}:{area}: unsupported mode {mode!r}")

        if entry.get("no_new_infrastructure") is not True:
            errors.append(
                f"{path}:{area}: no_new_infrastructure must be true; "
                "new infrastructure requires an explicit architecture "
                "decision before implementation"
            )

        components = entry.get("components")
        if not isinstance(components, list) or not components:
            errors.append(
                f"{path}:{area}: components must be a non-empty list"
            )
            components = []

        required_kinds = set(
            policy.get("areas", {})
            .get(area, {})
            .get("required_component_kinds")
            or []
        )
        has_external_or_stdlib = False
        has_relevant_kind = False
        for component_id in components:
            component_id = str(component_id)
            component = catalog_by_id.get(component_id)
            if component is None:
                errors.append(
                    f"{path}:{area}: unknown component {component_id!r}; "
                    "register/review it in REUSE_CATALOG.json first"
                )
                continue
            lifecycle = str(component.get("lifecycle") or "")
            if lifecycle in blocked:
                errors.append(
                    f"{path}:{area}: component {component_id!r} "
                    f"lifecycle={lifecycle} is blocked for new product use"
                )
            if _is_external_or_stdlib(component):
                has_external_or_stdlib = True
            if (
                not required_kinds
                or str(component.get("kind") or "") in required_kinds
            ):
                has_relevant_kind = True

        if components and not has_external_or_stdlib:
            errors.append(
                f"{path}:{area}: at least one mature external/stdlib "
                "component must be considered; xiaoyu_existing_core alone "
                "cannot satisfy a commodity capability decision"
            )
        if components and required_kinds and not has_relevant_kind:
            errors.append(
                f"{path}:{area}: none of the declared components match "
                f"required kinds {','.join(sorted(required_kinds))}"
            )

        gap = str(entry.get("gap") or "").strip()
        custom_surface = entry.get("custom_surface", [])
        if not isinstance(custom_surface, list):
            errors.append(f"{path}:{area}: custom_surface must be a list")
            custom_surface = []

        if mode == "reuse":
            if custom_surface:
                errors.append(
                    f"{path}:{area}: mode=reuse cannot declare "
                    "custom_surface; use extend/custom_policy for "
                    "XiaoYu-specific glue"
                )
        elif mode in {
            "extend",
            "custom_policy",
            "legacy_compat",
            "falsification",
        }:
            if len(gap) < 40:
                errors.append(
                    f"{path}:{area}: mode={mode} requires a concrete gap "
                    "of at least 40 characters"
                )
            if mode in {"extend", "custom_policy"} and not custom_surface:
                errors.append(
                    f"{path}:{area}: mode={mode} requires a bounded "
                    "custom_surface list"
                )

    return errors


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ReuseGateError(
            "git command failed: git %s\n%s"
            % (" ".join(args), result.stderr.strip())
        )
    return result.stdout


def changed_status_from_git(
    base: str,
    head: str = "HEAD",
) -> tuple[list[str], list[str]]:
    output = _git(
        "diff",
        "--name-status",
        "--find-renames",
        "--diff-filter=ACMRT",
        f"{base}...{head}",
    )
    changed: list[str] = []
    new_files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1].strip().replace("\\", "/")
        if not path:
            continue
        changed.append(path)
        if status.startswith("A") or status.startswith("R"):
            new_files.append(path)
    return changed, new_files


def changed_files_from_git(base: str, head: str = "HEAD") -> list[str]:
    changed, _ = changed_status_from_git(base, head)
    return changed


def _resolve_base(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_base = str(os.environ.get("XIAOYU_REUSE_BASE") or "").strip()
    if env_base and set(env_base) != {"0"}:
        return env_base
    github_base = str(os.environ.get("GITHUB_BASE_REF") or "").strip()
    if github_base:
        candidate = "origin/" + github_base
        try:
            _git("rev-parse", "--verify", candidate)
            return candidate
        except ReuseGateError:
            return github_base
    return "HEAD^"


def run(
    base: str | None,
    head: str,
    policy_path: Path,
    catalog_path: Path,
) -> int:
    policy = _load_json(policy_path)
    catalog = _load_json(catalog_path)
    resolved_base = _resolve_base(base)
    changed, new_files = changed_status_from_git(resolved_base, head)
    areas = affected_areas(changed, policy)

    decision_glob = str(policy.get("decision_glob") or "")
    decision_files = [
        path
        for path in changed
        if decision_glob and _matches(path, decision_glob)
    ]
    payloads: list[tuple[str, dict]] = []
    for relative in decision_files:
        try:
            payloads.append((relative, _load_json(ROOT / relative)))
        except ReuseGateError as exc:
            print(f"REUSE_GATE_FAIL {exc}")
            return 2

    errors = validate(
        changed_files=changed,
        decision_payloads=payloads,
        policy=policy,
        catalog=catalog,
        new_files=new_files,
    )
    if errors:
        print("REUSE_GATE_FAIL")
        print(f"base={resolved_base}")
        for area, files in sorted(areas.items()):
            print(f"affected[{area}]={','.join(sorted(files))}")
        for error in errors:
            print("- " + error)
        return 2

    print("REUSE_GATE_PASS")
    print(f"base={resolved_base}")
    if areas:
        print("affected_areas=" + ",".join(sorted(areas)))
        print("decision_files=" + ",".join(sorted(decision_files)))
    else:
        print("affected_areas=none")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail product implementation changes that bypass "
            "XiaoYu reuse-first policy."
        )
    )
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)
    try:
        return run(args.base, args.head, args.policy, args.catalog)
    except ReuseGateError as exc:
        print("REUSE_GATE_FAIL " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
