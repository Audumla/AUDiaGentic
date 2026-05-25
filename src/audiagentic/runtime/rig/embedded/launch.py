from __future__ import annotations

import argparse
import copy
import json
import os
import random
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import yaml

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
class ModelProfile:
    name: str
    model_file: str | None
    server_cfg: dict[str, object]
    agent_cfg: dict[str, object]
    chat_template_kwargs: dict[str, object]
    tool_call_proxy: str | None


# Maps rig.yaml keys whose CLI flag is not simple underscore->hyphen.
# Everything else passes through generically.
_LLAMA_ARG_MAP: list[tuple[str, str, str]] = [
    ("context_size", "--ctx-size", "value"),
]

_LLAMA_ARG_KEYS = {key for key, _, _ in _LLAMA_ARG_MAP}


_PKG_DIR = Path(__file__).parent           # .../rig/embedded/
_PKG_ROOT = Path(__file__).parents[3]      # .../audiagentic/


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


def rig_config_path() -> Path:
    return _PKG_ROOT / "config" / "provisioning" / "rig" / "rig.yaml"


def load_rig_config(profile_name: str) -> tuple[dict[str, object], dict[str, object], str | None]:
    """Load resolved rig profile sections.

    Returns (server_cfg, chat_template_kwargs, tool_call_proxy).
    server_cfg contains llama-server args only.
    tool_call_proxy is e.g. "pythonic" or None.
    """
    resolved = resolve_profile_definition(profile_name)
    server_cfg = resolved.get("server", {})
    prompt_cfg = resolved.get("prompt", {})
    proxy_cfg = resolved.get("proxy", {})
    chat_template_kwargs = prompt_cfg.get("chat_template", {}) if isinstance(prompt_cfg, dict) else {}
    tool_call_proxy = proxy_cfg.get("tool_call") if isinstance(proxy_cfg, dict) else None
    return (
        server_cfg if isinstance(server_cfg, dict) else {},
        chat_template_kwargs if isinstance(chat_template_kwargs, dict) else {},
        tool_call_proxy if isinstance(tool_call_proxy, str) else None,
    )



def load_rig_profiles(_profiles_path: Path | None = None) -> dict[str, object]:
    path = _profiles_path or rig_config_path()
    if not path.exists():
        raise SystemExit(f"Rig config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_rig_model(_profiles_path: Path | None = None) -> tuple[str, str]:
    data = load_rig_profiles(_profiles_path)
    raw = data.get("rig_model", {})
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid rig_model config: {rig_config_path()}")
    profile = raw.get("profile")
    model_id = raw.get("model_id")
    if not isinstance(profile, str) or not profile:
        raise SystemExit(f"rig_model.profile is required in {rig_config_path()}")
    if not isinstance(model_id, str) or not model_id:
        raise SystemExit(f"rig_model.model_id is required in {rig_config_path()}")
    return profile, model_id


def _deep_merge(base: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    for key, value in incoming.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge(current, value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def resolve_profile_definition(profile_name: str, _profiles_path: Path | None = None) -> dict[str, object]:
    data = load_rig_profiles(_profiles_path)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid rig config: {rig_config_path()}")
    raw = models.get(profile_name)
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {profile_name}")

    settings = data.get("profile_settings", {})
    if not isinstance(settings, dict):
        settings = {}

    merged: dict[str, object] = {}
    extends = raw.get("extends", [])
    if isinstance(extends, str):
        extends = [extends]
    for setting_name in extends:
        block = settings.get(setting_name, {})
        if not isinstance(block, dict):
            raise SystemExit(f"Profile setting not found or invalid: {setting_name}")
        _deep_merge(merged, block)

    local = {k: v for k, v in raw.items() if k != "extends"}
    _deep_merge(merged, local)

    server_cfg = merged.get("server", {})
    agent_cfg = merged.get("agent", {})
    prompt_cfg = merged.get("prompt", {})
    proxy_cfg = merged.get("proxy", {})
    if not isinstance(server_cfg, dict):
        server_cfg = {}
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
    if not isinstance(prompt_cfg, dict):
        prompt_cfg = {}
    if not isinstance(proxy_cfg, dict):
        proxy_cfg = {}

    if "context_size" not in agent_cfg and "context_size" in server_cfg:
        agent_cfg["context_size"] = server_cfg["context_size"]
    if "reasoning" not in agent_cfg and "reasoning" in server_cfg:
        raw_reasoning = server_cfg["reasoning"]
        agent_cfg["reasoning"] = str(raw_reasoning).lower() in {"1", "true", "on", "yes"}

    merged["server"] = server_cfg
    merged["agent"] = agent_cfg
    merged["prompt"] = prompt_cfg
    merged["proxy"] = proxy_cfg
    return merged


def load_model_profiles(_profiles_path: Path | None = None) -> dict[str, object]:
    """Compatibility name: returns rig.yaml payload."""
    return load_rig_profiles(_profiles_path)


def resolve_model_profile(requested: str | None, model_file: str | None, _profiles_path: Path | None = None) -> ModelProfile:
    data = load_rig_profiles(_profiles_path)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid rig config: {rig_config_path()}")

    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE")
    rig_profile, rig_model_id = load_rig_model(_profiles_path)
    if target == rig_model_id:
        target = rig_profile
    if not target and model_file:
        model_name = Path(model_file).name
        for name, raw_profile in models.items():
            if not isinstance(raw_profile, dict):
                continue
            if model_name == raw_profile.get("model_file"):
                target = str(name)
                break
    if not target:
        target = rig_profile
    if not target:
        raise SystemExit(f"No model profile specified and no rig_model.profile set in {rig_config_path()}")

    raw = models.get(target)
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {target}")

    resolved = resolve_profile_definition(target, _profiles_path)
    server_cfg = resolved.get("server", {})
    agent_cfg = resolved.get("agent", {})
    prompt_cfg = resolved.get("prompt", {})
    proxy_cfg = resolved.get("proxy", {})
    return ModelProfile(
        name=target,
        model_file=resolved.get("model_file") if isinstance(resolved.get("model_file"), str) else None,
        server_cfg=server_cfg if isinstance(server_cfg, dict) else {},
        agent_cfg=agent_cfg if isinstance(agent_cfg, dict) else {},
        chat_template_kwargs=(
            prompt_cfg.get("chat_template", {})
            if isinstance(prompt_cfg, dict) and isinstance(prompt_cfg.get("chat_template", {}), dict)
            else {}
        ),
        tool_call_proxy=(
            proxy_cfg.get("tool_call")
            if isinstance(proxy_cfg, dict) and isinstance(proxy_cfg.get("tool_call"), str)
            else None
        ),
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
        candidate = ensure_under(resolve_under(bin_dir, override) or Path(), bin_dir, "AUDIAGENTIC_RIG_SERVER_BIN")
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


def executable_command(binary: Path) -> list[str]:
    """Return command prefix for binary, wrapping APE/cosmopolitan files on Unix."""
    if sys.platform == "win32":
        return [str(binary)]
    try:
        if binary.read_bytes()[:2] == b"MZ":
            return ["sh", str(binary)]
    except OSError:
        pass
    return [str(binary)]


def resolve_model(bin_dir: Path, server_dir: Path, override: str | None) -> tuple[Path, str]:
    if not override:
        raise SystemExit("No model file specified. Set --model-file or AUDIAGENTIC_RIG_MODEL_FILE, or add model_file to the profile.")
    candidate = resolve_under(bin_dir, override, base=server_dir)
    assert candidate is not None
    ensure_under(candidate, bin_dir, "AUDIAGENTIC_RIG_MODEL_FILE")
    if not candidate.exists():
        raise SystemExit(f"Model not found: {candidate}")
    if Path(override).is_absolute():
        return candidate, str(candidate)
    return candidate, override


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
    server_cfg: dict[str, object],
    chat_template_kwargs: dict[str, object],
    alias: str | None = None,
) -> list[str]:
    args: list[str] = []
    if binary.name.startswith("llamafile"):
        args.append("--server")
    args.extend(["--host", host, "--port", str(port), "--model", model_arg])
    if alias:
        args.extend(["--alias", alias])
    if device:
        args.extend(["--device", device])
    for key, flag, kind in _LLAMA_ARG_MAP:
        val = server_cfg.get(key)
        if val is None:
            continue
        if kind == "value":
            args.extend([flag, str(val)])
        elif kind == "flag" and val:
            args.append(flag)
    for key, val in server_cfg.items():
        if key in _LLAMA_ARG_KEYS or val is None:
            continue
        flag = f"--{key.replace('_', '-')}"
        if isinstance(val, bool):
            if val:
                args.append(flag)
            continue
        args.extend([flag, str(val)])
    if chat_template_kwargs:
        args.extend(["--chat-template-kwargs", json.dumps(chat_template_kwargs, separators=(",", ":"))])
    return [*executable_command(binary), *args]


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


def _apply_cli_overrides(server_cfg: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    """Return a copy of server_cfg with any explicit CLI / env overrides applied."""
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
    bin_dir = runtime_bin_dir()
    from audiagentic.runtime.home import global_harness_runtime

    log_dir = global_harness_runtime() / "logs" / "rig"
    log_dir.mkdir(parents=True, exist_ok=True)

    profile = resolve_model_profile(model_profile, model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"))
    binary = find_server_bin(bin_dir, server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"))
    server_dir = binary.parent
    model_override = model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE") or profile.model_file
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
    last_error: str | None = None

    for candidate_port in candidate_ports(host, port):
        base_url = f"http://{host}:{candidate_port}/v1"
        log_path = log_dir / f"rig-{candidate_port}.log"
        meta_path = log_dir / f"rig-{candidate_port}.meta.json"
        command = build_command(
            binary=binary,
            model_arg=model_arg,
            host=host,
            port=candidate_port,
            device=resolved_device,
            server_cfg=server_cfg,
            chat_template_kwargs=profile.chat_template_kwargs,
            alias=profile.name,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "event": "launch_requested",
                    "binary": str(binary),
                    "working_dir": str(server_dir),
                    "command": command,
                    "host": host,
                    "port": candidate_port,
                    "model": model_path.name,
                    "model_profile": profile.name,
                    "server_cfg": server_cfg,
                    "chat_template_kwargs": profile.chat_template_kwargs,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if on_progress:
            on_progress(f"[rig] launching {profile.name} on {base_url}")

        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            process = subprocess.Popen(
                command,
                cwd=server_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        pid = process.pid

        try:
            wait_for_health(base_url, health_timeout, process=process, log_path=log_path)
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
            model=model_path.name,
            binary=str(binary),
            log_path=str(log_path),
        )
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
    bin_dir = runtime_bin_dir()
    profile = resolve_model_profile(args.model_profile, args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"))
    binary = find_server_bin(bin_dir, args.server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"))
    server_dir = binary.parent
    model_override = args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE") or profile.model_file
    model_path, model_arg = resolve_model(bin_dir, server_dir, model_override)
    device = args.device or os.environ.get("AUDIAGENTIC_RIG_DEVICE")
    server_cfg = _apply_cli_overrides(profile.server_cfg, args)

    command = build_command(
        binary=binary,
        model_arg=model_arg,
        host=args.host,
        port=args.port,
        device=device,
        server_cfg=server_cfg,
        chat_template_kwargs=profile.chat_template_kwargs,
        alias=profile.name,
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
