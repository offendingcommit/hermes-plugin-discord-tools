"""discord-tools - read-only Discord inspection for Hermes agents."""

from __future__ import annotations

import logging

from hermes_plugin_kit import RegistrationSummary, register_plugin

from . import hooks, tools

logger = logging.getLogger("discord-tools")

_DECLARATIONS = (
    tools.discord_read_channel,
    tools.discord_read_thread,
    tools.discord_get_message,
    tools.discord_read_story,
    hooks.inject_discord_read_hint,
)


def register(ctx) -> RegistrationSummary:
    """Register read-only Discord tools and hint hook with Hermes."""
    return register_plugin(
        ctx,
        _DECLARATIONS,
        plugin_name="discord-tools",
        logger=logger,
    )
