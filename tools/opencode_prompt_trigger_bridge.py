#!/usr/bin/env python
"""opencode-specific prompt-trigger bridge wrapper."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.execution.jobs.prompt_trigger_bridge import run as shared_run


REQUIRED_ASSETS = (
    Path("AGENTS.md"),
    Path(".agents/skills/ag-plan/SKILL.md"),
    Path(".agents/skills/ag-implement/SKILL.md"),
    Path(".agents/skills/ag-review/SKILL.md"),
    Path(".agents/skills/ag-audit/SKILL.md"),
    Path(".agents/skills/ag-check-in-prep/SKILL.md"),
)


def _missing_assets(project_root: Path) -> list[str]:
    missing: list[str] = []
    for relative_path in REQUIRED_ASSETS:
        if not (project_root / relative_path).exists():
            missing.append(str(relative_path))
    return missing


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opencode-prompt-trigger-bridge")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--prompt-file", help="Path to a raw prompt text file; stdin if omitted")
    parser.add_argument("--surface", default="cli", choices=["cli", "vscode"])
    parser.add_argument("--provider-id")
    parser.add_argument("--session-id")
    parser.add_argument("--model-id")
    parser.add_argument("--model-alias")
    parser.add_argument("--workflow-profile", default="standard")
    parser.add_argument("--stream-controls-json")
    parser.add_argument("--input-controls-json")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    missing = _missing_assets(project_root)
    if missing:
        print(
            json.dumps(
                {
                    "status": "error",
                    "kind": "validation",
                    "message": "missing opencode prompt-calling assets",
                    "missing": missing,
                    "project-root": str(project_root),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    bridge_args = ["--project-root", str(project_root), "--surface", args.surface]
    if args.prompt_file:
        bridge_args.extend(["--prompt-file", args.prompt_file])
    if args.provider_id:
        bridge_args.extend(["--provider-id", args.provider_id])
    if args.session_id:
        bridge_args.extend(["--session-id", args.session_id])
    if args.model_id:
        bridge_args.extend(["--model-id", args.model_id])
    if args.model_alias:
        bridge_args.extend(["--model-alias", args.model_alias])
    if args.workflow_profile:
        bridge_args.extend(["--workflow-profile", args.workflow_profile])
    if args.stream_controls_json:
        bridge_args.extend(["--stream-controls-json", args.stream_controls_json])
    if args.input_controls_json:
        bridge_args.extend(["--input-controls-json", args.input_controls_json])
    return shared_run(bridge_args)


if __name__ == "__main__":
    raise SystemExit(run(["--provider-id", "opencode", *sys.argv[1:]]))
