"""Package and repository root resolution."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.paths.names import find_package_root as _find_package_root


def find_package_root(start: Path) -> Path:
    """Walk up from start until a directory named 'audiagentic' is found.

    Delegates to the central resolver in foundation/paths/names.py.
    """
    return _find_package_root(start)


def find_repo_root(start: Path | None = None) -> Path:
    """Locate repo root for dev/runtime tooling.

    Resolution order:
    1. AUDIAGENTIC_REPO_ROOT env var (if it points to a valid checkout).
    2. Walk up from *start* (default: this module's __file__) looking for
        pyproject.toml or src/audiagentic — indicates a source checkout.
    3. Fallback to the installed package parent when no source checkout is
        found (installed wheel without explicit env var).
    """
    env_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if candidate.is_dir() and (
            (candidate / "pyproject.toml").is_file()
            or (candidate / "src" / "audiagentic").is_dir()
        ):
            return candidate

    anchor = (start or Path(__file__)).resolve()
    candidates = [anchor, *anchor.parents]

    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate
        if (candidate / "src" / "audiagentic").is_dir():
            return candidate

    # No source checkout found — likely a wheel install. Use the installed
    # package parent so imports can succeed without a checkout-specific cwd.
    return _find_package_root(Path(__file__)).parent.resolve()


PACKAGE_ROOT: Path = find_package_root(Path(__file__))
REPO_ROOT: Path = find_repo_root()
# Import root containing ``audiagentic``. In a checkout this is ``<repo>/src``;
# in a wheel it is site-packages. Never derive it from the repo fallback.
SRC_ROOT: Path = PACKAGE_ROOT.parent
