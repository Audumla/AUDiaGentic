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
from dataclasses import dataclass, field
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
    node_listen: SharedNodeListen | None = None
    nodes: tuple[SharedNodeGrant, ...] = ()
    config_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class SharedNodeListen:
    host: str
    port: int


@dataclass(frozen=True)
class SharedNodeGrant:
    """Server authorization: workspace IDs map to server project IDs, not paths."""

    node_id: str
    token_file: Path
    workspaces: dict[str, str]
    principals: frozenset[str]
    revision: int
    enabled: bool


@dataclass(frozen=True)
class SharedGatewayNodeWorkspace:
    """Node-local paths; never serialize this configuration onto the wire."""

    root: Path
    execution_profiles: frozenset[str]


@dataclass(frozen=True)
class SharedGatewayNodeConfig:
    node_id: str
    server_id: str
    endpoint: str
    token_file: Path
    state_root: Path
    workspaces: dict[str, SharedGatewayNodeWorkspace]
    ca_file: Path | None = None


@dataclass(frozen=True)
class SharedGatewayConnectorConfig:
    """One explicit gateway connection: ``plain`` (local standalone) or ``shared``.

    The project a shared connection addresses is the local project's declared
    ``project.id``; it is not part of the document.
    """

    mode: str
    endpoint: str
    token_file: Path
    server_id: str | None = None
    ca_file: Path | None = None
    source_node_config_file: Path | None = field(default=None, repr=False)


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


def _credential(base: Path, value: Any, previous: list[Path]) -> Path:
    token_file = _path(base, value, credential=True)
    try:
        duplicate = any(token_file.samefile(other) for other in previous)
    except OSError:
        raise _error(11, "Cannot verify shared gateway credential file identity") from None
    if duplicate:
        raise _error(11, "Shared gateway identities must use distinct credential files")
    previous.append(token_file)
    return token_file


def _listen(value: Any) -> SharedNodeListen:
    listen = _mapping(value, {"port"}, {"host"})
    host = _text(listen.get("host", "127.0.0.1"))
    if host != "127.0.0.1":
        raise _error(8, "Shared gateway listen host must be 127.0.0.1")
    port = listen["port"]
    if type(port) is not int or not 0 <= port <= 65535:
        raise _error(17, "Shared gateway listen port must be an integer from 0 through 65535")
    return SharedNodeListen(host, port)


def load_shared_server_config(path: Path) -> SharedGatewayServerConfig:
    """Load server identity, existing directories and principal grants."""
    base, data = _load(path)
    _mapping(data, {"schema-version", "server-id", "listen", "projects", "principals"},
             {"service-root", "node-listen", "nodes"})
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
        token_file = _credential(base, item["token-file"], credential_files)
        principals.append(SharedGatewayPrincipal(
            principal_id=principal_id,
            token_file=token_file,
            projects=_grants(item["projects"], set(projects)),
            actions=_grants(item["actions"], _ACTIONS),
        ))
    node_listen = _listen(data["node-listen"]) if "node-listen" in data else None
    nodes = []
    if "nodes" in data:
        if node_listen is None or not isinstance(data["nodes"], dict) or not data["nodes"]:
            raise _error(6, "Shared gateway nodes require node-listen and a non-empty mapping")
        for key, value in data["nodes"].items():
            node_id = _identifier(key)
            item = _mapping(value, {"token-file", "workspaces", "principals", "revision", "enabled"})
            revision = item["revision"]
            if type(revision) is not int or revision < 1 or type(item["enabled"]) is not bool:
                raise _error(6, "Node revision must be a positive integer and enabled a boolean")
            workspace_map = item["workspaces"]
            if not isinstance(workspace_map, dict) or not workspace_map:
                raise _error(6, "Node workspaces must be a non-empty project-ID mapping")
            workspaces = {_identifier(w): _identifier(p) for w, p in workspace_map.items()}
            if not set(workspaces.values()) <= projects.keys():
                raise _error(6, "Node workspaces must reference configured server projects")
            nodes.append(SharedNodeGrant(
                node_id=node_id, token_file=_credential(base, item["token-file"], credential_files),
                workspaces=workspaces, principals=_grants(item["principals"], {p.principal_id for p in principals}),
                revision=revision, enabled=item["enabled"],
            ))
    return SharedGatewayServerConfig(
        server_id=server_id, host=host, port=port,
        service_root=_path(base, data["service-root"], directory=True) if "service-root" in data else None,
        projects=projects, principals=tuple(principals),
        node_listen=node_listen, nodes=tuple(nodes), config_path=Path(path).resolve(strict=True),
    )


def _loopback_origin(endpoint: str) -> bool:
    """Whether ``endpoint`` is exactly ``http://127.0.0.1:PORT`` (the only plain-http origin)."""
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", endpoint)
    return match is not None and 1 <= int(match.group(1)) <= 65535


def load_shared_connector_config(path: Path) -> SharedGatewayConnectorConfig:
    """Load one connector document: ``mode: plain`` or ``mode: shared``.

    ``plain`` is a local standalone gateway: literal ``http://127.0.0.1:PORT`` and a
    token file. ``shared`` adds the pinned ``server-id`` and takes an HTTPS origin
    (no path, userinfo, query or fragment) or the literal loopback http origin.
    """
    base, data = _load(path)
    mode = data.get("mode")
    if mode == "plain":
        _mapping(data, {"schema-version", "mode", "endpoint", "token-file"})
    elif mode == "shared":
        _mapping(data, {"schema-version", "mode", "endpoint", "server-id", "token-file"},
                 {"ca-file", "source-node-config"})
    else:
        raise _error(6, "Connector mode must be plain or shared")
    endpoint = _text(data["endpoint"])
    if not _loopback_origin(endpoint):
        if mode == "plain":
            raise _error(6, "A plain connector endpoint must be http://127.0.0.1:PORT")
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.path or "?" in endpoint or "#" in endpoint
                    or "\\" in endpoint or any(c.isspace() for c in endpoint)
                    or (parsed.port is not None and not 1 <= parsed.port <= 65535)
                    or parsed.netloc.endswith(":")):
                raise ValueError
        except ValueError:
            raise _error(6, "Shared gateway endpoint must be an HTTPS origin or http://127.0.0.1:PORT") from None
    return SharedGatewayConnectorConfig(
        mode=mode, endpoint=endpoint,
        server_id=_identifier(data["server-id"]) if mode == "shared" else None,
        token_file=_path(base, data["token-file"], credential=True),
        ca_file=_path(base, data["ca-file"]) if "ca-file" in data else None,
        source_node_config_file=_path(base, data["source-node-config"]) if "source-node-config" in data else None,
    )


def load_shared_node_config(path: Path) -> SharedGatewayNodeConfig:
    """Load private node-local configuration, not a public wire payload.

    Component profile selection remains the existing one-profile-per-process
    CLI/environment mechanism. No profile or local root is supplied per request.
    Token values and certificate contents are validated by their startup owners.

    Schema 1 requires node-id, server-id, endpoint, token-file, state-root and
    workspaces. Each workspace maps its ID to {root, execution-profiles}; root
    and state-root are existing config-file-relative directories. ca-file is
    optional. endpoint is a WSS origin plus /shared/v1/nodes/connect exactly.
    Server enrollment is separate: node-listen selects a loopback port and nodes
    maps IDs to {token-file, workspaces, principals, revision, enabled} grants.
    Neither parsing function writes enrollment or configuration files.
    """
    base, data = _load(path)
    _mapping(data, {"schema-version", "node-id", "server-id", "endpoint", "token-file",
                    "state-root", "workspaces"}, {"ca-file"})
    endpoint = _text(data["endpoint"])
    try:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "wss" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path != "/shared/v1/nodes/connect"
                or "?" in endpoint or "#" in endpoint or "\\" in endpoint
                or any(c.isspace() for c in endpoint) or parsed.netloc.endswith(":")
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError
    except ValueError:
        raise _error(6, "Node endpoint must be WSS with exactly /shared/v1/nodes/connect") from None
    entries = data["workspaces"]
    if not isinstance(entries, dict) or not entries:
        raise _error(6, "Node workspaces must be a non-empty mapping")
    workspaces = {}
    for key, value in entries.items():
        workspace_id = _identifier(key)
        item = _mapping(value, {"root", "execution-profiles"})
        profiles = item["execution-profiles"]
        if not isinstance(profiles, list) or not profiles:
            raise _error(6, "Node execution-profiles must be a non-empty list")
        profile_ids = frozenset(_identifier(profile) for profile in profiles)
        if len(profile_ids) != len(profiles):
            raise _error(6, "Node execution-profiles must be distinct")
        workspaces[workspace_id] = SharedGatewayNodeWorkspace(
            root=_path(base, item["root"], directory=True), execution_profiles=profile_ids)
    return SharedGatewayNodeConfig(
        node_id=_identifier(data["node-id"]), server_id=_identifier(data["server-id"]),
        endpoint=endpoint, token_file=_path(base, data["token-file"], credential=True),
        state_root=_path(base, data["state-root"], directory=True), workspaces=workspaces,
        ca_file=_path(base, data["ca-file"]) if "ca-file" in data else None,
    )
