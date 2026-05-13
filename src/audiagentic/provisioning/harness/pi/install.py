from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

# Pinned Pi version. Update here and re-run `audiagentic install` to upgrade.
PI_VERSION = "0.74.0"
PI_MCP_ADAPTER_VERSION = "latest"

_PI_DIR = Path(__file__).parent


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise SystemExit("npm is required to install the Pi TUI.")
    return resolved


def _load_blocked_commands() -> list[str]:
    config_path = _PI_DIR / "config" / "config.yaml"
    if not config_path.exists():
        raise SystemExit(f"Pi config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("lockdown", {}).get("block_builtin_commands", [])


def _pi_pkg_dir(pi_node: Path) -> Path:
    return pi_node / "node_modules" / "@earendil-works" / "pi-coding-agent"


def _patch_slash_commands(pi_node: Path, blocked: list[str]) -> None:
    """Remove blocked commands from BUILTIN_SLASH_COMMANDS (autocomplete)."""
    target = _pi_pkg_dir(pi_node) / "dist" / "core" / "slash-commands.js"
    if not target.exists():
        raise SystemExit(f"Pi install incomplete — not found: {target}")

    source = target.read_text(encoding="utf-8")
    for cmd in blocked:
        source = re.sub(
            rf'[ \t]*\{{[^}}]*\bname:\s*"{re.escape(cmd)}"[^}}]*\}},?\n',
            "",
            source,
        )
    target.write_text(source, encoding="utf-8")


def _patch_interactive_mode(pi_node: Path, blocked: list[str]) -> None:
    """Remove blocked command handler blocks from onSubmit (execution)."""
    target = (
        _pi_pkg_dir(pi_node)
        / "dist"
        / "modes"
        / "interactive"
        / "interactive-mode.js"
    )
    if not target.exists():
        raise SystemExit(f"Pi install incomplete — not found: {target}")

    source = target.read_text(encoding="utf-8")
    for cmd in blocked:
        source = re.sub(
            rf'\s+if \(text === "/{re.escape(cmd)}"[^\n]*\n(?:[^\n]*\n)*?[^\n]*return;\n[^\n]*\}}\n',
            "\n",
            source,
        )
    target.write_text(source, encoding="utf-8")


def _apply_lockdown_patches(pi_node: Path) -> None:
    blocked = _load_blocked_commands()
    if not blocked:
        return
    _patch_slash_commands(pi_node, blocked)
    _patch_interactive_mode(pi_node, blocked)
    print(f"Patched Pi: blocked commands {blocked}")


def install_to(target: Path) -> int:
    pi_node = target / "node"

    for path in (pi_node, target / "agent", target / "sessions", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    npm = _npm()

    print(f"Installing Pi {PI_VERSION} into {pi_node}")
    subprocess.run(
        [npm, "install", "--prefix", str(pi_node),
         f"@earendil-works/pi-coding-agent@{PI_VERSION}"],
        check=True,
    )
    _apply_lockdown_patches(pi_node)

    print(f"Installing Pi MCP adapter into {pi_node}")
    subprocess.run(
        [npm, "install", "--prefix", str(pi_node),
         f"pi-mcp-adapter@{PI_MCP_ADAPTER_VERSION}"],
        check=True,
    )
    return 0
