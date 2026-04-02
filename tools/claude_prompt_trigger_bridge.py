"""Claude-specific prompt-trigger bridge wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.execution.jobs.prompt_trigger_bridge import run

REQUIRED_ASSETS = (
    Path("CLAUDE.md"),
    Path(".claude/rules/prompt-tags.md"),
    Path(".claude/rules/review-policy.md"),
    Path(".claude/skills/ag-plan/SKILL.md"),
    Path(".claude/skills/ag-implement/SKILL.md"),
    Path(".claude/skills/ag-review/SKILL.md"),
    Path(".claude/skills/ag-audit/SKILL.md"),
    Path(".claude/skills/ag-check-in-prep/SKILL.md"),
)


def _missing_assets(project_root: Path) -> list[str]:
    """Check for required Claude assets before launching."""
    missing: list[str] = []
    for relative_path in REQUIRED_ASSETS:
        if not (project_root / relative_path).exists():
            missing.append(str(relative_path))
    return missing


if __name__ == "__main__":
    import json

    # Extract --project-root from arguments if provided
    project_root = Path(".").resolve()
    try:
        if "--project-root" in sys.argv:
            idx = sys.argv.index("--project-root")
            project_root = Path(sys.argv[idx + 1]).resolve()
    except (IndexError, ValueError):
        pass

    missing = _missing_assets(project_root)
    if missing:
        print(
            json.dumps(
                {
                    "status": "error",
                    "kind": "validation",
                    "message": "missing Claude prompt-calling assets",
                    "missing": missing,
                    "project-root": str(project_root),
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(2)

    raise SystemExit(run(["--provider-id", "claude", *sys.argv[1:]]))
