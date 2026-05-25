from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_utc_iso() -> str:
    return now_utc().date().isoformat()
def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    )
