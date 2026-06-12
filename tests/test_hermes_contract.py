"""Contract tests: the plugin must satisfy the hermes-agent plugin API.

Two layers:

1. Standalone (always runs, stdlib + PyYAML only). A ``ContractCtx`` mirrors the
   *exact* ``PluginContext.register_tool`` / ``register_hook`` signatures from
   hermes-agent — no ``**kwargs`` catch-all — so any drift in how this plugin
   calls them surfaces as a ``TypeError`` here instead of at runtime. Handler and
   hook calling-conventions and plugin.yaml<->registration parity are checked the
   same way the live runtime would exercise them.

2. Against the real hermes-agent (skipped when it is not importable). The plugin's
   actual ``register()`` calls are bound to the genuine ``inspect.signature`` of
   ``PluginContext.register_tool`` / ``register_hook``, and the locally-mirrored
   hook set is cross-checked against the real ``VALID_HOOKS``.

The runtime contract, captured from hermes_cli/plugins.py and tools/registry.py:

    register_tool(name, toolset, schema, handler, check_fn=None,
                  requires_env=None, is_async=False, description="", emoji="")
    register_hook(hook_name, callback)            # hook_name in VALID_HOOKS
    handler(args, **kwargs) -> str                # positional args dict + kwargs
    callback(**kwargs) -> None | dict | str       # kwargs only, never positional
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML is optional — only the manifest-parity test needs it.
    yaml = None

from hermes_plugin_loader import load_plugin_module

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# Mirror of hermes_cli.plugins.VALID_HOOKS. The optional real-runtime test below
# asserts this stays in sync with the genuine set.
VALID_HOOKS = {
    "pre_tool_call",
    "post_tool_call",
    "pre_llm_call",
    "post_llm_call",
    "pre_api_request",
    "post_api_request",
    "on_session_start",
    "on_session_end",
    "on_session_finalize",
    "on_session_reset",
}


class ContractCtx:
    """A PluginContext stand-in whose method signatures match hermes exactly.

    Because the signatures carry the real parameter names and *no* ``**kwargs``
    sink, a call that passes an unknown keyword or drops a required positional
    raises ``TypeError`` at registration time — which is the point.
    """

    def __init__(self) -> None:
        self.tool_calls: list[dict] = []
        self.hook_calls: list[tuple[str, object]] = []

    def register_tool(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler,
        check_fn=None,
        requires_env: list | None = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
    ) -> None:
        self.tool_calls.append(
            {
                "name": name,
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
                "check_fn": check_fn,
                "requires_env": requires_env,
                "is_async": is_async,
                "description": description,
                "emoji": emoji,
            }
        )

    def register_hook(self, hook_name: str, callback) -> None:
        self.hook_calls.append((hook_name, callback))


def _cleared_token_env():
    """Context-managed os.environ with all Discord token vars removed (offline)."""

    class _Ctx:
        def __enter__(self):
            self._old = dict(os.environ)
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            os.environ.pop("DISCORD_TOKEN", None)
            return os.environ

        def __exit__(self, *exc):
            os.environ.clear()
            os.environ.update(self._old)

    return _Ctx()


class StandaloneContractTests(unittest.TestCase):
    """Run with only stdlib + PyYAML — no hermes-agent on the path."""

    def setUp(self) -> None:
        self.plugin = load_plugin_module()
        self.ctx = ContractCtx()
        self.plugin.register(self.ctx)

    # -- registration shape --------------------------------------------------

    def test_register_binds_to_real_tool_signature(self) -> None:
        # register() ran in setUp through ContractCtx without TypeError, which
        # already proves signature compatibility. Assert the surface explicitly.
        names = {c["name"] for c in self.ctx.tool_calls}
        self.assertEqual(
            names,
            {"discord_read_channel", "discord_read_thread", "discord_get_message"},
        )
        for call in self.ctx.tool_calls:
            self.assertEqual(call["toolset"], "messaging")
            self.assertIsInstance(call["schema"], dict)
            self.assertEqual(call["schema"].get("type"), "object")
            self.assertTrue(callable(call["handler"]))
            self.assertFalse(call["is_async"], "sync handlers must register is_async=False")
            self.assertIn("DISCORD_BOT_TOKEN", call["requires_env"] or [])
            self.assertTrue(call["description"])

    def test_registers_exactly_one_valid_hook(self) -> None:
        self.assertEqual(len(self.ctx.hook_calls), 1)
        hook_name, callback = self.ctx.hook_calls[0]
        self.assertEqual(hook_name, "pre_llm_call")
        self.assertIn(hook_name, VALID_HOOKS)
        self.assertTrue(callable(callback))

    # -- tool handler calling convention: handler(args, **kwargs) -> str -----

    def test_tool_handlers_accept_args_dict_plus_kwargs_and_return_json(self) -> None:
        sample_args = {
            "discord_read_channel": {"channel_id_or_url": "1" * 18},
            "discord_read_thread": {"thread_id_or_url": "1" * 18},
            "discord_get_message": {
                "message_id_or_url": "https://discord.com/channels/1/2/3"
            },
        }
        with _cleared_token_env():
            for call in self.ctx.tool_calls:
                handler = call["handler"]
                # hermes invokes handlers as handler(args, **kwargs); extra
                # kwargs (agent/session ids) must be tolerated, not crash.
                raw = handler(
                    sample_args[call["name"]],
                    agent_id="agent-x",
                    session_id="sess-y",
                )
                self.assertIsInstance(raw, str, f"{call['name']} must return a str")
                decoded = json.loads(raw)
                self.assertIn("success", decoded)
                # No token in env -> in-band failure, never an exception.
                self.assertFalse(decoded["success"])
                self.assertIn("DISCORD_BOT_TOKEN", decoded["error"])

    def test_tool_handler_signature_is_args_then_var_kwargs(self) -> None:
        for call in self.ctx.tool_calls:
            params = list(inspect.signature(call["handler"]).parameters.values())
            self.assertGreaterEqual(len(params), 1, "handler needs an args parameter")
            self.assertIn(
                params[0].kind,
                (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD),
                "first handler param must accept the positional args dict",
            )
            self.assertTrue(
                any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params),
                "handler must accept **kwargs so runtime-injected keys are tolerated",
            )

    # -- hook calling convention: callback(**kwargs) -> None | dict | str ----

    def test_hook_is_keyword_only_and_returns_contract_types(self) -> None:
        _, callback = self.ctx.hook_calls[0]

        # kwargs-only: hermes never calls the hook positionally.
        with self.assertRaises(TypeError):
            callback("a positional argument")

        # Empty invocation must be safe and yield no injection.
        self.assertIsNone(callback())

        # A turn mentioning a Discord link yields a context dict[str, str].
        result = callback(
            messages=[
                {"role": "user", "content": "see https://discord.com/channels/1/2/3"}
            ]
        )
        self.assertIsInstance(result, dict)
        self.assertIsInstance(result.get("context"), str)

    # -- plugin.yaml <-> registration parity ---------------------------------

    @unittest.skipUnless(yaml is not None, "PyYAML not installed")
    def test_manifest_matches_registration(self) -> None:
        manifest = yaml.safe_load((PLUGIN_ROOT / "plugin.yaml").read_text())

        registered_tools = {c["name"] for c in self.ctx.tool_calls}
        registered_hooks = {h for h, _ in self.ctx.hook_calls}
        self.assertEqual(set(manifest["provides_tools"]), registered_tools)
        self.assertEqual(set(manifest["provides_hooks"]), registered_hooks)

        # Every env a tool requires must be declared in the manifest.
        manifest_env = set()
        for entry in manifest.get("requires_env", []):
            manifest_env.add(entry["name"] if isinstance(entry, dict) else entry)
        for call in self.ctx.tool_calls:
            for env_name in call["requires_env"] or []:
                self.assertIn(env_name, manifest_env)


# ---------------------------------------------------------------------------
# Optional layer: validate against the genuine hermes-agent contract.
# ---------------------------------------------------------------------------

def _import_real_hermes():
    """Return (PluginContext, VALID_HOOKS) from hermes-agent, or None.

    Discovery order: an already-importable ``hermes_cli``; then ``HERMES_AGENT_PATH``;
    then a couple of conventional checkout locations. Import failures (missing
    runtime, missing deps) collapse to None so the suite stays green standalone.
    """
    candidates: list[Path] = []
    env_path = os.environ.get("HERMES_AGENT_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / "hermes-agent")
    candidates.append(Path.home() / ".hermes" / "hermes-agent")

    def _try():
        from hermes_cli.plugins import PluginContext, VALID_HOOKS  # type: ignore

        return PluginContext, VALID_HOOKS

    try:
        return _try()
    except Exception:
        pass

    for root in candidates:
        if not (root / "hermes_cli" / "plugins.py").exists():
            continue
        sys.path.insert(0, str(root))
        try:
            return _try()
        except Exception:
            continue
    return None


_REAL = _import_real_hermes()


@unittest.skipUnless(_REAL is not None, "hermes-agent runtime not importable")
class RealHermesContractTests(unittest.TestCase):
    """Bind the plugin's real register() calls against the genuine API."""

    def setUp(self) -> None:
        self.plugin = load_plugin_module()
        self.ctx = ContractCtx()
        self.plugin.register(self.ctx)
        self.PluginContext, self.real_valid_hooks = _REAL  # type: ignore[misc]

    def test_local_valid_hooks_match_runtime(self) -> None:
        self.assertEqual(
            VALID_HOOKS,
            set(self.real_valid_hooks),
            "VALID_HOOKS mirror has drifted from hermes-agent",
        )

    def test_tool_calls_bind_to_real_register_tool(self) -> None:
        sig = inspect.signature(self.PluginContext.register_tool)
        for call in self.ctx.tool_calls:
            # Drop the bookkeeping ContractCtx added; pass exactly what the
            # plugin specified, plus a placeholder self.
            kwargs = {k: v for k, v in call.items()}
            try:
                sig.bind(None, **kwargs)
            except TypeError as exc:  # pragma: no cover - failure path
                self.fail(f"{call['name']} does not match register_tool: {exc}")

    def test_hook_calls_bind_to_real_register_hook(self) -> None:
        sig = inspect.signature(self.PluginContext.register_hook)
        for hook_name, callback in self.ctx.hook_calls:
            try:
                sig.bind(None, hook_name, callback)
            except TypeError as exc:  # pragma: no cover - failure path
                self.fail(f"register_hook contract mismatch: {exc}")
            self.assertIn(hook_name, self.real_valid_hooks)


if __name__ == "__main__":
    unittest.main()
