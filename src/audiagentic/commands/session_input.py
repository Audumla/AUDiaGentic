"""Session input command implementation."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_json


def cmd_session_input(args: argparse.Namespace, project_root: Path) -> int:
    from audiagentic.components.agent_jobs.session_input_store import (
        build_and_persist_session_input,
    )

    input_root = Path(args.project_root).resolve() if args.project_root else project_root
    record = build_and_persist_session_input(
        input_root,
        job_id=args.job_id,
        prompt_id=args.prompt_id,
        provider_id=args.provider_id,
        surface=args.surface,
        stage=args.stage,
        event_kind=args.event_kind,
        message=args.message,
    )
    print_json({"status": "recorded", "record": record}, sort_keys=True)
    return 0
