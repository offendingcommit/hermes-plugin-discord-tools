from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def load_plugin_module():
    parent_name = "hermes_plugins"
    module_name = "hermes_plugins.discord_tools"
    if parent_name not in sys.modules:
        parent = types.ModuleType(parent_name)
        parent.__path__ = []  # type: ignore[attr-defined]
        sys.modules[parent_name] = parent

    for name in list(sys.modules):
        if name == module_name or name.startswith(module_name + "."):
            sys.modules.pop(name, None)

    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load discord-tools plugin")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
