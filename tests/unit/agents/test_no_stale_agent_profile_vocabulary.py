"""AS60: stale-name enforcement — no AgentProfile vocabulary on executable/config surfaces.

AS60 step 10 requires an architecture/search test proving no old terminology
remains in the migrated path. This is the ExecutionProfile-rename analogue of
SH12's test_no_stale_llm_vocabulary.py.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
CONFIG = SRC / "config"

STALE = re.compile(
    r"AgentProfile|agent_profile|agent-profile|[Aa]gent [Pp]rofile|VAL-AGP-|RES-AGP-|IO-AGP-"
)


def test_no_stale_vocabulary() -> None:
    """Assert no stale AgentProfile vocabulary remains on executable/config/doc surfaces.

    No exemptions: arch-standards §4 does not maintain backward compatibility
    by default, and there is no documented external obligation requiring the
    old `agent-profiles.yaml` name or `AgentProfile` type to remain resolvable.
    """
    offenders: list[tuple[Path, str]] = []
    scan_dirs = [
        SRC / "components" / "agents",
        SRC / "components" / "agent_jobs",
        SRC / "components" / "providers",
        CONFIG / "components",
        SRC / "foundation" / "contracts" / "schemas",
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for pattern in ("*.py", "*.yaml", "*.json", "*.md"):
            for filepath in scan_dir.rglob(pattern):
                try:
                    text = filepath.read_text(encoding="utf-8")
                except OSError:
                    continue  # noqa: S110 — read errors are not stale names
                for lineno, line in enumerate(text.splitlines(), start=1):
                    for m in STALE.finditer(line):
                        offenders.append((filepath, f"L{lineno}: {m.group()}"))

    assert not offenders, (
        "Stale AgentProfile vocabulary found on executable/config/doc surfaces:\n"
        + "\n".join(f"  {path.relative_to(SRC)}: {text}" for path, text in offenders)
    )
