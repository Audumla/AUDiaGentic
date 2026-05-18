from __future__ import annotations

import json
import subprocess
from typing import Any

from audiagentic.foundation.invoke.toolchains import npm

from ..descriptors.base import (
    AgentFile,
    CliInstallRecipe,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
)
from ..descriptors.registry import register

# Known context windows for Anthropic models (fallback when CLI omits them).
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
}


def _context_for(model_id: str) -> int:
    for prefix, ctx in _CONTEXT_WINDOWS.items():
        if model_id.startswith(prefix):
            return ctx
    return 200_000  # safe default for Anthropic models


def _fetch_claude_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch models via `claude models --output-format json`.

    Claude Code CLI returns a JSON array of model objects with fields:
      id, display_name, created_at (and optionally context_window).
    """
    try:
        result = subprocess.run(
            subprocess.list2cmdline(["claude", "models", "--output-format", "json"]),
            shell=True, capture_output=True, text=True, timeout=30, check=False,
        )
    except OSError:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    # API returns {"data": [...]} or bare array
    entries = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    models: list[dict[str, Any]] = []
    for entry in entries:
        model_id = entry.get("id") or entry.get("model_id", "")
        if not model_id:
            continue
        display_name = entry.get("display_name") or entry.get("name") or model_id
        ctx = entry.get("context_window") or _context_for(model_id)
        models.append({
            "model-id": model_id,
            "display-name": display_name,
            "status": "active",
            "supports-structured-output": True,
            "context-window": max(int(ctx), 1),
        })
    return models


register(ProviderDescriptor(
    provider_id="claude",
    display_name="Claude (Anthropic)",
    description="Anthropic's Claude Code CLI. Agentic coding assistant with deep codebase understanding and MCP tool use.",
    url="https://claude.ai/code",
    cli_probe=["claude", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="@anthropic-ai/claude-code",
        executable="claude",
        install=npm.install("@anthropic-ai/claude-code"),
        uninstall=npm.uninstall("@anthropic-ai/claude-code"),
    ),
    vscode_extensions=(
        VsCodeExtension("anthropic.claude-code", "Claude Code"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=True,
        can_read_env=True,
        notes="Full project access via tool use; bash, file read/write, web fetch",
    ),
    agent_files=(
        AgentFile("CLAUDE.md", managed=True, description="Project instructions / system prompt"),
        AgentFile(".claude/rules/prompt-tags.md", managed=True, description="Canonical prompt tag rules"),
        AgentFile(".claude/settings.json", managed=False, description="Claude Code user settings"),
    ),
    fetch_catalog_fn=_fetch_claude_catalog,
))
