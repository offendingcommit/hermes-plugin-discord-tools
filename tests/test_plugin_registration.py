from __future__ import annotations

import ast
import types
import unittest
from pathlib import Path

from hermes_plugin_kit import RegistrationSummary
from hermes_plugin_loader import load_plugin_module

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


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

        summary = plugin.register(ctx)

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
        self.assertEqual(
            summary,
            RegistrationSummary(
                tools=(
                    "discord_get_message",
                    "discord_read_channel",
                    "discord_read_story",
                    "discord_read_thread",
                ),
                hooks=("pre_llm_call",),
            ),
        )

    def test_registration_is_owned_by_plugin_kit(self) -> None:
        for path in sorted(PLUGIN_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertFalse(
                        node.func.attr.startswith("register_"),
                        f"{path.name} directly calls {node.func.attr}",
                    )
                if isinstance(node, ast.Name):
                    self.assertNotEqual(
                        node.id,
                        "register_all",
                        f"{path.name} still uses legacy register_all",
                    )


if __name__ == "__main__":
    unittest.main()
