# hermes-plugin-discord-tools

Discord tools for Hermes Discord-facing agents: reads, plus three small
actions held to the channel the bot is replying in.

The plugin lets a bot use its existing Discord bot token to read a channel,
thread, or linked message that the bot can already access. It is intended as a
backstop when Hindsight or other memory processing is behind, especially for
story channels where the bot should be able to inspect the current source of
truth before answering.

## Tools

All tools return JSON with a `success` flag. Each tool's required argument name
is repeated in its description (not only the JSON schema) so the agent can call
it correctly even when a runtime surfaces the schema's `properties` as empty.

### Reads (toolset `messaging`)

- `discord_read_channel`: read recent messages from a Discord channel URL or ID
  (`channel_id_or_url`).
- `discord_read_thread`: read recent messages from a Discord thread URL or ID
  (`thread_id_or_url`).
- `discord_get_message`: fetch one linked message plus bounded prior context
  (`message_id_or_url`).
- `discord_read_story`: read a **preconfigured** story thread by `name` (or with
  no arguments when only one is configured). No Discord URL/ID needed: the
  thread ID comes from `DISCORD_TOOLS_STORY_THREADS_JSON` or
  `DISCORD_TOOLS_STORY_THREAD_ID`, so the agent never has to supply a snowflake
  it does not have. Keep that configuration static and env/file backed.

These four never write to Discord or to memory, and only read content the
configured bot token can already access.

### Channel-scoped actions (toolset `discord`, in `actions.py`)

- `discord_list_emojis`: this server's own custom emoji the bot can use, each
  with a ready `usage` string (`<:name:id>`). Optional `query`, `limit`.
- `discord_react`: react with one emoji (`emoji`), any standard emoji or one of
  this server's as `:name:` or `<:name:id>`. Reacts to the message being
  answered, or to `message_id` when that message is in this same channel.
- `discord_send_embed`: post one embed card (`title` and/or `description`,
  optional `url`, `color`, `fields`, `footer`, `image_url`, `thumbnail_url`) in
  this channel, held to Discord's embed limits (`schemas.EMBED_LIMITS`), with
  mentions suppressed.

The channel, server and triggering message come from the Hermes session the
gateway binds for the turn (`HERMES_SESSION_*`), never from model arguments, so
a model cannot aim one of these at another channel. They refuse on other
platforms and in scheduled runs. Custom emoji from other servers are refused.
One incoming message can cause at most 5 reactions and 2 embeds
(`schemas.TURN_BUDGET`).

They join Hermes' own `discord` toolset, so a profile gets them only where its
config turns that toolset on for Discord (`platform_toolsets.discord`), the same
switch as Hermes' built-in Discord tool.

Bot permissions they need in the channel: **Add Reactions** and **Read Message
History** (react), **Send Messages** and **Embed Links** (embeds). Listing
emoji needs none beyond being in the server. Use External Emojis is not needed,
since only the server's own emoji are allowed.

## Hook

`pre_llm_call` injects a compact hint when the current turn mentions a Discord
channel/message link. It can also surface static story hints from
`DISCORD_TOOLS_STORY_HINTS` or `DISCORD_TOOLS_STORY_HINTS_JSON`.

Example inline story hint config:

```json
[
  {
    "name": "Bea's House of Tea",
    "keywords": ["bea's house of tea", "house of tea", "ember revealed"],
    "hint": "Use discord_read_channel or discord_get_message on linked source channels before relying on stale memory."
  }
]
```

If `DISCORD_TOOLS_STORY_HINTS_JSON` is a JSON string it is parsed directly. If
it is a filesystem path, the hook reads that local JSON file.

This is the plugin's only hook. It registers no write hooks, commands, skills,
or memory integrations.

## Environment

- `DISCORD_BOT_TOKEN`: the bot token the Hermes gateway already loads, reused
  for live Discord reads and the channel-scoped actions. `DISCORD_TOKEN` is
  accepted as a fallback alias for standalone use.
- `DISCORD_TOOLS_ALLOWED_GUILDS`: optional comma-separated guild allowlist for
  reads and actions. If unset, Discord access is bounded only by the bot
  token's existing visibility.
- `DISCORD_TOOLS_MAX_MESSAGES`: optional default/max message limit, default 100.
- `DISCORD_TOOLS_MAX_CHARS`: optional result character budget, default 12000.
- `DISCORD_TOOLS_TIMEOUT_SECONDS`: optional live API timeout, default 20.
- `DISCORD_TOOLS_STORY_HINTS`: optional inline story hint JSON.
- `DISCORD_TOOLS_STORY_HINTS_JSON`: optional inline story hint JSON or path to a
  local JSON file.
- `DISCORD_TOOLS_STORY_THREADS_JSON`: optional inline JSON (or path to a local
  JSON file) listing preconfigured story threads for `discord_read_story`, e.g.
  `[{"name":"House of Tea","thread_id":"123456789012345678","aliases":["bea"]}]`.
- `DISCORD_TOOLS_STORY_THREAD_ID`: optional single story thread ID for
  `discord_read_story` when only one story is needed.

## Logging

The plugin logs under the `discord-tools` logger. On a rejected argument it logs
a `WARNING` with the offending value (truncated, never the token), and on a
successful read an `INFO` line with the resolved target. At startup,
`hermes-plugin-kit` emits one lifecycle receipt listing the seven tools and
`pre_llm_call` hook that it registered. To watch it in a pod:

```bash
kubectl logs -f <pod> | grep discord-tools
```

## Registration

Every tool uses `@tool`, the hint callback uses `@hook`, and
[`hermes-plugin-kit`](https://github.com/offendingcommit/hermes-plugin-kit)
owns the complete lifecycle through `register_plugin`. This keeps Hermes tool
schemas, handlers, validation, logging, JSON envelopes, and the startup
registration inventory under one contract.

## Guardrails

- The read tools stay read-only. The three actions in `actions.py` are the
  whole write surface: no edit, delete, pin, role, member, retain, or
  memory-write behavior, and no action that takes its channel from a model
  argument.
- Actions register into Hermes' own `discord` toolset, never `messaging` or a
  new plugin toolset: Hermes turns unseen plugin toolsets on by default, while
  `discord` is on only where a profile's config names it.
- Every action refuses outside a live Discord turn (other platforms, cron runs),
  holds custom emoji to the current server's palette, sends embeds with no
  mentions, and spends from a per-message budget (`schemas.TURN_BUDGET`).
- Reuse the profile's existing `DISCORD_BOT_TOKEN` (the token the Hermes gateway
  loads); do not introduce a second token. `DISCORD_TOKEN` is an optional
  standalone fallback alias only.
- Tests must not call Discord. Keep live API access behind injectable seams.
- The hook is hint-only. It may inspect current turn text and local static
  config, but it must not call Discord, Hindsight, Honcho, or the network.
- Keep every tool and lifecycle hook declared with `hermes-plugin-kit`
  decorators. `register_plugin` owns the complete registration path and returns
  the exact `RegistrationSummary`; do not add direct `ctx.register_*` calls or
  legacy `register_all` wiring.

## Validation

```bash
make install
make test
HERMES_AGENT_PATH=<hermes checkout> make test   # adds the real-Hermes layer
```

The real-Hermes layer binds sessions with Hermes' own `set_session_vars` and
registers into its real registry and toolsets. It also checks the contract
against the real `PluginContext.register_tool` / `register_hook` signatures.
Registration tests reject direct lifecycle wiring and assert the exact kit
summary. Keep that coverage in place for registration changes.

Dev tooling is uv-native; dependencies live in `pyproject.toml`.
