"""Provider session status — provider-agnostic session info interface.

RU02 / AS54: session component must not query rig internals directly.
Each provider harness implements this interface to resolve its own
session status data. Runtime injects the implementation; session uses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderSessionInfo:
    """Generic provider session status — resolved by harness-specific code, consumed by session component."""

    # Agent version info (always available from installed harness)
    agent_version: str | None = None
    mcp_adapter_version: str | None = None

    # Model configuration
    configured_model: str | None = None
    model_profile_name: str | None = None
    model_file: str | None = None

    # Harness server / endpoint
    server_version: str | None = None
    base_url: str | None = None
    endpoint_reachable: bool = False

    # Config details
    config_path: str | None = None
    models_data: dict[str, Any] | None = None

    # Harness-specific extensions (arbitrary extra fields per provider)
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionStatusResolver:
    """Resolves provider session status for a given harness.

    Each harness type (pi, opencode, etc.) provides its own resolver
    implementation that reads from the correct rig/config sources.
    The session component calls this — it never touches rig internals.
    """

    resolve: Any  # callable: (project_root: Path | None) -> ProviderSessionInfo
