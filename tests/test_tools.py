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
        self.assertIn("DISCORD_BOT_TOKEN", result["error"])

    def test_live_fetcher_uses_gateway_bot_token(self) -> None:
        # Hermes' gateway loads the token as DISCORD_BOT_TOKEN — reads must reuse it.
        fetcher = tools._live_fetcher({"DISCORD_BOT_TOKEN": "bot-tok"})
        self.assertIsInstance(fetcher, tools.DiscordLiveFetcher)
        self.assertEqual(fetcher.token, "bot-tok")

    def test_live_fetcher_falls_back_to_discord_token_alias(self) -> None:
        fetcher = tools._live_fetcher({"DISCORD_TOKEN": "legacy-tok"})
        self.assertIsInstance(fetcher, tools.DiscordLiveFetcher)
        self.assertEqual(fetcher.token, "legacy-tok")

    def test_live_fetcher_prefers_bot_token_over_alias(self) -> None:
        fetcher = tools._live_fetcher({"DISCORD_BOT_TOKEN": "bot", "DISCORD_TOKEN": "alias"})
        self.assertEqual(fetcher.token, "bot")

    def test_live_fetcher_missing_token_returns_message(self) -> None:
        result = tools._live_fetcher({})
        self.assertIsInstance(result, str)
        self.assertIn("DISCORD_BOT_TOKEN", result)

    def test_read_story_uses_single_configured_thread(self) -> None:
        # No name needed when exactly one story is configured — survives an
        # empty/opaque tool schema because the only arg is optional.
        fetcher = FakeFetcher()
        result = decoded(
            tools.read_story_impl({}, fetcher, {"DISCORD_TOOLS_STORY_THREAD_ID": CHANNEL_ID})
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["kind"], "story")
        self.assertEqual(result["data"]["channel_id"], CHANNEL_ID)
        self.assertEqual(fetcher.calls[0][0], "read_channel")

    def test_read_story_resolves_by_name_and_alias(self) -> None:
        env = {
            "DISCORD_TOOLS_STORY_THREADS_JSON": json.dumps(
                [{"name": "House of Tea", "thread_id": CHANNEL_ID, "aliases": ["bea"]}]
            )
        }
        by_name = decoded(tools.read_story_impl({"name": "house of tea"}, FakeFetcher(), env))
        by_alias = decoded(tools.read_story_impl({"name": "Bea"}, FakeFetcher(), env))

        self.assertTrue(by_name["success"])
        self.assertEqual(by_name["data"]["story_name"], "House of Tea")
        self.assertTrue(by_alias["success"])

    def test_read_story_requires_name_when_multiple(self) -> None:
        env = {
            "DISCORD_TOOLS_STORY_THREADS_JSON": json.dumps(
                [
                    {"name": "House of Tea", "thread_id": CHANNEL_ID},
                    {"name": "Other", "thread_id": "999999999999999999"},
                ]
            )
        }
        result = decoded(tools.read_story_impl({}, FakeFetcher(), env))

        self.assertFalse(result["success"])
        self.assertIn("Multiple story threads", result["error"])

    def test_read_story_unknown_name_lists_available(self) -> None:
        env = {"DISCORD_TOOLS_STORY_THREAD_ID": CHANNEL_ID}
        result = decoded(tools.read_story_impl({"name": "nope"}, FakeFetcher(), env))

        self.assertFalse(result["success"])
        self.assertIn("No story thread named", result["error"])

    def test_read_story_none_configured(self) -> None:
        result = decoded(tools.read_story_impl({}, FakeFetcher(), {}))

        self.assertFalse(result["success"])
        self.assertIn("No story threads are configured", result["error"])


if __name__ == "__main__":
    unittest.main()
