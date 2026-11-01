"""``gateway init``: generate a working same-machine shared-gateway setup (CFG15).

One directory holds ``server.yaml``, ``connector.yaml`` and ``credentials/operator.token``.
Ids and the token are generated, never typed; nothing is overwritten and no existing identity
or credential is rotated. Base security only: the token file is created exclusively with mode
0600 in a 0700 directory, is never printed, and dry-run never generates one.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import make_error_factory

from . import shared_config

_error = make_error_factory("CFG", "AGSV", "gateway-service")
PORT = 8765
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_FILES = ("server.yaml", "connector.yaml", "credentials/operator.token")


def default_directory() -> Path:
    from audiagentic.foundation.paths.home import user_config_dir

    return user_config_dir() / "gateway"


def _project_root(project: Path | None) -> Path:
    from audiagentic.foundation.config.settings import discover_project_root, project_config_dir

    root = discover_project_root(project, cwd=Path.cwd())
    if root is None or not (root / ".git").exists() and not project_config_dir(root).exists():
        raise _error(8, "gateway init needs a project: run it inside a git checkout or give `project PATH`")
    return Path(root).resolve()


def _suggest_id(root: Path) -> str:
    from audiagentic.foundation.paths.identity import project_identity

    candidate = re.sub(r"[^a-z0-9_-]+", "-", project_identity(root).lower()).strip("-_")[:64].rstrip("-_")
    return candidate or "project"


def _plan_project_id(root: Path) -> tuple[str, bool]:
    """The project's declared id and whether init must write it (one-time, from a derived suggestion)."""
    from .. import settings

    declared = settings.declared_project_id(root)
    if declared is None:
        return _suggest_id(root), True
    if not _ID.fullmatch(declared):
        raise _error(8, "The declared project.id is not a valid gateway id (lowercase letters, digits, - and _, "
                        "starting with a letter or digit); set a valid one with "
                        "`audiagentic config set --scope project project.id=NAME`")
    return declared, False


def _binding(connector: Path) -> tuple[str, str]:
    """(action, note) for the machine-level binding: bind, same, kept or conflict."""
    from ..settings import gateway_setting

    current = gateway_setting("connector")
    if current:
        same = Path(str(current)).expanduser() == connector
        return ("same", "already bound to this connector") if same else (
            "kept", f"gateway.connector is already {current}; switch with: audiagentic gateway connect config {connector}")
    implementation = gateway_setting("implementation")
    if implementation not in (None, "standalone"):
        return "conflict", (f"gateway.implementation is {implementation}; to use this gateway run: "
                            f"audiagentic gateway connect config {connector}")
    return "bind", "will bind this machine to the generated connector"


def _documents(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    server_id = "gw-" + secrets.token_hex(8)
    token = "./credentials/operator.token"
    server = {
        "schema-version": 1, "server-id": server_id, "listen": {"port": PORT},
        "projects": [str(root)],
        "principals": {"operator": {"token-file": token}},
    }
    connector = {
        "schema-version": 1, "mode": "shared", "endpoint": f"http://127.0.0.1:{PORT}",
        "server-id": server_id, "token-file": token,
    }
    return server, connector


def _exclusive_write(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _check_existing(directory: Path, root: Path) -> dict[str, Any]:
    """All three files exist: they must load and agree, else the set is refused."""
    server = shared_config.load_shared_server_config(directory / "server.yaml", default_root=root)
    connector = shared_config.load_shared_connector_config(directory / "connector.yaml")
    if connector.mode != "shared" or connector.server_id != server.server_id:
        raise _error(7, "The existing connector does not match the existing server (server-id or mode)")
    if root not in server.projects.values():
        raise _error(7, "The existing server.yaml does not serve this project")
    return {"server-id": server.server_id}


def gateway_init(*, directory: Path | None = None, project: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Create (or report) the generated setup; returns a result mapping that never contains a token."""
    directory = Path(directory).expanduser().resolve() if directory else default_directory()
    root = _project_root(project)
    project_id, write_id = _plan_project_id(root)
    present = [name for name in _FILES if (directory / name).exists()]
    connector_path = directory / "connector.yaml"
    result: dict[str, Any] = {
        "directory": str(directory), "project-root": str(root), "project-id": project_id,
        "project-id-written": False, "files": [str(directory / name) for name in _FILES],
    }
    if present and len(present) != len(_FILES):
        raise _error(7, "A partial gateway setup exists in this directory; remove the incomplete files or choose "
                        "another `dir PATH`", present=present)
    if present:
        result.update(_check_existing(directory, root))
        state = "already-initialized"
    else:
        state = "dry-run" if dry_run else "created"
    action, note = _binding(connector_path)
    result.update({"state": state, "binding": action, "binding-note": note})
    if dry_run:
        result["project-id-would-write"] = write_id
        return result
    if write_id:
        from audiagentic.foundation.config.writer import write_settings_patch

        write_settings_patch("project", {"project": {"id": project_id}}, project_root=root)
        result["project-id-written"] = True
    if state == "created":
        _create(directory, root)
        result["server-id"] = shared_config.load_shared_server_config(directory / "server.yaml").server_id
    if action == "bind":
        from audiagentic.foundation.config.writer import write_settings_patch

        write_settings_patch("user", {"gateway": {"connector": str(connector_path)}})
        result["binding"] = "bound"
    return result


def _create(directory: Path, root: Path) -> None:
    server, connector = _documents(root)
    created: list[Path] = []
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        credentials = directory / "credentials"
        credentials.mkdir(exist_ok=True, mode=0o700)
        for path, data, mode in (
            (credentials / "operator.token", (secrets.token_urlsafe(32) + "\n").encode(), 0o600),
            (directory / "server.yaml", yaml.safe_dump(server, sort_keys=False).encode(), 0o600),
            (directory / "connector.yaml", yaml.safe_dump(connector, sort_keys=False).encode(), 0o600),
        ):
            _exclusive_write(path, data, mode)
            created.append(path)
        shared_config.load_shared_server_config(directory / "server.yaml", default_root=root)
        shared_config.load_shared_connector_config(directory / "connector.yaml")
    except BaseException:
        for path in reversed(created):  # only what this run made
            path.unlink(missing_ok=True)
        raise
