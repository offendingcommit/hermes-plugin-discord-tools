from __future__ import annotations

import json
import os
import tempfile
import unittest

from hermes_plugin_loader import load_plugin_module


plugin = load_plugin_module()
hooks = plugin.hooks


class HookTests(unittest.TestCase):
    def test_injects_hint_for_discord_link(self) -> None:
        result = hooks.inject_discord_read_hint(
            messages=[
                {"role": "system", "content": "hello"},
                {"role": "user", "content": "Check https://discord.com/channels/111/222/333"},
            ]
        )

        self.assertIsNotNone(result)
        self.assertIn("discord_get_message", result["context"])
        self.assertIn("https://discord.com/channels/111/222/333", result["context"])

    def test_injects_story_hint_from_inline_json(self) -> None:
        old = os.environ.get("DISCORD_TOOLS_STORY_HINTS")
        os.environ["DISCORD_TOOLS_STORY_HINTS"] = json.dumps(
            [{"name": "Bea's House of Tea", "keywords": ["house of tea"], "hint": "Check source channels."}]
        )
        try:
            result = hooks.inject_discord_read_hint(message="What happened in House of Tea?")
        finally:
            if old is None:
                os.environ.pop("DISCORD_TOOLS_STORY_HINTS", None)
            else:
                os.environ["DISCORD_TOOLS_STORY_HINTS"] = old

        self.assertIsNotNone(result)
        self.assertIn("Bea's House of Tea", result["context"])

    def test_story_hint_can_load_from_file_path(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as fh:
            json.dump({"hints": [{"name": "Tea", "keywords": ["ember"], "hint": "Read the channel."}]}, fh)
            fh.flush()
            result = hooks.inject_discord_read_hint(
                message="ember revealed",
                env={"DISCORD_TOOLS_STORY_HINTS_JSON": fh.name},
            )

        self.assertIsNotNone(result)
        self.assertIn("Read the channel", result["context"])

    def test_no_hint_without_link_or_keyword(self) -> None:
        self.assertIsNone(hooks.inject_discord_read_hint(message="ordinary chat"))


if __name__ == "__main__":
    unittest.main()
