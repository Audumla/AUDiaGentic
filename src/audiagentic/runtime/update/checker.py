"""Check for available audiagentic updates via GitHub Releases API."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GITHUB_REPO = "Audumla/AUDiaGentic"
_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_CHECK_INTERVAL = timedelta(hours=24)


def current_version() -> str:
    try:
        from importlib.metadata import version
        return version("audiagentic")
    except Exception:  # noqa: BLE001
        try:
            from audiagentic import __version__
            return __version__
        except Exception:  # noqa: BLE001
            return "0.0.0"


def _cache_path() -> Path:
    from audiagentic.provisioning.home import audiagentic_home
    return audiagentic_home() / "update-check.json"


def _read_cache() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_cache(data: dict) -> None:
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:  # noqa: BLE001
        return (0,)


def fetch_latest_version(timeout: int = 5) -> str | None:
    """Query GitHub Releases API for the latest version tag. Returns None on any failure."""
    try:
        req = urllib.request.Request(
            _RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"audiagentic-update-checker/{current_version()}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception:  # noqa: BLE001
        return None


def check_update(*, force: bool = False) -> dict | None:
    """Return update info if a newer version is available, else None.

    Respects the 24-hour check interval unless force=True.
    Returns None if: within interval, network failure, up to date, or version skipped.
    Returns {"latest": "x.y.z", "current": "x.y.z"} when an update is available.
    """
    cache = _read_cache()
    current = current_version()

    if not force:
        last_checked = cache.get("checked_at")
        if last_checked:
            try:
                last_dt = datetime.fromisoformat(last_checked)
                if datetime.now(timezone.utc) - last_dt < _CHECK_INTERVAL:
                    # Use cached result without hitting the network
                    latest = cache.get("latest_version")
                    if not latest:
                        return None
                    if latest in cache.get("skipped_versions", []):
                        return None
                    if _version_tuple(latest) <= _version_tuple(current):
                        return None
                    return {"latest": latest, "current": current}
            except Exception:  # noqa: BLE001
                pass

    latest = fetch_latest_version()
    cache["checked_at"] = datetime.now(timezone.utc).isoformat()
    if latest:
        cache["latest_version"] = latest
    _write_cache(cache)

    if not latest:
        return None
    if latest in cache.get("skipped_versions", []):
        return None
    if _version_tuple(latest) <= _version_tuple(current):
        return None

    return {"latest": latest, "current": current}


def skip_version(version: str) -> None:
    """Record a version as skipped so it won't be offered again."""
    cache = _read_cache()
    skipped: list[str] = cache.get("skipped_versions", [])
    if version not in skipped:
        skipped.append(version)
    cache["skipped_versions"] = skipped
    _write_cache(cache)
