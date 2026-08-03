"""SH12: stale-name enforcement — no LLM vocabulary on executable/config surfaces."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
CONFIG = SRC / "config"

# Allowed legacy literals: only the _LEGACY constants in agents_paths.py.
ALLOWED_LEGACY = {
    # agents_paths.py — one-shot migration path (SH12, delete after one release)
    "agents_paths.py:_LEGACY",
}

STALE = re.compile(
    r"agent_llm|agents\.llm|agent-llm|Agent LLM|_llm_request|_llm_session"
)


def _is_allowed(filepath: Path, match_text: str) -> bool:
    """Check if this stale hit is an allowed legacy literal."""
    for allowed in ALLOWED_LEGACY:
        if allowed.startswith(filepath.name + ":"):
            return True
    return False


def test_no_stale_vocabulary() -> None:
    """Assert no stale LLM vocabulary remains on executable/config surfaces."""
    offenders: list[tuple[Path, str]] = []
    scan_dirs = [SRC / "components" / "agents", CONFIG / "components"]

    for scan_dir in scan_dirs:
        for filepath in scan_dir.rglob("*.py"):
            try:
                text = filepath.read_text(encoding="utf-8")
            except OSError:
                continue  # noqa: S110 — read errors are not stale names
            for m in STALE.finditer(text):
                if _is_allowed(filepath, m.group()):
                    continue
                offenders.append((filepath, m.group()))
        # Also scan YAML config files
        for filepath in scan_dir.rglob("*.yaml"):
            try:
                text = filepath.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in STALE.finditer(text):
                offenders.append((filepath, m.group()))

    assert not offenders, (
        "Stale LLM vocabulary found on executable/config surfaces:\n"
        + "\n".join(f"  {path.relative_to(SRC)}: {text}" for path, text in offenders)
    )
