"""Main CLI entrypoint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import lifecycle_stub
import refresh_model_catalog as refresh_model_catalog_tool
from audiagentic.release import bootstrap as release_bootstrap
import provider_status as provider_status_tool
from audiagentic.jobs import control as job_control_tool
from audiagentic.jobs import prompt_launch as prompt_launch_tool
from audiagentic.jobs import prompt_trigger_bridge as prompt_trigger_bridge_tool
from audiagentic.jobs import session_input as session_input_tool
from audiagentic.jobs.prompt_parser import parse_prompt_launch_request
from audiagentic.jobs import store as job_store


def _load_json_argument(raw_value: str | None) -> dict[str, object] | None:
    if raw_value is None:
        return None
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        raise ValueError("JSON argument must decode to an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audiagentic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lifecycle_parser = subparsers.add_parser("lifecycle-stub")
    lifecycle_parser.add_argument("--mode", required=True, choices=["plan", "apply", "validate"])
    lifecycle_parser.add_argument("--project-root", required=True)

    prompt_parser = subparsers.add_parser("prompt-launch")
    prompt_parser.add_argument("--project-root", required=True)
    prompt_parser.add_argument("--prompt-file", help="Path to a prompt text file; stdin if omitted")
    prompt_parser.add_argument("--surface", required=True, choices=["cli", "vscode"])
    prompt_parser.add_argument("--provider-id")
    prompt_parser.add_argument("--session-id")
    prompt_parser.add_argument("--model-id")
    prompt_parser.add_argument("--model-alias")
    prompt_parser.add_argument("--workflow-profile", default="standard")
    prompt_parser.add_argument("--stream-controls-json")
    prompt_parser.add_argument("--input-controls-json")

    bridge_parser = subparsers.add_parser("prompt-trigger-bridge")
    bridge_parser.add_argument("--project-root", default=".")
    bridge_parser.add_argument("--prompt-file", help="Path to a raw prompt text file; stdin if omitted")
    bridge_parser.add_argument("--surface", default="cli", choices=["cli", "vscode"])
    bridge_parser.add_argument("--provider-id")
    bridge_parser.add_argument("--session-id")
    bridge_parser.add_argument("--model-id")
    bridge_parser.add_argument("--model-alias")
    bridge_parser.add_argument("--workflow-profile", default="standard")
    bridge_parser.add_argument("--stream-controls-json")
    bridge_parser.add_argument("--input-controls-json")

    refresh_parser = subparsers.add_parser("refresh-model-catalog")
    refresh_parser.add_argument("--project-root", required=True)
    refresh_parser.add_argument("--catalog-file")

    status_parser = subparsers.add_parser("providers-status")
    status_parser.add_argument("--project-root", required=True)
    status_parser.add_argument("--provider-id")

    job_control_parser = subparsers.add_parser("job-control")
    job_control_parser.add_argument("--project-root", required=True)
    job_control_parser.add_argument("--job-id", required=True)
    job_control_parser.add_argument("--action", required=True, choices=["cancel", "stop", "kill"])
    job_control_parser.add_argument("--requested-by", default="operator")
    job_control_parser.add_argument("--reason", default="")

    session_input_parser = subparsers.add_parser("session-input")
    session_input_parser.add_argument("--project-root", required=True)
    session_input_parser.add_argument("--job-id", required=True)
    session_input_parser.add_argument("--message")
    session_input_parser.add_argument("--message-file")
    session_input_parser.add_argument("--provider-id")
    session_input_parser.add_argument("--prompt-id")
    session_input_parser.add_argument("--surface", default="cli", choices=["cli", "vscode"])
    session_input_parser.add_argument("--stage", default="running")
    session_input_parser.add_argument(
        "--event-kind",
        default="input-submitted",
        choices=[
            "input-requested",
            "input-submitted",
            "input-applied",
            "input-rejected",
            "input-timeout",
            "pause-requested",
            "resume-requested",
            "turn-complete",
        ],
    )
    session_input_parser.add_argument("--details-json")

    release_bootstrap_parser = subparsers.add_parser("release-bootstrap")
    release_bootstrap_parser.add_argument("--project-root", required=True)
    release_bootstrap_parser.add_argument("--release-id", default="rel_0001")

    args = parser.parse_args(argv)
    if args.command == "lifecycle-stub":
        return lifecycle_stub.run(["--mode", args.mode, "--project-root", args.project_root])
    if args.command == "prompt-launch":
        try:
            if args.prompt_file:
                prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
            else:
                prompt_text = sys.stdin.read()
            request = parse_prompt_launch_request(
                prompt_text,
                surface=args.surface,
                provider_id=args.provider_id,
                session_id=args.session_id,
                model_id=args.model_id,
                model_alias=args.model_alias,
                workflow_profile=args.workflow_profile,
                stream_controls=_load_json_argument(args.stream_controls_json),
                input_controls=_load_json_argument(args.input_controls_json),
                allow_adhoc_target=False,
            )
        except ValueError as exc:
            print(json.dumps({"status": "error", "kind": "validation", "message": str(exc)}, indent=2, sort_keys=True))
            return 2
        result = prompt_launch_tool.launch_prompt_request(Path(args.project_root), request)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "refresh-model-catalog":
        refresh_args = ["--project-root", args.project_root]
        if args.catalog_file:
            refresh_args.extend(["--catalog-file", args.catalog_file])
        return refresh_model_catalog_tool.run(refresh_args)
    if args.command == "prompt-trigger-bridge":
        bridge_args = ["--project-root", args.project_root, "--surface", args.surface]
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
        return prompt_trigger_bridge_tool.run(bridge_args)
    if args.command == "providers-status":
        status_args = ["--project-root", args.project_root]
        if args.provider_id:
            status_args.extend(["--provider-id", args.provider_id])
        return provider_status_tool.run(status_args)
    if args.command == "job-control":
        request = job_control_tool.build_job_control_request(
            job_id=args.job_id,
            project_id=job_store.read_job_record(Path(args.project_root), args.job_id)["project-id"],
            requested_action=args.action,
            requested_by=args.requested_by,
            reason=args.reason,
        )
        result = job_control_tool.request_job_control(Path(args.project_root), request)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "session-input":
        if args.message_file:
            message = Path(args.message_file).read_text(encoding="utf-8")
        elif args.message is not None:
            message = args.message
        else:
            message = sys.stdin.read()
        details = json.loads(args.details_json) if args.details_json else None
        job = job_store.read_job_record(Path(args.project_root), args.job_id)
        record = session_input_tool.build_and_persist_session_input(
            Path(args.project_root),
            job_id=args.job_id,
            prompt_id=args.prompt_id,
            provider_id=args.provider_id or job.get("provider-id"),
            surface=args.surface,
            stage=args.stage,
            event_kind=args.event_kind,
            message=message,
            details=details,
        )
        print(json.dumps({"status": "recorded", "session-input": record}, indent=2, sort_keys=True))
        return 0
    if args.command == "release-bootstrap":
        result = release_bootstrap.bootstrap_release_workflow(Path(args.project_root), release_id=args.release_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
