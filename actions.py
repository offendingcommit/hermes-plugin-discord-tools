"""Channel-scoped Discord actions: react, list this server's emoji, send an embed.

Every action works only where the bot is talking right now. The channel, server
and triggering message come from the Hermes session (``HERMES_SESSION_*``, which
the gateway binds per turn), never from model arguments, so a model cannot aim
a reaction or an embed at another channel. These tools join Hermes' own
``discord`` toolset, so a profile gets them only where its config already turns
that toolset on.

The pure pieces (``current_scope``, ``parse_emoji``, ``resolve_emoji``,
``build_embed``, ``TurnBudget``) do no I/O. Live Discord calls are isolated in
``DiscordLiveActions``.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from hermes_plugin_kit import arg, int_arg, str_arg, tool

from . import schemas
from .tools import (
    SNOWFLAKE_RE,
    DiscordLiveFetcher,
    _allowed_guilds,
    _clamp,
    _err,
    _guard_guild,
    _ok,
    _parse_message_ref,
    _run_async,
    logger,
)

Lookup = Callable[[str], str]

EMOJI_NAME = r"[A-Za-z0-9_]{2,32}"
CUSTOM_TAG_RE = re.compile(rf"^<(?P<animated>a)?:(?P<name>{EMOJI_NAME}):(?P<id>\d{{15,25}})>$")
NAME_ID_RE = re.compile(rf"^(?P<name>{EMOJI_NAME}):(?P<id>\d{{15,25}})$")
COLON_NAME_RE = re.compile(rf"^:(?P<name>{EMOJI_NAME}):$")
BARE_NAME_RE = re.compile(rf"^(?P<name>{EMOJI_NAME})$")
HEX_COLOUR_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
# Longest Unicode emoji sequences (families, flags with modifiers) stay under this.
MAX_UNICODE_EMOJI_CODEPOINTS = 10
CRON_TRUE = {"1", "true", "yes", "on"}


class Refusal(str):
    """A reason an action will not run. A ``str`` so it drops into ``_err``."""


class MessageNotFound(Exception):
    def __init__(self, channel_id: str, message_id: str) -> None:
        super().__init__(f"message {message_id} not in channel {channel_id}")
        self.channel_id = channel_id
        self.message_id = message_id


@dataclass(frozen=True)
class ChannelScope:
    guild_id: str | None
    channel_id: str
    message_id: str | None
    parent_channel_id: str | None


@dataclass(frozen=True)
class EmojiRef:
    unicode: str | None = None
    name: str | None = None
    id: str | None = None


class ActionClient(Protocol):
    def list_emojis(self, guild_id: str) -> list[dict[str, Any]]:
        ...

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        """Raise ``MessageNotFound`` when the message is not in that channel."""
        ...

    def send_embed(self, channel_id: str, embed: dict[str, Any]) -> str:
        """Send one embed; return the new message id."""
        ...


# -- session scope -----------------------------------------------------------


def session_lookup(environ: Mapping[str, str] | None = None) -> Lookup:
    """Read session vars the way Hermes tools do.

    With an explicit mapping, read that. Otherwise use Hermes'
    ``get_session_env`` (task-local ContextVars, falling back to the process
    env), or the process env when running outside Hermes.
    """
    if environ is not None:
        return lambda name: str(environ.get(name, "") or "")
    try:
        from gateway.session_context import get_session_env
    except ImportError:
        return lambda name: os.environ.get(name, "")
    return lambda name: get_session_env(name, "")


def _snowflake(value: str) -> str | None:
    text = (value or "").strip()
    return text if SNOWFLAKE_RE.match(text) else None


def current_scope(lookup: Lookup) -> ChannelScope | Refusal:
    if lookup("HERMES_SESSION_PLATFORM") != "discord":
        return Refusal("This only works while replying in a Discord channel.")
    if lookup("HERMES_CRON_SESSION").strip().lower() in CRON_TRUE:
        return Refusal("This doesn't run in a scheduled job; there is no channel being replied in.")
    channel_id = _snowflake(lookup("HERMES_SESSION_CHAT_ID"))
    if not channel_id:
        return Refusal("The current Discord channel is unknown.")
    return ChannelScope(
        guild_id=_snowflake(lookup("HERMES_SESSION_SCOPE_ID")),
        channel_id=channel_id,
        message_id=_snowflake(lookup("HERMES_SESSION_MESSAGE_ID")),
        parent_channel_id=_snowflake(lookup("HERMES_SESSION_PARENT_CHAT_ID")),
    )


def _scope_or_refusal(lookup: Lookup, env: Mapping[str, str]) -> ChannelScope | Refusal:
    scope = current_scope(lookup)
    if isinstance(scope, Refusal):
        return scope
    guard = _guard_guild(scope.guild_id, _allowed_guilds(dict(env)))
    return Refusal(guard) if guard else scope


# -- emoji -------------------------------------------------------------------


def _looks_like_unicode_emoji(text: str) -> bool:
    if len(text) > MAX_UNICODE_EMOJI_CODEPOINTS:
        return False
    if any(ch.isspace() or ch in "<>@:`" or (ch.isascii() and ch.isalpha()) for ch in text):
        return False
    return any(unicodedata.category(ch) in ("So", "Me") for ch in text)


def parse_emoji(value: Any) -> EmojiRef | None:
    """Parse what a model wrote into a Unicode emoji or a custom-emoji reference."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for pattern in (CUSTOM_TAG_RE, NAME_ID_RE):
        match = pattern.match(text)
        if match:
            return EmojiRef(name=match.group("name"), id=match.group("id"))
    for pattern in (COLON_NAME_RE, BARE_NAME_RE):
        match = pattern.match(text)
        if match:
            return EmojiRef(name=match.group("name"))
    if _looks_like_unicode_emoji(text):
        return EmojiRef(unicode=text)
    return None


def _usable(entry: Mapping[str, Any]) -> bool:
    # Emoji lost with a boost tier are unavailable; role-locked ones may not be
    # usable by the bot, so leave them out rather than fail at Discord.
    return entry.get("available", True) is not False and not entry.get("roles")


def resolve_emoji(ref: EmojiRef, palette: list[Mapping[str, Any]] | None) -> str | Refusal:
    """The string Discord's reaction endpoint takes, or why it can't be used.

    Custom emoji must come from this server's own palette.
    """
    if ref.unicode:
        return ref.unicode
    if palette is None:
        return Refusal("Custom server emoji only work in a server channel.")
    if ref.id:
        matches = [e for e in palette if str(e.get("id")) == ref.id]
    else:
        matches = [e for e in palette if e.get("name") == ref.name]
        if not matches:
            wanted = (ref.name or "").lower()
            matches = [e for e in palette if str(e.get("name", "")).lower() == wanted]
            if len(matches) > 1:
                names = ", ".join(sorted(str(e.get("name")) for e in matches))
                return Refusal(f"More than one server emoji matches {ref.name!r}: {names}.")
    if not matches:
        return Refusal("That emoji isn't one of this server's emoji.")
    entry = matches[0]
    if not _usable(entry):
        return Refusal(f"The server emoji {entry.get('name')!r} isn't usable by the bot right now.")
    return f"{entry['name']}:{entry['id']}"


def emoji_usage(entry: Mapping[str, Any]) -> str:
    prefix = "a" if entry.get("animated") else ""
    return f"<{prefix}:{entry['name']}:{entry['id']}>"


# -- embeds ------------------------------------------------------------------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _https(value: Any) -> str | None | Refusal:
    text = _text(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return Refusal("Embed links and images must be https:// URLs.")
    return text


def _colour(value: Any) -> int | None | Refusal:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, float):
        return Refusal("color must be a hex colour like #FF8800.")
    if isinstance(value, int):
        return value if 0 <= value <= 0xFFFFFF else Refusal("color must be between 0 and 0xFFFFFF.")
    match = HEX_COLOUR_RE.match(_text(value))
    if not match:
        return Refusal("color must be a hex colour like #FF8800.")
    return int(match.group(1), 16)


def build_embed(args: Mapping[str, Any]) -> dict[str, Any] | Refusal:
    """A Discord embed object from tool arguments, held to Discord's limits."""
    limits = schemas.EMBED_LIMITS
    title = _text(args.get("title"))
    description = _text(args.get("description"))
    footer = _text(args.get("footer"))
    if not title and not description:
        return Refusal("An embed needs a title or a description.")
    for name, value in (("title", title), ("description", description), ("footer", footer)):
        if len(value) > limits[name]:
            return Refusal(f"Embed {name} is over Discord's {limits[name]}-character limit.")

    raw_fields = args.get("fields")
    if raw_fields is None:
        raw_fields = []
    if not isinstance(raw_fields, list):
        return Refusal("fields must be a list of {name, value, inline}.")
    if len(raw_fields) > limits["fields"]:
        return Refusal(f"An embed holds at most {limits['fields']} fields.")
    fields: list[dict[str, Any]] = []
    for raw in raw_fields:
        if not isinstance(raw, Mapping):
            return Refusal("Each field needs a name and a value.")
        name, value, inline = _text(raw.get("name")), _text(raw.get("value")), raw.get("inline", False)
        if not name or not value:
            return Refusal("Each field needs a name and a value.")
        if len(name) > limits["field_name"]:
            return Refusal(f"A field name is over Discord's {limits['field_name']}-character limit.")
        if len(value) > limits["field_value"]:
            return Refusal(f"A field value is over Discord's {limits['field_value']}-character limit.")
        if not isinstance(inline, bool):
            return Refusal("A field's inline must be true or false.")
        fields.append({"name": name, "value": value, "inline": inline})

    total = len(title) + len(description) + len(footer) + sum(len(f["name"]) + len(f["value"]) for f in fields)
    if total > limits["total"]:
        return Refusal(f"The embed's text adds up to more than Discord's {limits['total']}-character limit.")

    links: dict[str, str | None] = {}
    for key in ("url", "image_url", "thumbnail_url"):
        link = _https(args.get(key))
        if isinstance(link, Refusal):
            return link
        links[key] = link
    colour = _colour(args.get("color"))
    if isinstance(colour, Refusal):
        return colour

    embed: dict[str, Any] = {}
    if title:
        embed["title"] = title
    if description:
        embed["description"] = description
    if links["url"]:
        embed["url"] = links["url"]
    if colour is not None:
        embed["color"] = colour
    if fields:
        embed["fields"] = fields
    if footer:
        embed["footer"] = {"text": footer}
    if links["image_url"]:
        embed["image"] = {"url": links["image_url"]}
    if links["thumbnail_url"]:
        embed["thumbnail"] = {"url": links["thumbnail_url"]}
    return embed


# -- per-message budget ------------------------------------------------------


class TurnBudget:
    """How many writes of each kind one incoming message may still cause."""

    def __init__(self, limits: Mapping[str, int], remember: int = schemas.TURN_BUDGET_REMEMBER) -> None:
        self._limits = dict(limits)
        self._remember = remember
        self._spent: OrderedDict[tuple, Counter] = OrderedDict()
        self._lock = threading.Lock()

    def spend(self, kind: str, key: tuple) -> bool:
        with self._lock:
            spent = self._spent.get(key)
            if spent is None:
                spent = self._spent[key] = Counter()
                while len(self._spent) > self._remember:
                    self._spent.popitem(last=False)
            self._spent.move_to_end(key)
            if spent[kind] >= self._limits.get(kind, 0):
                return False
            spent[kind] += 1
            return True

    def refund(self, kind: str, key: tuple) -> None:
        with self._lock:
            spent = self._spent.get(key)
            if spent and spent[kind] > 0:
                spent[kind] -= 1


_BUDGET = TurnBudget(schemas.TURN_BUDGET)


# -- live error mapping ------------------------------------------------------

_PERMISSION_FOR = {
    "react": "Add Reactions (and Read Message History)",
    "embed": "Send Messages and Embed Links",
    "emojis": "View Channel",
}


def is_not_found(exc: BaseException) -> bool:
    try:
        import discord
    except ImportError:  # pragma: no cover - discord.py is a runtime dependency
        return False
    return isinstance(exc, discord.NotFound)


def describe_discord_error(exc: BaseException, kind: str) -> str:
    try:
        import discord
    except ImportError:  # pragma: no cover
        discord = None  # type: ignore[assignment]
    if discord is not None:
        if isinstance(exc, discord.Forbidden):
            return f"The bot is missing a Discord permission here: {_PERMISSION_FOR[kind]}."
        if isinstance(exc, discord.NotFound):
            return "Discord couldn't find that message or channel."
        if isinstance(exc, discord.HTTPException) and getattr(exc, "code", 0) == 10014:
            return "Discord doesn't know that emoji."
    if isinstance(exc, TimeoutError):
        return "Discord didn't answer in time."
    return f"Discord request failed: {type(exc).__name__}"


# -- tool impls --------------------------------------------------------------


def list_emojis_impl(
    args: Mapping[str, Any], client: ActionClient, lookup: Lookup, env: Mapping[str, str]
) -> str:
    scope = _scope_or_refusal(lookup, env)
    if isinstance(scope, Refusal):
        return _err(scope)
    if not scope.guild_id:
        return _err("Server emoji only exist in a server channel, not here.")
    try:
        palette = client.list_emojis(scope.guild_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("discord-tools: emoji list failed in guild %s: %s", scope.guild_id, type(exc).__name__)
        return _err(describe_discord_error(exc, "emojis"))
    query = _text((args or {}).get("query")).lower()
    limit = _clamp((args or {}).get("limit"), schemas.DEFAULT_EMOJI_LIST, 1, schemas.MAX_EMOJI_LIST)
    matching = [e for e in palette if _usable(e) and query in str(e.get("name", "")).lower()]
    shown = [
        {"name": e["name"], "id": str(e["id"]), "animated": bool(e.get("animated")), "usage": emoji_usage(e)}
        for e in matching[:limit]
    ]
    return _ok(guild_id=scope.guild_id, emojis=shown, count=len(matching), truncated=len(matching) > limit)


def _reaction_target(args: Mapping[str, Any], scope: ChannelScope) -> tuple[str, list[str]] | Refusal:
    raw = _text(args.get("message_id"))
    if not raw:
        if not scope.message_id:
            return Refusal("There is no message here to react to; pass message_id.")
        target, named_channel = scope.message_id, None
    else:
        ref = _parse_message_ref(raw, scope.channel_id)
        if ref is None or not ref.message_id:
            return Refusal("message_id must be a message ID or link from this channel.")
        target, named_channel = ref.message_id, ref.channel_id
    channels = [scope.channel_id]
    # An auto-created thread answers a message that sits in its parent channel.
    if target == scope.message_id and scope.parent_channel_id and scope.parent_channel_id != scope.channel_id:
        channels.append(scope.parent_channel_id)
    if named_channel and named_channel not in channels:
        return Refusal("You can only react to messages in this channel.")
    return target, channels


def react_impl(
    args: Mapping[str, Any],
    client: ActionClient,
    lookup: Lookup,
    env: Mapping[str, str],
    budget: TurnBudget = _BUDGET,
) -> str:
    args = args or {}
    scope = _scope_or_refusal(lookup, env)
    if isinstance(scope, Refusal):
        return _err(scope)
    ref = parse_emoji(args.get("emoji"))
    if ref is None:
        return _err("emoji must be one emoji, like 🔥, or a server emoji, like :name: or <:name:id>.")
    target = _reaction_target(args, scope)
    if isinstance(target, Refusal):
        return _err(target)
    message_id, channels = target

    palette = None
    if not ref.unicode and scope.guild_id:
        try:
            palette = client.list_emojis(scope.guild_id)
        except Exception as exc:  # noqa: BLE001
            return _err(describe_discord_error(exc, "emojis"))
    emoji = resolve_emoji(ref, palette)
    if isinstance(emoji, Refusal):
        return _err(emoji)

    key = (scope.channel_id, scope.message_id)
    if not budget.spend("react", key):
        return _err(f"Already reacted {schemas.TURN_BUDGET['react']} times for this message.")
    for channel_id in channels:
        try:
            client.add_reaction(channel_id, message_id, emoji)
        except MessageNotFound:
            continue
        except Exception as exc:  # noqa: BLE001
            budget.refund("react", key)
            logger.warning("discord-tools: reaction failed in %s: %s", channel_id, type(exc).__name__)
            return _err(describe_discord_error(exc, "react"))
        logger.info("discord-tools: reacted %s on %s/%s", emoji, channel_id, message_id)
        return _ok(channel_id=channel_id, message_id=message_id, emoji=emoji)
    budget.refund("react", key)
    return _err("That message isn't in this channel.")


def send_embed_impl(
    args: Mapping[str, Any],
    client: ActionClient,
    lookup: Lookup,
    env: Mapping[str, str],
    budget: TurnBudget = _BUDGET,
) -> str:
    scope = _scope_or_refusal(lookup, env)
    if isinstance(scope, Refusal):
        return _err(scope)
    embed = build_embed(args or {})
    if isinstance(embed, Refusal):
        return _err(embed)
    key = (scope.channel_id, scope.message_id)
    if not budget.spend("embed", key):
        return _err(f"Already sent {schemas.TURN_BUDGET['embed']} embeds for this message.")
    try:
        message_id = client.send_embed(scope.channel_id, embed)
    except Exception as exc:  # noqa: BLE001
        budget.refund("embed", key)
        logger.warning("discord-tools: embed failed in %s: %s", scope.channel_id, type(exc).__name__)
        return _err(describe_discord_error(exc, "embed"))
    logger.info("discord-tools: sent embed %s in %s", message_id, scope.channel_id)
    return _ok(channel_id=scope.channel_id, message_id=str(message_id))


# -- live client -------------------------------------------------------------


class DiscordLiveActions(DiscordLiveFetcher):
    """REST-only Discord client for the three actions; reuses the fetcher's login."""

    def list_emojis(self, guild_id: str) -> list[dict[str, Any]]:
        async def _operation(client: Any, _discord: Any) -> list[dict[str, Any]]:
            raw = await client.http.get_all_custom_emojis(int(guild_id))
            return [
                {
                    "id": str(e.get("id")),
                    "name": e.get("name"),
                    "animated": bool(e.get("animated")),
                    "available": e.get("available", True),
                    "roles": [str(r) for r in e.get("roles") or []],
                }
                for e in raw
                if e.get("id") and e.get("name")
            ]

        return _run_async(self._with_client(_operation))

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        async def _operation(client: Any, discord: Any) -> None:
            try:
                await client.http.add_reaction(int(channel_id), int(message_id), emoji)
            except discord.NotFound as exc:
                if getattr(exc, "code", 0) == 10008:  # Unknown Message
                    raise MessageNotFound(channel_id, message_id) from exc
                raise

        _run_async(self._with_client(_operation))

    def send_embed(self, channel_id: str, embed: dict[str, Any]) -> str:
        async def _operation(client: Any, discord: Any) -> str:
            channel = client.get_partial_messageable(int(channel_id))
            message = await channel.send(
                embed=discord.Embed.from_dict(embed),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return str(message.id)

        return _run_async(self._with_client(_operation))


def _live_actions(env: Mapping[str, str]) -> DiscordLiveActions | str:
    token = env.get("DISCORD_BOT_TOKEN") or env.get("DISCORD_TOKEN")
    if not token:
        return "DISCORD_BOT_TOKEN is required for Discord actions"
    try:
        timeout = float(env.get("DISCORD_TOOLS_TIMEOUT_SECONDS", schemas.DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = schemas.DEFAULT_TIMEOUT_SECONDS
    return DiscordLiveActions(token=token, timeout_seconds=timeout)


def _run(impl: Callable[..., str], args: Mapping[str, Any]) -> str:
    lookup = session_lookup()
    scope = _scope_or_refusal(lookup, os.environ)
    if isinstance(scope, Refusal):
        return _err(scope)
    client = _live_actions(os.environ)
    if isinstance(client, str):
        return _err(client)
    return impl(args or {}, client, lookup, os.environ)


@tool(
    toolset="discord",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "List this Discord server's own custom emoji you can react with. Works only "
        "in the server you are replying in. Each entry's usage string can be passed "
        "to discord_react."
    ),
    params={
        "query": str_arg("Optional part of an emoji name to filter by."),
        "limit": int_arg(
            f"Emoji to return, capped at {schemas.MAX_EMOJI_LIST}.",
            minimum=1,
            maximum=schemas.MAX_EMOJI_LIST,
        ),
    },
)
def discord_list_emojis(args: dict[str, Any], **_kwargs: Any) -> str:
    return _run(list_emojis_impl, args)


@tool(
    toolset="discord",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "React with one emoji to the message you are replying to, or to another "
        "message in this same channel. Takes any standard emoji, or one of this "
        "server's emoji as :name: or <:name:id>."
    ),
    params={
        "emoji": str_arg("One emoji, like 🔥, or a server emoji like :name:.", required=True, example="🔥"),
        "message_id": str_arg(
            "Optional message ID or link in this channel. Leave out to react to the message you are replying to."
        ),
    },
)
def discord_react(args: dict[str, Any], **_kwargs: Any) -> str:
    return _run(react_impl, args)


@tool(
    toolset="discord",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "Post one embed card in the channel you are replying in. Use for a tidy "
        "card such as a now-playing note or a schedule, not for ordinary replies. "
        "It never mentions or pings anyone."
    ),
    params={
        "title": str_arg(f"Card title, up to {schemas.EMBED_LIMITS['title']} characters."),
        "description": str_arg(f"Card body, up to {schemas.EMBED_LIMITS['description']} characters."),
        "url": str_arg("Optional https link for the title."),
        "color": str_arg("Optional hex colour for the side bar, like #FF8800."),
        "fields": arg(
            "array",
            f"Optional fields, at most {schemas.EMBED_LIMITS['fields']}.",
            maxItems=schemas.EMBED_LIMITS["fields"],
            items={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "inline": {"type": "boolean"},
                },
                "required": ["name", "value"],
            },
        ),
        "footer": str_arg("Optional small footer text."),
        "image_url": str_arg("Optional https image shown large."),
        "thumbnail_url": str_arg("Optional https image shown small in the corner."),
    },
)
def discord_send_embed(args: dict[str, Any], **_kwargs: Any) -> str:
    return _run(send_embed_impl, args)
