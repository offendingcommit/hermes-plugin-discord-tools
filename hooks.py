"""Hint-only hooks for discord-tools."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .tools import DISCORD_URL_RE

logger = logging.getLogger("discord-tools")


def _latest_user_text(**kwargs: Any) -> str:
    for key in ("user_text", "prompt", "message", "content"):
        value = kwargs.get(key)
        if isinstance(value, str) and value.strip():
            return value

    messages = kwargs.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and isinstance(content, str) and content.strip():
                return content
    return ""


def _load_story_hints(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    env = os.environ if env is None else env
    raw = env.get("DISCORD_TOOLS_STORY_HINTS") or env.get("DISCORD_TOOLS_STORY_HINTS_JSON") or ""
    raw = raw.strip()
    if not raw:
        return []

    if not raw.startswith(("{", "[")):
        try:
            raw = Path(raw).read_text(encoding="utf-8")
        except OSError:
            logger.debug("discord-tools: story hints path is unreadable")
            return []

    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.debug("discord-tools: story hints JSON is invalid")
        return []

    if isinstance(parsed, dict):
        parsed = parsed.get("hints") or []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _matched_story_hints(text: str, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    lowered = text.lower()
    matches: list[dict[str, Any]] = []
    for hint in _load_story_hints(env):
        keywords = hint.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        if any(str(keyword).lower() in lowered for keyword in keywords):
            matches.append(hint)
    return matches[:5]


def _render_hint(discord_links: list[str], story_hints: list[dict[str, Any]]) -> str:
    lines = [
        "## Discord source context",
        "",
        "Read-only Discord tools are available for channels, threads, and messages the bot can already access.",
    ]
    if discord_links:
        lines.append("Mentioned Discord links:")
        lines.extend(f"- {link}" for link in discord_links[:5])
        lines.append(
            "Use `discord_get_message`, `discord_read_thread`, or `discord_read_channel` before relying on stale memory."
        )
    if story_hints:
        lines.append("Relevant story hints:")
        for hint in story_hints:
            name = str(hint.get("name") or "story context")
            detail = str(hint.get("hint") or "Check Discord source context before answering.")
            lines.append(f"- {name}: {detail}")
    return "\n".join(lines)


def inject_discord_read_hint(**kwargs: Any) -> dict[str, str] | None:
    """pre_llm_call hook: hint that read-only Discord tools can inspect links.

    This hook does not call Discord or memory. It only reads the current turn and
    optional static story hint config from environment/file.
    """
    text = _latest_user_text(**kwargs)
    if not text:
        return None

    links = [match.group(0) for match in DISCORD_URL_RE.finditer(text)]
    env = kwargs.get("env") if isinstance(kwargs.get("env"), dict) else None
    story_hints = _matched_story_hints(text, env)
    if not links and not story_hints:
        return None

    logger.info(
        "discord-tools: injected hint links=%d story_hints=%d",
        len(links),
        len(story_hints),
    )
    return {"context": _render_hint(links, story_hints)}
