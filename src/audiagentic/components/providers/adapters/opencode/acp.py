"""OpenCode-specific launch declaration for shared ACP transport."""

from __future__ import annotations

import json
import os
from pathlib import Path

from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.foundation.transports import AcpLaunch


def _resolve_env_placeholders(value):
    if isinstance(value, str) and value.startswith("{env:") and value.endswith("}"):
        return os.environ.get(value[5:-1], "")
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    return value


def build_acp_launch(project_root: Path, *, model_id: str | None = None) -> AcpLaunch:
    environment = {}
    if model_id:
        # OpenCode documents inline config as highest-precedence runtime config.
        # Snapshot the project config so session workers do not fall through to
        # user-global auth/config when the provider was materialized locally.
        config_path = project_root / ".opencode" / "opencode.json"
        document = {}
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    document = loaded
            except (OSError, json.JSONDecodeError):
                document = {}
        document.pop("providers", None)
        resolved = _resolve_env_placeholders(document)
        # OpenCode uses enabled_providers as a whitelist; when we pass inline config
        # via OPENCODE_CONFIG_CONTENT, missing enabled_providers causes opencode to
        # fall back to the global config's whitelist which blocks our custom provider.
        if isinstance(resolved, dict):
            document = resolved
            provider_map = document.get("provider")
            if isinstance(provider_map, dict):
                document["enabled_providers"] = list(provider_map.keys())
        document["model"] = model_id
        environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(document)
    return AcpLaunch(
        executable=require_executable("opencode", "opencode"),
        args=("acp", "--cwd", str(project_root.resolve())),
        environment=environment,
    )
