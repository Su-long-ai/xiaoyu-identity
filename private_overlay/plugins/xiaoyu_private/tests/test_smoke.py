import tomllib
from pathlib import Path


def test_manifest_entry_is_explicit():
    root = Path(__file__).resolve().parents[1]
    with (root / "plugin.toml").open("rb") as fh:
        manifest = tomllib.load(fh)
    assert manifest["plugin"]["id"] == "xiaoyu_private"
    assert (
        manifest["plugin"]["entry"]
        == "plugin.plugins.xiaoyu_private:XiaoYuPrivatePlugin"
    )
