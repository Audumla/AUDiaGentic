"""SH12: stale-name enforcement — no LLM vocabulary on executable/config surfaces."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
CONFIG = SRC / "config"

STALE = re.compile(r"agent_llm|agents\.llm|agent-llm|Agent LLM|_llm_request|_llm_session")


def test_no_stale_vocabulary() -> None:
    """Assert no stale LLM vocabulary remains on executable/config/doc surfaces.

    No exemptions: arch-standards §4 does not maintain backward compatibility
    by default, and there is no documented external obligation requiring the
    old `agent-llm-gateway` path to remain resolvable.
    """
    offenders: list[tuple[Path, str]] = []
    scan_dirs = [SRC / "components" / "agents", SRC / "components" / "agent_jobs", CONFIG / "components"]

    for scan_dir in scan_dirs:
        for pattern in ("*.py", "*.yaml", "*.md"):
            for filepath in scan_dir.rglob(pattern):
                try:
                    text = filepath.read_text(encoding="utf-8")
                except OSError:
                    continue  # noqa: S110 — read errors are not stale names
                for lineno, line in enumerate(text.splitlines(), start=1):
                    for m in STALE.finditer(line):
                        offenders.append((filepath, f"L{lineno}: {m.group()}"))

    assert not offenders, "Stale LLM vocabulary found on executable/config/doc surfaces:\n" + "\n".join(
        f"  {path.relative_to(SRC)}: {text}" for path, text in offenders
    )
