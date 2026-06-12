from __future__ import annotations

import types
import unittest

from hermes_plugin_loader import load_plugin_module


class FakeCtx:
    def __init__(self) -> None:
        self.manifest = types.SimpleNamespace(config={})
        self.tools: list[dict] = []
        self.hooks: list[tuple[str, object]] = []

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)

    def register_hook(self, name, handler) -> None:
        self.hooks.append((name, handler))


class RegistrationTests(unittest.TestCase):
    def test_registers_read_only_tools_and_hook(self) -> None:
        plugin = load_plugin_module()
        ctx = FakeCtx()

        plugin.register(ctx)

        self.assertEqual(
            {tool["name"] for tool in ctx.tools},
            {
                "discord_read_channel",
                "discord_read_thread",
                "discord_get_message",
                "discord_read_story",
            },
        )
        self.assertEqual({tool["toolset"] for tool in ctx.tools}, {"messaging"})
        self.assertIn(("pre_llm_call", plugin.hooks.inject_discord_read_hint), ctx.hooks)


if __name__ == "__main__":
    unittest.main()
