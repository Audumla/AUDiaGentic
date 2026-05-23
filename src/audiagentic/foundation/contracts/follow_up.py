"""Generic follow-up action contracts.

These payloads are harness-neutral. Components may suggest a follow-up action,
but they do not decide how any specific harness asks the user or executes it.
"""
from __future__ import annotations

from typing import Any


def build_confirmable_handler_follow_up(
    *,
    title: str,
    message: str,
    handler: str,
    kwargs: dict[str, Any] | None = None,
    id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "confirmable_handler_call",
        "title": title,
        "message": message,
        "target": {
            "handler": handler,
            "kwargs": kwargs or {},
        },
    }
    if id:
        payload["id"] = id
    return payload

