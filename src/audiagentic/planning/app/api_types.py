from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ItemView:
    kind: str
    path: Path
    data: dict[str, Any]
    body: str
