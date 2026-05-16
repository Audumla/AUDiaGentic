"""Provider registry — importing this package registers all built-in providers."""

from __future__ import annotations

import importlib

from . import (
    aider,
    claude,
    cline,
    codex,
    copilot,
    gemini,
    goose,
    local_openai,
    opencode,
    openhands,
    pi,
    qwen,
    roo,
)

__all__ = [
    "aider", "claude", "cline", "codex", "continue_", "copilot",
    "gemini", "goose", "local_openai", "openhands", "opencode", "pi", "roo", "qwen",
]

continue_ = importlib.import_module(".continue", __name__)

_ = (aider, claude, cline, codex, continue_, copilot, gemini, goose, local_openai, openhands, opencode, pi, roo, qwen)
