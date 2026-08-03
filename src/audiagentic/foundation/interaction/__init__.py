"""Operator interaction — live ask, durable store, and push-status.

Public API:
    ask, ask_async, push_status, request, respond, get_response
    CliBackend, set_backend, clear_backend
    ResponseStatus, AskRequest, AskResponse, PushStatusMessage
    interactions_root, interaction_path
"""
from audiagentic.foundation.interaction.api import (
    ask,
    get_response,
    push_status,
    request,
    respond,
)
from audiagentic.foundation.interaction.backend import (
    CliBackend,
    clear_backend,
    set_backend,
)
from audiagentic.foundation.interaction.mcp import ask_async
from audiagentic.foundation.interaction.models import (
    AskRequest,
    AskResponse,
    PushStatusMessage,
    ResponseStatus,
)
from audiagentic.foundation.interaction.store import (
    interaction_path,
    interactions_root,
    read_record,
    write_record,
)

__all__ = [
    "CliBackend",
    "AskRequest",
    "AskResponse",
    "PushStatusMessage",
    "ResponseStatus",
    "ask",
    "ask_async",
    "push_status",
    "request",
    "respond",
    "get_response",
    "set_backend",
    "clear_backend",
    "interactions_root",
    "interaction_path",
    "read_record",
    "write_record",
]
