"""Typed provider family contracts."""

from .harness_status_observer import HarnessStatusObserverCapability
from .conversation_focus import (
    ConversationFocusLocator,
    ConversationFocusOutcome,
    ConversationFocusResult,
)
from .language_server_projection import (
    LanguageServerEntry,
    LanguageServerProjectionMode,
    LanguageServerProjectionRequest,
    LanguageServerProjectionResult,
)
from .managed_mcp import (
    ManagedMcpEntry,
    ManagedMcpMode,
    ManagedMcpRequest,
    ManagedMcpResult,
)
from .plugin_entry import PluginEntryMode, PluginEntryRequest, PluginEntryResult
from .session_surface import ResolvedSessionSurface, SurfaceHint

__all__ = [
    # AS19 harness status observer capability descriptor
    "HarnessStatusObserverCapability",
    "ConversationFocusLocator",
    "ConversationFocusOutcome",
    "ConversationFocusResult",
    "LanguageServerEntry",
    "LanguageServerProjectionMode",
    "LanguageServerProjectionRequest",
    "LanguageServerProjectionResult",
    "ManagedMcpEntry",
    "ManagedMcpMode",
    "ManagedMcpRequest",
    "ManagedMcpResult",
    "PluginEntryMode",
    "PluginEntryRequest",
    "PluginEntryResult",
    "ResolvedSessionSurface",
    "SurfaceHint",
]
