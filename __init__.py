"""discord-tools - Discord reads plus three channel-scoped actions for Hermes agents."""

from __future__ import annotations

import logging

from hermes_plugin_kit import RegistrationSummary, register_plugin

from . import actions, hooks, tools

logger = logging.getLogger("discord-tools")

_DECLARATIONS = (
    tools.discord_read_channel,
    tools.discord_read_thread,
    tools.discord_get_message,
    tools.discord_read_story,
    actions.discord_list_emojis,
    actions.discord_react,
    actions.discord_send_embed,
    hooks.inject_discord_read_hint,
)


def register(ctx) -> RegistrationSummary:
    """Register the Discord read tools, the channel-scoped actions and the hint hook."""
    return register_plugin(
        ctx,
        _DECLARATIONS,
        plugin_name="discord-tools",
        logger=logger,
    )
