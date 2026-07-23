"""Project-root containment safety for filesystem paths.

Ensures that user-supplied paths (from YAML config, prompt templates, etc.)
cannot escape the project root via ``../`` traversal, absolute paths outside
the root, or symlink manipulation.

Error codes:
    IO-PATH-001 — resolved path escapes the project root containment boundary.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError


def ensure_contained(
    project_root: str | Path,
    requested_path: str | Path,
) -> Path:
    """Resolve *requested_path* relative to *project_root* and verify containment.

    The path is resolved against the project root using ``Path.resolve()`` so
    that symlinks, ``..`` segments, and other indirection are canonicalised
    before the containment check.  On Windows this works correctly across
    case-insensitive drives (``C:`` == ``c:``).

    Parameters
    ----------
    project_root:
        Absolute path to the project root directory.
    requested_path:
        A relative or absolute path supplied by configuration.

    Returns
    -------
    Path
        The resolved, contained absolute path.

    Raises
    ------
    AudiaGenticError
        IO-PATH-001 if the resolved path escapes the project root.
    """
    root = Path(project_root).resolve()
    target = Path(requested_path)

    # If already absolute, check containment directly; otherwise join with root.
    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (root / target).resolve()

    _check_contained(root, resolved, requested_path)
    return resolved


def _check_contained(
    root: Path,
    resolved: Path,
    original: str | Path,
) -> None:
    """Raise IO-PATH-001 if *resolved* is not inside *root*."""

    # Normalise both paths for case-insensitive comparison on Windows.
    root_lower = _normalise(root)
    resolved_lower = _normalise(resolved)

    # Check prefix containment (handles the root itself as a valid boundary).
    try:
        resolved_lower.relative_to(root_lower)
    except ValueError:
        raise AudiaGenticError(
            code="IO-PATH-001",
            kind="foundation",
            message=(
                f"Path {original!r} resolves outside the project root. "
                f"Resolved to {resolved}, but must stay within {root}."
            ),
            details={
                "requested_path": str(original),
                "resolved_path": str(resolved),
                "project_root": str(root),
            },
        )


def _normalise(p: Path) -> Path:
    """Return a lowercased path for case-insensitive comparison.

    Handles Windows drive letters correctly (e.g. ``C:\\`` → ``c:\\``).
    """
    parts = list(p.parts)
    if parts and len(parts[0]) >= 1 and ":" in parts[0]:
        # Windows drive letter at the front — lowercase it.
        parts[0] = parts[0].lower()
    normalised_parts: list[str] = []
    for part in parts:
        if not normalised_parts:
            normalised_parts.append(part)
        else:
            normalised_parts.append(part.lower())
    return Path(*normalised_parts)
