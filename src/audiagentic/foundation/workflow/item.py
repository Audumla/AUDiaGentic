from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ItemView:
    """Neutral DTO for workflow items."""

    kind: str
    path: Path
    data: dict[str, Any]
    body: str
