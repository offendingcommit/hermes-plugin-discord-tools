"""JSON schemas and tunable constants for discord-tools."""

from __future__ import annotations

DEFAULT_MAX_MESSAGES = 100
MAX_MAX_MESSAGES = 100
DEFAULT_CONTEXT_LIMIT = 25
MAX_CONTEXT_LIMIT = 50
DEFAULT_MAX_CHARS = 12000
MAX_MAX_CHARS = 30000
DEFAULT_TIMEOUT_SECONDS = 20.0

READ_CHANNEL_SCHEMA = {
    "type": "object",
    "description": (
        "Read recent messages from a Discord channel the bot can already access. "
        "Use when memory may be stale and the user gives a Discord channel URL or ID."
    ),
    "properties": {
        "channel_id_or_url": {
            "type": "string",
            "minLength": 1,
            "description": "Discord channel URL or raw channel snowflake.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_MAX_MESSAGES,
            "description": f"Messages to return, capped at {MAX_MAX_MESSAGES}.",
        },
        "before": {
            "type": "string",
            "description": "Optional Discord message snowflake to page before.",
        },
        "after": {
            "type": "string",
            "description": "Optional Discord message snowflake to page after.",
        },
    },
    "required": ["channel_id_or_url"],
    "additionalProperties": False,
}

READ_THREAD_SCHEMA = {
    **READ_CHANNEL_SCHEMA,
    "description": (
        "Read recent messages from a Discord thread the bot can already access. "
        "A Discord thread is fetched through the same read-only channel API."
    ),
    "properties": {
        **READ_CHANNEL_SCHEMA["properties"],
        "thread_id_or_url": {
            "type": "string",
            "minLength": 1,
            "description": "Discord thread URL or raw thread snowflake.",
        },
    },
    "required": ["thread_id_or_url"],
}

GET_MESSAGE_SCHEMA = {
    "type": "object",
    "description": (
        "Fetch a specific Discord message plus bounded prior context. Prefer a "
        "full Discord message URL so the channel ID is unambiguous."
    ),
    "properties": {
        "message_id_or_url": {
            "type": "string",
            "minLength": 1,
            "description": "Discord message URL or raw message snowflake.",
        },
        "channel_id": {
            "type": "string",
            "description": "Required only when message_id_or_url is a raw message ID.",
        },
        "context_limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_CONTEXT_LIMIT,
            "description": f"Total messages including the target, capped at {MAX_CONTEXT_LIMIT}.",
        },
    },
    "required": ["message_id_or_url"],
    "additionalProperties": False,
}
