"""Interaction backend abstraction and CLI implementation."""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from audiagentic.foundation.cli_io import print_error, print_message
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

    def __init__(self, *, quiet_status: bool | None = None) -> None:
        if quiet_status is None:
            import os

            quiet_status = os.environ.get("AUDIAGENTIC_QUIET_STATUS") == "1"
        self.quiet_status = quiet_status

    def ask(self, request: AskRequest) -> AskResponse:
        if not sys.stdout.isatty():
            return AskResponse(status=ResponseStatus.TIMED_OUT)
        try:
            if request.choices:
                print_message(f"\n{request.title}")
                if request.description:
                    print_message(f"  {request.description}")
                for i, c in enumerate(request.choices, 1):
                    print_message(f"  [{i}] {c}")
                default = request.default_choice
                if default:
                    idx = list(request.choices).index(default) + 1
                    print_message(f"  (default: [{idx}] {default})")
                else:
                    idx = 1
                    default = request.choices[0] if request.choices else ""
                    print_message(f"  (default: [{idx}] {default})")

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
                print_message(f"\n{request.title}")
                if request.description:
                    print_message(f"  {request.description}")
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
        if self.quiet_status and msg.level in {"debug", "info"}:
            return
        prefix = f"[{msg.component}] " if msg.component else ""
        print_error(f"{prefix}{msg.message}")

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


def current_backend() -> InteractionBackend | None:
    """Return the currently active backend, or None if unset."""
    return _backend


@contextmanager
def use_backend(backend: InteractionBackend) -> Iterator[None]:
    """Set the live backend for the duration of this context, then clear it.

    Formalizes the set_backend/clear_backend try-finally pair every test
    substituting a fake backend otherwise has to hand-write. Always clears
    on exit, including when the block raises.
    """
    set_backend(backend)
    try:
        yield
    finally:
        clear_backend()
