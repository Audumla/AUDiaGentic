"""Workflow-operation CLI handlers owned by installed components."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json
from audiagentic.foundation.components.registry import get_descriptor


def cmd_job_control(args: argparse.Namespace, project_root: Path) -> int:
    if not get_descriptor("agent-jobs"):
        print_error("agent_jobs component not available")
        return 1

    from audiagentic.components.agent_jobs.control import (
        build_job_control_request,
        request_job_control,
    )
    from audiagentic.components.agent_jobs.jobs_store import read_job_record

    control_root = Path(args.project_root).resolve() if args.project_root else project_root
    job = read_job_record(control_root, args.job_id)
    payload = build_job_control_request(
        job_id=args.job_id,
        project_id=job["project-id"],
        requested_action=args.action,
        requested_by=args.requested_by,
        reason=args.reason,
    )
    print_json(request_job_control(control_root, payload), sort_keys=True)
    return 0


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


def cmd_release_bootstrap(args: argparse.Namespace, project_root: Path) -> int:
    if not get_descriptor("agent-ledger"):
        print_error("ledger component not available")
        return 1

    from audiagentic.components.ledger.ledger_bootstrap import bootstrap_ledger

    bootstrap_root = Path(args.project_root).resolve() if args.project_root else project_root
    print_json(bootstrap_ledger(bootstrap_root), sort_keys=True)
    return 0
