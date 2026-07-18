"""OpenCode catalog and probe functions."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any


def _opencode_probe(_descriptor) -> dict:
    from audiagentic.components.providers.adapters.probe import probe_cli_version
    return probe_cli_version("opencode", ["opencode", "--version"])


def _fetch_opencode_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch models via `opencode models --verbose`."""
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
                "vendor-id": model_key.partition("/")[0],
                "display-name": data.get("name", model_key),
                "status": status,
                "supports-structured-output": toolcall,
                "context-window": max(context, 1),
            })
        else:
            i += 1
    return models
