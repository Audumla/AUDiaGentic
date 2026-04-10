from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from .util import now_iso


class Claims:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"claims": []}, indent=2), encoding="utf-8")

    def _is_expired(self, claim: dict) -> bool:
        """Check if a claim has expired based on TTL."""
        if claim.get("ttl") is None:
            return False
        claimed_at = claim.get("claimed_at")
        if not claimed_at:
            return False
        try:
            claimed_dt = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            elapsed = (now_dt - claimed_dt).total_seconds()
            return elapsed > claim["ttl"]
        except (ValueError, TypeError):
            return False

    def load(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # Filter out expired claims (lazy purge on read)
        data["claims"] = [c for c in data["claims"] if not self._is_expired(c)]
        return data

    def save(self, data):
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        data = self.load()
        data["claims"] = [c for c in data["claims"] if c["id"] != id_]
        rec = {
            "kind": kind,
            "id": id_,
            "holder": holder,
            "claimed_at": now_iso(),
            "ttl": ttl,
        }
        data["claims"].append(rec)
        self.save(data)
        return rec

    def unclaim(self, id_: str):
        data = self.load()
        before = len(data["claims"])
        data["claims"] = [c for c in data["claims"] if c["id"] != id_]
        self.save(data)
        return before != len(data["claims"])
