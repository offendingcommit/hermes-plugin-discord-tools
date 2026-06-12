# hermes-plugin-discord-tools

Read-only Discord tools for Hermes Discord-facing agents.

The plugin lets a bot use its existing Discord bot token to read a channel,
thread, or linked message that the bot can already access. It is intended as a
backstop when Hindsight or other memory processing is behind, especially for
story channels where the bot should be able to inspect the current source of
truth before answering.

## Tools

- `discord_read_channel`: read recent messages from a Discord channel URL or ID
  (`channel_id_or_url`).
- `discord_read_thread`: read recent messages from a Discord thread URL or ID
  (`thread_id_or_url`).
- `discord_get_message`: fetch one linked message plus bounded prior context
  (`message_id_or_url`).
- `discord_read_story`: read a **preconfigured** story thread by `name` (or with
  no arguments when only one is configured). No Discord URL/ID needed — the
  thread ID comes from env config, so the agent never has to supply a snowflake
  it does not have. See `DISCORD_TOOLS_STORY_THREADS_JSON` below.

All tools return JSON with a `success` flag. They never write to Discord or to
memory. Each tool's required argument name is repeated in its description (not
only the JSON schema) so the agent can call it correctly even when a runtime
surfaces the schema's `properties` as empty.

## Logging

The plugin logs under the `discord-tools` logger. On a rejected argument it logs
a `WARNING` with the offending value (truncated, never the token), and on a
successful read an `INFO` line with the resolved target. To watch it in a pod:

```bash
kubectl logs -f <pod> | grep discord-tools
```

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

## Environment

- `DISCORD_BOT_TOKEN`: the bot token the Hermes gateway already loads — reused
  for live Discord reads. `DISCORD_TOKEN` is accepted as a fallback alias for
  standalone use.
- `DISCORD_TOOLS_ALLOWED_GUILDS`: optional comma-separated guild allowlist. If
  unset, Discord access is bounded only by the bot token's existing visibility.
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

## Validation

```bash
python3 -m unittest discover -s tests
```
