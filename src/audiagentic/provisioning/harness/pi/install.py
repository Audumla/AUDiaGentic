from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise SystemExit("npm is required to install the Pi TUI.")
    return resolved


def install_to(target: Path) -> int:
    pi_node = target / "node"

    for path in (pi_node, target / "agent", target / "sessions", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    npm = _npm()
    print(f"Installing Pi into {pi_node}")
    subprocess.run([npm, "install", "--prefix", str(pi_node), "@earendil-works/pi-coding-agent"], check=True)
    print(f"Installing Pi MCP adapter into {pi_node}")
    subprocess.run([npm, "install", "--prefix", str(pi_node), "pi-mcp-adapter"], check=True)
    return 0
