"""Hindsight backend config export — provider-agnostic data only.

The memory component exports active backend configuration as
:class:`HindsightBackendConfig`. The Hindsight implementation package consumes
this to build harness-specific integration recipes through generic provider
seams. Memory core owns only backend identity: base URL, transport, and auth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HindsightBackendConfig:
    """Provider-agnostic Hindsight backend identity exported by memory component.

    Memory core owns ONLY backend identity; it names no providers and writes no
    provider paths. The Hindsight implementation consumes this dataclass to
    build its contained provider-facing recipes.
    """

    base_url: str
    transport: str = "http"  # "http" | "sse" | "stdio"
    api_key: str | None = None
    bank_id: str | None = None
    timeout_seconds: int = 30
    server_name: str = "hindsight"

    @property
    def mcp_url(self) -> str:
        """Return the MCP endpoint URL (base_url with /mcp appended)."""
        url = self.base_url.rstrip("/")
        if url.endswith("/mcp"):
            return url
        return url + "/mcp"

    def headers(self) -> dict[str, str]:
        """Return HTTP headers for authenticating with the Hindsight server.

        Returns empty dict if no auth is configured.
        """
        result: dict[str, str] = {}
        if self.api_key:
            result["Authorization"] = f"Bearer {self.api_key}"
        if self.bank_id:
            result["X-Bank-Id"] = self.bank_id
        return result


def build_hindsight_backend(project_root: Path) -> HindsightBackendConfig | None:
    """Build HindsightBackendConfig from active memory implementation state.

    Reads the active implementation via _active_implementation_id, constructs
    the backend config from its options. Returns None when base-url is empty
    or unset.

    This is the canonical entry point for Hindsight implementation recipes to
    obtain backend config.
    """
    from audiagentic.foundation.features.state import get_implementation_state

    project_root = Path(project_root)
    active_impl = _active_implementation_id(project_root)
    if not active_impl:
        return None

    impl_state = get_implementation_state(project_root, "memory", active_impl)
    if not impl_state.options:
        return None

    config = dict(impl_state.options)
    base_url = config.get("base-url") or config.get("base_url", "")
    if not base_url:
        return None

    return HindsightBackendConfig(
        base_url=base_url,
        transport=config.get("transport", "http"),
        api_key=config.get("api-key"),
        bank_id=config.get("bank-id"),
        timeout_seconds=config.get("timeout-seconds", 30),
    )


def _active_implementation_id(project_root: Path) -> str:
    """Return the enabled implementation ID, or the first registered default."""
    from audiagentic.foundation.features.registry import get_implementations
    from audiagentic.foundation.features.state import get_component_state

    component = get_component_state(project_root, "memory")
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for impl_id, state in implementations.items():
            if isinstance(state, dict) and state.get("enabled"):
                return impl_id
    impls = get_implementations("memory")
    for impl_id in sorted(impls):
        if impls[impl_id].raw.get("default"):
            return impl_id
    return next(iter(sorted(impls)), "")


__all__ = [
    "HindsightBackendConfig",
    "build_hindsight_backend",
]
