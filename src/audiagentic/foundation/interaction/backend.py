"""Interaction backend abstraction and CLI implementation."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from audiagentic.foundation.interaction.models import (
    AskRequest,
    AskResponse,
    PushStatusMessage,
    ResponseStatus,
)

logger = logging.getLogger(__name__)


class InteractionBackend(Protocol):
    """Different surfaces (CLI input, MCP elicitation) implement this."""

    def ask(self, request: AskRequest) -> AskResponse: ...
    def push_status(self, msg: PushStatusMessage) -> None: ...
    def respond(self, request_id: str, choice: str | None, *, details: dict[str, Any]) -> None: ...


class CliBackend:
    """Sync backend that uses sys.stdin/sys.stdout for interaction."""

    def ask(self, request: AskRequest) -> AskResponse:
        try:
            if request.choices:
                print(f"\n{request.title}")  # noqa: T201
                if request.description:
                    print(f"  {request.description}")  # noqa: T201
                for i, c in enumerate(request.choices, 1):
                    print(f"  [{i}] {c}")  # noqa: T201
                default = request.default_choice
                if default:
                    idx = list(request.choices).index(default) + 1
                    print(f"  (default: [{idx}] {default})")  # noqa: T201
                else:
                    idx = 1
                    default = request.choices[0] if request.choices else ""
                    print(f"  (default: [{idx}] {default})")  # noqa: T201

                raw = input("> ").strip()
                if not raw:
                    choice = default
                else:
                    try:
                        sel = int(raw) - 1
                        choice = request.choices[sel] if 0 <= sel < len(request.choices) else default
                    except ValueError:
                        choice = raw if raw in request.choices else default

                return AskResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.ANSWERED,
                    choice=choice or None,
                )
            else:
                print(f"\n{request.title}")  # noqa: T201
                if request.description:
                    print(f"  {request.description}")  # noqa: T201
                raw = input("> ").strip()
                return AskResponse(
                    request_id=request.request_id,
                    status=ResponseStatus.ANSWERED if raw else ResponseStatus.DECLINED,
                    choice=raw or None,
                )
        except (EOFError, KeyboardInterrupt):
            return AskResponse(status=ResponseStatus.TIMED_OUT)
        except Exception:
            logger.debug("CLI ask failed", exc_info=True)
            return AskResponse(status=ResponseStatus.TIMED_OUT)

    def push_status(self, msg: PushStatusMessage) -> None:
        prefix = f"[{msg.component}] " if msg.component else ""
        print(f"{prefix}{msg.message}")  # noqa: T201

    def respond(self, request_id: str, choice: str | None, *, details: dict[str, Any]) -> None:
        pass


# ── Global backend ─────────────────────────────────────────────────────────

_backend: InteractionBackend | None = None


def set_backend(backend: InteractionBackend) -> None:
    """Set the live interaction backend. Call once at harness startup."""
    global _backend
    _backend = backend


def clear_backend() -> None:
    """Clear the backend. Useful for test teardown."""
    global _backend
    _backend = None
