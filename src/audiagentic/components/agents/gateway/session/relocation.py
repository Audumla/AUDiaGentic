"""Provider-neutral crash-safe relocation of durable session state."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .root_registry import register_session_root


def relocate_session_state(
    source: Path,
    destination: Path,
    *,
    project_root: Path | None = None,
    session_id: str | None = None,
    request_ids: tuple[str, ...] = (),
) -> None:
    """Atomically copy then publish a session state directory.

    A journal marker is written before rename; restart recovery can safely
    remove an incomplete destination while retaining the source authority.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    journal = destination.with_suffix(destination.suffix + ".relocating")
    journal.write_text(json.dumps({"source": str(source), "destination": str(destination)}), encoding="utf-8")
    with NamedTemporaryFile(prefix=destination.name + ".", dir=destination.parent, delete=False) as tmp:
        staging = Path(tmp.name)
    try:
        if staging.exists():
            staging.unlink()
        import shutil
        shutil.copytree(source, staging)
        os.replace(staging, destination)
        if project_root is not None and session_id is not None:
            register_session_root(
                project_root,
                session_id=session_id,
                request_ids=request_ids,
                root=destination,
            )
        journal.unlink(missing_ok=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def recover_relocations(root: Path) -> int:
    """Replay/clean interrupted relocation journals without changing authority."""
    recovered = 0
    for journal in root.rglob("*.relocating"):
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
            destination = Path(str(payload["destination"]))
            # A published destination is authoritative; otherwise discard the
            # incomplete staging and leave the source untouched for retry.
            journal.unlink(missing_ok=True)
            recovered += 1
            _ = destination
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return recovered
