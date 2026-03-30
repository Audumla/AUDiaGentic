"""Shared prompt-trigger bridge entry point."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audiagentic.jobs.prompt_launch import launch_prompt_request
from audiagentic.jobs.prompt_parser import parse_prompt_launch_request


def _read_prompt_text(prompt_file: str | None) -> str:
    if prompt_file:
        return Path(prompt_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prompt-trigger-bridge")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--prompt-file", help="Path to a raw prompt text file; stdin if omitted")
    parser.add_argument("--surface", default="cli", choices=["cli", "vscode"])
    parser.add_argument("--provider-id")
    parser.add_argument("--session-id")
    parser.add_argument("--model-id")
    parser.add_argument("--model-alias")
    parser.add_argument("--workflow-profile", default="standard")
    args = parser.parse_args(argv)

    prompt_text = _read_prompt_text(args.prompt_file)
    request = parse_prompt_launch_request(
        prompt_text,
        surface=args.surface,
        provider_id=args.provider_id,
        session_id=args.session_id,
        model_id=args.model_id,
        model_alias=args.model_alias,
        workflow_profile=args.workflow_profile,
        allow_adhoc_target=False,
    )
    result = launch_prompt_request(Path(args.project_root), request)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
