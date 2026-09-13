"""Environment overrides for machine-local runtime settings."""
from __future__ import annotations

import os

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_RIG_PORT = 42001


def _local_config_error(message: str, **details: object) -> AudiaGenticError:
    return make_error(prefix="CFG", component="LOCAL", number=1, kind="local-runtime", message=message, details=details)


def local_rig_host() -> str:
    value = os.environ.get("AUDIAGENTIC_RIG_HOST", DEFAULT_LOCAL_HOST).strip()
    if not value or any(ch in value for ch in " /\\\t\r\n"):
        raise _local_config_error("AUDIAGENTIC_RIG_HOST must be a host name or IP address", value=value)
    return value


def local_rig_port(configured: object = None, *, use_env: bool = True) -> int:
    raw = (os.environ.get("AUDIAGENTIC_RIG_PORT") if use_env else None) or (configured if configured is not None else DEFAULT_RIG_PORT)
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise _local_config_error("AUDIAGENTIC_RIG_PORT must be an integer", value=raw) from exc
    if not 1 <= port <= 65535:
        raise _local_config_error("AUDIAGENTIC_RIG_PORT must be between 1 and 65535", value=raw)
    return port


def local_provider_base_url(configured: object = None) -> str:
    """Resolve an explicit provider URL or the machine-local environment fallback."""
    value = configured or os.environ.get("AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL") or "https://api.openai.com"
    value = str(value).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise _local_config_error("local provider base URL must use http:// or https://", value=value)
    return value


def local_provider_api_key(configured: object = None) -> str | None:
    """Resolve a local-provider key without ever placing it in project config."""
    return configured or os.environ.get("AUDIAGENTIC_LOCAL_PROVIDER_API_KEY") or os.environ.get("OPENAI_API_KEY")


__all__ = ["DEFAULT_LOCAL_HOST", "DEFAULT_RIG_PORT", "local_provider_api_key", "local_provider_base_url", "local_rig_host", "local_rig_port"]
