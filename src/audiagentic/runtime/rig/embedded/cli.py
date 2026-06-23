from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import asdict
from typing import cast

from audiagentic.cli_io import print_json, print_message
from audiagentic.runtime.rig.embedded.process import build_command

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42001


def print_result(result: object, as_json: bool) -> None:
    from audiagentic.runtime.rig.embedded.launch import LaunchResult

    if isinstance(result, LaunchResult):
        launch_result = result
    elif hasattr(result, "__dict__"):
        launch_result = cast(LaunchResult, LaunchResult(**result.__dict__))
    else:
        return

    payload = asdict(launch_result)
    if as_json:
        print_json(payload)
        return
    print_message("Embedded rig ready")
    print_message(f"  PID:      {launch_result.pid}")
    print_message(f"  Endpoint: {launch_result.base_url}")
    print_message(f"  Model:    {launch_result.model}")
    print_message(f"  Binary:   {launch_result.binary}")
    if launch_result.log_path:
        print_message(f"  Log:      {launch_result.log_path}")


def _apply_cli_overrides(server_cfg: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    cfg = dict(server_cfg)
    if args.gpu_layers:
        cfg["gpu_layers"] = args.gpu_layers
    if args.context is not None:
        cfg["context_size"] = args.context
    if args.parallel is not None:
        cfg["parallel"] = args.parallel
    if args.fit:
        cfg["fit"] = args.fit
    if args.reasoning:
        cfg["reasoning"] = args.reasoning
    return cfg


def launch_background(args: argparse.Namespace) -> int:
    from audiagentic.runtime.rig.embedded.launch import start_embedded_rig

    result = start_embedded_rig(
        model_profile=args.model_profile,
        port=args.port,
        host=args.host,
        server_bin=args.server_bin,
        model_file=args.model_file,
        device=args.device,
        gpu_layers=args.gpu_layers,
        context=args.context,
        parallel=args.parallel,
        fit=args.fit,
        reasoning=args.reasoning,
        health_timeout=args.health_timeout,
    )
    print_result(result, args.json)
    return 0


def launch_foreground(args: argparse.Namespace) -> int:
    from audiagentic.runtime.rig.embedded.launch import prepare_launch

    plan = prepare_launch(
        model_profile=args.model_profile,
        server_bin=args.server_bin,
        model_file=args.model_file,
        device=args.device,
        gpu_layers=args.gpu_layers,
        context=args.context,
        parallel=args.parallel,
        fit=args.fit,
        reasoning=args.reasoning,
    )

    command = build_command(
        binary=plan.binary,
        model_arg=plan.model_arg,
        host=args.host,
        port=args.port,
        device=plan.device,
        server_cfg=plan.server_cfg,
        chat_template_kwargs=plan.profile.chat_template_kwargs,
        alias=plan.profile.name,
    )

    if not args.json:
        print_message("Starting embedded rig...")
        print_message(f"  Endpoint: http://{args.host}:{args.port}/v1")
        print_message(f"  Model:    {plan.model_path.name}")
        print_message(f"  Binary:   {plan.binary}")
        print_message(f"  ModelArg: {plan.model_arg}")
        print_message(f"  Profile:  {plan.profile.name}")

    completed = subprocess.run(command, cwd=plan.server_dir, check=False)
    return int(completed.returncode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch AUDiaGentic embedded llama rig.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Use 0 to auto-pick a free local port.")
    parser.add_argument("--background", action="store_true", help="Start detached, wait for health, then return.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON result.")
    parser.add_argument("--server-bin")
    parser.add_argument("--model-file")
    parser.add_argument("--model-profile")
    parser.add_argument("--device", default=None, help="Pass through to llama-server. Falls back to AUDIAGENTIC_RIG_DEVICE env var.")
    parser.add_argument("--gpu-layers", default=os.environ.get("AUDIAGENTIC_RIG_GPU_LAYERS"))
    parser.add_argument("--context", type=int, default=int(os.environ["AUDIAGENTIC_RIG_CONTEXT"]) if os.environ.get("AUDIAGENTIC_RIG_CONTEXT") else None)
    parser.add_argument("--parallel", type=int, default=int(os.environ["AUDIAGENTIC_RIG_PARALLEL"]) if os.environ.get("AUDIAGENTIC_RIG_PARALLEL") else None)
    parser.add_argument("--fit", default=os.environ.get("AUDIAGENTIC_RIG_FIT"))
    parser.add_argument("--reasoning", default=os.environ.get("AUDIAGENTIC_RIG_REASONING"))
    parser.add_argument("--health-timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.background:
        return launch_background(args)
    if args.port == 0:
        raise SystemExit("--port 0 requires --background")
    return launch_foreground(args)


if __name__ == "__main__":
    raise SystemExit(main())
