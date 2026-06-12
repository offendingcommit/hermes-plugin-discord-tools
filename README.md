# hermes-plugin-discord-tools

Read-only Discord tools for Hermes Discord-facing agents.

The plugin lets a bot use its existing Discord bot token to read a channel,
thread, or linked message that the bot can already access. It is intended as a
backstop when Hindsight or other memory processing is behind, especially for
story channels where the bot should be able to inspect the current source of
truth before answering.

## Tools

- `discord_read_channel`: read recent messages from a Discord channel URL or ID.
- `discord_read_thread`: read recent messages from a Discord thread URL or ID.
- `discord_get_message`: fetch one linked message plus bounded prior context.

All tools return JSON with a `success` flag. They never write to Discord or to
memory.

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

- `DISCORD_TOKEN`: required for live Discord reads.
- `DISCORD_TOOLS_ALLOWED_GUILDS`: optional comma-separated guild allowlist. If
  unset, Discord access is bounded only by the bot token's existing visibility.
- `DISCORD_TOOLS_MAX_MESSAGES`: optional default/max message limit, default 100.
- `DISCORD_TOOLS_MAX_CHARS`: optional result character budget, default 12000.
- `DISCORD_TOOLS_TIMEOUT_SECONDS`: optional live API timeout, default 20.
- `DISCORD_TOOLS_STORY_HINTS`: optional inline story hint JSON.
- `DISCORD_TOOLS_STORY_HINTS_JSON`: optional inline story hint JSON or path to a
  local JSON file.

## Validation

```bash
python3 -m unittest discover -s tests
```
