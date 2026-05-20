from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml


def dump_markdown(path: Path, data: dict, body: str) -> None:
    """Write markdown file atomically using temp file + rename pattern.

    This prevents corruption from interrupted writes or crashes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    content = f"---\n{fm}\n---\n\n{body.rstrip()}\n"

    # Write to temp file in same directory (for atomic rename)
    dir_ = path.parent
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(dir_))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic rename (same filesystem)
        shutil.move(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        if Path(tmp_path).exists():
            Path(tmp_path).unlink(missing_ok=True)
        raise
