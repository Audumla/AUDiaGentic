"""Provider LSP routing policy.

Determines which providers use the enhanced generic LSP MCP tools, their native
LSP, or a hybrid of both. Defaults from the plan's Provider Capability Mapping.
"""
from __future__ import annotations

from typing import Any

# Routing modes
ROUTING_NATIVE = "native"
ROUTING_MCP = "mcp"
ROUTING_HYBRID = "hybrid"
ROUTING_NONE = "none"

# Default routing per provider (from plan's Provider Capability Mapping)
_DEFAULT_ROUTING: dict[str, str] = {
    # Providers with no MCP — no LSP routing
    "aider": ROUTING_NONE,
    "local-openai": ROUTING_NONE,
    "openhands": ROUTING_NONE,
    "plandex": ROUTING_NONE,

    # Providers with native LSP config — prefer native for v1
    "opencode": ROUTING_NATIVE,
    "qwen": ROUTING_NATIVE,

    # Providers with native LSP config — prefer enhanced MCP
    "codex": ROUTING_MCP,

    # Providers with pi-lens — use pi-lens
    "pi": ROUTING_NATIVE,

    # Providers with MCP but no native LSP — use enhanced MCP
    "claude": ROUTING_MCP,
    "cline": ROUTING_MCP,
    "continue": ROUTING_MCP,
    "copilot": ROUTING_MCP,
    "gemini": ROUTING_MCP,
    "goose": ROUTING_MCP,
    "roo": ROUTING_MCP,
}


def get_routing_policy(provider: str) -> str:
    """Get the routing mode for a provider.

    Returns one of: native, mcp, hybrid, none.
    Unknown providers default to mcp (safe fallback).
    """
    return _DEFAULT_ROUTING.get(provider, ROUTING_MCP)


def get_routing_summary() -> dict[str, dict[str, Any]]:
    """Get routing decision for all known providers.

    Returns dict mapping provider name to {mode, reason}.
    """
    reasons: dict[str, dict[str, Any]] = {}
    for provider, mode in _DEFAULT_ROUTING.items():
        if mode == ROUTING_NATIVE:
            reason = "provider has native LSP config; prefer native for v1"
        elif mode == ROUTING_MCP:
            reason = "provider supports MCP; use enhanced coding-lsp tools"
        elif mode == ROUTING_HYBRID:
            reason = "provider has native LSP; enhanced tools fill gaps"
        else:
            reason = "provider lacks MCP support; no LSP routing"
        reasons[provider] = {"mode": mode, "reason": reason}
    return reasons


def should_include_mcp(provider: str) -> bool:
    """Check if the enhanced LSP MCP should be included for a provider."""
    mode = get_routing_policy(provider)
    return mode in (ROUTING_MCP, ROUTING_HYBRID)
