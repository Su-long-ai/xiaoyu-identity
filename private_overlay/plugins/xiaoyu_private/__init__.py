from plugin.sdk.plugin import NekoPluginBase, Ok, neko_plugin, plugin_entry


@neko_plugin
class XiaoYuPrivatePlugin(NekoPluginBase):
    """Thin private overlay. N.E.K.O remains the memory/task authority."""

    @plugin_entry(
        id="status",
        name="XiaoYu private overlay status",
        description="Return the active XiaoYu private-overlay authority contract.",
    )
    async def status(self, **_):
        return Ok(
            {
                "identity": "xiaoyu",
                "mode": "private_overlay",
                "memory_authority": "neko_native",
                "task_authority": "neko_native",
                "core_patch_count": 0,
                "dual_write": False,
            }
        )
