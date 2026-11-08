# hermes-plugin-discord-tools

Discord reading tools, plus three channel-scoped actions, for Hermes
Discord-facing agents.

## Current surface

- `discord_read_channel`, `discord_read_thread`, `discord_get_message`, and
  `discord_read_story` (toolset `messaging`) return JSON and only read Discord
  content the configured bot token can already access.
- `discord_list_emojis`, `discord_react`, and `discord_send_embed` (toolset
  `discord`, in `actions.py`) are the only write paths. They act only in the
  channel the bot is replying in, taken from the Hermes session
  (`HERMES_SESSION_*`), never from model arguments.
- `discord_read_story` reads preconfigured story threads from
  `DISCORD_TOOLS_STORY_THREADS_JSON` or `DISCORD_TOOLS_STORY_THREAD_ID`; keep
  that configuration static and env/file backed.
- The plugin registers one `pre_llm_call` hint hook and no write hooks,
  commands, skills, or memory integrations.

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
- The shared kit contract lives at:
  https://github.com/offendingcommit/hermes-plugin-kit

## Validation

```bash
make install
make test
```

Run the real-Hermes layer too when a Hermes checkout is at hand:
`HERMES_AGENT_PATH=<checkout> make test`. It binds sessions with Hermes' own
`set_session_vars` and registers into its real registry and toolsets.

The tests include a Hermes contract check against the real
`PluginContext.register_tool` / `register_hook` signatures when a local Hermes
checkout is available. Registration tests also reject direct lifecycle wiring
and assert the exact kit summary. Keep that coverage in place for registration
changes.
Dev tooling is uv-native; dependencies live in `pyproject.toml`.
