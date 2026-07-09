"""Data models for operator interaction."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


DEFAULT_TTL_SECONDS = 8 * 60 * 60


class ResponseStatus(Enum):
    ANSWERED = "answered"
    DECLINED = "declined"
    TIMED_OUT = "timed_out"


@dataclass
class AskRequest:
    """A request sent to the user/operator for a decision."""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    choices: tuple[str, ...] = ()
    default_choice: str | None = None
    timeout_seconds: int = 30


@dataclass
class AskResponse:
    """Response to an ask request."""
    request_id: str = ""
    status: ResponseStatus = ResponseStatus.TIMED_OUT
    choice: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PushStatusMessage:
    """A one-way status update pushed to the operator."""
    component: str = ""
    level: str = "info"  # info, warning, error
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
