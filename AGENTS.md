# hermes-plugin-discord-tools

Read-only Discord inspection tools for Hermes Discord-facing agents.

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
