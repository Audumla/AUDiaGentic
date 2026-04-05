from __future__ import annotations

from . import claude, cline, codex, gemini, opencode
from .base import ProviderSurfaceRenderer


def load_renderer_registry() -> dict[str, ProviderSurfaceRenderer]:
    return {
        "claude": claude.render,
        "codex": codex.render,
        "cline": cline.render,
        "gemini": gemini.render,
        "opencode": opencode.render,
    }
