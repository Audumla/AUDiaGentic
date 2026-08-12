"""Source control component bootstrap.

Detects git and gh CLI availability and manages the post-commit ledger-stamp hook.
External MCP server registration is handled generically by mcp.config_builder via
the external-mcp-servers declarations in source-control.yaml.
"""

from __future__ import annotations

import logging
import re
import stat as _stat
from pathlib import Path
from typing import Any

from audiagentic.foundation.components import is_enabled, is_installed
from audiagentic.foundation.components.dependencies import (
    build_dependency_probes,
)
from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.components.loader import component_yaml_path
from audiagentic.foundation.io import atomic_write_text, load_yaml_file
from audiagentic.foundation.toolchains.config.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config.managed_block import (
    apply_managed_block,
    remove_managed_block,
)
from audiagentic.foundation.toolchains.detect import tool_available

logger = logging.getLogger(__name__)

_COMPONENT_ID = "source-control"
_SOURCE_CONTROL_RECIPE = "source-control/post-commit-hook"

SOURCE_CONTROL_DEPENDENCY_IDS = ["git", "gh", "gh-mcp", "uv"]

_HOOK_BLOCK_ID = "audiagentic-ledger-stamp"


def _load_probes() -> dict[str, Any]:
    cfg = load_yaml_file(component_yaml_path(_COMPONENT_ID))
    dep_cfgs = cfg.get("dependencies") or {}
    return build_dependency_probes(dep_cfgs)


def detect_availability() -> dict[str, Any]:
    probes = _load_probes()
    git_ok = tool_available("git")
    uvx_ok = tool_available("uvx")
    gh_ok = tool_available("gh")
    gh_mcp_ok = probes.get("gh-mcp", lambda: False)()

    return {
        "git": git_ok,
        "uvx": uvx_ok,
        "gh": gh_ok,
        "gh-mcp": gh_mcp_ok,
        "git-mcp-server-available": git_ok and uvx_ok,
        "github-mcp-server-available": gh_mcp_ok,
    }


def _ledger_hook_template_path() -> Path:
    return Path(__file__).with_name("post_commit_ledger_hook.sh")


def _post_commit_hook_body() -> str:
    return _ledger_hook_template_path().read_text(encoding="utf-8")


def ledger_integration_enabled(project_root: Path) -> bool:
    # Cross-component reference: probing the optional ledger integration.
    return is_installed("agent-ledger", project_root)


EVENT_INSTALLED = "lifecycle.component.installed"
EVENT_UNINSTALLED = "lifecycle.component.uninstalled"


def on_component_lifecycle(event_type: str, payload: dict, metadata: dict) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if not isinstance(project_root, Path):
        return

    if component_id != _COMPONENT_ID:
        return

    if event_type == EVENT_INSTALLED:
        install_post_commit_hook(project_root)
    elif event_type == EVENT_UNINSTALLED:
        remove_post_commit_hook(project_root)


def _hook_registry(project_root: Path) -> ArtifactRegistry:
    return ArtifactRegistry(project_root)


def _set_executable(path: Path) -> None:
    """Set executable bits on hook; no-op on failure (Windows may not support)."""
    try:
        path.chmod(path.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
    except OSError:
        pass


def _hook_body_lf() -> str:
    """Return hook body with LF line endings enforced for shell script."""
    return _post_commit_hook_body().replace("\r\n", "\n").rstrip("\n")


def _install_hook_absent(hook_path: Path, project_root: Path) -> bool:
    """Create fresh whole-owned hook file when no hook exists."""
    content = "#!/bin/sh\n" + _hook_body_lf() + "\n"
    atomic_write_text(hook_path, content)
    _set_executable(hook_path)
    reg = _hook_registry(project_root)
    rel = (
        Path(hook_path.relative_to(project_root)).as_posix()
        if hook_path.is_relative_to(project_root)
        else Path(hook_path).as_posix()
    )
    reg.register(_SOURCE_CONTROL_RECIPE, files=[rel])
    return True


def _strip_legacy_marker_body(existing: str) -> str | None:
    """Remove a pre-managed-block hook body, returning the remaining content.

    The legacy body runs from the marker comment to the end of the ``python -c``
    invocation that closes it. Returns None when that terminator is not found,
    so the caller can fall back rather than guess at how much to delete.
    """
    lines = existing.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().startswith(f"# {_HOOK_BLOCK_ID}")),
        None,
    )
    if start is None:
        return None
    terminator = re.compile(r'^"\s*(?:2>\s*/dev/null\s*)?(?:\|\|\s*true\s*)?$')
    end = next((i for i in range(start, len(lines)) if terminator.match(lines[i])), None)
    if end is None:
        return None
    remaining = lines[:start] + lines[end + 1 :]
    return "\n".join(remaining).rstrip("\n") + "\n"


def _replace_legacy_marker(hook_path: Path, existing: str, hook_body_lf: str) -> None:
    """Upgrade a legacy hook body in place to a managed block."""
    stripped = _strip_legacy_marker_body(existing)
    if stripped is None:
        # Could not identify the legacy region; append the block rather than
        # delete content we do not understand. Stamping is idempotent, so a
        # leftover legacy invocation is harmless and now fails loudly.
        logger.warning(
            "Legacy hook body could not be delimited; appending managed block alongside it.",
            extra={"path": str(hook_path)},
        )
    else:
        atomic_write_text(hook_path, stripped)
    apply_managed_block(hook_path, _HOOK_BLOCK_ID, hook_body_lf)


def _install_hook_user_owned(hook_path: Path, project_root: Path) -> bool:
    """Append managed block to existing user-owned hook file."""
    change = apply_managed_block(
        hook_path,
        _HOOK_BLOCK_ID,
        _hook_body_lf(),
    )
    _set_executable(hook_path)
    reg = _hook_registry(project_root)
    reg.register(_SOURCE_CONTROL_RECIPE, blocks=[change])
    return True


def install_post_commit_hook(
    project_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install or update the post-commit hook with atomic writes and ownership tracking.

    Returns dict with keys: installed (bool), path, ownership_mode (whole-file|block|collision|skipped),
    reason, dry_run_changes. On collision a warning is logged; bytes never overwritten.
    """
    if not ledger_integration_enabled(project_root):
        return {
            "installed": False,
            "reason": "ledger integration not enabled",
            "ownership_mode": "skipped",
        }

    hooks_dir = project_root / ".git" / "hooks"
    if not hooks_dir.exists():
        return {"installed": False, "reason": "hooks directory absent", "ownership_mode": "skipped"}

    hook_path = hooks_dir / "post-commit"
    hook_body_lf = _hook_body_lf()

    if not hook_path.exists():
        # Absent file → create whole-owned
        result = {
            "installed": True,
            "path": str(hook_path),
            "ownership_mode": "whole-file",
        }
        if dry_run:
            content = "#!/bin/sh\n" + hook_body_lf + "\n"
            result["dry_run_changes"] = {
                "action": "create",
                "bytes_new": len(content.encode("utf-8")),
                "executable": True,
            }
        else:
            _install_hook_absent(hook_path, project_root)
        return result

    existing = hook_path.read_text(encoding="utf-8")

    # Check for existing managed block via apply_managed_block detection logic
    from audiagentic.foundation.toolchains.config.managed_block import (
        _block_pattern as _detect_block_pattern,
    )

    pattern = _detect_block_pattern(_HOOK_BLOCK_ID, "#")
    if pattern.search(existing):
        change = apply_managed_block(hook_path, _HOOK_BLOCK_ID, hook_body_lf)
        result = {
            "installed": True,
            "path": str(hook_path),
            "ownership_mode": "block" if not change.existed else "block",
            "reason": "replaced-existing-block" if change.existed else "appended-block",
        }
        if dry_run:
            wrapped = f"# >>> audiagentic:{_HOOK_BLOCK_ID} >>>\n{hook_body_lf}\n# <<< audiagentic:{_HOOK_BLOCK_ID} <<<\n"
            result["dry_run_changes"] = {
                "action": "replace-block" if change.existed else "append-block",
                "bytes_new": len(wrapped.encode("utf-8")),
                "executable": True,
            }
        return result

    # Check for legacy marker (pre-managed-block format)
    if _HOOK_BLOCK_ID in existing:
        # Ours, but written before the managed-block format. Upgrade it to a
        # real block: reporting "installed" without rewriting would freeze the
        # hook at its original body forever, so a stale entry point could never
        # be corrected by reinstalling.
        logger.info(
            "Legacy hook marker detected without block delimiters; upgrading to a managed block.",
            extra={"path": str(hook_path)},
        )
        result = {
            "installed": True,
            "path": str(hook_path),
            "ownership_mode": "block",
            "reason": "upgraded-legacy-marker",
        }
        if dry_run:
            result["dry_run_changes"] = {
                "action": "replace-legacy-marker",
                "bytes_before": len(existing.encode("utf-8")),
            }
            return result
        _replace_legacy_marker(hook_path, existing, hook_body_lf)
        _set_executable(hook_path)
        return result

    # User-owned file (no marker, no block) → collision: append managed block
    result = {
        "installed": True,
        "path": str(hook_path),
        "ownership_mode": "block",
        "reason": "appended-to-user-file",
    }
    if dry_run:
        existing_bytes = len(existing.encode("utf-8"))
        updated = existing.rstrip("\n") + "\n\n" + hook_body_lf + "\n"
        result["dry_run_changes"] = {
            "action": "append-block",
            "bytes_before": existing_bytes,
            "bytes_after": len(updated.encode("utf-8")),
            "executable": True,
        }
    else:
        _install_hook_user_owned(hook_path, project_root)
    return result


def remove_post_commit_hook(
    project_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove the AUDiaGentic post-commit hook with registry-proven deletion.

    Returns dict with keys: removed (bool), path, ownership_mode, reason.
    Whole-owned file deleted with registry proof; block-owned preserves user content.
    """
    result = prune_post_commit_hook(project_root, dry_run=dry_run)
    result.setdefault("removed", result.get("pruned", False))
    if not dry_run:
        _legacy_remove_fallback(project_root)
    return result


def _legacy_remove_fallback(project_root: Path) -> bool:
    """Legacy removal path for pre-managed-block hooks (raw marker without block delimiters)."""
    hook_path = project_root / ".git" / "hooks" / "post-commit"
    if not hook_path.exists():
        return False

    # Try managed-block removal first (preferred path)
    change = remove_managed_block(hook_path, _HOOK_BLOCK_ID)
    if change.existed:
        reg = _hook_registry(project_root)
        bucket = reg.owned(_SOURCE_CONTROL_RECIPE)
        rel = (
            Path(hook_path.relative_to(project_root)).as_posix()
            if hook_path.is_relative_to(project_root)
            else Path(hook_path).as_posix()
        )
        files_owned = rel in bucket.get("files", [])
        if not files_owned:
            return True
        remaining = hook_path.read_text(encoding="utf-8").strip()
        if not remaining:
            try:
                hook_path.unlink()
            except OSError:
                logger.warning("Could not unlink empty hook after block removal", exc_info=True)
        reg.register(_SOURCE_CONTROL_RECIPE, files=[rel])
        return True

    # Legacy marker removal (pre-managed-block format)
    content = hook_path.read_text(encoding="utf-8")
    if _HOOK_BLOCK_ID not in content:
        return False
    lines = content.splitlines()
    marker_idx = next((idx for idx, line in enumerate(lines) if _HOOK_BLOCK_ID in line), None)
    if marker_idx is None:
        return False
    out = lines[:marker_idx]
    while out and not out[-1].strip():
        out.pop()
    result = ("\n".join(out) + "\n") if out else ""
    if result.strip():
        atomic_write_text(hook_path, result)
    else:
        _safe_unlink_on_prune(project_root, hook_path)
    return True


def prune_post_commit_hook(
    project_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove the managed hook with registry-proven deletion semantics.

    Whole-owned file: deleted only with ArtifactRegistry proof.
    Block-owned file: block removed, file preserved.
    """
    hook_path = project_root / ".git" / "hooks" / "post-commit"
    reg = _hook_registry(project_root)
    bucket = reg.owned(_SOURCE_CONTROL_RECIPE)
    rel = (
        Path(hook_path.relative_to(project_root)).as_posix()
        if hook_path.is_relative_to(project_root)
        else Path(hook_path).as_posix()
    )

    result: dict[str, Any] = {
        "pruned": False,
        "path": str(hook_path),
    }

    if not hook_path.exists():
        result["reason"] = "hook absent"
        return result

    files_owned = rel in bucket.get("files", [])
    blocks_owned = any(e.get("block_id") == _HOOK_BLOCK_ID for e in bucket.get("blocks", []))

    if files_owned:
        # Whole-owned file — safe to delete entirely (registry proof exists)
        if dry_run:
            result["dry_run_changes"] = {
                "action": "delete-whole-file",
                "ownership_mode": "whole-file",
            }
            result["pruned"] = True
        else:
            try:
                import time as _time

                for attempt in range(3):
                    hook_path.unlink(missing_ok=True)
                    if not hook_path.exists():
                        break
                    _time.sleep(0.05)
                reg.register(_SOURCE_CONTROL_RECIPE, files=[rel])
                result["pruned"] = True
            except OSError as exc:
                result["error"] = str(exc)

    elif blocks_owned or _HOOK_BLOCK_ID in (
        hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""
    ):
        # Block-owned file — remove block only, preserve user content
        if dry_run:
            result["dry_run_changes"] = {"action": "remove-block", "ownership_mode": "block"}
            result["pruned"] = True
        else:
            removed = _legacy_remove_fallback(project_root)
            result["pruned"] = removed

    else:
        result["reason"] = "not-owned"

    return result


def _safe_unlink_on_prune(project_root: Path, hook_path: Path) -> None:
    """Delete hook file only if ArtifactRegistry proves AUDiaGentic created it."""
    reg = _hook_registry(project_root)
    bucket = reg.owned(_SOURCE_CONTROL_RECIPE)
    rel = (
        Path(hook_path.relative_to(project_root)).as_posix()
        if hook_path.is_relative_to(project_root)
        else Path(hook_path).as_posix()
    )
    if rel in bucket.get("files", []):
        try:
            hook_path.unlink()
        except OSError:
            logger.warning("Could not unlink whole-owned hook during prune", exc_info=True)
    else:
        # Block-owned or unknown — leave file with marker stripped (user content preserved)
        pass


def status_payload(project_root: Path | None = None) -> ComponentStatusPayload:
    from audiagentic.foundation.components.registry import get_external_probe_results

    probe_cache = get_external_probe_results("source-control", project_root) if project_root else {}
    return ComponentStatusPayload(
        enabled=bool(project_root and is_enabled(_COMPONENT_ID, project_root)),
        configured=True,
        active_implementation=None,
        missing_required=[],
        details={
            "ledger_integration_enabled": bool(
                project_root and ledger_integration_enabled(project_root)
            ),
            "mcp_servers": {
                name: ("available" if probe_cache.get(name, True) else "unavailable")
                for name in ("git", "github")
            },
            "hint": "Use ag-sc-mgmt.get_source_control_status for full dependency checks.",
        },
    )
