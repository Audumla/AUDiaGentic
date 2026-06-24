"""Source control component bootstrap.

Detects git and gh CLI availability and manages the post-commit ledger-stamp hook.
External MCP server registration is handled generically by mcp.config_builder via
the external-mcp-servers declarations in source-control.yaml.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.source_control.probes import gh_mcp_available
from audiagentic.foundation.components import is_installed
from audiagentic.foundation.components.ids import COMPONENT_AGENT_LEDGER, COMPONENT_SOURCE_CONTROL
from audiagentic.foundation.toolchains.detect import tool_available

SOURCE_CONTROL_DEPENDENCY_IDS = ["git", "gh", "gh-mcp", "uv"]


def detect_availability() -> dict[str, Any]:
    git_ok = tool_available("git")
    uvx_ok = tool_available("uvx")
    gh_ok = tool_available("gh")
    gh_mcp_ok = gh_mcp_available() if gh_ok else False

    return {
        "git": git_ok,
        "uvx": uvx_ok,
        "gh": gh_ok,
        "gh-mcp": gh_mcp_ok,
        "git-mcp-server-available": git_ok and uvx_ok,
        "github-mcp-server-available": gh_mcp_ok,
    }


_HOOK_MARKER = "audiagentic-ledger-stamp"


def _ledger_hook_template_path() -> Path:
    return Path(__file__).with_name("post_commit_ledger_hook.sh")


def _post_commit_hook_body() -> str:
    return _ledger_hook_template_path().read_text(encoding="utf-8")


def ledger_integration_enabled(project_root: Path) -> bool:
    return is_installed(COMPONENT_AGENT_LEDGER, project_root)


EVENT_INSTALLED = "lifecycle.component.installed"
EVENT_UNINSTALLED = "lifecycle.component.uninstalled"


def on_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        return

    if component_id != COMPONENT_SOURCE_CONTROL:
        return

    if event_type == EVENT_INSTALLED:
        _install_post_commit_hook(project_root)
    elif event_type == EVENT_UNINSTALLED:
        _remove_post_commit_hook(project_root)


def _install_post_commit_hook(project_root: Path) -> bool:
    """Install or update the post-commit hook. Returns True if installed."""
    if not ledger_integration_enabled(project_root):
        return False
    hooks_dir = project_root / ".git" / "hooks"
    if not hooks_dir.exists():
        return False
    hook_path = hooks_dir / "post-commit"
    hook_body = _post_commit_hook_body()
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER in existing:
            return False  # already installed
        # append to existing hook (shebang already present in existing file)
        updated = existing.rstrip("\n") + "\n\n" + hook_body
        hook_path.write_text(updated, encoding="utf-8", newline="\n")
    else:
        hook_path.write_text("#!/bin/sh\n" + hook_body, encoding="utf-8", newline="\n")
    try:
        import stat
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return True


def _remove_post_commit_hook(project_root: Path) -> bool:
    """Remove the AUDiaGentic post-commit hook block. Returns True if removed."""
    hook_path = project_root / ".git" / "hooks" / "post-commit"
    if not hook_path.exists():
        return False
    content = hook_path.read_text(encoding="utf-8")
    if _HOOK_MARKER not in content:
        return False
    lines = content.splitlines()
    marker_idx = next((idx for idx, line in enumerate(lines) if _HOOK_MARKER in line), None)
    if marker_idx is None:
        return False
    out = lines[:marker_idx]
    while out and not out[-1].strip():
        out.pop()
    result = ("\n".join(out) + "\n") if out else ""
    if result.strip():
        hook_path.write_text(result, encoding="utf-8")
    else:
        hook_path.unlink()
    return True


def status_payload(project_root: Path | None = None) -> dict[str, Any]:
    from audiagentic.foundation.components.registry import get_external_probe_results
    probe_cache = get_external_probe_results("source-control", project_root) if project_root else {}
    return {
        "ledger-integration-enabled": bool(project_root and ledger_integration_enabled(project_root)),
        "mcp-servers": {
            name: ("available" if probe_cache.get(name, True) else "unavailable")
            for name in ("git", "github")
        },
        "hint": "Use ag-sc-mgmt.get_source_control_status for full dependency checks.",
    }
