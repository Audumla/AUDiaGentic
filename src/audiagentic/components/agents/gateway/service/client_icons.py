"""Gateway-owned cycling client badges; never expose client identity."""
import hashlib
import json
from pathlib import Path

from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock

_ASSETS = Path(__file__).with_suffix("")
ICON_COUNT = 24


def assign_client_icon(service_root: Path, client_id: str) -> int:
    key = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    path = service_root / "client-icons.json"
    with StartupLock(path.with_suffix(".lock")):
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"next": 0, "clients": {}}
        if key not in state["clients"]:
            state["clients"][key] = state["next"] % ICON_COUNT
            state["next"] += 1
            atomic_write_json(path, state)
        return state["clients"][key]


def read_client_icon(index: str) -> bytes:
    if not index.isascii() or not index.isdecimal() or not 0 <= int(index) < ICON_COUNT:
        return b""
    assets = sorted(_ASSETS.glob("*.png"))
    return assets[int(index)].read_bytes() if len(assets) == ICON_COUNT else b""
