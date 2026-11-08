"""Channel-scoped Discord actions: react, list the server's emoji, send an embed.

The pure pieces (session scope, emoji parsing and resolution, embed building,
the per-message budget) are exercised directly. The tool impls run against
``RecordingClient``, an in-memory ``ActionClient`` that holds messages by
channel so "is this message in this channel" is answered the way Discord
answers it: a 404 for the wrong channel. Embeds are round-tripped through
discord.py's own ``Embed`` type, the one the live client sends.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from pathlib import Path

import discord

from hermes_plugin_loader import load_plugin_module

plugin = load_plugin_module()
actions = plugin.actions
schemas = plugin.schemas

GUILD = "111111111111111111"
CHANNEL = "222222222222222222"
PARENT = "444444444444444444"
TRIGGER = "333333333333333333"
OTHER_MESSAGE = "555555555555555555"
ELSEWHERE = "666666666666666666"

PALETTE = [
    {"id": "900000000000000001", "name": "dsl_hype", "animated": False, "available": True, "roles": []},
    {"id": "900000000000000002", "name": "spin", "animated": True, "available": True, "roles": []},
    {"id": "900000000000000003", "name": "lost_boost", "animated": False, "available": False, "roles": []},
    {"id": "900000000000000004", "name": "mods_only", "animated": False, "available": True, "roles": ["7"]},
    {"id": "900000000000000005", "name": "Tea", "animated": False, "available": True, "roles": []},
    {"id": "900000000000000006", "name": "tea", "animated": False, "available": True, "roles": []},
]


def session(**overrides: str):
    values = {
        "HERMES_SESSION_PLATFORM": "discord",
        "HERMES_SESSION_CHAT_ID": CHANNEL,
        "HERMES_SESSION_SCOPE_ID": GUILD,
        "HERMES_SESSION_MESSAGE_ID": TRIGGER,
        "HERMES_SESSION_PARENT_CHAT_ID": "",
        "HERMES_CRON_SESSION": "",
    }
    values.update(overrides)
    return lambda name: values.get(name, "")


class RecordingClient:
    """In-memory ActionClient: messages live in channels, like on Discord."""

    def __init__(self, messages: dict[str, str] | None = None, palette: list[dict] | None = None) -> None:
        self.messages = {TRIGGER: CHANNEL, OTHER_MESSAGE: CHANNEL} if messages is None else messages
        self.palette = PALETTE if palette is None else palette
        self.reactions: list[tuple[str, str, str]] = []
        self.attempts: list[tuple[str, str]] = []
        self.embeds: list[tuple[str, dict]] = []
        self.palette_reads: list[str] = []

    def list_emojis(self, guild_id: str) -> list[dict]:
        self.palette_reads.append(guild_id)
        return [dict(e) for e in self.palette]

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        self.attempts.append((channel_id, message_id))
        if self.messages.get(message_id) != channel_id:
            raise actions.MessageNotFound(channel_id, message_id)
        self.reactions.append((channel_id, message_id, emoji))

    def send_embed(self, channel_id: str, embed: dict) -> str:
        # The live client builds discord.Embed.from_dict(embed); do the same so
        # a shape discord.py would drop or reject fails here too.
        sent = discord.Embed.from_dict(embed).to_dict()
        self.embeds.append((channel_id, sent))
        return "777777777777777777"


def decoded(raw: str) -> dict:
    return json.loads(raw)


class ScopeTests(unittest.TestCase):
    def test_reads_current_discord_channel(self) -> None:
        scope = actions.current_scope(session(HERMES_SESSION_PARENT_CHAT_ID=PARENT))
        self.assertEqual(scope, actions.ChannelScope(GUILD, CHANNEL, TRIGGER, PARENT))

    def test_refuses_other_platforms(self) -> None:
        for platform in ("telegram", "cli", "", "Discord "):
            with self.subTest(platform=platform):
                self.assertIsInstance(actions.current_scope(session(HERMES_SESSION_PLATFORM=platform)), str)

    def test_refuses_cron_runs(self) -> None:
        for flag in ("1", "true", "yes"):
            with self.subTest(flag=flag):
                self.assertIn("scheduled", actions.current_scope(session(HERMES_CRON_SESSION=flag)))
        self.assertIsInstance(actions.current_scope(session(HERMES_CRON_SESSION="0")), actions.ChannelScope)

    def test_refuses_missing_or_malformed_channel(self) -> None:
        for chat in ("", "general", "12345", f"{CHANNEL}x"):
            with self.subTest(chat=chat):
                self.assertIsInstance(actions.current_scope(session(HERMES_SESSION_CHAT_ID=chat)), str)

    def test_malformed_optional_ids_collapse_to_none(self) -> None:
        scope = actions.current_scope(
            session(HERMES_SESSION_SCOPE_ID="dm", HERMES_SESSION_MESSAGE_ID="", HERMES_SESSION_PARENT_CHAT_ID="x")
        )
        self.assertEqual(scope, actions.ChannelScope(None, CHANNEL, None, None))

    def test_session_lookup_reads_an_explicit_mapping(self) -> None:
        lookup = actions.session_lookup({"HERMES_SESSION_PLATFORM": "discord"})
        self.assertEqual(lookup("HERMES_SESSION_PLATFORM"), "discord")
        self.assertEqual(lookup("HERMES_SESSION_CHAT_ID"), "")


class EmojiParseTests(unittest.TestCase):
    def test_unicode_emoji(self) -> None:
        for text in ("🔥", "👍🏽", "1️⃣", "🏳️‍🌈", "🇺🇸", "❤️", "  🎉 "):
            with self.subTest(text=text):
                ref = actions.parse_emoji(text)
                self.assertEqual(ref, actions.EmojiRef(unicode=text.strip()))

    def test_custom_emoji_forms(self) -> None:
        cases = {
            "<:dsl_hype:900000000000000001>": actions.EmojiRef(name="dsl_hype", id="900000000000000001"),
            "<a:spin:900000000000000002>": actions.EmojiRef(name="spin", id="900000000000000002"),
            "dsl_hype:900000000000000001": actions.EmojiRef(name="dsl_hype", id="900000000000000001"),
            ":dsl_hype:": actions.EmojiRef(name="dsl_hype"),
            "dsl_hype": actions.EmojiRef(name="dsl_hype"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(actions.parse_emoji(text), expected)

    def test_rejects_text_that_is_not_an_emoji(self) -> None:
        for text in ("", "   ", "x", "hello world", "🔥🔥 lit", "<:bad name:1>", "@everyone",
                     "<@123456789012345678>", "a" * 33, "🔥lit", "ok👍", "🔥" * 20, None, 42):
            with self.subTest(text=text):
                self.assertIsNone(actions.parse_emoji(text))


class EmojiResolveTests(unittest.TestCase):
    def test_unicode_needs_no_palette(self) -> None:
        self.assertEqual(actions.resolve_emoji(actions.EmojiRef(unicode="🔥"), None), "🔥")

    def test_custom_by_id_and_by_name(self) -> None:
        by_id = actions.resolve_emoji(actions.EmojiRef(name="whatever", id="900000000000000002"), PALETTE)
        by_name = actions.resolve_emoji(actions.EmojiRef(name="dsl_hype"), PALETTE)
        self.assertEqual(by_id, "spin:900000000000000002")
        self.assertEqual(by_name, "dsl_hype:900000000000000001")

    def test_exact_name_wins_over_case_insensitive(self) -> None:
        self.assertEqual(actions.resolve_emoji(actions.EmojiRef(name="Tea"), PALETTE), "Tea:900000000000000005")
        self.assertEqual(actions.resolve_emoji(actions.EmojiRef(name="tea"), PALETTE), "tea:900000000000000006")

    def test_case_insensitive_only_when_unique(self) -> None:
        self.assertEqual(
            actions.resolve_emoji(actions.EmojiRef(name="DSL_HYPE"), PALETTE), "dsl_hype:900000000000000001"
        )
        self.assertIsInstance(actions.resolve_emoji(actions.EmojiRef(name="TEA"), PALETTE), actions.Refusal)

    def test_refuses_emoji_from_other_servers_and_unusable_ones(self) -> None:
        for ref in (
            actions.EmojiRef(name="foreign", id="912345678901234567"),
            actions.EmojiRef(name="lost_boost"),
            actions.EmojiRef(name="mods_only"),
            actions.EmojiRef(name="nope"),
        ):
            with self.subTest(ref=ref):
                self.assertIsInstance(actions.resolve_emoji(ref, PALETTE), actions.Refusal)

    def test_custom_without_a_server_is_refused(self) -> None:
        self.assertIsInstance(actions.resolve_emoji(actions.EmojiRef(name="dsl_hype"), None), actions.Refusal)


class EmbedBuildTests(unittest.TestCase):
    def test_builds_discord_shape_that_discord_py_round_trips(self) -> None:
        embed = actions.build_embed(
            {
                "title": "Tonight on Amber",
                "description": "New hour at 9.",
                "url": "https://example.com/amber",
                "color": "#FF8800",
                "fields": [{"name": "Host", "value": "Amber", "inline": True}],
                "footer": "Dopamine Sound Labs",
                "image_url": "https://example.com/a.png",
                "thumbnail_url": "https://example.com/t.png",
            }
        )
        self.assertIsInstance(embed, dict)
        self.assertEqual(embed["color"], 0xFF8800)
        self.assertEqual(embed["footer"], {"text": "Dopamine Sound Labs"})
        rebuilt = discord.Embed.from_dict(embed).to_dict()
        for key, value in embed.items():
            self.assertEqual(rebuilt[key], value, key)

    def test_colour_forms(self) -> None:
        for given, expected in (("ff8800", 0xFF8800), ("#00ff00", 0x00FF00), (255, 255), (0, 0), ("", None), (None, None)):
            with self.subTest(given=given):
                embed = actions.build_embed({"title": "t", "color": given})
                self.assertEqual(embed.get("color"), expected)
        for bad in ("orange", "#12345", -1, 0x1000000, True, 1.5):
            with self.subTest(bad=bad):
                self.assertIsInstance(actions.build_embed({"title": "t", "color": bad}), actions.Refusal)

    def test_needs_title_or_description(self) -> None:
        self.assertIsInstance(actions.build_embed({}), actions.Refusal)
        self.assertIsInstance(actions.build_embed({"title": "  ", "description": ""}), actions.Refusal)
        self.assertIsInstance(actions.build_embed({"description": "only text"}), dict)

    def test_discord_limits_hold_at_the_boundary(self) -> None:
        limits = schemas.EMBED_LIMITS
        at_limit = {
            "title": "t" * limits["title"],
            "fields": [{"name": "n", "value": "v"}] * limits["fields"],
        }
        self.assertIsInstance(actions.build_embed(at_limit), dict)
        for key, args in (
            ("title", {"title": "t" * (limits["title"] + 1)}),
            ("description", {"description": "d" * (limits["description"] + 1)}),
            ("footer", {"title": "t", "footer": "f" * (limits["footer"] + 1)}),
            ("fields", {"title": "t", "fields": [{"name": "n", "value": "v"}] * (limits["fields"] + 1)}),
            ("field_name", {"title": "t", "fields": [{"name": "n" * (limits["field_name"] + 1), "value": "v"}]}),
            ("field_value", {"title": "t", "fields": [{"name": "n", "value": "v" * (limits["field_value"] + 1)}]}),
            ("total", {"description": "d" * limits["description"], "fields": [{"name": "n" * 256, "value": "v" * 1024}] * 2}),
        ):
            with self.subTest(limit=key):
                self.assertIsInstance(actions.build_embed(args), actions.Refusal)

    def test_total_counts_every_text_part(self) -> None:
        limits = schemas.EMBED_LIMITS
        description = "d" * limits["description"]
        # 1 + 4096 + 1 + (1 + 1024) + (1 + 876) == 6000: title, description,
        # footer, both field names and values all count toward the total.
        fields = [{"name": "n", "value": "v" * 1024}, {"name": "n", "value": "v" * 876}]
        exact = {"title": "t", "description": description, "footer": "f", "fields": fields}
        self.assertIsInstance(actions.build_embed(exact), dict)
        for grown in ("title", "footer"):
            with self.subTest(grown=grown):
                self.assertIsInstance(actions.build_embed({**exact, grown: exact[grown] * 2}), actions.Refusal)
        longer_name = [{"name": "nn", "value": "v" * 1024}, fields[1]]
        self.assertIsInstance(actions.build_embed({**exact, "fields": longer_name}), actions.Refusal)

    def test_fields_need_name_and_value(self) -> None:
        for field in ({"name": "", "value": "v"}, {"name": "n", "value": " "}, {"name": "n"}, "not a field"):
            with self.subTest(field=field):
                self.assertIsInstance(actions.build_embed({"title": "t", "fields": [field]}), actions.Refusal)
        self.assertIsInstance(actions.build_embed({"title": "t", "fields": "nope"}), actions.Refusal)

    def test_links_must_be_https(self) -> None:
        for key in ("url", "image_url", "thumbnail_url"):
            for bad in ("http://example.com/x", "javascript:alert(1)", "example.com", "https://"):
                with self.subTest(key=key, bad=bad):
                    self.assertIsInstance(actions.build_embed({"title": "t", key: bad}), actions.Refusal)

    def test_inline_defaults_false_and_must_be_bool(self) -> None:
        embed = actions.build_embed({"title": "t", "fields": [{"name": "n", "value": "v"}]})
        self.assertIs(embed["fields"][0]["inline"], False)
        self.assertIsInstance(
            actions.build_embed({"title": "t", "fields": [{"name": "n", "value": "v", "inline": "yes"}]}),
            actions.Refusal,
        )


class BudgetTests(unittest.TestCase):
    def test_spends_per_message_and_kind(self) -> None:
        budget = actions.TurnBudget({"react": 2, "embed": 1})
        key = (CHANNEL, TRIGGER)
        self.assertTrue(budget.spend("react", key))
        self.assertTrue(budget.spend("react", key))
        self.assertFalse(budget.spend("react", key))
        self.assertTrue(budget.spend("embed", key))
        self.assertFalse(budget.spend("embed", key))
        self.assertTrue(budget.spend("react", (CHANNEL, OTHER_MESSAGE)))

    def test_forgets_old_messages(self) -> None:
        budget = actions.TurnBudget({"react": 1}, remember=2)
        for message in ("1", "2", "3"):
            self.assertTrue(budget.spend("react", (CHANNEL, message)))
        self.assertTrue(budget.spend("react", (CHANNEL, "1")))
        self.assertFalse(budget.spend("react", (CHANNEL, "3")))

    def test_forgets_least_recently_used(self) -> None:
        budget = actions.TurnBudget({"react": 2}, remember=2)
        self.assertTrue(budget.spend("react", (CHANNEL, "1")))
        self.assertTrue(budget.spend("react", (CHANNEL, "2")))
        self.assertTrue(budget.spend("react", (CHANNEL, "1")))  # "1" is now the freshest
        self.assertTrue(budget.spend("react", (CHANNEL, "3")))  # so "2" is forgotten
        self.assertFalse(budget.spend("react", (CHANNEL, "1")))

    def test_no_message_shares_one_bucket(self) -> None:
        budget = actions.TurnBudget({"embed": 1})
        self.assertTrue(budget.spend("embed", (CHANNEL, None)))
        self.assertFalse(budget.spend("embed", (CHANNEL, None)))


class ListEmojisTests(unittest.TestCase):
    def test_lists_usable_palette_with_usage_strings(self) -> None:
        client = RecordingClient()
        result = decoded(actions.list_emojis_impl({}, client, session(), {}))
        self.assertTrue(result["success"])
        self.assertEqual(client.palette_reads, [GUILD])
        names = [e["name"] for e in result["data"]["emojis"]]
        self.assertEqual(names, ["dsl_hype", "spin", "Tea", "tea"])
        self.assertEqual(result["data"]["emojis"][1]["usage"], "<a:spin:900000000000000002>")
        self.assertEqual(result["data"]["emojis"][0]["usage"], "<:dsl_hype:900000000000000001>")
        self.assertEqual(result["data"]["count"], 4)
        self.assertFalse(result["data"]["truncated"])

    def test_query_and_limit(self) -> None:
        result = decoded(actions.list_emojis_impl({"query": "TEA", "limit": 1}, RecordingClient(), session(), {}))
        self.assertEqual([e["name"] for e in result["data"]["emojis"]], ["Tea"])
        self.assertEqual(result["data"]["count"], 2)
        self.assertTrue(result["data"]["truncated"])

    def test_needs_a_server(self) -> None:
        client = RecordingClient()
        result = decoded(actions.list_emojis_impl({}, client, session(HERMES_SESSION_SCOPE_ID=""), {}))
        self.assertFalse(result["success"])
        self.assertEqual(client.palette_reads, [])

    def test_respects_guild_allowlist(self) -> None:
        client = RecordingClient()
        env = {"DISCORD_TOOLS_ALLOWED_GUILDS": ELSEWHERE}
        self.assertFalse(decoded(actions.list_emojis_impl({}, client, session(), env))["success"])
        self.assertEqual(client.palette_reads, [])
        env = {"DISCORD_TOOLS_ALLOWED_GUILDS": f"{ELSEWHERE}, {GUILD}"}
        self.assertTrue(decoded(actions.list_emojis_impl({}, client, session(), env))["success"])

    def test_outside_discord_does_nothing(self) -> None:
        client = RecordingClient()
        result = decoded(actions.list_emojis_impl({}, client, session(HERMES_SESSION_PLATFORM="telegram"), {}))
        self.assertFalse(result["success"])
        self.assertEqual(client.palette_reads, [])


class ReactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = actions.TurnBudget(schemas.TURN_BUDGET)

    def react(self, args, client, lookup=None, env=None):
        return decoded(actions.react_impl(args, client, lookup or session(), env or {}, self.budget))

    def test_reacts_to_the_triggering_message_by_default(self) -> None:
        client = RecordingClient()
        result = self.react({"emoji": "🔥"}, client)
        self.assertTrue(result["success"], result)
        self.assertEqual(client.reactions, [(CHANNEL, TRIGGER, "🔥")])
        self.assertEqual(client.palette_reads, [], "unicode needs no palette read")

    def test_custom_emoji_resolves_through_this_servers_palette(self) -> None:
        client = RecordingClient()
        self.assertTrue(self.react({"emoji": ":dsl_hype:"}, client)["success"])
        self.assertEqual(client.reactions, [(CHANNEL, TRIGGER, "dsl_hype:900000000000000001")])
        self.assertEqual(client.palette_reads, [GUILD])

    def test_foreign_custom_emoji_is_refused_before_any_write(self) -> None:
        client = RecordingClient()
        self.assertFalse(self.react({"emoji": "<:foreign:912345678901234567>"}, client)["success"])
        self.assertEqual(client.reactions, [])

    def test_other_message_in_this_channel(self) -> None:
        client = RecordingClient()
        self.assertTrue(self.react({"emoji": "👍", "message_id": OTHER_MESSAGE}, client)["success"])
        self.assertTrue(
            self.react(
                {"emoji": "👍", "message_id": f"https://discord.com/channels/{GUILD}/{CHANNEL}/{OTHER_MESSAGE}"},
                RecordingClient(),
            )["success"]
        )
        self.assertEqual(client.reactions, [(CHANNEL, OTHER_MESSAGE, "👍")])

    def test_message_in_another_channel_is_refused(self) -> None:
        client = RecordingClient(messages={TRIGGER: CHANNEL, OTHER_MESSAGE: ELSEWHERE})
        by_id = self.react({"emoji": "👍", "message_id": OTHER_MESSAGE}, client)
        by_url = self.react(
            {"emoji": "👍", "message_id": f"https://discord.com/channels/{GUILD}/{ELSEWHERE}/{OTHER_MESSAGE}"},
            client,
        )
        self.assertFalse(by_id["success"])
        self.assertFalse(by_url["success"])
        self.assertEqual(client.reactions, [])
        # A link naming another channel is refused without asking Discord.
        self.assertEqual(client.attempts, [(CHANNEL, OTHER_MESSAGE)])

    def test_triggering_message_in_parent_of_auto_thread(self) -> None:
        client = RecordingClient(messages={TRIGGER: PARENT})
        result = self.react({"emoji": "✅"}, client, session(HERMES_SESSION_PARENT_CHAT_ID=PARENT))
        self.assertTrue(result["success"], result)
        self.assertEqual(client.reactions, [(PARENT, TRIGGER, "✅")])

    def test_parent_fallback_is_only_for_the_triggering_message(self) -> None:
        client = RecordingClient(messages={TRIGGER: CHANNEL, OTHER_MESSAGE: PARENT})
        result = self.react(
            {"emoji": "✅", "message_id": OTHER_MESSAGE}, client, session(HERMES_SESSION_PARENT_CHAT_ID=PARENT)
        )
        self.assertFalse(result["success"])
        self.assertEqual(client.reactions, [])

    def test_no_message_to_react_to(self) -> None:
        client = RecordingClient()
        self.assertFalse(self.react({"emoji": "🔥"}, client, session(HERMES_SESSION_MESSAGE_ID=""))["success"])
        self.assertFalse(self.react({"emoji": "🔥", "message_id": "not-an-id"}, client)["success"])
        self.assertEqual(client.reactions, [])

    def test_bad_emoji_and_platform_are_refused_before_any_write(self) -> None:
        client = RecordingClient()
        self.assertFalse(self.react({"emoji": "hello there"}, client)["success"])
        self.assertFalse(self.react({}, client)["success"])
        self.assertFalse(self.react({"emoji": "🔥"}, client, session(HERMES_SESSION_PLATFORM="telegram"))["success"])
        self.assertFalse(self.react({"emoji": "🔥"}, client, env={"DISCORD_TOOLS_ALLOWED_GUILDS": ELSEWHERE})["success"])
        self.assertEqual(client.reactions, [])

    def test_budget_caps_reactions_per_message(self) -> None:
        client = RecordingClient()
        cap = schemas.TURN_BUDGET["react"]
        outcomes = [self.react({"emoji": "🔥"}, client)["success"] for _ in range(cap + 1)]
        self.assertEqual(outcomes, [True] * cap + [False])
        self.assertEqual(len(client.reactions), cap)

    def test_refused_reaction_does_not_spend_budget(self) -> None:
        client = RecordingClient()
        for _ in range(schemas.TURN_BUDGET["react"] + 2):
            self.react({"emoji": "nope nope"}, client)
        self.assertTrue(self.react({"emoji": "🔥"}, client)["success"])

    def test_message_not_found_refunds_budget(self) -> None:
        client = RecordingClient(messages={TRIGGER: CHANNEL, OTHER_MESSAGE: ELSEWHERE})
        for _ in range(schemas.TURN_BUDGET["react"] + 1):
            self.assertFalse(self.react({"emoji": "🔥", "message_id": OTHER_MESSAGE}, client)["success"])
        self.assertTrue(self.react({"emoji": "🔥"}, client)["success"])


class SendEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = actions.TurnBudget(schemas.TURN_BUDGET)

    def send(self, args, client, lookup=None, env=None):
        return decoded(actions.send_embed_impl(args, client, lookup or session(), env or {}, self.budget))

    def test_sends_to_the_current_channel_only(self) -> None:
        client = RecordingClient()
        result = self.send({"title": "Now playing", "description": "Track one", "channel_id": ELSEWHERE}, client)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"], {"channel_id": CHANNEL, "message_id": "777777777777777777"})
        [(channel, sent)] = client.embeds
        self.assertEqual(channel, CHANNEL)
        self.assertEqual((sent["title"], sent["description"]), ("Now playing", "Track one"))

    def test_invalid_embed_is_refused_before_any_write(self) -> None:
        client = RecordingClient()
        self.assertFalse(self.send({"title": "t", "url": "http://insecure.example"}, client)["success"])
        self.assertFalse(self.send({"title": "t"}, client, session(HERMES_SESSION_PLATFORM="cli"))["success"])
        self.assertEqual(client.embeds, [])

    def test_discord_failure_is_reported_and_refunded(self) -> None:
        class Refusing(RecordingClient):
            def send_embed(self, channel_id: str, embed: dict) -> str:
                response = type("R", (), {"status": 403, "reason": "x"})()
                raise discord.Forbidden(response, {"code": 50013, "message": "x"})

        failing = Refusing()
        for _ in range(schemas.TURN_BUDGET["embed"] + 1):
            result = self.send({"title": "t"}, failing)
            self.assertFalse(result["success"])
            self.assertIn("Embed Links", result["error"])
        self.assertTrue(self.send({"title": "t"}, RecordingClient())["success"])

    def test_budget_caps_embeds_per_message(self) -> None:
        client = RecordingClient()
        cap = schemas.TURN_BUDGET["embed"]
        outcomes = [self.send({"title": "t"}, client)["success"] for _ in range(cap + 1)]
        self.assertEqual(outcomes, [True] * cap + [False])


class LiveErrorMappingTests(unittest.TestCase):
    """discord.py's own exceptions map to plain refusals naming the permission."""

    def _http_error(self, cls, status: int, code: int = 0):
        response = type("R", (), {"status": status, "reason": "x"})()
        return cls(response, {"code": code, "message": "x"})

    def test_forbidden_names_the_permission(self) -> None:
        err = self._http_error(discord.Forbidden, 403, 50013)
        self.assertIn("Add Reactions", actions.describe_discord_error(err, "react"))
        self.assertIn("Embed Links", actions.describe_discord_error(err, "embed"))

    def test_unknown_emoji(self) -> None:
        err = self._http_error(discord.HTTPException, 400, 10014)
        self.assertIn("emoji", actions.describe_discord_error(err, "react").lower())

    def test_not_found_becomes_message_not_found(self) -> None:
        err = self._http_error(discord.NotFound, 404, 10008)
        self.assertTrue(actions.is_not_found(err))
        self.assertFalse(actions.is_not_found(self._http_error(discord.Forbidden, 403)))


# ---------------------------------------------------------------------------
# Optional layer: the real Hermes session context, registry and toolsets.
# Runs when HERMES_AGENT_PATH points at a Hermes checkout; these three modules
# need only the standard library.
# ---------------------------------------------------------------------------


def _real_hermes():
    root = os.environ.get("HERMES_AGENT_PATH")
    if not root or not (Path(root) / "gateway" / "session_context.py").exists():
        return None
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import toolsets as real_toolsets
        from gateway import session_context
        from tools.registry import registry
        from tools.thread_context import propagate_context_to_thread
    except Exception:
        return None
    return session_context, registry, real_toolsets, propagate_context_to_thread


_HERMES = _real_hermes()
ACTION_TOOLS = {"discord_list_emojis", "discord_react", "discord_send_embed"}
READ_TOOLS = {"discord_read_channel", "discord_read_thread", "discord_get_message", "discord_read_story"}


class _RegistryCtx:
    """Forwards the plugin's register_tool calls to Hermes' real registry."""

    def __init__(self, registry) -> None:
        self.registry = registry
        self.names: list[str] = []

    def register_tool(self, **kwargs) -> None:
        self.registry.register(**kwargs)
        self.names.append(kwargs["name"])

    def register_hook(self, *_args) -> None:
        pass


@unittest.skipUnless(_HERMES is not None, "set HERMES_AGENT_PATH to a Hermes checkout")
class RealHermesActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_context, self.registry, self.toolsets, self.propagate = _HERMES  # type: ignore[misc]

    def bind(self, **values):
        self.session_context.set_session_vars(**values)
        # Back to "never bound" so later tests fall through to os.environ.
        self.addCleanup(self.session_context.reset_session_vars)

    def test_actions_join_hermes_discord_toolset_and_nothing_else(self) -> None:
        ctx = _RegistryCtx(self.registry)
        plugin.register(ctx)
        for name in ctx.names:
            self.addCleanup(self.registry.deregister, name)
        resolve = self.toolsets.resolve_toolset

        self.assertEqual(set(resolve("discord")), {"discord"} | ACTION_TOOLS)
        self.assertEqual(resolve("discord", include_registry=False), ["discord"])
        # `discord` is a core toolset, so Hermes never treats it as a plugin
        # toolset that defaults on; a profile must name it to get it.
        self.assertNotIn("discord", self.toolsets._get_plugin_toolset_names())
        self.assertTrue(READ_TOOLS <= set(resolve("messaging")))
        self.assertFalse(ACTION_TOOLS & set(resolve("messaging")))
        for composite in ("hermes-telegram", "hermes-cli", "hermes-api-server"):
            with self.subTest(composite=composite):
                self.assertFalse(ACTION_TOOLS & set(resolve(composite)))
        # No other static toolset carries the actions. (A profile whose config
        # names a bundle such as hermes-discord still gets them: Hermes maps the
        # bundle's `discord` tool back to the `discord` toolset, exactly as it
        # does for its own discord tool.)
        for composite in self.toolsets.TOOLSETS:
            if composite == "discord":
                continue
            with self.subTest(composite=composite):
                self.assertFalse(ACTION_TOOLS & set(resolve(composite)))
        self.assertTrue(ACTION_TOOLS <= set(resolve("all")))

    def test_scope_reads_the_session_the_gateway_binds(self) -> None:
        self.bind(platform="discord", chat_id=CHANNEL, scope_id=GUILD, message_id=TRIGGER, parent_chat_id=PARENT)
        scope = actions.current_scope(actions.session_lookup())
        self.assertEqual(scope, actions.ChannelScope(GUILD, CHANNEL, TRIGGER, PARENT))

    def test_scope_follows_the_turn_into_tool_worker_threads(self) -> None:
        self.bind(platform="discord", chat_id=CHANNEL, scope_id=GUILD, message_id=TRIGGER)
        seen: list = []
        worker = threading.Thread(target=self.propagate(lambda: seen.append(actions.current_scope(actions.session_lookup()))))
        worker.start()
        worker.join()
        self.assertEqual(seen, [actions.ChannelScope(GUILD, CHANNEL, TRIGGER, None)])

    def test_other_platforms_and_cron_are_refused(self) -> None:
        self.bind(platform="telegram", chat_id=CHANNEL)
        self.assertIsInstance(actions.current_scope(actions.session_lookup()), actions.Refusal)
        self.bind(platform="discord", chat_id=CHANNEL, cron_session="1")
        self.assertIsInstance(actions.current_scope(actions.session_lookup()), actions.Refusal)


if __name__ == "__main__":
    unittest.main()
