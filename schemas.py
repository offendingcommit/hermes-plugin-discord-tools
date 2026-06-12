"""Tunable constants for discord-tools.

Tool schemas now live on the ``@tool`` decorators in ``tools.py`` (built via
hermes-plugin-kit, which guarantees the ``parameters`` wrapper). This module
keeps only the numeric limits shared across the impl functions.
"""

from __future__ import annotations

DEFAULT_MAX_MESSAGES = 100
MAX_MAX_MESSAGES = 100
DEFAULT_CONTEXT_LIMIT = 25
MAX_CONTEXT_LIMIT = 50
DEFAULT_MAX_CHARS = 12000
MAX_MAX_CHARS = 30000
DEFAULT_TIMEOUT_SECONDS = 20.0
