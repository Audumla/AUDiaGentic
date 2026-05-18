from __future__ import annotations

import json
import re
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


def _fetch_opencode_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch models via `opencode models --verbose`.

    Output format: each model is a line `providerID/modelID` followed by a JSON block.
    """
    try:
        result = subprocess.run(
            subprocess.list2cmdline(["opencode", "models", "--verbose"]),
            shell=True, capture_output=True, text=True, timeout=30, check=False,
        )
    except OSError:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    models: list[dict[str, Any]] = []
    lines = result.stdout.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # header line: "providerID/modelID"
        if re.match(r"^[^\s{}\[\]]+/[^\s{}\[\]]+$", line):
            model_key = line
            json_lines: list[str] = []
            i += 1
            depth = 0
            while i < len(lines):
                json_lines.append(lines[i])
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
                if depth == 0 and json_lines:
                    break
            try:
                data = json.loads("\n".join(json_lines))
            except (json.JSONDecodeError, ValueError):
                continue
            context = data.get("limit", {}).get("context", 0) or 0
            toolcall = bool(data.get("capabilities", {}).get("toolcall", False))
            raw_status = data.get("status", "active")
            status = "active" if raw_status == "active" else "deprecated"
            models.append({
                "model-id": model_key,
                "display-name": data.get("name", model_key),
                "status": status,
                "supports-structured-output": toolcall,
                "context-window": max(context, 1),
            })
        else:
            i += 1
    return models


register(ProviderDescriptor(
    provider_id="opencode",
    display_name="OpenCode",
    description="Terminal-based AI coding assistant. Supports multiple LLM providers via a unified CLI.",
    url="https://opencode.ai",
    cli_probe=["opencode", "--version"],
    cli_install=CliInstallRecipe(
        package_manager="npm",
        package_name="opencode-ai",
        executable="opencode",
        install=npm.install("opencode-ai"),
        uninstall=npm.uninstall("opencode-ai"),
    ),
    vscode_extensions=(
        VsCodeExtension("sst-dev.opencode", "OpenCode"),
    ),
    permissions=ProviderPermissions(
        can_write_files=True,
        can_execute_shell=True,
        can_browse_web=False,
        can_read_env=True,
        notes="CLI agent; multi-provider backend, full tool use",
    ),
    agent_files=(
        AgentFile("AGENTS.md", managed=False, description="OpenCode project instructions"),
    ),
    fetch_catalog_fn=_fetch_opencode_catalog,
))
