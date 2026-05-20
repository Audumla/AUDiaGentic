"""Provider adapter implementations for all supported AI providers."""

from __future__ import annotations

from . import (
    aider,
    claude,
    cline,
    codex,
    continue_,
    copilot,
    gemini,
    goose,
    local_openai,
    opencode,
    openhands,
    pi,
    plandex,
    qwen,
    roo,
)

__all__ = [
    "aider", "claude", "cline", "codex", "continue_", "copilot",
    "gemini", "goose", "local_openai", "openhands", "opencode", "pi", "plandex", "roo", "qwen",
]

_ = (aider, claude, cline, codex, continue_, copilot, gemini, goose, local_openai, openhands, opencode, pi, plandex, roo, qwen)
