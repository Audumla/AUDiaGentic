from __future__ import annotations

import json
import subprocess
from typing import Any

from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)

from ...descriptors.base import (
    AgentFile,
    McpConfigSpec,
    ProviderDescriptor,
    ProviderPermissions,
    VsCodeExtension,
    cli_recipe,
)
from ...descriptors.registry import register


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
        if result.returncode != 0 or not result.stdout.strip():
            return []
        raw = json.loads(result.stdout)
    except (OSError, json.JSONDecodeError):
        return []

    entries = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    result = []
    for entry in entries:
        model_id = entry.get("id") or entry.get("model_id", "")
        if not model_id:
            continue
        result.append({
            "model-id": model_id,
            "display-name": entry.get("display_name") or entry.get("name") or model_id,
            "status": "active",
            "supports-structured-output": True,
            "context-window": max(int(entry.get("context_window") or 200_000), 1),
        })
    return result


register(ProviderDescriptor(
    provider_id="claude",
    prompt_aliases=("cld",),
    display_name="Claude (Anthropic)",
    description="Anthropic's Claude Code CLI. Agentic coding assistant with deep codebase understanding and MCP tool use.",
    url="https://claude.ai/code",
    cli_probe=["claude", "--version"],
    cli_install=cli_recipe("npm", "@anthropic-ai/claude-code", executable="claude"),
    host_capabilities=(
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
    instruction_file="CLAUDE.md",
    skill_surface_path=".claude/skills/{tag}/SKILL.md",
    fetch_catalog_fn=_fetch_claude_catalog,
    mcp_config=McpConfigSpec(
        config_path=".mcp.json",
        reader=read_mcp_json,
        writer=write_mcp_json,
        remover=remove_mcp_json,
        format="mcp-json",
        refresh_mode="file-watch",
    ),
))
