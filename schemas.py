"""Tunable constants for discord-tools.

Tool schemas now live on the ``@tool`` decorators in ``tools.py`` (built via
hermes-plugin-kit, which guarantees the ``parameters`` wrapper). This module
keeps only the numeric limits shared across the impl functions.
"""

from __future__ import annotations

DEFAULT_MAX_MESSAGES = 100
MAX_MAX_MESSAGES = 100
DEFAULT_CONTEXT_LIMIT = 25
MAX_CONTEXT_LIMIT = 50
DEFAULT_MAX_CHARS = 12000
MAX_MAX_CHARS = 30000
DEFAULT_TIMEOUT_SECONDS = 20.0

# Discord's documented embed limits (https://discord.com/developers/docs/resources/message#embed-object-embed-limits).
# "total" is the sum of every text part a single embed carries.
EMBED_LIMITS = {
    "title": 256,
    "description": 4096,
    "fields": 25,
    "field_name": 256,
    "field_value": 1024,
    "footer": 2048,
    "total": 6000,
}

# Most writes one incoming message may cause, per kind. Stops a model loop from
# carpeting a channel in reactions or embeds off a single prompt.
TURN_BUDGET = {"react": 5, "embed": 2}
# Incoming messages the budget remembers before the oldest is forgotten.
TURN_BUDGET_REMEMBER = 512

DEFAULT_EMOJI_LIST = 100
MAX_EMOJI_LIST = 250
