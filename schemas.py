"""JSON schemas and tunable constants for discord-tools.

Tool schemas follow the hermes-agent convention: a top-level ``name`` and
``description`` plus a ``parameters`` object holding the JSON Schema. The
registry builds the LLM tool as ``{"type": "function", "function": {**schema,
"name": ...}}`` — so arguments MUST live under ``parameters``. Putting
``properties`` at the top level makes the model receive an empty parameter set.
"""

from __future__ import annotations

DEFAULT_MAX_MESSAGES = 100
MAX_MAX_MESSAGES = 100
DEFAULT_CONTEXT_LIMIT = 25
MAX_CONTEXT_LIMIT = 50
DEFAULT_MAX_CHARS = 12000
MAX_MAX_CHARS = 30000
DEFAULT_TIMEOUT_SECONDS = 20.0

READ_CHANNEL_SCHEMA = {
    "name": "discord_read_channel",
    "description": (
        "Read recent messages from a Discord channel the bot can already access. "
        "Use when memory may be stale and the user gives a Discord channel URL or ID. "
        'Pass the channel as the `channel_id_or_url` argument — a Discord channel '
        'link or numeric ID, e.g. channel_id_or_url="123456789012345678".'
    ),
    "parameters": {
        "type": "object",
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
    },
}

READ_THREAD_SCHEMA = {
    "name": "discord_read_thread",
    "description": (
        "Read recent messages from a Discord thread the bot can already access. "
        "A Discord thread is fetched through the same read-only channel API. "
        'Pass the thread as the `thread_id_or_url` argument — a Discord thread '
        'link or numeric ID, e.g. thread_id_or_url="123456789012345678".'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "thread_id_or_url": {
                "type": "string",
                "minLength": 1,
                "description": "Discord thread URL or raw thread snowflake.",
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
        "required": ["thread_id_or_url"],
        "additionalProperties": False,
    },
}

GET_MESSAGE_SCHEMA = {
    "name": "discord_get_message",
    "description": (
        "Fetch a specific Discord message plus bounded prior context. Prefer a "
        "full Discord message URL so the channel ID is unambiguous. Pass it as the "
        "`message_id_or_url` argument."
    ),
    "parameters": {
        "type": "object",
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
    },
}

READ_STORY_SCHEMA = {
    "name": "discord_read_story",
    "description": (
        "Read recent messages from a preconfigured story thread (such as the House "
        "of Tea) by name. Use this for a known ongoing story thread when you do not "
        "have its link or ID — no Discord URL or snowflake is required. Optionally "
        "pass `name` to choose among configured stories; omit it when only one is "
        "configured."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Which configured story to read. Optional when only one is configured.",
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
        },
        "required": [],
        "additionalProperties": False,
    },
}
