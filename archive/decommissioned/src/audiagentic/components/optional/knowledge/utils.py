from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_utc_iso() -> str:
    return now_utc().date().isoformat()
def load_yaml_file(path: Path, default: Any = None) -> Any:
    """Read a YAML file and return its contents, or default if the file is absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    loaded = yaml.safe_load(text)
    return loaded if loaded is not None else default


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    )
