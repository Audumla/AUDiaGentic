from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "Qwen_Qwen3.5-2B-Q4_K_S.gguf"
DEFAULT_PROVIDER = "audiagentic"
DEFAULT_RIG_PORT = 42001
DEFAULT_SMOKE_TIMEOUT = 60.0
TRUTHY = {"1", "true", "yes", "on"}

# Package-relative paths — work in both dev layout (src/) and pip-installed layout.
_AGENT_DIR = Path(__file__).parent                              # .../harness/pi/
_PKG_ROOT = Path(__file__).parents[3]                          # .../audiagentic/
_MODELS_JSON = _PKG_ROOT / "provisioning" / "rig" / "embedded" / "models.json"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"


@dataclass
class AgentContext:
    project_root: Path
    agent_runtime: Path
    agent_home: Path
    agent_dir: Path
    agent_bin: Path
    agent_work: Path
    agent_log_dir: Path
    endpoint: str
    model: str
    model_profile: dict[str, object]
    profile_name: str
    provider: str
    rig_pid: int | None
    manages_rig: bool           # True when connected to embedded rig (started or reused)
    enable_mcp: bool
    harness_cfg: dict = field(default_factory=dict)


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.provisioning.config_loader import load_layered_config
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def resolve_agent_bin(agent_runtime: Path) -> Path:
    return agent_runtime / "cli" / "node_modules" / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")


def load_model_profile(requested: str | None, model: str) -> tuple[str, dict[str, object]]:
    data = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid model profile file: {_MODELS_JSON}")
    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE") or os.environ.get("AUDIAGENTIC_AG_MODEL_PROFILE")
    if not target:
        # Direct key match first, then alias search, then default.
        if model in models:
            target = model
        else:
            for name, raw_profile in models.items():
                if isinstance(raw_profile, dict) and model in raw_profile.get("aliases", []):
                    target = str(name)
                    break
    target = target or str(data.get("default"))
    raw = models.get(target)
    if raw is None:
        for name, raw_profile in models.items():
            if isinstance(raw_profile, dict) and target in raw_profile.get("aliases", []):
                target = str(name)
                raw = raw_profile
                break
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {target}")
    return target, raw


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in TRUTHY




def launch_rig_if_needed(
    model: str,
    profile_name: str,
    model_profile: dict[str, object],
    rig_port: int = DEFAULT_RIG_PORT,
) -> tuple[str, str, int | None, bool]:
    """Return (endpoint, model, rig_pid, manages_rig).

    manages_rig is True when connected to an embedded rig (started now or reused).
    rig_pid is set only when *this* call started the rig; None means reused or external.
    """
    if os.environ.get("AUDIAGENTIC_AG_BASE_URL"):
        return os.environ["AUDIAGENTIC_AG_BASE_URL"], model, None, False
    if not model_profile.get("model_file"):
        return f"http://127.0.0.1:{rig_port}/v1", model, None, False

    from audiagentic.provisioning.rig.registry import StartupLock, read_rig_state, write_rig_state

    with StartupLock():
        # Reuse a running rig if one already exists.
        state = read_rig_state()
        if state is not None:
            endpoint = str(state["endpoint"])
            reused_model = os.environ.get("AUDIAGENTIC_AG_MODEL", str(state.get("model", model)))
            os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
            os.environ.setdefault("AUDIAGENTIC_AG_MODEL", reused_model)
            return endpoint, reused_model, None, True

        # Start a new embedded rig.
        env = env_with_pythonpath()
        completed = subprocess.run(
            [sys.executable, "-m", "audiagentic.provisioning.rig.embedded.launch",
             "--model-profile", profile_name, "--port", str(rig_port), "--background", "--json"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(
                completed.stderr.strip() or completed.stdout.strip() or "Failed to launch embedded rig."
            )

        payload = json.loads(completed.stdout.strip())
        endpoint = payload["base_url"]
        pid = int(payload["pid"])
        model = os.environ.get("AUDIAGENTIC_AG_MODEL", payload["model"])
        write_rig_state(pid, rig_port, endpoint, model)
        os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
        os.environ.setdefault("AUDIAGENTIC_AG_MODEL", model)
        return endpoint, model, pid, True


def build_global_context(*, project_root: Path, agent_runtime: Path, enable_mcp: bool) -> AgentContext:
    harness_cfg = load_harness_config(project_root=project_root)
    requested_model = os.environ.get("AUDIAGENTIC_AG_MODEL", harness_cfg.get("model", DEFAULT_MODEL))
    profile_name, model_profile = load_model_profile(None, requested_model)
    rig_port = int(harness_cfg.get("rig", {}).get("port", DEFAULT_RIG_PORT))
    endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(
        requested_model, profile_name, model_profile, rig_port=rig_port
    )
    model = query_server_model(endpoint) or model
    provider = os.environ.get("AUDIAGENTIC_AG_PROVIDER", DEFAULT_PROVIDER)
    resolved_enable_mcp = enable_mcp or bool(harness_cfg.get("mcp", {}).get("enabled", False))
    return AgentContext(
        project_root=project_root,
        agent_runtime=agent_runtime,
        agent_home=agent_runtime,
        agent_dir=agent_runtime / "agent",
        agent_bin=resolve_agent_bin(agent_runtime),
        agent_work=project_root,
        agent_log_dir=project_root / ".audiagentic" / "logs" / "cli",
        endpoint=endpoint,
        model=model,
        model_profile=model_profile,
        profile_name=profile_name,
        provider=provider,
        rig_pid=rig_pid,
        manages_rig=manages_rig,
        enable_mcp=resolved_enable_mcp,
        harness_cfg=harness_cfg,
    )



def query_server_model(endpoint: str, timeout: float = 10.0) -> str | None:
    """Query the server's /models endpoint and return the first model ID, or None on failure."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{endpoint}/models", timeout=timeout) as response:
            if response.status == 200:
                data = json.loads(response.read())
                models = data.get("data", [])
                if models:
                    return str(models[0]["id"])
    except Exception:
        pass
    return None


def check_endpoint(ctx: AgentContext) -> None:
    import urllib.request
    with urllib.request.urlopen(f"{ctx.endpoint}/models", timeout=15) as response:
        if response.status != 200:
            raise SystemExit(f"Endpoint health failed: {ctx.endpoint}/models -> {response.status}")


def direct_mcp_smoke(ctx: AgentContext, env: dict[str, str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "audiagentic.provisioning.mcp.server", "--readonly", "--smoke-only", "--direct-smoke"],
        cwd=ctx.project_root,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def cleanup_rig(pid: int | None) -> None:
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def cleanup_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def build_agent_command(ctx: AgentContext, *, smoke: bool) -> list[str]:
    cfg = ctx.harness_cfg
    tools_cfg = cfg.get("tools", {})
    ext_cfg = cfg.get("extensions", {})
    sandbox_cfg = cfg.get("sandbox", {})
    lockdown_cfg = cfg.get("lockdown", {})

    command = [str(ctx.agent_bin)]

    command.extend(["--provider", ctx.provider, "--model", ctx.model])

    if smoke:
        command.extend([
            "--no-session", "--no-tools", "--no-context-files",
            "--no-skills", "--no-prompt-templates", "--no-themes",
            "--thinking", "off",
            "--system-prompt", "Return only the exact requested string. No markdown. No explanation.",
            "-p", "Return only this exact ASCII string, no punctuation, no markdown: audiagentic-agent-local-ok",
        ])
    else:
        if tools_cfg.get("no_all", False):
            command.append("--no-tools")
        elif tools_cfg.get("no_builtin", False):
            command.append("--no-builtin-tools")
        elif tools_cfg.get("allow") is not None:
            command.extend(["--tools", ",".join(tools_cfg["allow"])])

        for ext_path in ext_cfg.get("load", []):
            command.extend(["-e", str(ext_path)])

        custom_header = cfg.get("ui", {}).get("custom_header_extension")
        if custom_header:
            command.extend(["-e", str(custom_header)])

        if sandbox_cfg.get("enabled"):
            sandbox_path = sandbox_cfg.get("config_path")
            if sandbox_path:
                command.extend(["--sandbox-config", str(sandbox_path)])

        if lockdown_cfg.get("no_skills", True):
            command.append("--no-skills")
        if lockdown_cfg.get("no_prompt_templates", True):
            command.append("--no-prompt-templates")
        if lockdown_cfg.get("no_context_files", True):
            command.append("--no-context-files")

        for flag in cfg.get("extra_flags", []):
            command.append(flag)

    if not smoke:
        # Block auto-discovery then explicitly load our extensions.
        command.append("--no-extensions")
        command.extend(["--extension", str(ctx.agent_dir / "extensions" / "footer.ts")])
        for ext in ext_cfg.get("load", []):
            command.extend(["--extension", str(ext)])

    if ctx.enable_mcp:
        command.extend([
            "--extension", str(ctx.agent_runtime / "cli" / "node_modules" / "pi-mcp-adapter"),
            "--mcp-config", str(ctx.agent_dir / "mcp.json"),
        ])

    return command


def _build_run_env(ctx: AgentContext) -> dict[str, str]:
    env = env_with_pythonpath()
    env["HOME"] = str(ctx.agent_home)
    env["PI_CODING_AGENT_DIR"] = str(ctx.agent_dir)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(ctx.project_root / ".audiagentic" / "sessions")
    env["AUDIAGENTIC_REPO_ROOT"] = str(ctx.project_root)
    env["AUDIAGENTIC_AG_BASE_URL"] = ctx.endpoint
    env["AUDIAGENTIC_AG_MODEL"] = ctx.model
    env["AUDIAGENTIC_RIG_TYPE"] = "embedded" if ctx.rig_pid is not None else "external"
    env["AUDIAGENTIC_RIG_PROFILE"] = ctx.profile_name
    return env


def run_agent(ctx: AgentContext, agent_args: list[str], *, smoke: bool) -> int:
    if not ctx.agent_bin.exists():
        raise SystemExit("AudiaGentic agent not found. Run: audiagentic install")

    if not smoke:
        print("\033[2J\033[H", end="", flush=True)

    ctx.agent_work.mkdir(parents=True, exist_ok=True)
    ctx.agent_log_dir.mkdir(parents=True, exist_ok=True)
    (ctx.project_root / ".audiagentic" / "sessions").mkdir(parents=True, exist_ok=True)

    env = _build_run_env(ctx)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "smoke" if smoke else "run"
    log_path = ctx.agent_log_dir / f"{mode}-{stamp}.log"

    if smoke:
        print(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        check_endpoint(ctx)
        if ctx.enable_mcp:
            print("Checking direct MCP smoke")
            direct_mcp_smoke(ctx, env)
        else:
            print("MCP disabled")
        print(f"Writing AudiaGentic smoke log: {log_path}")
    else:
        ui_cfg = ctx.harness_cfg.get("ui", {})
        tools_cfg = ctx.harness_cfg.get("tools", {})

        banner = ui_cfg.get("startup_banner")
        if banner:
            print(banner, end="" if str(banner).endswith("\n") else "\n")

        if ui_cfg.get("show_startup_info", True):
            print("AUDiaGentic")
            print(f"  Project:  {ctx.project_root}")
            print(f"  Provider: {ctx.provider}")
            print(f"  Model:    {ctx.model}")
            print(f"  Endpoint: {ctx.endpoint}")
            print(f"  MCP:      {'enabled' if ctx.enable_mcp else 'disabled'}")
            if tools_cfg.get("no_all"):
                print("  Tools:    none (all disabled)")
            elif tools_cfg.get("no_builtin"):
                print("  Tools:    MCP/extensions only (built-ins disabled)")
            elif tools_cfg.get("allow") is not None:
                print(f"  Tools:    {','.join(tools_cfg['allow'])}")
            else:
                print("  Tools:    AudiaGentic defaults")
            print(f"  Log:      {log_path}")
            print()

    command = build_agent_command(ctx, smoke=smoke)

    if smoke:
        smoke_timeout = float(
            os.environ.get("AUDIAGENTIC_AG_SMOKE_TIMEOUT",
                           ctx.harness_cfg.get("smoke", {}).get("timeout", DEFAULT_SMOKE_TIMEOUT))
        )
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(command, cwd=ctx.agent_work, env=env,
                                       stdout=handle, stderr=subprocess.STDOUT, text=True)
            try:
                returncode = process.wait(timeout=smoke_timeout)
            except subprocess.TimeoutExpired:
                cleanup_process_tree(process.pid)
                handle.write(f"\nSmoke timed out after {smoke_timeout:.1f}s\n")
                return 124
        sys.stdout.write(log_path.read_text(encoding="utf-8"))
        if returncode == 0 and "audiagentic-agent-local-ok" not in log_path.read_text(encoding="utf-8"):
            return 1
        return int(returncode)

    command.extend(agent_args)
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "event": "agent_run_started", "project_root": str(ctx.project_root),
            "provider": ctx.provider, "model": ctx.model,
            "endpoint": ctx.endpoint, "mcp": ctx.enable_mcp, "args": agent_args,
        }, indent=2) + "\n")

    completed = subprocess.run(command, cwd=ctx.agent_work, env=env, check=False)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "agent_run_finished", "returncode": int(completed.returncode)}) + "\n")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(1)  # Use: audiagentic [args]
