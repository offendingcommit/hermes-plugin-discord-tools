from __future__ import annotations

import json
import unittest

from hermes_plugin_loader import load_plugin_module


plugin = load_plugin_module()
tools = plugin.tools

GUILD_ID = "111111111111111111"
CHANNEL_ID = "222222222222222222"
MESSAGE_ID = "333333333333333333"


class FakeFetcher:
    def __init__(self, guild_id: str = GUILD_ID, messages: list[dict] | None = None) -> None:
        self.guild_id = guild_id
        self.messages = messages or [
            {"id": "10", "author_name": "Bea", "content": "tea one"},
            {"id": "11", "author_name": "Amber", "content": "tea two"},
        ]
        self.calls: list[tuple] = []

    def read_channel(self, channel_id: str, *, limit: int, before: str | None = None, after: str | None = None) -> dict:
        self.calls.append(("read_channel", channel_id, limit, before, after))
        return {
            "guild_id": self.guild_id,
            "channel_id": channel_id,
            "channel_name": "bea-house-of-tea",
            "messages": self.messages[:limit],
        }

    def get_message(self, channel_id: str, message_id: str, *, context_limit: int) -> dict:
        self.calls.append(("get_message", channel_id, message_id, context_limit))
        return {
            "guild_id": self.guild_id,
            "channel_id": channel_id,
            "channel_name": "bea-house-of-tea",
            "messages": self.messages[:context_limit],
        }


def decoded(raw: str) -> dict:
    return json.loads(raw)


class DiscordToolTests(unittest.TestCase):
    def test_parse_discord_message_url(self) -> None:
        ref = tools.parse_discord_ref(f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}/{MESSAGE_ID}")

        self.assertEqual(ref.guild_id, GUILD_ID)
        self.assertEqual(ref.channel_id, CHANNEL_ID)
        self.assertEqual(ref.message_id, MESSAGE_ID)

    def test_read_channel_uses_fetcher_and_shapes_messages(self) -> None:
        fetcher = FakeFetcher()
        result = decoded(
            tools.read_channel_impl(
                {"channel_id_or_url": f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}", "limit": 1},
                fetcher,
                {"DISCORD_TOOLS_ALLOWED_GUILDS": GUILD_ID},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["channel_id"], CHANNEL_ID)
        self.assertEqual(len(result["data"]["messages"]), 1)
        self.assertEqual(fetcher.calls[0], ("read_channel", CHANNEL_ID, 1, None, None))

    def test_read_thread_sets_kind(self) -> None:
        result = decoded(
            tools.read_thread_impl(
                {"thread_id_or_url": CHANNEL_ID},
                FakeFetcher(),
                {},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["kind"], "thread")

    def test_rejects_disallowed_guild_from_url(self) -> None:
        result = decoded(
            tools.read_channel_impl(
                {"channel_id_or_url": f"https://discord.com/channels/999999999999999999/{CHANNEL_ID}"},
                FakeFetcher(guild_id="999"),
                {"DISCORD_TOOLS_ALLOWED_GUILDS": GUILD_ID},
            )
        )

        self.assertFalse(result["success"])
        self.assertIn("not allowed", result["error"])

    def test_rejects_disallowed_guild_after_fetch_for_raw_channel_id(self) -> None:
        result = decoded(
            tools.read_channel_impl(
                {"channel_id_or_url": CHANNEL_ID},
                FakeFetcher(guild_id="999"),
                {"DISCORD_TOOLS_ALLOWED_GUILDS": GUILD_ID},
            )
        )

        self.assertFalse(result["success"])
        self.assertIn("not allowed", result["error"])

    def test_get_message_requires_channel_for_raw_message_id(self) -> None:
        result = decoded(
            tools.get_message_impl(
                {"message_id_or_url": MESSAGE_ID},
                FakeFetcher(),
                {},
            )
        )

        self.assertFalse(result["success"])
        self.assertIn("channel_id", result["error"])

    def test_get_message_accepts_full_url(self) -> None:
        fetcher = FakeFetcher()
        result = decoded(
            tools.get_message_impl(
                {"message_id_or_url": f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}/{MESSAGE_ID}", "context_limit": 2},
                fetcher,
                {"DISCORD_TOOLS_ALLOWED_GUILDS": GUILD_ID},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["message_id"], MESSAGE_ID)
        self.assertEqual(fetcher.calls[0], ("get_message", CHANNEL_ID, MESSAGE_ID, 2))

    def test_content_budget_truncates(self) -> None:
        result = decoded(
            tools.read_channel_impl(
                {"channel_id_or_url": CHANNEL_ID},
                FakeFetcher(messages=[{"id": "1", "content": "x" * 201}]),
                {"DISCORD_TOOLS_MAX_CHARS": "200"},
            )
        )

        self.assertTrue(result["data"]["truncated"])
        self.assertEqual(len(result["data"]["messages"][0]["content"]), 200)

    def test_live_handler_reports_missing_token_in_band(self) -> None:
        old = dict(tools.os.environ)
        try:
            tools.os.environ.clear()
            result = decoded(tools.discord_read_channel({"channel_id_or_url": CHANNEL_ID}))
        finally:
            tools.os.environ.clear()
            tools.os.environ.update(old)

        self.assertFalse(result["success"])
        self.assertIn("DISCORD_TOKEN", result["error"])


if __name__ == "__main__":
    unittest.main()
