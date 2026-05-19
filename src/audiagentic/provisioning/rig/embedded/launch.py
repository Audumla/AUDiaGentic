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
    server_cfg: dict[str, object]            # merged rig.yaml defaults + model overrides
    chat_template_kwargs: dict[str, object]  # serialised as --chat-template-kwargs JSON
    tool_call_proxy: str | None              # "pythonic" → start reformat proxy


# Maps rig.yaml keys → (llama-server flag, kind)
# kind "value": --flag <val>   kind "flag": --flag  (boolean, emitted only when true)
_LLAMA_ARG_MAP: list[tuple[str, str, str]] = [
    ("ctx_size",          "--ctx-size",            "value"),
    ("parallel",          "--parallel",            "value"),
    ("gpu_layers",        "--gpu-layers",          "value"),
    ("fit",               "--fit",                 "value"),
    ("reasoning",         "--reasoning",           "value"),
    ("threads",           "--threads",             "value"),
    ("batch_size",        "--batch-size",          "value"),
    ("ubatch_size",       "--ubatch-size",         "value"),
    ("cache_type_k",      "--cache-type-k",        "value"),
    ("cache_type_v",      "--cache-type-v",        "value"),
    ("jinja",             "--jinja",               "flag"),
    ("no_mmap",           "--no-mmap",             "flag"),
    ("mlock",             "--mlock",               "flag"),
    ("flash_attn",        "--flash-attn",          "value"),
    ("temp",              "--temp",                "value"),
    ("top_p",             "--top-p",               "value"),
    ("top_k",             "--top-k",               "value"),
    ("min_p",             "--min-p",               "value"),
    ("top_a",             "--top-a",               "value"),
    ("presence_penalty",  "--presence-penalty",    "value"),
    ("frequency_penalty", "--frequency-penalty",   "value"),
    ("repeat_penalty",    "--repeat-penalty",      "value"),
]


_PKG_DIR = Path(__file__).parent           # .../rig/embedded/
_PKG_ROOT = Path(__file__).parents[3]      # .../audiagentic/


def runtime_bin_dir() -> Path:
    from audiagentic.provisioning.home import global_harness_runtime
    return global_harness_runtime() / "rig" / "bin"


def model_profiles_path() -> Path:
    return _PKG_DIR / "models.json"


def rig_config_path() -> Path:
    return _PKG_ROOT / "config" / "provisioning" / "rig" / "rig.yaml"


def load_rig_config(profile_name: str) -> tuple[dict[str, object], dict[str, object], str | None]:
    """Load rig.yaml and merge defaults with per-model overrides.

    Returns (server_cfg, chat_template_kwargs, tool_call_proxy).
    server_cfg contains llama-server args only.
    tool_call_proxy is e.g. "pythonic" or None.
    """
    path = rig_config_path()
    if not path.exists():
        return {}, {}, None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged: dict[str, object] = dict(data.get("defaults", {}))
    model_overrides = data.get("models", {}).get(profile_name, {})
    if isinstance(model_overrides, dict):
        merged.update(model_overrides)
    chat_template_kwargs: dict[str, object] = {}
    raw_ctkw = merged.pop("chat_template_kwargs", None)
    if isinstance(raw_ctkw, dict):
        chat_template_kwargs = raw_ctkw
    tool_call_proxy: str | None = merged.pop("tool_call_proxy", None)  # type: ignore[assignment]
    if not isinstance(tool_call_proxy, str):
        tool_call_proxy = None
    return merged, chat_template_kwargs, tool_call_proxy



def load_model_profiles(_profiles_path: Path | None = None) -> dict[str, object]:
    path = _profiles_path or model_profiles_path()
    if not path.exists():
        raise SystemExit(f"Model profiles config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_model_profile(requested: str | None, model_file: str | None, _profiles_path: Path | None = None) -> ModelProfile:
    data = load_model_profiles(_profiles_path)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid model profile file: {model_profiles_path()}")

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
    if not target:
        raise SystemExit(f"No model profile specified and no default set in {model_profiles_path()}")

    raw = models.get(target)
    if raw is None:
        for name, raw_profile in models.items():
            if isinstance(raw_profile, dict) and target in raw_profile.get("aliases", []):
                target = str(name)
                raw = raw_profile
                break
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {target}")

    server_cfg, chat_template_kwargs, tool_call_proxy = load_rig_config(target)
    return ModelProfile(
        name=target,
        model_file=raw.get("model_file") if isinstance(raw.get("model_file"), str) else None,
        server_cfg=server_cfg,
        chat_template_kwargs=chat_template_kwargs,
        tool_call_proxy=tool_call_proxy,
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
    if chat_template_kwargs:
        args.extend(["--chat-template-kwargs", json.dumps(chat_template_kwargs, separators=(",", ":"))])
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


def _apply_cli_overrides(server_cfg: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    """Return a copy of server_cfg with any explicit CLI / env overrides applied."""
    cfg = dict(server_cfg)
    if args.gpu_layers:
        cfg["gpu_layers"] = args.gpu_layers
    if args.context is not None:
        cfg["ctx_size"] = args.context
    if args.parallel is not None:
        cfg["parallel"] = args.parallel
    if args.fit:
        cfg["fit"] = args.fit
    if args.reasoning:
        cfg["reasoning"] = args.reasoning
    return cfg


def launch_background(args: argparse.Namespace) -> int:
    bin_dir = runtime_bin_dir()
    from audiagentic.provisioning.home import global_harness_runtime
    log_dir = global_harness_runtime() / "logs" / "rig"
    log_dir.mkdir(parents=True, exist_ok=True)

    profile = resolve_model_profile(args.model_profile, args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE"))
    binary = find_server_bin(bin_dir, args.server_bin or os.environ.get("AUDIAGENTIC_RIG_SERVER_BIN"))
    server_dir = binary.parent
    model_override = args.model_file or os.environ.get("AUDIAGENTIC_RIG_MODEL_FILE") or profile.model_file
    model_path, model_arg = resolve_model(bin_dir, server_dir, model_override)
    device = args.device or os.environ.get("AUDIAGENTIC_RIG_DEVICE")
    server_cfg = _apply_cli_overrides(profile.server_cfg, args)
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
                    "host": args.host,
                    "port": port,
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
