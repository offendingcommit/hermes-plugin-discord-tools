# hermes-plugin-discord-tools

Read-only Discord inspection tools for Hermes Discord-facing agents.

## Current surface

- `discord_read_channel`, `discord_read_thread`, `discord_get_message`, and
  `discord_read_story` are the only tools. They return JSON and must only read
  Discord content the configured bot token can already access.
- `discord_read_story` reads preconfigured story threads from
  `DISCORD_TOOLS_STORY_THREADS_JSON` or `DISCORD_TOOLS_STORY_THREAD_ID`; keep
  that configuration static and env/file backed.
- The plugin registers one `pre_llm_call` hint hook and no write hooks,
  commands, skills, or memory integrations.

## Guardrails

- This plugin must stay read-only. Do not add send, edit, delete, react, pin,
  retain, or memory-write behavior here.
- Reuse the profile's existing `DISCORD_BOT_TOKEN` (the token the Hermes gateway
  loads); do not introduce a second token. `DISCORD_TOKEN` is an optional
  standalone fallback alias only.
- Tests must not call Discord. Keep live API access behind injectable seams.
- The hook is hint-only. It may inspect current turn text and local static
  config, but it must not call Discord, Hindsight, Honcho, or the network.

## Validation

```bash
python3 -m unittest discover -s tests
```

The tests include a Hermes contract check against the real
`PluginContext.register_tool` / `register_hook` signatures when a local Hermes
checkout is available. Keep that coverage in place for registration changes.
