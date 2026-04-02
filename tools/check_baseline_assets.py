from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PATHS = [
    ".audiagentic/project.yaml",
    ".audiagentic/components.yaml",
    ".audiagentic/providers.yaml",
    ".audiagentic/prompt-syntax.yaml",
    ".audiagentic/prompts/review/default.md",
    ".audiagentic/prompts/plan/default.md",
    ".audiagentic/prompts/implement/default.md",
    ".audiagentic/prompts/audit/default.md",
    ".audiagentic/prompts/check-in-prep/default.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".clinerules/prompt-tags.md",
    ".claude/rules/prompt-tags.md",
    ".agents/skills/review/SKILL.md",
    ".github/workflows/release-please.audiagentic.yml",
    "tools/seed_example_project.py",
    "src/audiagentic/runtime/lifecycle/baseline_sync.py",
    "src/audiagentic/runtime/release/bootstrap.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check managed baseline asset visibility.")
    parser.add_argument(
        "--check-gitignore",
        action="store_true",
        help="Also verify that .gitignore excludes .audiagentic/runtime/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = [path for path in REQUIRED_PATHS if not (REPO_ROOT / path).exists()]
    issues = []
    if missing:
        issues.extend(f"missing required asset: {path}" for path in missing)

    runtime_root = REPO_ROOT / ".audiagentic" / "runtime"
    if not runtime_root.exists():
        issues.append("missing runtime root: .audiagentic/runtime")

    if args.check_gitignore:
        gitignore = REPO_ROOT / ".gitignore"
        if not gitignore.exists():
            issues.append("missing .gitignore")
        else:
            text = gitignore.read_text(encoding="utf-8")
            if ".audiagentic/runtime/" not in text.replace("\\", "/"):
                issues.append(".gitignore does not explicitly exclude .audiagentic/runtime/")

    if issues:
        print("Baseline asset check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Baseline asset check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
