"""Main CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tools.misc import lifecycle_stub
from tools.misc import provider_status as provider_status_tool
from tools.misc import refresh_model_catalog as refresh_model_catalog_tool

from audiagentic.execution.jobs import control as job_control_tool
from audiagentic.execution.jobs import prompt_launch as prompt_launch_tool
from audiagentic.execution.jobs import prompt_trigger_bridge as prompt_trigger_bridge_tool
from audiagentic.execution.jobs.prompt_parser import parse_prompt_launch_request
from audiagentic.release import bootstrap as release_bootstrap
from audiagentic.runtime.state import jobs_store as job_store
from audiagentic.runtime.state import session_input_store as session_input_tool


def _load_json_argument(raw_value: str | None) -> dict[str, Any] | None:
    """Load and validate JSON argument from string.

    Parses JSON string and validates that it decodes to a dictionary object.
    Used for CLI arguments that accept JSON payloads.

    Args:
        raw_value: JSON string to parse, or None for optional arguments

    Returns:
        Parsed dictionary or None if input was None

    Raises:
        ValueError: If JSON is invalid or does not decode to an object

    Example:
        >>> _load_json_argument('{"key": "value"}')
        {"key": "value"}
        >>> _load_json_argument(None)
        None
        >>> _load_json_argument('["array"]')
        ValueError: JSON argument must decode to an object
    """
    if raw_value is None:
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError("JSON argument must decode to an object")
    return payload


def _validate_json_schema(data: dict[str, Any], required_keys: list[str] | None = None) -> None:
    """Validate JSON data against required schema.

    Performs basic schema validation including:
    - Required keys presence
    - Type validation for known fields
    - Nested structure validation

    Args:
        data: Parsed JSON data to validate
        required_keys: List of required top-level keys

    Raises:
        ValueError: If validation fails with details about missing/invalid fields

    Example:
        >>> _validate_json_schema({"key": "value"}, ["key"])
        # Passes validation
        >>> _validate_json_schema({}, ["key"])
        ValueError: Missing required key: key
    """
    if required_keys:
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required key: {key}")


def _validate_session_input_details(details: dict[str, Any]) -> None:
    """Validate session input details JSON structure.

    Validates that session input details contain valid event data structure.
    Checks for required fields and proper types based on event_kind.

    Args:
        details: Parsed details JSON to validate

    Raises:
        ValueError: If validation fails with specific field error

    Valid structure:
        {
            "kind": "string (optional)",
            "label": "string (optional)",
            "summary": "string (optional)",
            "metadata": "object (optional)",
            "attachments": "array (optional)"
        }
    """
    if not isinstance(details, dict):
        raise ValueError("details must be a JSON object")

    if "kind" in details and not isinstance(details["kind"], str):
        raise ValueError("details.kind must be a string")
    if "label" in details and not isinstance(details["label"], str):
        raise ValueError("details.label must be a string")
    if "summary" in details and not isinstance(details["summary"], str):
        raise ValueError("details.summary must be a string")
    if "metadata" in details and not isinstance(details["metadata"], dict):
        raise ValueError("details.metadata must be an object")
    if "attachments" in details and not isinstance(details["attachments"], list):
        raise ValueError("details.attachments must be an array")


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
    bridge_parser.add_argument(
        "--prompt-file", help="Path to a raw prompt text file; stdin if omitted"
    )
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
            error_msg = str(exc)
            # Provide recovery guidance based on error type
            if "JSON" in error_msg or "json" in error_msg:
                suggestion = "Check that JSON arguments are valid and properly formatted"
            elif "prompt" in error_msg.lower():
                suggestion = "Ensure prompt contains valid @ag-* tag and required fields"
            else:
                suggestion = "Review argument values and ensure they match expected format"
            print(
                json.dumps(
                    {
                        "status": "error",
                        "kind": "validation",
                        "error-code": "CLI-VALIDATION-001",
                        "message": error_msg,
                        "suggestion": suggestion,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
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
            project_id=job_store.read_job_record(Path(args.project_root), args.job_id)[
                "project-id"
            ],
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
        details = _load_json_argument(args.details_json)
        if details is not None:
            _validate_session_input_details(details)
        record = session_input_tool.build_and_persist_session_input(
            Path(args.project_root),
            job_id=args.job_id,
            prompt_id=args.prompt_id,
            provider_id=args.provider_id,
            surface=args.surface,
            stage=args.stage,
            event_kind=args.event_kind,
            message=message,
            details=details,
            job_store=job_store.read_job_record,
        )
        print(json.dumps({"status": "recorded", "session-input": record}, indent=2, sort_keys=True))
        return 0
    if args.command == "release-bootstrap":
        result = release_bootstrap.bootstrap_release_workflow(
            Path(args.project_root), release_id=args.release_id
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
