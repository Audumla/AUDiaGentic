"""Workflow-operation CLI handlers owned by installed components."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json
from audiagentic.foundation.components.registry import get_descriptor


def cmd_session_input(args: argparse.Namespace, project_root: Path) -> int:
    from hashlib import sha256

    from audiagentic.components.agents.work import work_api

    input_root = Path(args.project_root).resolve() if args.project_root else project_root
    work = work_api.get_status(input_root, args.work_id)
    if work.get("current_interaction_id"):
        result = work_api.answer(
            input_root,
            args.work_id,
            details={"message": args.message, "event-kind": args.event_kind},
        )
    else:
        message_id = "input_" + sha256(
            f"{args.work_id}:{args.event_kind}:{args.message}".encode()
        ).hexdigest()[:20]
        result = work_api.add_message(
            input_root,
            args.work_id,
            message_id=message_id,
            text=args.message,
            inputs={"event-kind": args.event_kind},
        )
    print_json({"status": "recorded", "work": result}, sort_keys=True)
    return 0


def cmd_work_control(args: argparse.Namespace, project_root: Path) -> int:
    """Control canonical Work without touching the retired job store."""
    from audiagentic.components.agents.gateway.client import get_gateway_client

    control_root = Path(args.project_root).resolve() if args.project_root else project_root
    client = get_gateway_client(control_root)
    if args.action == "cancel":
        result = client.cancel_agent_work(control_root, args.work_id)
    else:
        result = client.get_agent_work(control_root, args.work_id)
    print_json(result, sort_keys=True)
    return 0


def cmd_release_bootstrap(args: argparse.Namespace, project_root: Path) -> int:
    if not get_descriptor("agent-ledger"):
        print_error("ledger component not available")
        return 1

    from audiagentic.components.ledger.ledger_bootstrap import bootstrap_ledger

    bootstrap_root = Path(args.project_root).resolve() if args.project_root else project_root
    print_json(bootstrap_ledger(bootstrap_root), sort_keys=True)
    return 0
