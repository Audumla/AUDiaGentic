from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42001
DEFAULT_MODEL_ARG = Path("..") / ".." / "models" / "Qwen_Qwen3.5-2B-Q4_K_S.gguf"
DEFAULT_CONTEXT = 262144
DEFAULT_PARALLEL = 2
DEFAULT_GPU_LAYERS = "all"
DEFAULT_FIT = "on"
DEFAULT_REASONING = "off"
DEFAULT_MODEL_PROFILE = "qwen3.5-2b-q4_k_s"


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
class ModelProfile:
    name: str
    model_file: str | None
    context: int
    parallel: int
    gpu_layers: str
    fit: str
    reasoning: str
    sampling: dict[str, object]
    chat_template_kwargs: dict[str, object]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def runtime_bin_dir(root: Path) -> Path:
    return root / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin"


def model_profiles_path(root: Path) -> Path:
    return root / "src" / "audiagentic" / "provisioning" / "rig" / "embedded" / "models.json"


def provisioning_log_dir(root: Path, component: str) -> Path:
    return root / ".audiagentic" / "provisioning" / "logs" / component


def load_model_profiles(root: Path) -> dict[str, object]:
    path = model_profiles_path(root)
    if not path.exists():
        return {"default": DEFAULT_MODEL_PROFILE, "models": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_model_profile(root: Path, requested: str | None, model_file: str | None) -> ModelProfile:
    data = load_model_profiles(root)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid model profile file: {model_profiles_path(root)}")

    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE")
    if not target and model_file:
        model_name = Path(model_file).name
        for name, raw_profile in models.items():
            if not isinstance(raw_profile, dict):
                continue
            aliases = raw_profile.get("aliases", [])
            if model_name == raw_profile.get("model_file") or model_name in aliases:
                target = str(name)
                break
    target = target or str(data.get("default") or DEFAULT_MODEL_PROFILE)

    raw = models.get(target)
    if raw is None:
        for name, raw_profile in models.items():
            if isinstance(raw_profile, dict) and target in raw_profile.get("aliases", []):
                target = str(name)
                raw = raw_profile
                break
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {target}")

    return ModelProfile(
        name=target,
        model_file=raw.get("model_file") if isinstance(raw.get("model_file"), str) else None,
        context=int(raw.get("context", DEFAULT_CONTEXT)),
        parallel=int(raw.get("parallel", DEFAULT_PARALLEL)),
        gpu_layers=str(raw.get("gpu_layers", DEFAULT_GPU_LAYERS)),
        fit=str(raw.get("fit", DEFAULT_FIT)),
        reasoning=str(raw.get("reasoning", DEFAULT_REASONING)),
        sampling=raw.get("sampling", {}) if isinstance(raw.get("sampling"), dict) else {},
        chat_template_kwargs=raw.get("chat_template_kwargs", {}) if isinstance(raw.get("chat_template_kwargs"), dict) else {},
    )


def resolve_platform_dirs(bin_dir: Path) -> tuple[Path, Path]:
    if sys.platform == "win32":
        return bin_dir / "llama-server" / "windows", bin_dir / "llamafile" / "windows"
    if sys.platform == "darwin":
        return bin_dir / "llama-server" / "macOS", bin_dir / "llamafile" / "macOS"
    return bin_dir / "llama-server" / "linux", bin_dir / "llamafile" / "linux"


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
        candidate = ensure_under(resolve_under(repo_root(), override) or Path(), bin_dir, "AUDIAGENTIC_RIG_SERVER_BIN")
        if not candidate.exists():
            raise SystemExit(f"Rig binary not found: {candidate}")
        return candidate

    if sys.platform == "win32":
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


def default_model_path(server_dir: Path) -> tuple[Path, str]:
    model_relative = "../../models/Qwen_Qwen3.5-2B-Q4_K_S.gguf"
    return (server_dir / DEFAULT_MODEL_ARG).resolve(), model_relative


def resolve_model(bin_dir: Path, server_dir: Path, override: str | None) -> tuple[Path, str]:
    if override:
        candidate = resolve_under(repo_root(), override, base=server_dir)
        assert candidate is not None
        ensure_under(candidate, bin_dir, "AUDIAGENTIC_RIG_MODEL_FILE")
        if not candidate.exists():
            raise SystemExit(f"Model not found: {candidate}")
        if Path(override).is_absolute():
            return candidate, str(candidate)
        return candidate, override

    candidate, model_arg = default_model_path(server_dir)
    if candidate.exists():
        return candidate, model_arg

    fallback = bin_dir / "models" / "Qwen_Qwen3.5-2B-Q4_K_S.gguf"
    if fallback.exists():
        return fallback, str(fallback)

    raise SystemExit(f"Local rig model not found under {bin_dir / 'models'}")


def choose_free_port(host: str) -> int:
    candidates = list(range(30000, 61000))
    random.shuffle(candidates)
    for port in candidates[:64]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"Unable to find free port on {host}")


def candidate_ports(host: str, requested_port: int) -> list[int]:
    if requested_port != 0:
        return [requested_port]
    primary = choose_free_port(host)
    extras = []
    seen = {primary}
    while len(extras) < 7:
        port = choose_free_port(host)
        if port in seen:
            continue
        seen.add(port)
        extras.append(port)
    return [primary, *extras]


def build_command(
    binary: Path,
    model_arg: str,
    host: str,
    port: int,
    device: str | None,
    gpu_layers: str,
    context: int,
    parallel: int,
    fit: str,
    reasoning: str,
    sampling: dict[str, object],
    chat_template_kwargs: dict[str, object],
) -> list[str]:
    args: list[str] = []
    if binary.name.startswith("llamafile"):
        args.append("--server")
    args.extend(["--host", host, "--port", str(port)])
    if device:
        args.extend(["--device", device])
    args.extend(["--gpu-layers", str(gpu_layers), "--model", model_arg])
    if "temperature" in sampling:
        args.extend(["--temp", str(sampling["temperature"])])
    if "top_p" in sampling:
        args.extend(["--top-p", str(sampling["top_p"])])
    if "top_k" in sampling:
        args.extend(["--top-k", str(sampling["top_k"])])
    if "presence_penalty" in sampling:
        args.extend(["--presence-penalty", str(sampling["presence_penalty"])])
    if chat_template_kwargs:
        args.extend(["--chat-template-kwargs", json.dumps(chat_template_kwargs, separators=(",", ":"))])
    args.extend(
        [
            "--ctx-size",
            str(context),
            "--parallel",
            str(parallel),
            "--fit",
            fit,
            "--no-mmap",
            "--reasoning",
            reasoning,
        ]
    )
    return [str(binary), *args]


def wait_for_health(
    base_url: str,
    timeout_s: float,
    *,
    process: subprocess.Popen[bytes] | None = None,
    log_path: Path | None = None,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = "unknown error"
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/models", timeout=5) as response:
                if response.status == 200:
                    return
                last_error = f"unexpected status {response.status}"
        except URLError as exc:
            last_error = str(exc)
        except OSError as exc:
            last_error = str(exc)
        if process is not None and process.poll() is not None:
            detail = f"Rig exited early with code {process.returncode}"
            if log_path is not None:
                detail += f". See log: {log_path}"
            raise SystemExit(detail)
        time.sleep(0.5)
    raise SystemExit(f"Rig health check failed for {base_url}/models: {last_error}")


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


def launch_background(args: argparse.Namespace) -> int:
    root = repo_root()
    bin_dir = runtime_bin_dir(root)
    log_dir = provisioning_log_dir(root, "rig")
    log_dir.mkdir(parents=True, exist_ok=True)

    profile = resolve_model_profile(root, args.model_profile, args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"))
    binary = find_server_bin(bin_dir, args.server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"))
    server_dir = binary.parent
    model_override = args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE") or profile.model_file
    model_path, model_arg = resolve_model(bin_dir, server_dir, model_override)
    device = args.device
    if device is None and sys.platform == "win32":
        device = "Vulkan0"
    last_error: str | None = None

    for port in candidate_ports(args.host, args.port):
        base_url = f"http://{args.host}:{port}/v1"
        log_path = log_dir / f"rig-{port}.log"
        meta_path = log_dir / f"rig-{port}.meta.json"
        command = build_command(
            binary=binary,
            model_arg=model_arg,
            host=args.host,
            port=port,
            device=device,
            gpu_layers=args.gpu_layers or profile.gpu_layers,
            context=args.context if args.context is not None else profile.context,
            parallel=args.parallel if args.parallel is not None else profile.parallel,
            fit=args.fit or profile.fit,
            reasoning=args.reasoning or profile.reasoning,
            sampling=profile.sampling,
            chat_template_kwargs=profile.chat_template_kwargs,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "event": "launch_requested",
                    "binary": str(binary),
                    "working_dir": str(server_dir),
                    "command": command,
                    "host": args.host,
                    "port": port,
                    "model": model_path.name,
                    "model_profile": profile.name,
                    "sampling": profile.sampling,
                    "chat_template_kwargs": profile.chat_template_kwargs,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            process = subprocess.Popen(
                command,
                cwd=server_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        pid = process.pid
        log_path_for_result: Path | None = log_path

        try:
            wait_for_health(base_url, args.health_timeout, process=process, log_path=log_path_for_result)
        except BaseException as exc:
            last_error = str(exc)
            try:
                process.kill()
            except OSError:
                pass
            continue

        result = LaunchResult(
            pid=pid,
            port=port,
            host=args.host,
            base_url=base_url,
            model=model_path.name,
            binary=str(binary),
            log_path=str(log_path_for_result) if log_path_for_result else None,
        )
        if log_path_for_result is not None:
            with meta_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "event": "launch_ready",
                            "pid": pid,
                            "base_url": base_url,
                            "model": model_path.name,
                            "model_profile": profile.name,
                        }
                    )
                    + "\n"
                )
        print_result(result, args.json)
        return 0

    raise SystemExit(last_error or f"Unable to launch rig on {args.host}")


def launch_foreground(args: argparse.Namespace) -> int:
    root = repo_root()
    bin_dir = runtime_bin_dir(root)
    profile = resolve_model_profile(root, args.model_profile, args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"))
    binary = find_server_bin(bin_dir, args.server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"))
    server_dir = binary.parent
    model_override = args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE") or profile.model_file
    model_path, model_arg = resolve_model(bin_dir, server_dir, model_override)
    device = args.device
    if device is None and sys.platform == "win32":
        device = "Vulkan0"

    command = build_command(
        binary=binary,
        model_arg=model_arg,
        host=args.host,
        port=args.port,
        device=device,
        gpu_layers=args.gpu_layers or profile.gpu_layers,
        context=args.context if args.context is not None else profile.context,
        parallel=args.parallel if args.parallel is not None else profile.parallel,
        fit=args.fit or profile.fit,
        reasoning=args.reasoning or profile.reasoning,
        sampling=profile.sampling,
        chat_template_kwargs=profile.chat_template_kwargs,
    )

    if not args.json:
        print("Starting embedded rig...")
        print(f"  Endpoint: http://{args.host}:{args.port}/v1")
        print(f"  Model:    {model_path.name}")
        print(f"  Binary:   {binary}")
        print(f"  ModelArg: {model_arg}")
        print(f"  Profile:  {profile.name}")

    completed = subprocess.run(command, cwd=server_dir, check=False)
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
    parser.add_argument("--device", default=None, help="Pass through to llama-server. Windows default is 'Vulkan0'.")
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
