from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Use the shared repo-root helper so this tool works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT

MANAGED_MARKDOWN_HEADER = "<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->"
REQUIRED_PATHS = [
    ".audiagentic/project.yaml",
    ".audiagentic/components.yaml",
    ".audiagentic/providers.yaml",
    ".audiagentic/prompt-syntax.yaml",
    ".audiagentic/prompts/ag-review/default.md",
    ".audiagentic/prompts/ag-plan/default.md",
    ".audiagentic/prompts/ag-implement/default.md",
    ".audiagentic/prompts/ag-audit/default.md",
    ".audiagentic/prompts/ag-check-in-prep/default.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".clinerules/prompt-tags.md",
    ".claude/rules/prompt-tags.md",
    ".agents/skills/ag-plan/SKILL.md",
    ".agents/skills/ag-implement/SKILL.md",
    ".agents/skills/ag-review/SKILL.md",
    ".agents/skills/ag-audit/SKILL.md",
    ".agents/skills/ag-check-in-prep/SKILL.md",
    ".claude/skills/ag-plan/SKILL.md",
    ".claude/skills/ag-implement/SKILL.md",
    ".claude/skills/ag-review/SKILL.md",
    ".claude/skills/ag-audit/SKILL.md",
    ".claude/skills/ag-check-in-prep/SKILL.md",
    ".clinerules/skills/ag-plan.md",
    ".clinerules/skills/ag-implement.md",
    ".clinerules/skills/ag-review.md",
    ".clinerules/skills/ag-audit.md",
    ".clinerules/skills/ag-check-in-prep.md",
    ".gemini/commands/ag-plan.md",
    ".gemini/commands/ag-implement.md",
    ".gemini/commands/ag-review.md",
    ".gemini/commands/ag-audit.md",
    ".gemini/commands/ag-check-in-prep.md",
    ".opencode/skills/ag-plan/SKILL.md",
    ".opencode/skills/ag-implement/SKILL.md",
    ".opencode/skills/ag-review/SKILL.md",
    ".opencode/skills/ag-audit/SKILL.md",
    ".opencode/skills/ag-check-in-prep/SKILL.md",
    "tools/misc/regenerate_tag_surfaces.py",
    ".github/workflows/release-please.audiagentic.yml",
    "tools/misc/seed_example_project.py",
    "src/audiagentic/runtime/lifecycle/baseline_sync.py",
    "src/audiagentic/release/bootstrap.py",
    ".audiagentic/planning/config/planning.yaml",
    ".audiagentic/planning/config/profiles.yaml",
    ".audiagentic/planning/config/workflows.yaml",
    ".audiagentic/planning/config/automations.yaml",
    ".audiagentic/planning/config/hooks.yaml",
]
MANAGED_HEADER_PATHS = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".clinerules/prompt-tags.md",
    ".claude/rules/prompt-tags.md",
    ".agents/skills/ag-plan/SKILL.md",
    ".agents/skills/ag-implement/SKILL.md",
    ".agents/skills/ag-review/SKILL.md",
    ".agents/skills/ag-audit/SKILL.md",
    ".agents/skills/ag-check-in-prep/SKILL.md",
    ".claude/skills/ag-plan/SKILL.md",
    ".claude/skills/ag-implement/SKILL.md",
    ".claude/skills/ag-review/SKILL.md",
    ".claude/skills/ag-audit/SKILL.md",
    ".claude/skills/ag-check-in-prep/SKILL.md",
    ".clinerules/skills/ag-plan.md",
    ".clinerules/skills/ag-implement.md",
    ".clinerules/skills/ag-review.md",
    ".clinerules/skills/ag-audit.md",
    ".clinerules/skills/ag-check-in-prep.md",
    ".gemini/commands/ag-plan.md",
    ".gemini/commands/ag-implement.md",
    ".gemini/commands/ag-review.md",
    ".gemini/commands/ag-audit.md",
    ".gemini/commands/ag-check-in-prep.md",
    ".opencode/skills/ag-plan/SKILL.md",
    ".opencode/skills/ag-implement/SKILL.md",
    ".opencode/skills/ag-review/SKILL.md",
    ".opencode/skills/ag-audit/SKILL.md",
    ".opencode/skills/ag-check-in-prep/SKILL.md",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check managed baseline asset visibility.")
    parser.add_argument(
        "--check-gitignore",
        action="store_true",
        help="Also verify that .gitignore excludes .audiagentic/runtime/.",
    )
    parser.add_argument(
        "--check-managed-headers",
        action="store_true",
        help="Also verify that managed markdown surfaces carry the AUDiaGentic managed header.",
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

    if args.check_managed_headers:
        for rel_path in MANAGED_HEADER_PATHS:
            path = REPO_ROOT / rel_path
            if not path.exists():
                issues.append(f"missing managed file for header check: {rel_path}")
                continue
            text = path.read_text(encoding="utf-8")
            if not text.startswith(MANAGED_MARKDOWN_HEADER):
                issues.append(f"managed header missing: {rel_path}")

    if issues:
        print("Baseline asset check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Baseline asset check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
