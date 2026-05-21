"""Source control component bootstrap.

Detects git and gh CLI availability and manages the post-commit ledger-stamp hook.
External MCP server registration is handled generically by mcp_config_builder via
the external-mcp-servers declarations in source-control.yaml.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _gh_mcp_available() -> bool:
    if not _tool_available("gh"):
        return False
    result = subprocess.run(
        ["gh", "mcp", "serve", "--help"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def detect_availability() -> dict[str, Any]:
    git_ok = _tool_available("git")
    uvx_ok = _tool_available("uvx")
    gh_ok = _tool_available("gh")
    gh_mcp_ok = _gh_mcp_available() if gh_ok else False

    return {
        "git": git_ok,
        "uvx": uvx_ok,
        "gh": gh_ok,
        "gh-mcp": gh_mcp_ok,
        "git-mcp-server-available": git_ok and uvx_ok,
        "github-mcp-server-available": gh_mcp_ok,
    }


_HOOK_MARKER = "audiagentic-ledger-stamp"

_POST_COMMIT_HOOK_BODY = """\
# {marker}
# Installed by AUDiaGentic source-control component.
# Stamps ledger fragments with the commit SHA for any files that intersect.
python -c "
from pathlib import Path
from audiagentic.components.optional.source_control.git_commits import stamp_fragments_for_commit
stamp_fragments_for_commit(Path('.').resolve())
" 2>/dev/null || true
""".format(marker=_HOOK_MARKER)


def _install_post_commit_hook(project_root: Path) -> bool:
    """Install or update the post-commit hook. Returns True if installed."""
    hooks_dir = project_root / ".git" / "hooks"
    if not hooks_dir.exists():
        return False
    hook_path = hooks_dir / "post-commit"
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _HOOK_MARKER in existing:
            return False  # already installed
        # append to existing hook (shebang already present in existing file)
        updated = existing.rstrip("\n") + "\n\n" + _POST_COMMIT_HOOK_BODY
        hook_path.write_text(updated, encoding="utf-8")
    else:
        hook_path.write_text("#!/bin/sh\n" + _POST_COMMIT_HOOK_BODY, encoding="utf-8")
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
    # Remove from the marker line onward until end of our block
    lines = content.splitlines(keepends=True)
    out = []
    skip = False
    for line in lines:
        if _HOOK_MARKER in line:
            skip = True
        if not skip:
            out.append(line)
        elif line.strip() == "" and skip:
            skip = False  # blank line ends our block
    result = "".join(out).rstrip("\n") + "\n" if out else ""
    if result.strip():
        hook_path.write_text(result, encoding="utf-8")
    else:
        hook_path.unlink()
    return True


def _build_warnings(availability: dict[str, Any]) -> list[str]:
    warnings = []
    if not availability["git"]:
        warnings.append("git not found — install git to enable source control operations")
    if not availability["uvx"]:
        warnings.append("uvx not found — install uv to enable git MCP server (mcp-server-git)")
    if not availability["gh"]:
        warnings.append("gh CLI not found — install GitHub CLI to enable GitHub MCP server")
    elif not availability["gh-mcp"]:
        warnings.append("gh mcp serve not available — run: gh extension install github/gh-mcp")
    return warnings
