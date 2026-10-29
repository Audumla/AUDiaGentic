"""Strict, owner-local shared gateway configuration.

Paths are relative to the configuration file, never the working directory.
Credential contents are read by ``load_auth_token`` at owner startup, not here.
POSIX token files must exclude group/other access; Windows ACL enforcement is
an external deployment responsibility. No Foundation configuration policy is added.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.io import load_yaml_file

_error = make_error_factory("VAL", "AGSV", "gateway-service")
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_ACTIONS = frozenset({"read", "submit", "cancel", "session"})


@dataclass(frozen=True)
class SharedGatewayPrincipal:
    principal_id: str
    token_file: Path
    projects: frozenset[str]
    actions: frozenset[str]


@dataclass(frozen=True, kw_only=True)
class SharedGatewayServerConfig:
    server_id: str
    host: str = "127.0.0.1"
    port: int
    service_root: Path | None
    projects: dict[str, Path]
    principals: tuple[SharedGatewayPrincipal, ...]


@dataclass(frozen=True)
class SharedGatewayConnectorConfig:
    endpoint: str
    server_id: str
    project_id: str
    token_file: Path
    ca_file: Path | None = None


def _mapping(value: Any, required: set[str], optional: set[str] | None = None) -> dict:
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - (optional or set())):
        raise _error(6, "Invalid shared gateway configuration fields")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(
        ord(c) < 32 or ord(c) == 127 for c in value
    ):
        raise _error(8, "Shared gateway configuration requires a non-empty string")
    return value


def _identifier(value: Any) -> str:
    value = _text(value)
    if not _ID.fullmatch(value):
        raise _error(8, "Shared gateway identifier must be 1-64 safe lowercase characters")
    return value


def _load(path: Path) -> tuple[Path, dict]:
    try:
        path = Path(path).resolve(strict=True)
        data = load_yaml_file(path)
    except (OSError, ValueError, TypeError, RuntimeError, AudiaGenticError):
        # YAML exception chains may contain source lines with secrets.
        raise _error(6, "Cannot load shared gateway YAML configuration") from None
    if (not isinstance(data, dict) or type(data.get("schema-version")) is not int
            or data["schema-version"] != 1):
        raise _error(6, "Shared gateway schema-version must be integer 1")
    return path.parent, data


def _path(base: Path, value: Any, *, directory: bool = False, credential: bool = False) -> Path:
    value = _text(value)
    try:
        path = (base / value).resolve(strict=True)
        if not (path.is_dir() if directory else path.is_file()):
            raise ValueError
        if credential and os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise _error(11, "Shared gateway credential file permits group or other access")
        return path
    except (OSError, ValueError, RuntimeError):
        raise _error(11 if credential else 6, "Shared gateway path must exist with the required type") from None


def _grants(value: Any, allowed: set[str] | frozenset[str]) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise _error(6, "Shared gateway grants must be a non-empty list")
    grants = frozenset(_identifier(item) for item in value)
    if len(grants) != len(value) or not grants <= allowed:
        raise _error(6, "Shared gateway grants contain duplicate or unknown entries")
    return grants


def load_shared_server_config(path: Path) -> SharedGatewayServerConfig:
    """Load server identity, existing directories and principal grants."""
    base, data = _load(path)
    _mapping(data, {"schema-version", "server-id", "listen", "projects", "principals"}, {"service-root"})
    server_id = _identifier(data["server-id"])
    listen = _mapping(data["listen"], {"port"}, {"host"})
    host = _text(listen.get("host", "127.0.0.1"))
    if host != "127.0.0.1":
        raise _error(8, "Shared gateway listen host must be 127.0.0.1")
    port = listen["port"]
    if type(port) is not int or not 0 <= port <= 65535:
        raise _error(17, "Shared gateway listen port must be an integer from 0 through 65535")
    roots = data["projects"]
    if not isinstance(roots, dict) or not roots:
        raise _error(6, "Shared gateway projects must be a non-empty mapping")
    projects = {_identifier(key): _path(base, value, directory=True) for key, value in roots.items()}
    if len(set(projects.values())) != len(projects):
        raise _error(6, "Shared gateway projects must have distinct resolved roots")
    entries = data["principals"]
    if not isinstance(entries, dict) or not entries:
        raise _error(6, "Shared gateway principals must be a non-empty mapping")
    principals = []
    credential_files: list[Path] = []
    for key, value in entries.items():
        principal_id = _identifier(key)
        item = _mapping(value, {"token-file", "projects", "actions"})
        token_file = _path(base, item["token-file"], credential=True)
        try:
            duplicate = any(token_file.samefile(previous) for previous in credential_files)
        except OSError:
            raise _error(11, "Cannot verify shared gateway credential file identity") from None
        if duplicate:
            raise _error(11, "Shared gateway principals must use distinct credential files")
        credential_files.append(token_file)
        principals.append(SharedGatewayPrincipal(
            principal_id=principal_id,
            token_file=token_file,
            projects=_grants(item["projects"], set(projects)),
            actions=_grants(item["actions"], _ACTIONS),
        ))
    return SharedGatewayServerConfig(
        server_id=server_id, host=host, port=port,
        service_root=_path(base, data["service-root"], directory=True) if "service-root" in data else None,
        projects=projects, principals=tuple(principals),
    )


def load_shared_connector_config(path: Path) -> SharedGatewayConnectorConfig:
    """Load an HTTPS origin with no path, userinfo, query or fragment."""
    base, data = _load(path)
    _mapping(data, {"schema-version", "endpoint", "server-id", "project-id", "token-file"}, {"ca-file"})
    endpoint = _text(data["endpoint"])
    try:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path or "?" in endpoint or "#" in endpoint
                or "\\" in endpoint or any(c.isspace() for c in endpoint)
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)
                or parsed.netloc.endswith(":")):
            raise ValueError
    except ValueError:
        raise _error(6, "Shared gateway endpoint must be an HTTPS origin without path or credentials") from None
    return SharedGatewayConnectorConfig(
        endpoint=endpoint, server_id=_identifier(data["server-id"]),
        project_id=_identifier(data["project-id"]),
        token_file=_path(base, data["token-file"], credential=True),
        ca_file=_path(base, data["ca-file"]) if "ca-file" in data else None,
    )
