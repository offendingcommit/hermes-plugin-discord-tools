"""Read-only Discord tool handlers.

Live Discord I/O is isolated in ``DiscordLiveFetcher``. Tests exercise the pure
tool orchestration with fake fetchers, so validation never needs network access
or a Discord token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from hermes_plugin_kit import int_arg, str_arg, tool

from . import schemas

logger = logging.getLogger("discord-tools")

DISCORD_URL_RE = re.compile(
    r"https?://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>@me|\d+)/(?P<channel>\d+)(?:/(?P<message>\d+))?"
)
SNOWFLAKE_RE = re.compile(r"^\d{15,25}$")


class Fetcher(Protocol):
    def read_channel(
        self,
        channel_id: str,
        *,
        limit: int,
        before: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        ...

    def get_message(
        self,
        channel_id: str,
        message_id: str,
        *,
        context_limit: int,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class DiscordRef:
    guild_id: str | None
    channel_id: str | None
    message_id: str | None


def _ok(**data: Any) -> str:
    return json.dumps({"success": True, "data": data}, ensure_ascii=False)


def _err(msg: str, **extra: Any) -> str:
    payload = {"success": False, "error": msg}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _env_int(env: dict[str, str], name: str, default: int, lo: int, hi: int) -> int:
    return _clamp(env.get(name), default, lo, hi)


def _allowed_guilds(env: dict[str, str]) -> set[str]:
    raw = env.get("DISCORD_TOOLS_ALLOWED_GUILDS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def parse_discord_ref(value: Any) -> DiscordRef | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = DISCORD_URL_RE.search(text)
    if match:
        guild_id = match.group("guild")
        return DiscordRef(
            guild_id=None if guild_id == "@me" else guild_id,
            channel_id=match.group("channel"),
            message_id=match.group("message"),
        )
    if SNOWFLAKE_RE.match(text):
        return DiscordRef(guild_id=None, channel_id=text, message_id=None)
    return None


def _parse_message_ref(message_id_or_url: Any, channel_id: Any = None) -> DiscordRef | None:
    text = str(message_id_or_url or "").strip()
    match = DISCORD_URL_RE.search(text)
    if match:
        guild_id = match.group("guild")
        return DiscordRef(
            guild_id=None if guild_id == "@me" else guild_id,
            channel_id=match.group("channel"),
            message_id=match.group("message"),
        )
    if SNOWFLAKE_RE.match(text):
        channel = str(channel_id or "").strip()
        if channel and SNOWFLAKE_RE.match(channel):
            return DiscordRef(guild_id=None, channel_id=channel, message_id=text)
        return DiscordRef(guild_id=None, channel_id=None, message_id=text)
    return None


def _guard_guild(guild_id: Any, allowed: set[str]) -> str | None:
    if not allowed:
        return None
    if not guild_id:
        return "Discord guild is unknown; a guild allowlist is configured."
    if str(guild_id) not in allowed:
        return "Discord guild is not allowed for this profile."
    return None


def _message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)

    author = getattr(message, "author", None)
    created_at = getattr(message, "created_at", None)
    if isinstance(created_at, datetime):
        created = created_at.isoformat()
    else:
        created = str(created_at or "")

    return {
        "id": str(getattr(message, "id", "")),
        "author_id": str(getattr(author, "id", "")) if author else "",
        "author_name": str(getattr(author, "display_name", None) or getattr(author, "name", "") or ""),
        "created_at": created,
        "content": str(getattr(message, "content", "") or ""),
        "jump_url": str(getattr(message, "jump_url", "") or ""),
    }


def _shape_messages(raw_messages: list[Any], max_chars: int) -> tuple[list[dict[str, Any]], bool]:
    shaped: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for raw in raw_messages:
        msg = _message_to_dict(raw)
        content = str(msg.get("content") or "")
        cost = len(content)
        if used + cost > max_chars:
            remaining = max_chars - used
            if remaining > 0:
                msg["content"] = content[:remaining]
                shaped.append(msg)
            truncated = True
            break
        used += cost
        shaped.append(msg)
    return shaped, truncated


def read_channel_impl(args: dict[str, Any], fetcher: Fetcher, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    raw = (args or {}).get("channel_id_or_url")
    ref = parse_discord_ref(raw)
    if not ref or not ref.channel_id:
        logger.warning(
            "discord-tools: read_channel rejected channel_id_or_url=%r", str(raw)[:120]
        )
        return _err(
            "channel_id_or_url must be a Discord channel link or numeric ID "
            "(e.g. https://discord.com/channels/<guild>/<channel> or 123456789012345678)"
        )

    allowed_guilds = _allowed_guilds(env)
    if ref.guild_id:
        guild_error = _guard_guild(ref.guild_id, allowed_guilds)
        if guild_error:
            return _err(guild_error)

    max_messages = _env_int(env, "DISCORD_TOOLS_MAX_MESSAGES", schemas.DEFAULT_MAX_MESSAGES, 1, schemas.MAX_MAX_MESSAGES)
    limit = _clamp((args or {}).get("limit"), max_messages, 1, max_messages)
    max_chars = _env_int(env, "DISCORD_TOOLS_MAX_CHARS", schemas.DEFAULT_MAX_CHARS, 200, schemas.MAX_MAX_CHARS)

    logger.info("discord-tools: reading channel %s (limit=%d)", ref.channel_id, limit)
    try:
        fetched = fetcher.read_channel(
            ref.channel_id,
            limit=limit,
            before=(args or {}).get("before"),
            after=(args or {}).get("after"),
        )
    except Exception as exc:  # noqa: BLE001 - tool errors should stay in-band
        return _err(f"Discord read failed: {exc}")

    fetched_guild = fetched.get("guild_id") or ref.guild_id
    guild_error = _guard_guild(fetched_guild, allowed_guilds)
    if guild_error:
        return _err(guild_error)

    messages, truncated = _shape_messages(list(fetched.get("messages") or []), max_chars)
    return _ok(
        kind="channel",
        guild_id=fetched_guild,
        channel_id=str(fetched.get("channel_id") or ref.channel_id),
        channel_name=fetched.get("channel_name"),
        limit=limit,
        messages=messages,
        truncated=truncated,
    )


def read_thread_impl(args: dict[str, Any], fetcher: Fetcher, env: dict[str, str] | None = None) -> str:
    translated = dict(args or {})
    translated["channel_id_or_url"] = translated.get("thread_id_or_url")
    result = json.loads(read_channel_impl(translated, fetcher, env))
    if result.get("success"):
        result["data"]["kind"] = "thread"
    return json.dumps(result, ensure_ascii=False)


def _load_story_threads(env: dict[str, str]) -> list[dict[str, Any]]:
    """Load preconfigured story threads from env: inline JSON, a file path, or a single ID."""
    threads: list[dict[str, Any]] = []
    raw = env.get("DISCORD_TOOLS_STORY_THREADS") or env.get("DISCORD_TOOLS_STORY_THREADS_JSON") or ""
    raw = raw.strip()
    if raw:
        if not raw.startswith(("{", "[")):
            try:
                raw = Path(raw).read_text(encoding="utf-8")
            except OSError:
                logger.debug("discord-tools: story threads path is unreadable")
                raw = ""
        if raw:
            try:
                parsed: Any = json.loads(raw)
            except ValueError:
                logger.debug("discord-tools: story threads JSON is invalid")
                parsed = None
            if isinstance(parsed, dict):
                parsed = parsed.get("threads") or parsed.get("stories") or []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("thread_id"):
                        threads.append(
                            {
                                "name": str(item.get("name") or "").strip(),
                                "thread_id": str(item["thread_id"]).strip(),
                                "aliases": [
                                    str(alias).strip().lower()
                                    for alias in (item.get("aliases") or [])
                                ],
                            }
                        )

    single = (env.get("DISCORD_TOOLS_STORY_THREAD_ID") or "").strip()
    if single:
        threads.append({"name": "default", "thread_id": single, "aliases": []})
    return threads


def _resolve_story_thread(
    name: Any, threads: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    if not threads:
        return None, (
            "No story threads are configured. Set DISCORD_TOOLS_STORY_THREADS_JSON "
            "or DISCORD_TOOLS_STORY_THREAD_ID."
        )
    wanted = str(name or "").strip().lower()
    if not wanted:
        if len(threads) == 1:
            return threads[0], None
        names = ", ".join(thread["name"] for thread in threads if thread["name"])
        return None, f"Multiple story threads configured; pass a name. Available: {names}"
    for thread in threads:
        if thread["name"].lower() == wanted or wanted in thread["aliases"]:
            return thread, None
    names = ", ".join(thread["name"] for thread in threads if thread["name"])
    return None, f"No story thread named {name!r}. Available: {names}"


def read_story_impl(args: dict[str, Any], fetcher: Fetcher, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    threads = _load_story_threads(env)
    story, error = _resolve_story_thread((args or {}).get("name"), threads)
    if error:
        logger.warning("discord-tools: read_story could not resolve a thread: %s", error)
        return _err(error)

    logger.info("discord-tools: reading story %r thread %s", story["name"], story["thread_id"])
    translated = dict(args or {})
    translated["channel_id_or_url"] = story["thread_id"]
    result = json.loads(read_channel_impl(translated, fetcher, env))
    if result.get("success"):
        result["data"]["kind"] = "story"
        result["data"]["story_name"] = story["name"]
    return json.dumps(result, ensure_ascii=False)


def get_message_impl(args: dict[str, Any], fetcher: Fetcher, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    raw = (args or {}).get("message_id_or_url")
    ref = _parse_message_ref(raw, (args or {}).get("channel_id"))
    if not ref or not ref.message_id:
        logger.warning("discord-tools: get_message rejected message_id_or_url=%r", str(raw)[:120])
        return _err(
            "message_id_or_url must be a Discord message link or numeric ID "
            "(e.g. https://discord.com/channels/<guild>/<channel>/<message>)"
        )
    if not ref.channel_id:
        return _err("A raw message ID requires channel_id; prefer a Discord message URL.")

    allowed_guilds = _allowed_guilds(env)
    if ref.guild_id:
        guild_error = _guard_guild(ref.guild_id, allowed_guilds)
        if guild_error:
            return _err(guild_error)

    context_limit = _clamp(
        (args or {}).get("context_limit"),
        schemas.DEFAULT_CONTEXT_LIMIT,
        1,
        schemas.MAX_CONTEXT_LIMIT,
    )
    max_chars = _env_int(env, "DISCORD_TOOLS_MAX_CHARS", schemas.DEFAULT_MAX_CHARS, 200, schemas.MAX_MAX_CHARS)

    try:
        fetched = fetcher.get_message(ref.channel_id, ref.message_id, context_limit=context_limit)
    except Exception as exc:  # noqa: BLE001
        return _err(f"Discord message fetch failed: {exc}")

    fetched_guild = fetched.get("guild_id") or ref.guild_id
    guild_error = _guard_guild(fetched_guild, allowed_guilds)
    if guild_error:
        return _err(guild_error)

    messages, truncated = _shape_messages(list(fetched.get("messages") or []), max_chars)
    return _ok(
        kind="message",
        guild_id=fetched_guild,
        channel_id=str(fetched.get("channel_id") or ref.channel_id),
        channel_name=fetched.get("channel_name"),
        message_id=ref.message_id,
        context_limit=context_limit,
        messages=messages,
        truncated=truncated,
    )


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class DiscordLiveFetcher:
    def __init__(self, token: str, timeout_seconds: float = schemas.DEFAULT_TIMEOUT_SECONDS) -> None:
        self.token = token
        self.timeout_seconds = timeout_seconds

    def read_channel(
        self,
        channel_id: str,
        *,
        limit: int,
        before: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        return _run_async(self._read_channel(channel_id, limit=limit, before=before, after=after))

    def get_message(self, channel_id: str, message_id: str, *, context_limit: int) -> dict[str, Any]:
        return _run_async(self._get_message(channel_id, message_id, context_limit=context_limit))

    async def _with_client(self, operation: Any) -> Any:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        await asyncio.wait_for(client.login(self.token), timeout=self.timeout_seconds)
        try:
            return await asyncio.wait_for(operation(client, discord), timeout=self.timeout_seconds)
        finally:
            await client.close()

    async def _read_channel(
        self,
        channel_id: str,
        *,
        limit: int,
        before: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        async def _operation(client: Any, discord: Any) -> dict[str, Any]:
            channel = await client.fetch_channel(int(channel_id))
            if not hasattr(channel, "history"):
                raise RuntimeError("Discord target is not a readable message channel")
            history_kwargs: dict[str, Any] = {"limit": limit}
            if before and SNOWFLAKE_RE.match(str(before)):
                history_kwargs["before"] = discord.Object(id=int(before))
            if after and SNOWFLAKE_RE.match(str(after)):
                history_kwargs["after"] = discord.Object(id=int(after))
                history_kwargs["oldest_first"] = True

            messages = [_message_to_dict(msg) async for msg in channel.history(**history_kwargs)]
            if not after:
                messages.reverse()
            guild = getattr(channel, "guild", None)
            return {
                "guild_id": str(getattr(guild, "id", "")) if guild else None,
                "channel_id": str(getattr(channel, "id", channel_id)),
                "channel_name": str(getattr(channel, "name", "") or ""),
                "messages": messages,
            }

        return await self._with_client(_operation)

    async def _get_message(self, channel_id: str, message_id: str, *, context_limit: int) -> dict[str, Any]:
        async def _operation(client: Any, discord: Any) -> dict[str, Any]:
            channel = await client.fetch_channel(int(channel_id))
            if not hasattr(channel, "fetch_message"):
                raise RuntimeError("Discord target is not a readable message channel")
            target = await channel.fetch_message(int(message_id))
            messages: list[dict[str, Any]] = []
            if context_limit > 1 and hasattr(channel, "history"):
                before_limit = context_limit - 1
                before_obj = discord.Object(id=int(message_id))
                prior = [_message_to_dict(msg) async for msg in channel.history(limit=before_limit, before=before_obj)]
                prior.reverse()
                messages.extend(prior)
            messages.append(_message_to_dict(target))
            guild = getattr(channel, "guild", None)
            return {
                "guild_id": str(getattr(guild, "id", "")) if guild else None,
                "channel_id": str(getattr(channel, "id", channel_id)),
                "channel_name": str(getattr(channel, "name", "") or ""),
                "messages": messages,
            }

        return await self._with_client(_operation)


def _live_fetcher(env: dict[str, str]) -> Fetcher | str:
    # Hermes' Discord gateway loads the bot token as DISCORD_BOT_TOKEN; reuse it.
    # DISCORD_TOKEN is kept as a fallback alias for standalone use.
    token = env.get("DISCORD_BOT_TOKEN") or env.get("DISCORD_TOKEN")
    if not token:
        return "DISCORD_BOT_TOKEN is required for live Discord reads"
    try:
        timeout = float(env.get("DISCORD_TOOLS_TIMEOUT_SECONDS", schemas.DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = schemas.DEFAULT_TIMEOUT_SECONDS
    return DiscordLiveFetcher(token=token, timeout_seconds=timeout)


@tool(
    toolset="messaging",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "Read recent messages from a Discord channel the bot can already access. "
        "Use when memory may be stale and the user gives a Discord channel URL or ID."
    ),
    params={
        "channel_id_or_url": str_arg(
            "Discord channel URL or raw channel snowflake.",
            required=True,
            example="123456789012345678",
        ),
        "limit": int_arg(
            f"Messages to return, capped at {schemas.MAX_MAX_MESSAGES}.",
            minimum=1,
            maximum=schemas.MAX_MAX_MESSAGES,
        ),
        "before": str_arg("Optional Discord message snowflake to page before."),
        "after": str_arg("Optional Discord message snowflake to page after."),
    },
)
def discord_read_channel(args: dict[str, Any], **_kwargs: Any) -> str:
    fetcher = _live_fetcher(os.environ)
    if isinstance(fetcher, str):
        return _err(fetcher)
    return read_channel_impl(args or {}, fetcher, os.environ)


@tool(
    toolset="messaging",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "Read recent messages from a Discord thread the bot can already access. "
        "A Discord thread is fetched through the same read-only channel API."
    ),
    params={
        "thread_id_or_url": str_arg(
            "Discord thread URL or raw thread snowflake.",
            required=True,
            example="123456789012345678",
        ),
        "limit": int_arg(
            f"Messages to return, capped at {schemas.MAX_MAX_MESSAGES}.",
            minimum=1,
            maximum=schemas.MAX_MAX_MESSAGES,
        ),
        "before": str_arg("Optional Discord message snowflake to page before."),
        "after": str_arg("Optional Discord message snowflake to page after."),
    },
)
def discord_read_thread(args: dict[str, Any], **_kwargs: Any) -> str:
    fetcher = _live_fetcher(os.environ)
    if isinstance(fetcher, str):
        return _err(fetcher)
    return read_thread_impl(args or {}, fetcher, os.environ)


@tool(
    toolset="messaging",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "Fetch a specific Discord message plus bounded prior context. Prefer a "
        "full Discord message URL so the channel ID is unambiguous."
    ),
    params={
        "message_id_or_url": str_arg(
            "Discord message URL or raw message snowflake.",
            required=True,
            example="https://discord.com/channels/<guild>/<channel>/<message>",
        ),
        "channel_id": str_arg(
            "Required only when message_id_or_url is a raw message ID."
        ),
        "context_limit": int_arg(
            f"Total messages including the target, capped at {schemas.MAX_CONTEXT_LIMIT}.",
            minimum=1,
            maximum=schemas.MAX_CONTEXT_LIMIT,
        ),
    },
)
def discord_get_message(args: dict[str, Any], **_kwargs: Any) -> str:
    fetcher = _live_fetcher(os.environ)
    if isinstance(fetcher, str):
        return _err(fetcher)
    return get_message_impl(args or {}, fetcher, os.environ)


@tool(
    toolset="messaging",
    requires_env=["DISCORD_BOT_TOKEN"],
    description=(
        "Read recent messages from a preconfigured story thread (such as the House "
        "of Tea) by name. Use this for a known ongoing story thread when you do not "
        "have its link or ID. No Discord URL or snowflake is required."
    ),
    params={
        "name": str_arg(
            "Which configured story to read. Optional when only one is configured."
        ),
        "limit": int_arg(
            f"Messages to return, capped at {schemas.MAX_MAX_MESSAGES}.",
            minimum=1,
            maximum=schemas.MAX_MAX_MESSAGES,
        ),
        "before": str_arg("Optional Discord message snowflake to page before."),
    },
)
def discord_read_story(args: dict[str, Any], **_kwargs: Any) -> str:
    fetcher = _live_fetcher(os.environ)
    if isinstance(fetcher, str):
        return _err(fetcher)
    return read_story_impl(args or {}, fetcher, os.environ)
