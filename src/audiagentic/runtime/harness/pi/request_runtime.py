"""Request-local Pi runtime state.

This is state layout, not a security boundary. The Pi process still runs with
the project as its cwd and consumes the project's shared MCP configuration.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.io import atomic_write_json
from audiagentic.runtime.harness.pi.install.config import materialize_agent_config


@dataclass(frozen=True)
class PiRequestRuntime:
    request_id: str
    root: Path
    agent_dir: Path
    session_dir: Path
    temp_dir: Path
    cache_dir: Path
    project_root: Path
    project_mcp_path: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.root / "home"),
            "PI_CODING_AGENT_DIR": str(self.agent_dir),
            "PI_CODING_AGENT_SESSION_DIR": str(self.session_dir),
            "TMPDIR": str(self.temp_dir),
            "TEMP": str(self.temp_dir),
            "TMP": str(self.temp_dir),
            "XDG_CACHE_HOME": str(self.cache_dir),
        }


def create_request_runtime(
    agent_runtime: Path,
    project_root: Path,
    request_id: str,
    harness_cfg: dict,
    *,
    runtime_root: Path | None = None,
) -> PiRequestRuntime:
    """Create and materialize a request-local Pi state root."""
    root = runtime_root if runtime_root is not None else agent_runtime / "requests" / request_id
    runtime = PiRequestRuntime(
        request_id=request_id,
        root=root,
        agent_dir=root / "agent",
        session_dir=root / "sessions",
        temp_dir=root / "tmp",
        cache_dir=root / "cache",
        project_root=project_root,
        project_mcp_path=project_root / ".audiagentic" / "mcp.json",
    )
    for path in (runtime.agent_dir, runtime.session_dir, runtime.temp_dir, runtime.cache_dir, runtime.root / "home"):
        path.mkdir(parents=True, exist_ok=True)
    materialize_agent_config(runtime.root, harness_cfg, project_root=project_root)
    atomic_write_json(runtime.manifest_path, {
        "request-id": request_id,
        "root": str(root),
        "agent-dir": str(runtime.agent_dir),
        "session-dir": str(runtime.session_dir),
        "temp-dir": str(runtime.temp_dir),
        "cache-dir": str(runtime.cache_dir),
        "project-root": str(project_root),
        "cwd": str(project_root),
        "project-mcp-path": str(runtime.project_mcp_path),
        "shared-project-pi-semantics": True,
    }, indent=2, sort_keys=True)
    return runtime


def cleanup_request_runtime(runtime: PiRequestRuntime) -> None:
    """Remove a completed request root; missing roots are harmless."""
    shutil.rmtree(runtime.root, ignore_errors=True)


def quarantine_request_runtime(runtime: PiRequestRuntime, quarantine_root: Path) -> Path:
    """Move failed/interrupted state aside for later inspection."""
    quarantine_root.mkdir(parents=True, exist_ok=True)
    destination = quarantine_root / runtime.request_id
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(runtime.root), str(destination))
    return destination
