from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.system.process import candidate_ports
from audiagentic.runtime.rig.embedded.config import (
    ModelProfile,
    resolve_model_profile,
)
from audiagentic.runtime.rig.embedded.process import (
    build_command,
    wait_for_health,
)
from audiagentic.runtime.rig.embedded.resolution import (
    find_server_bin,
    resolve_model,
    runtime_bin_dir,
)

logger = logging.getLogger(__name__)

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
    from audiagentic.runtime.rig.embedded.cli import _apply_cli_overrides

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


# -- backward-compatible re-exports --

from audiagentic.runtime.rig.embedded.cli import main  # noqa: E402, F401
from audiagentic.runtime.rig.embedded.resolution import (  # noqa: E402, F401
    ensure_under,
    resolve_under,
)

if __name__ == "__main__":
    raise SystemExit(main())
