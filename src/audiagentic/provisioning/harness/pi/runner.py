from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

DEFAULT_MODEL = "Qwen_Qwen3.5-2B-Q4_K_S.gguf"
DEFAULT_PROVIDER = "llamaswap"
DEFAULT_API_KEY = "dummy"
DEFAULT_BASE_URL = "http://127.0.0.1:42001/v1"
DEFAULT_SMOKE_TIMEOUT = 60.0
TRUTHY = {"1", "true", "yes", "on"}

# Package-relative paths — work in both dev layout (src/) and pip-installed layout.
_PI_DIR = Path(__file__).parent                         # .../harness/pi/
_PROVISIONING_DIR = Path(__file__).parents[2]           # .../provisioning/
_TEMPLATES_DIR = _PI_DIR / "templates" / "harness-home"
_MODELS_JSON = _PROVISIONING_DIR / "rig" / "embedded" / "models.json"


@dataclass
class PiContext:
    project_root: Path
    pi_runtime: Path
    pi_home: Path
    pi_agent_dir: Path
    pi_bin: Path
    pi_work: Path
    pi_log_dir: Path
    endpoint: str
    model: str
    model_profile: dict[str, object]
    provider: str
    rig_pid: int | None
    enable_mcp: bool
    harness_cfg: dict = field(default_factory=dict)


def load_harness_config() -> dict:
    config_path = _PI_DIR / "config" / "config.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def resolve_pi_bin(pi_runtime: Path) -> Path:
    return pi_runtime / "node" / "node_modules" / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")


def load_model_profile(requested: str | None, model: str) -> tuple[str, dict[str, object]]:
    data = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid model profile file: {_MODELS_JSON}")
    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE") or os.environ.get("AUDIAGENTIC_PI_MODEL_PROFILE")
    if not target:
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


def _materialize_ui(ctx: PiContext) -> None:
    ui = ctx.harness_cfg.get("ui", {})
    if not ui:
        return

    theme_name = ui.get("theme", "dark")
    theme_colors = ui.get("theme_colors") or {}

    if theme_colors:
        base_theme_dir = (
            ctx.pi_runtime
            / "node"
            / "node_modules"
            / "@earendil-works"
            / "pi-coding-agent"
            / "dist"
            / "modes"
            / "interactive"
            / "theme"
        )
        base_path = base_theme_dir / f"{theme_name}.json"
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"vars": {}, "colors": {}, "export": {}}
        base.setdefault("colors", {}).update(theme_colors)
        themes_dir = ctx.pi_agent_dir / "themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        custom_theme_path = themes_dir / "audiagentic.json"
        custom_theme_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        theme_name = str(custom_theme_path)

    settings: dict[str, object] = {}
    settings["theme"] = theme_name
    if "quiet_startup" in ui:
        settings["quietStartup"] = bool(ui["quiet_startup"])
    if "collapse_changelog" in ui:
        settings["collapseChangelog"] = bool(ui["collapse_changelog"])
    if "hide_thinking_block" in ui:
        settings["hideThinkingBlock"] = bool(ui["hide_thinking_block"])
    if "thinking" in ui:
        settings["defaultThinkingLevel"] = str(ui["thinking"])
    if "editor_padding_x" in ui:
        settings["editorPaddingX"] = int(ui["editor_padding_x"])

    settings["extensions"] = ["extensions/footer.ts"]

    settings_path = ctx.pi_agent_dir / "settings.json"
    existing: dict[str, object] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    existing.update(settings)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def materialize_config(ctx: PiContext) -> None:
    ctx.pi_home.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_TEMPLATES_DIR, ctx.pi_home, dirs_exist_ok=True)

    replacements = {
        "__AUDIAGENTIC_PI_BASE_URL__": ctx.endpoint,
        "__AUDIAGENTIC_PI_API_KEY__": os.environ.get("AUDIAGENTIC_PI_API_KEY", DEFAULT_API_KEY),
        "__AUDIAGENTIC_PI_MODEL__": ctx.model,
        "__AUDIAGENTIC_PI_FALLBACK_MODEL__": os.environ.get("AUDIAGENTIC_PI_FALLBACK_MODEL", ctx.model),
        "__AUDIAGENTIC_REPO_ROOT__": str(ctx.project_root).replace("\\", "/"),
        "__AUDIAGENTIC_PYTHON__": os.environ.get("AUDIAGENTIC_PI_PYTHON", "python").replace("\\", "/"),
    }

    for path in (ctx.pi_agent_dir / "models.json", ctx.pi_agent_dir / "mcp.json"):
        text = path.read_text(encoding="utf-8")
        for needle, value in replacements.items():
            text = text.replace(needle, value)
        path.write_text(text, encoding="utf-8")

    pi_profile = ctx.model_profile.get("pi", {})
    if isinstance(pi_profile, dict):
        models_path = ctx.pi_agent_dir / "models.json"
        models_config = json.loads(models_path.read_text(encoding="utf-8"))
        provider_config = models_config["providers"][ctx.provider]
        for model_config in provider_config.get("models", []):
            model_config["contextWindow"] = int(pi_profile.get("context_window", model_config["contextWindow"]))
            model_config["maxTokens"] = int(pi_profile.get("max_tokens", model_config["maxTokens"]))
            model_config["reasoning"] = bool(pi_profile.get("reasoning", model_config.get("reasoning", False)))
            if isinstance(pi_profile.get("compat"), dict):
                provider_config["compat"] = pi_profile["compat"]
        models_path.write_text(json.dumps(models_config, indent=2) + "\n", encoding="utf-8")

    _materialize_ui(ctx)

    if not ctx.enable_mcp:
        (ctx.pi_agent_dir / "mcp.json").write_text(
            json.dumps(
                {"settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": False}, "mcpServers": {}},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        extra_server_args = ctx.harness_cfg.get("mcp", {}).get("extra_server_args", [])
        if extra_server_args:
            mcp_path = ctx.pi_agent_dir / "mcp.json"
            mcp_config = json.loads(mcp_path.read_text(encoding="utf-8"))
            for server in mcp_config.get("mcpServers", {}).values():
                server.setdefault("args", [])
                server["args"].extend(extra_server_args)
            mcp_path.write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")


def launch_rig_if_needed(model: str, profile_name: str) -> tuple[str, str, int | None]:
    endpoint = os.environ.get("AUDIAGENTIC_PI_BASE_URL", DEFAULT_BASE_URL)
    if os.environ.get("AUDIAGENTIC_PI_BASE_URL"):
        return endpoint, model, None

    env = env_with_pythonpath()
    completed = subprocess.run(
        [sys.executable, "-m", "audiagentic.provisioning.rig.embedded.launch",
         "--model-profile", profile_name, "--port", "0", "--background", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip() or "Failed to launch embedded rig.")

    payload = json.loads(completed.stdout.strip())
    endpoint = payload["base_url"]
    model = os.environ.get("AUDIAGENTIC_PI_MODEL", payload["model"])
    os.environ["AUDIAGENTIC_PI_BASE_URL"] = endpoint
    os.environ.setdefault("AUDIAGENTIC_PI_MODEL", model)
    return endpoint, model, int(payload["pid"])


def build_global_context(*, project_root: Path, pi_runtime: Path, enable_mcp: bool) -> PiContext:
    harness_cfg = load_harness_config()
    requested_model = os.environ.get("AUDIAGENTIC_PI_MODEL", harness_cfg.get("model", DEFAULT_MODEL))
    profile_name, model_profile = load_model_profile(None, requested_model)
    endpoint, model, rig_pid = launch_rig_if_needed(requested_model, profile_name)
    provider = os.environ.get("AUDIAGENTIC_PI_PROVIDER", DEFAULT_PROVIDER)
    resolved_enable_mcp = enable_mcp or bool(harness_cfg.get("mcp", {}).get("enabled", False))
    return PiContext(
        project_root=project_root,
        pi_runtime=pi_runtime,
        pi_home=pi_runtime,
        pi_agent_dir=pi_runtime / "agent",
        pi_bin=resolve_pi_bin(pi_runtime),
        pi_work=project_root,
        pi_log_dir=project_root / ".audiagentic" / "logs" / "tui",
        endpoint=endpoint,
        model=model,
        model_profile=model_profile,
        provider=provider,
        rig_pid=rig_pid,
        enable_mcp=resolved_enable_mcp,
        harness_cfg=harness_cfg,
    )



def check_endpoint(ctx: PiContext) -> None:
    import urllib.request
    with urllib.request.urlopen(f"{ctx.endpoint}/models", timeout=15) as response:
        if response.status != 200:
            raise SystemExit(f"Endpoint health failed: {ctx.endpoint}/models -> {response.status}")


def direct_mcp_smoke(ctx: PiContext, env: dict[str, str]) -> None:
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


def build_pi_command(ctx: PiContext, *, smoke: bool) -> list[str]:
    cfg = ctx.harness_cfg
    tools_cfg = cfg.get("tools", {})
    ext_cfg = cfg.get("extensions", {})
    sandbox_cfg = cfg.get("sandbox", {})

    command = [str(ctx.pi_bin)]

    command.extend(["--provider", ctx.provider, "--model", ctx.model])

    if smoke:
        command.extend([
            "--no-session", "--no-tools", "--no-context-files",
            "--no-skills", "--no-prompt-templates", "--no-themes",
            "--thinking", "off",
            "--system-prompt", "Return only the exact requested string. No markdown. No explanation.",
            "-p", "Return only this exact ASCII string, no punctuation, no markdown: audiagentic-pi-local-ok",
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

        for flag in cfg.get("extra_flags", []):
            command.append(flag)

    if not smoke:
        # Block auto-discovery then explicitly load our extensions.
        command.append("--no-extensions")
        command.extend(["--extension", str(ctx.pi_agent_dir / "extensions" / "footer.ts")])
        for ext in ext_cfg.get("load", []):
            command.extend(["--extension", str(ext)])

    if ctx.enable_mcp:
        command.extend([
            "--extension", str(ctx.pi_runtime / "node" / "node_modules" / "pi-mcp-adapter"),
            "--mcp-config", str(ctx.pi_agent_dir / "mcp.json"),
        ])

    return command


def run_pi(ctx: PiContext, pi_args: list[str], *, smoke: bool) -> int:
    if not ctx.pi_bin.exists():
        raise SystemExit("Pi not found. Run: audiagentic install")

    if not smoke:
        print("\033[2J\033[H", end="", flush=True)

    ctx.pi_work.mkdir(parents=True, exist_ok=True)
    ctx.pi_log_dir.mkdir(parents=True, exist_ok=True)
    materialize_config(ctx)

    env = env_with_pythonpath()
    env["HOME"] = str(ctx.pi_home)
    env["PI_CODING_AGENT_DIR"] = str(ctx.pi_agent_dir)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(ctx.pi_runtime / "sessions")
    env["AUDIAGENTIC_REPO_ROOT"] = str(ctx.project_root)
    env["AUDIAGENTIC_PI_BASE_URL"] = ctx.endpoint
    env["AUDIAGENTIC_PI_MODEL"] = ctx.model

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "smoke" if smoke else "run"
    log_path = ctx.pi_log_dir / f"{mode}-{stamp}.log"

    if smoke:
        print(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        check_endpoint(ctx)
        if ctx.enable_mcp:
            print("Checking direct MCP smoke")
            direct_mcp_smoke(ctx, env)
        else:
            print("MCP disabled")
        print(f"Writing Pi smoke log: {log_path}")
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
                print("  Tools:    Pi defaults")
            print(f"  Log:      {log_path}")
            print()

    command = build_pi_command(ctx, smoke=smoke)

    if smoke:
        smoke_timeout = float(
            os.environ.get("AUDIAGENTIC_PI_SMOKE_TIMEOUT",
                           ctx.harness_cfg.get("smoke", {}).get("timeout", DEFAULT_SMOKE_TIMEOUT))
        )
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(command, cwd=ctx.pi_work, env=env,
                                       stdout=handle, stderr=subprocess.STDOUT, text=True)
            try:
                returncode = process.wait(timeout=smoke_timeout)
            except subprocess.TimeoutExpired:
                cleanup_process_tree(process.pid)
                handle.write(f"\nSmoke timed out after {smoke_timeout:.1f}s\n")
                return 124
        sys.stdout.write(log_path.read_text(encoding="utf-8"))
        if returncode == 0 and "audiagentic-pi-local-ok" not in log_path.read_text(encoding="utf-8"):
            return 1
        return int(returncode)

    command.extend(pi_args)
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "event": "pi_run_started", "project_root": str(ctx.project_root),
            "provider": ctx.provider, "model": ctx.model,
            "endpoint": ctx.endpoint, "mcp": ctx.enable_mcp, "args": pi_args,
        }, indent=2) + "\n")

    completed = subprocess.run(command, cwd=ctx.project_root, env=env, check=False)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "pi_run_finished", "returncode": int(completed.returncode)}) + "\n")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(1)  # Use: audiagentic [args]
