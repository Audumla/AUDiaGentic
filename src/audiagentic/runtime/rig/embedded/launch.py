from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from audiagentic.runtime.rig.embedded.config import (
    ModelProfile,
    resolve_model_profile,
)
from audiagentic.runtime.rig.embedded.process import (
    build_command,
    candidate_ports,
    resolve_platform_dirs,
    wait_for_health,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42001


@dataclass
class LaunchResult:
    pid: int
    port: int
    host: str
    base_url: str
    model: str
    binary: str
    log_path: str | None


@dataclass
class LaunchPlan:
    bin_dir: Path
    binary: Path
    server_dir: Path
    model_path: Path
    model_arg: str
    device: str | None
    profile: ModelProfile
    server_cfg: dict[str, object]


def runtime_bin_dir() -> Path:
    from audiagentic.paths import find_repo_root
    from audiagentic.runtime.home import global_harness_runtime

    project_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if project_root:
        project_bin = Path(project_root) / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin"
        if project_bin.exists():
            return project_bin
    try:
        repo_root = find_repo_root(Path.cwd())
        project_bin = repo_root / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin"
        if project_bin.exists():
            return project_bin
    except Exception:
        pass
    return global_harness_runtime() / "rig" / "bin"


def resolve_under(root: Path, value: str | None, *, base: Path | None = None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    resolved = raw if raw.is_absolute() else (base or root) / raw
    return resolved.resolve()


def ensure_under(path: Path, root: Path, label: str) -> Path:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay under {root}") from exc
    return path


def find_server_bin(bin_dir: Path, override: str | None) -> Path:
    server_dir, llamafile_dir = resolve_platform_dirs(bin_dir)
    if override:
        candidate = ensure_under(
            resolve_under(bin_dir, override) or Path(),
            bin_dir,
            "AUDIAGENTIC_RIG_SERVER_BIN",
        )
        if not candidate.exists():
            raise SystemExit(f"Rig binary not found: {candidate}")
        return candidate

    if os.name == "nt":
        server_name = "llama-server.exe"
        fallback_name = "llamafile.exe"
    else:
        server_name = "llama-server"
        fallback_name = "llamafile"

    server_bin = server_dir / server_name
    if server_bin.exists():
        return server_bin

    fallback_bin = llamafile_dir / fallback_name
    if fallback_bin.exists():
        return fallback_bin

    raise SystemExit(f"Local rig binary not found under {bin_dir}")


def resolve_model(bin_dir: Path, server_dir: Path, override: str | None) -> tuple[Path, str]:
    if not override:
        raise SystemExit(
            "No model file specified. Set --model-file or AUDIAGENTIC_RIG_MODEL_FILE, or add model_file to the profile."
        )
    candidate = resolve_under(bin_dir, override, base=server_dir)
    assert candidate is not None
    ensure_under(candidate, bin_dir, "AUDIAGENTIC_RIG_MODEL_FILE")
    if not candidate.exists():
        raise SystemExit(f"Model not found: {candidate}")
    if Path(override).is_absolute():
        return candidate, str(candidate)
    return candidate, override


def print_result(result: LaunchResult, as_json: bool) -> None:
    payload = asdict(result)
    if as_json:
        print(json.dumps(payload))
        return
    print("Embedded rig ready")
    print(f"  PID:      {result.pid}")
    print(f"  Endpoint: {result.base_url}")
    print(f"  Model:    {result.model}")
    print(f"  Binary:   {result.binary}")
    if result.log_path:
        print(f"  Log:      {result.log_path}")


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


def prepare_launch(
    *,
    model_profile: str | None,
    server_bin: str | None,
    model_file: str | None,
    device: str | None,
    gpu_layers: str | None,
    context: int | None,
    parallel: int | None,
    fit: str | None,
    reasoning: str | None,
) -> LaunchPlan:
    bin_dir = runtime_bin_dir()
    profile = resolve_model_profile(
        model_profile,
        model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"),
    )
    binary = find_server_bin(
        bin_dir,
        server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"),
    )
    server_dir = binary.parent
    model_override = (
        model_file
        or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE")
        or profile.model_file
    )
    model_path, model_arg = resolve_model(bin_dir, server_dir, model_override)
    resolved_device = device or os.environ.get("AUDIAGENTIC_RIG_DEVICE")
    override_args = argparse.Namespace(
        gpu_layers=gpu_layers,
        context=context,
        parallel=parallel,
        fit=fit,
        reasoning=reasoning,
    )
    server_cfg = _apply_cli_overrides(profile.server_cfg, override_args)
    return LaunchPlan(
        bin_dir=bin_dir,
        binary=binary,
        server_dir=server_dir,
        model_path=model_path,
        model_arg=model_arg,
        device=resolved_device,
        profile=profile,
        server_cfg=server_cfg,
    )


def start_embedded_rig(
    *,
    model_profile: str,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    server_bin: str | None = None,
    model_file: str | None = None,
    device: str | None = None,
    gpu_layers: str | None = None,
    context: int | None = None,
    parallel: int | None = None,
    fit: str | None = None,
    reasoning: str | None = None,
    health_timeout: float = 60.0,
    on_progress: Callable[[str], None] | None = None,
) -> LaunchResult:
    from audiagentic.runtime.home import global_harness_runtime

    log_dir = global_harness_runtime() / "logs" / "rig"
    log_dir.mkdir(parents=True, exist_ok=True)

    plan = prepare_launch(
        model_profile=model_profile,
        server_bin=server_bin,
        model_file=model_file,
        device=device,
        gpu_layers=gpu_layers,
        context=context,
        parallel=parallel,
        fit=fit,
        reasoning=reasoning,
    )
    last_error: str | None = None

    for candidate_port in candidate_ports(host, port):
        base_url = f"http://{host}:{candidate_port}/v1"
        log_path = log_dir / f"rig-{candidate_port}.log"
        meta_path = log_dir / f"rig-{candidate_port}.meta.json"
        command = build_command(
            binary=plan.binary,
            model_arg=plan.model_arg,
            host=host,
            port=candidate_port,
            device=plan.device,
            server_cfg=plan.server_cfg,
            chat_template_kwargs=plan.profile.chat_template_kwargs,
            alias=plan.profile.name,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "event": "launch_requested",
                    "binary": str(plan.binary),
                    "working_dir": str(plan.server_dir),
                    "command": command,
                    "host": host,
                    "port": candidate_port,
                    "model": plan.model_path.name,
                    "model_profile": plan.profile.name,
                    "server_cfg": plan.server_cfg,
                    "chat_template_kwargs": plan.profile.chat_template_kwargs,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if on_progress:
            on_progress(f"[rig] launching {plan.profile.name} on {base_url}")

        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            process = subprocess.Popen(
                command,
                cwd=plan.server_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        pid = process.pid

        try:
            wait_for_health(
                base_url,
                health_timeout,
                process=process,
                log_path=log_path,
            )
        except BaseException as exc:
            last_error = str(exc)
            try:
                process.kill()
            except OSError:
                pass
            continue

        result = LaunchResult(
            pid=pid,
            port=candidate_port,
            host=host,
            base_url=base_url,
            model=plan.model_path.name,
            binary=str(plan.binary),
            log_path=str(log_path),
        )
        with meta_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event": "launch_ready",
                        "pid": pid,
                        "base_url": base_url,
                        "model": plan.model_path.name,
                        "model_profile": plan.profile.name,
                    }
                )
                + "\n"
            )
        if on_progress:
            on_progress(f"[rig] healthy at {base_url}")
        return result

    raise SystemExit(last_error or f"Unable to launch rig on {host}")


def launch_background(args: argparse.Namespace) -> int:
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
        print("Starting embedded rig...")
        print(f"  Endpoint: http://{args.host}:{args.port}/v1")
        print(f"  Model:    {plan.model_path.name}")
        print(f"  Binary:   {plan.binary}")
        print(f"  ModelArg: {plan.model_arg}")
        print(f"  Profile:  {plan.profile.name}")

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
