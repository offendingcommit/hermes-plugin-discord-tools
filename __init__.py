"""discord-tools - read-only Discord inspection for Hermes agents."""

from __future__ import annotations

import logging

from hermes_plugin_kit import register_all

from . import hooks, tools

logger = logging.getLogger("discord-tools")


def register(ctx) -> None:
    """Register read-only Discord tools and hint hook with Hermes."""
    count = register_all(ctx, tools)
    ctx.register_hook("pre_llm_call", hooks.inject_discord_read_hint)
    logger.info("discord-tools: registered %d read-only tools + pre_llm_call hook", count)
