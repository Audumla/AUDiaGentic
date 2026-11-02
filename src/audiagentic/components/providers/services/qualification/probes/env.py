"""The disposable process environment every live probe starts a harness in.

Nothing is inherited that could carry a credential, proxy or gateway setting: only a short allowlist (``PATH`` and
the locale) plus a throw-away HOME/XDG tree rooted in the probe's temp directory. A probe adds only the variables
its own harness needs through ``extra``.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_XDG = {"XDG_CONFIG_HOME": "xdg-config", "XDG_DATA_HOME": "xdg-data", "XDG_CACHE_HOME": "xdg-cache",
        "XDG_STATE_HOME": "xdg-state"}


def disposable_env(root: Path, *, tmp: Path | None = None, extra_dirs: tuple[str, ...] = (),
                   keep: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> dict[str, str]:
    """Create the throw-away directories under ``root`` and return the allowlisted environment for them.

    ``tmp`` replaces the scratch TMPDIR (an exec-capable one when the system temp dir is noexec), ``keep`` names
    further inherited variables the harness cannot run without, ``extra`` the harness's own settings.
    """
    for name in ("home", "tmp", *_XDG.values(), *extra_dirs):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in (*ENV_ALLOWLIST, *keep) if key in os.environ}
    env.update({"HOME": str(root / "home"), "TMPDIR": str(tmp or root / "tmp"),
                **{variable: str(root / folder) for variable, folder in _XDG.items()}, **(extra or {})})
    return env
