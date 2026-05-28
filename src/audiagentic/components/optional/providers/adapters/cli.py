"""CLI executable resolution for provider adapters."""
from __future__ import annotations

import shutil

from audiagentic.foundation.contracts.errors import AudiaGenticError


def require_executable(provider_id: str, *aliases: str) -> str:
    """Return path to first found alias, or raise AudiaGenticError listing all tried.

    Iterates aliases in order; returns the first shutil.which() hit.
    Raises if none are found.
    """
    for alias in aliases:
        path = shutil.which(alias)
        if path:
            return path
    tried = ", ".join(aliases)
    raise AudiaGenticError(
        code="PRV-EXTERNAL-NOT-FOUND",
        kind="external",
        message=f"Provider '{provider_id}' executable not found. Tried: {tried}. Ensure it is installed and on PATH.",
        details={"provider-id": provider_id, "aliases": list(aliases)},
    )
