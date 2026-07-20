"""Transient OpenCode configuration for an isolated execution worker."""
from __future__ import annotations

import json
import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError


def _source_config_path() -> Path:
    explicit = os.environ.get("OPENCODE_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "opencode" / "opencode.json"


def build_execution_environment(*, model_id: str) -> dict[str, str]:
    """Return inline config without sharing the host config directory.

    OpenCode documents ``OPENCODE_CONFIG_CONTENT`` as its highest-precedence
    isolated configuration channel.  Preserve an explicitly supplied inline
    document; otherwise snapshot the host document before the worker receives
    its private HOME.  The value is transient child environment only.
    """
    inline = os.environ.get("OPENCODE_CONFIG_CONTENT")
    try:
        document = json.loads(inline) if inline else {}
        if not inline:
            source = _source_config_path()
            if source.is_file():
                document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AudiaGenticError(
            code="CFG-OPENC-001",
            kind="providers",
            message="OpenCode execution configuration could not be materialized",
        ) from exc
    if not isinstance(document, dict):
        raise AudiaGenticError(
            code="CFG-OPENC-001",
            kind="providers",
            message="OpenCode execution configuration must be a JSON object",
        )
    # OpenCode uses enabled_providers as a whitelist; when we pass inline config
    # via OPENCODE_CONFIG_CONTENT, missing enabled_providers causes opencode to
    # fall back to the machine's global config whitelist instead of failing —
    # silently running against whatever providers happen to be configured on
    # this machine, which has nothing to do with this project. A project with
    # no declared providers must fail loudly here, not inherit unrelated
    # global state (see the 2026-07-19 SH07 batch incident where a worker's
    # config probe clobbered the global whitelist and later launches silently
    # picked up the wrong providers).
    provider_map = document.get("provider")
    if not isinstance(provider_map, dict) or not provider_map:
        raise AudiaGenticError(
            code="CFG-OPENC-002",
            kind="providers",
            message="OpenCode execution configuration declares no providers",
        )
    document["enabled_providers"] = list(provider_map.keys())
    document["model"] = model_id
    return {
        "OPENCODE_CONFIG_CONTENT": json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        )
    }


__all__ = ["build_execution_environment"]
