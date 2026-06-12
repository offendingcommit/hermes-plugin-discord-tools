"""discord-tools - read-only Discord inspection for Hermes agents."""

from __future__ import annotations

import logging

from . import hooks, schemas, tools

logger = logging.getLogger("discord-tools")

TOOLSET = "messaging"


def register(ctx) -> None:
    """Register read-only Discord tools and hint hook with Hermes."""
    for name, schema, handler in (
        ("discord_read_channel", schemas.READ_CHANNEL_SCHEMA, tools.discord_read_channel),
        ("discord_read_thread", schemas.READ_THREAD_SCHEMA, tools.discord_read_thread),
        ("discord_get_message", schemas.GET_MESSAGE_SCHEMA, tools.discord_get_message),
    ):
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            requires_env=["DISCORD_TOKEN"],
            description=schema.get("description", ""),
        )

    ctx.register_hook("pre_llm_call", hooks.inject_discord_read_hint)
    logger.info("discord-tools: registered 3 read-only tools + pre_llm_call hook")
