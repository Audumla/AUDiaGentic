"""Marker-delimited managed text blocks for hook/snippet registration.

Some integrations register by appending a block of text to a line-oriented file
(a shell rc, a hooks section, an instruction file) rather than setting a
structured config key. To make those blocks reliably identifiable for prune,
each is wrapped in sentinel markers keyed by a stable ``block_id``::

    # >>> audiagentic:managed-block-id >>>
    ...managed content...
    # <<< audiagentic:managed-block-id <<<

Re-applying replaces the existing block in place; removing strips exactly the
marked region and nothing else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.logging.redaction import DEFAULT_REDACT_PATTERNS


@dataclass(frozen=True)
class BlockChange:
    """Record of a managed-block mutation, for artifact ownership tracking."""

    artifact_id: str
    path: str
    block_id: str
    operation: str  # "apply" | "remove"
    existed: bool


def _markers(block_id: str, comment_prefix: str) -> tuple[str, str]:
    begin = f"{comment_prefix} >>> audiagentic:{block_id} >>>"
    end = f"{comment_prefix} <<< audiagentic:{block_id} <<<"
    return begin, end


def _block_pattern(block_id: str, comment_prefix: str) -> re.Pattern[str]:
    begin, end = _markers(block_id, comment_prefix)
    # Match the whole block including a single trailing newline if present.
    return re.compile(
        re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
        re.DOTALL,
    )


def block_artifact_id(path: str | Path, block_id: str) -> str:
    return f"{Path(path).as_posix()}::block:{block_id}"


_mb_error = make_error_factory("CON", "MB", "managed-block")


def _check_sensitive_content(content: str) -> None:
    """Fail-closed check: reject content that contains secret-shaped values.

    Managed blocks can end up in git-tracked files; this prevents a secret
    from being committed. See OU01 step 5.
    """
    for pattern in DEFAULT_REDACT_PATTERNS:
        if pattern.pattern.startswith(r"(https?://"):
            continue  # URL-credential patterns have special replacement
        if pattern.search(content):
            raise _mb_error(
                1,
                "Managed block content contains secret-shaped value; write rejected",
                block_id=None,
            )


def apply_managed_block(
    path: str | Path,
    block_id: str,
    content: str,
    *,
    comment_prefix: str = "#",
) -> BlockChange:
    """Insert or replace the managed block ``block_id`` in ``path``.

    Raises CON-MB-001 if the content contains secret-shaped values (fail-closed).
    """
    target = Path(path)
    _check_sensitive_content(content)
    begin, end = _markers(block_id, comment_prefix)
    wrapped = f"{begin}\n{content.rstrip()}\n{end}\n"

    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    pattern = _block_pattern(block_id, comment_prefix)
    existed = bool(pattern.search(existing))

    if existed:
        updated = pattern.sub(wrapped, existing, count=1)
    elif existing and not existing.endswith("\n"):
        updated = existing + "\n" + wrapped
    else:
        updated = existing + wrapped

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return BlockChange(
        artifact_id=block_artifact_id(target, block_id),
        path=target.as_posix(),
        block_id=block_id,
        operation="apply",
        existed=existed,
    )


def remove_managed_block(
    path: str | Path,
    block_id: str,
    *,
    comment_prefix: str = "#",
) -> BlockChange:
    """Strip the managed block ``block_id`` from ``path`` if present."""
    target = Path(path)
    existed = False
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        pattern = _block_pattern(block_id, comment_prefix)
        if pattern.search(existing):
            existed = True
            updated = pattern.sub("", existing)
            target.write_text(updated, encoding="utf-8")
    return BlockChange(
        artifact_id=block_artifact_id(target, block_id),
        path=target.as_posix(),
        block_id=block_id,
        operation="remove",
        existed=existed,
    )


__all__ = [
    "BlockChange",
    "apply_managed_block",
    "block_artifact_id",
    "remove_managed_block",
]
