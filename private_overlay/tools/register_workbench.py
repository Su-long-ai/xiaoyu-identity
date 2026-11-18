import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = OVERLAY_ROOT / "plugins" / "xiaoyu_private"
NEKO_ROOT = Path(os.environ.get("NEKO_ROOT", r"D:\xiaoyu_external_audit\N.E.K.O"))
sys.path.insert(0, str(NEKO_ROOT))

from plugin.server.application import plugin_projects  # noqa: E402


async def main() -> int:
    source = str(PLUGIN_ROOT.resolve())
    projects = plugin_projects.list_projects_sync()
    current = next(
        (item for item in projects if Path(item.source_dir).resolve() == PLUGIN_ROOT.resolve()),
        None,
    )
    if current is None:
        current = await plugin_projects.register_project(source)
        action = "REGISTERED"
    else:
        action = "ALREADY_REGISTERED"

    print(action)
    print(json.dumps(asdict(current), ensure_ascii=False, indent=2))

    if current.status != "ok":
        return 2

    # A standalone setup command does not run the full N.E.K.O plugin server.
    # In that state the Workbench correctly reports runtime_inactive; the
    # subsequent live-host smoke is the runtime validation.
    acceptable_problems = {None, "runtime_inactive", "not_registered"}
    if current.problem not in acceptable_problems:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
