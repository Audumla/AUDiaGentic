"""Git pre-commit hook sync for LSP languages.

Provides a single entry-point function _sync_hook_for_language that owns all
decision logic for managing git pre-commit hooks per language. Callers never
need to know about flag checks, descriptor lookups, or managed-block mechanics.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.toolchains.config.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config.managed_block import (
    apply_managed_block,
    remove_managed_block,
)

logger = logging.getLogger(__name__)

_COMPONENT_ID = "coding-lsp"
_HOOK_BLOCK_ID = "audiagentic-lsp-hooks"
_SOURCE_CONTROL_RECIPE = "coding-lsp/pre-commit-hooks"


def _get_feature_state(project_root: Path, language_id: str) -> dict[str, Any] | None:
    """Get pre-commit-hooks spec for a language from feature registry."""
    from audiagentic.components.coding_lsp import language_registry

    spec = language_registry.get_language(language_id)
    if not spec or not spec.pre_commit_hooks:
        return None

    hooks = spec.pre_commit_hooks
    result: dict[str, Any] = {}

    if "check" in hooks and hooks["check"]:
        result["check"] = " ".join(hooks["check"])
    if "format" in hooks and hooks["format"]:
        result["format"] = " ".join(hooks["format"])

    return result if result else None


def _hook_registry(project_root: Path) -> ArtifactRegistry:
    """Return the artifact registry for hook management."""
    return ArtifactRegistry(project_root)


def _hook_body_for_language(language_id: str, hooks_spec: dict[str, Any]) -> str:
    """Generate the hook body block for a specific language."""
    lines = [f"# >>> audiagentic:{_HOOK_BLOCK_ID}:{language_id} >>>"]

    if "check" in hooks_spec:
        lines.append(f"# check: {hooks_spec['check']}")

    if "format" in hooks_spec:
        lines.append(f"# format: {hooks_spec['format']}")

    lines.append(f"# <<< audiagentic:{_HOOK_BLOCK_ID}:language-hooks <<<\n")
    return "\n".join(lines) + "\n"


def _get_hook_path(project_root: Path) -> Path | None:
    """Get the pre-commit hook path if .git/hooks exists."""
    hooks_dir = project_root / ".git" / "hooks"
    if not hooks_dir.exists():
        return None

    hook_path = hooks_dir / "pre-commit"
    if not hook_path.exists():
        return None

    return hook_path


def _sync_hook_for_language(project_root: Path, language_id: str, install: bool = True) -> bool:
    """Sync pre-commit hook block for a language.

    Args:
        project_root: The project root directory.
        language_id: The language identifier (e.g., 'python-ruff').
        install: True to install/add the hook block, False to remove it.

    Returns:
        True if operation succeeded or was skipped, False on error.
    """
    # Check component flag first
    from audiagentic.foundation.features.state import get_feature_state

    coding_lsp_state = get_feature_state(project_root, _COMPONENT_ID, "coding-lsp", "coding-lsp")
    pre_commit_hooks_enabled = coding_lsp_state.options.get("pre-commit-hooks-enabled", True)

    if not pre_commit_hooks_enabled:
        if install:
            return False

        # Remove hook block even if flag is disabled
        pass

    # Get hooks spec for this language
    hooks_spec = _get_feature_state(project_root, language_id)

    if install and not hooks_spec:
        return True  # Language has no pre-commit hooks defined

    hook_path = _get_hook_path(project_root)
    if not hook_path:
        return False  # No .git/hooks or pre-commit hook exists

    if install and hooks_spec is not None:
        return _install_or_append_hook_block(hook_path, project_root, language_id, hooks_spec)
    else:
        return _remove_hook_block(hook_path, project_root, language_id)


def _install_or_append_hook_block(
    hook_path: Path, project_root: Path, language_id: str, hooks_spec: dict[str, Any]
) -> bool:
    """Install or append managed block to existing hook file."""
    # Check if hook file exists
    if not hook_path.exists():
        # No managed blocks - create whole-owned file with managed block
        hook_body = _hook_body_for_language(language_id, hooks_spec)
        full_content = "#!/bin/sh\n" + hook_body + "\n"

        atomic_write_text(hook_path, full_content)

        # Set executable bits
        try:
            import stat as _stat

            hook_path.chmod(
                hook_path.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH
            )
        except OSError:
            pass

        reg = _hook_registry(project_root)
        rel = (
            Path(hook_path.relative_to(project_root)).as_posix()
            if hook_path.is_relative_to(project_root)
            else Path(hook_path).as_posix()
        )
        reg.register(_SOURCE_CONTROL_RECIPE, files=[rel])
        return True

    # File exists - read content
    content = hook_path.read_text(encoding="utf-8")

    # Check if this language's block already exists
    block_marker = f"# >>> audiagentic:{_HOOK_BLOCK_ID}:{language_id} >>>"
    if block_marker in content:
        # Block exists, update it
        change = apply_managed_block(
            hook_path,
            f"{_HOOK_BLOCK_ID}:{language_id}",
            _hook_body_for_language(language_id, hooks_spec),
        )
        reg = _hook_registry(project_root)
        rel = (
            Path(hook_path.relative_to(project_root)).as_posix()
            if hook_path.is_relative_to(project_root)
            else Path(hook_path).as_posix()
        )
        reg.register(_SOURCE_CONTROL_RECIPE, blocks=[change])
        return True

    # Check for any existing managed block pattern
    from audiagentic.foundation.toolchains.config.managed_block import (
        _block_pattern as _detect_block_pattern,
    )

    pattern = _detect_block_pattern(_HOOK_BLOCK_ID, "#")

    if pattern.search(content):
        # Has managed blocks but not this language's block - append it
        new_content = (
            content.rstrip("\n") + "\n\n" + _hook_body_for_language(language_id, hooks_spec) + "\n"
        )
        atomic_write_text(hook_path, new_content)
        reg = _hook_registry(project_root)
        rel = (
            Path(hook_path.relative_to(project_root)).as_posix()
            if hook_path.is_relative_to(project_root)
            else Path(hook_path).as_posix()
        )
        # Register the block change (not a dict)
        return True

    # No managed blocks - create whole-owned file with managed block
    hook_body = _hook_body_for_language(language_id, hooks_spec)
    full_content = "#!/bin/sh\n" + hook_body + "\n"

    atomic_write_text(hook_path, full_content)

    # Set executable bits
    try:
        import stat as _stat

        hook_path.chmod(hook_path.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
    except OSError:
        pass

    reg = _hook_registry(project_root)
    rel = (
        Path(hook_path.relative_to(project_root)).as_posix()
        if hook_path.is_relative_to(project_root)
        else Path(hook_path).as_posix()
    )
    reg.register(_SOURCE_CONTROL_RECIPE, files=[rel])

    return True


def _remove_hook_block(hook_path: Path, project_root: Path, language_id: str) -> bool:
    """Remove a specific language's hook block from the pre-commit file."""
    block_id = f"{_HOOK_BLOCK_ID}:{language_id}"
    change = remove_managed_block(hook_path, block_id)

    if not change.existed:
        # Try removing by marker pattern
        content = hook_path.read_text(encoding="utf-8")
        block_marker = f"# >>> audiagentic:{_HOOK_BLOCK_ID}:{language_id} >>>"
        if block_marker not in content:
            return False

        lines = content.splitlines()
        new_lines = []
        in_block = False
        for line in lines:
            if block_marker in line:
                in_block = True
                continue
            if in_block and "# <<< audiagentic:_HOOK_BLOCK_ID:language-hooks <<<" in line:
                in_block = False
                continue
            if not in_block:
                new_lines.append(line)

        result_content = "\n".join(new_lines) + ("\n" if new_lines else "")

        # Clean up trailing empty lines
        while result_content.endswith("\n\n"):
            result_content = result_content[:-1]

        if result_content.strip():
            atomic_write_text(hook_path, result_content)
        else:
            # File is now empty or only has shebang - keep it minimal
            hook_path.unlink()

    reg = _hook_registry(project_root)
    bucket = reg.owned(_SOURCE_CONTROL_RECIPE)
    rel = (
        Path(hook_path.relative_to(project_root)).as_posix()
        if hook_path.is_relative_to(project_root)
        else Path(hook_path).as_posix()
    )

    # Update registry to remove this language's block
    blocks_owned = [e for e in bucket.get("blocks", []) if e.get("block_id") != block_id]
    reg.register(_SOURCE_CONTROL_RECIPE, files=bucket.get("files", []), blocks=blocks_owned)

    return True
