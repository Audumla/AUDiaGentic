"""Machine-local runtime defaults for local providers (the API key still comes from the environment)."""
from __future__ import annotations

import os

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error


def _local_config_error(message: str, **details: object) -> AudiaGenticError:
    return make_error(prefix="CFG", component="LOCAL", number=1, kind="local-runtime", message=message, details=details)


def local_provider_base_url(configured: object = None) -> str:
    """Resolve an explicit provider URL (from the provider's settings) or the OpenAI default."""
    value = configured or "https://api.openai.com"
    value = str(value).strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise _local_config_error("local provider base URL must use http:// or https://", value=value)
    return value


def local_provider_api_key(configured: object = None) -> str | None:
    """Resolve a local-provider key without ever placing it in project config."""
    return configured or os.environ.get("AUDIAGENTIC_LOCAL_PROVIDER_API_KEY") or os.environ.get("OPENAI_API_KEY")


__all__ = ["local_provider_api_key", "local_provider_base_url"]
