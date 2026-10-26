"""Central grant authorization and revocation, ordered by one config-file lock.

The protected local server YAML is the only durable authority. All participating
writers must use this lock. Unsupported/out-of-band edits fail closed; an
administrator able to replace both config and process state is outside this
boundary. Callbacks run under the lock: canonical local mutations only, never
network/native I/O or recursive authority calls. Atomic replacement inherits
Foundation filesystem durability limits; this is not power-loss qualification.
"""
from __future__ import annotations

import copy
import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import yaml

from audiagentic.components.agents.gateway.remote_client import load_auth_token
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayServerConfig,
    load_shared_server_config,
)
from audiagentic.foundation.io import atomic_write_bytes, load_yaml_file
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.process import StartupLock

from .contracts import CommandIdentity, _identifier, conflict, invalid
from .placement import NodeAdmissionPlacement

T = TypeVar("T")


@dataclass(frozen=True)
class NodeConnectionIdentity:
    """Trusted live-channel snapshot supplied by the connection owner."""

    node_id: str
    node_epoch: str
    gateway_owner_epoch: str
    connection_generation: int


@dataclass(frozen=True)
class SealedNodePlacement:
    """Server-owned admission placement; never construct from a node payload."""

    identity: CommandIdentity
    server_id: str
    principal_id: str
    server_project_id: str


class NodeGrantAuthority:
    """Use one instance per service; instances/processes share the same lock.

    A peer's supported revoke-only edits are recognized on reload. Other config
    changes require explicit service restart with freshly validated config.
    An uncertain write poisons this instance; it never restores old bytes or
    authorizes effects again. Reconcile durable config before restarting it.
    """

    def __init__(self, config: SharedGatewayServerConfig, service_root: Path | None = None,
                 *, lock_timeout: float = 30.0):
        if config.config_path is None:
            raise invalid(1, "Node authority requires the owning server config path")
        self.path = config.config_path.resolve(strict=True)
        from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY

        expected_root = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root).root.resolve()
        if service_root is not None and service_root.resolve() != expected_root:
            raise conflict(1, "Node authority service root does not match the owning server config")
        # The service owner supplies its resolved state root. The authority lock
        # is config-source scoped, independent of alternate runtime-root choices.
        self.service_root = expected_root
        if self.path.is_relative_to(self.service_root):
            raise invalid(1, "Node authority config must be outside managed service state")
        self.lock_path = self.path.with_name(self.path.name + ".node-authority.lock")
        if self.lock_path.is_symlink() or self.lock_path.with_name(self.lock_path.name + ".guard").is_symlink():
            raise invalid(1, "Node authority lock paths must not be symbolic links")
        self._timeout = lock_timeout
        self._poisoned = False
        with self._lock():
            current, raw, digest = self._read()
            if current != config:
                raise conflict(1, "Server config changed before node authority startup")
            tokens: set[str] = set()
            for identity in (*current.principals, *current.nodes):
                token = load_auth_token(identity.token_file)
                if token in tokens:
                    raise invalid(1, "Shared gateway identities must use distinct auth tokens")
                tokens.add(token)
            self._config, self._raw, self._digest = current, raw, digest

    @property
    def config_digest(self) -> str:
        """Last observed exact-byte SHA256; optionally supply as a writer CAS."""
        return self._digest

    def _lock(self) -> StartupLock:
        return StartupLock(self.lock_path, timeout=self._timeout)

    def _read(self) -> tuple[SharedGatewayServerConfig, dict, str]:
        try:
            before = self.path.read_bytes()
            config = load_shared_server_config(self.path)
            raw = load_yaml_file(self.path)
            if self.path.read_bytes() != before:
                raise conflict(1, "Server config changed during authority reload")
            return config, raw, hashlib.sha256(before).hexdigest()
        except (OSError, ValueError, TypeError):
            raise conflict(1, "Cannot reload node authority config") from None

    def _reload(self, expected_digest: str | None):
        if self._poisoned:
            raise conflict(1, "Node authority persistence is uncertain; reconcile before restart")
        config, raw, digest = self._read()
        if expected_digest is not None and expected_digest != digest:
            raise conflict(1, "Node authority config digest is stale")
        if digest != self._digest:
            # Only the exact revoke transformation is supported while running.
            supported = copy.deepcopy(self._raw)
            for node_id, old in self._raw.get("nodes", {}).items():
                new = raw.get("nodes", {}).get(node_id, {})
                if old["enabled"] is True and new.get("enabled") is False:
                    supported["nodes"][node_id]["enabled"] = False
                    supported["nodes"][node_id]["revision"] = old["revision"] + 1
            if supported != raw or supported == self._raw:
                self._poisoned = True
                raise conflict(1, "Unsupported external server config edit")
        self._config, self._raw, self._digest = config, raw, digest
        return config

    def authorize_admission(
        self, *, principal_id: str, server_project_id: str,
        node_id: str, workspace_id: str,
        callback: Callable[[NodeAdmissionPlacement], T],
    ) -> T:
        """Seal current configured placement, then mutate under the grant lock.

        principal_id must come from the authenticated calling owner, never an
        untrusted request field. IDs select configured grants; they do not grant
        authority themselves. No live connection/effect permission is implied.

        The callback receives only this owner's constructed placement. Its
        return value is opaque operation output, never placement authority.
        Canonical local mutations only: no queue drain, network/native I/O or
        recursive authority calls. Callback exceptions propagate without retry.
        """
        with self._lock():
            server_id = self._config.server_id
            config = self._reload(None)
            for value in (principal_id, server_project_id, node_id, workspace_id):
                _identifier(value)
            principal = next((p for p in config.principals if p.principal_id == principal_id), None)
            grant = next((n for n in config.nodes if n.node_id == node_id), None)
            if (config.server_id != server_id or server_project_id not in config.projects
                    or principal is None or server_project_id not in principal.projects
                    or "submit" not in principal.actions or grant is None or not grant.enabled
                    or principal_id not in grant.principals
                    or grant.workspaces.get(workspace_id) != server_project_id):
                raise conflict(1, "Node admission placement is not authorized by current configuration")
            placement = NodeAdmissionPlacement(
                config.server_id, grant.node_id, workspace_id, principal.principal_id,
                server_project_id, grant.revision,
            )
            return callback(placement)

    def authorize_effect(
        self, placement: SealedNodePlacement, *,
        connection: Callable[[], NodeConnectionIdentity], callback: Callable[[], T],
        expected_config_digest: str | None = None,
    ) -> T:
        """Validate sealed scopes and live identity, then mutate under auth lock.

        ``connection`` reads owner-controlled live connection state under this
        same lock. Connection replacement/disconnect must use ``serialize``.
        No callback exception is retried, and no network reply is sent here.
        """
        with self._lock():
            config = self._reload(expected_config_digest)
            identity = placement.identity
            live = connection()
            expected = NodeConnectionIdentity(identity.node_id, identity.node_epoch,
                                              identity.gateway_owner_epoch, identity.connection_generation)
            grant = next((n for n in config.nodes if n.node_id == identity.node_id), None)
            principal = next((p for p in config.principals if p.principal_id == placement.principal_id), None)
            if (not isinstance(live, NodeConnectionIdentity) or live != expected
                    or type(live.connection_generation) is not int
                    or placement.server_id != config.server_id or grant is None
                    or not grant.enabled or grant.revision != identity.grant_revision
                    or grant.workspaces.get(identity.workspace_id) != placement.server_project_id
                    or placement.principal_id not in grant.principals or principal is None
                    or placement.server_project_id not in principal.projects
                    or "submit" not in principal.actions):
                raise conflict(1, "Node effect placement or live connection is no longer authorized")
            return callback()

    def serialize(self, callback: Callable[[], T]) -> T:
        """Order local connection replacement/disconnect with effect/revoke."""
        with self._lock():
            self._reload(None)
            return callback()

    def revoke(self, node_id: str, *, expected_grant_revision: int,
               expected_config_digest: str | None = None) -> int:
        """CAS an enabled grant to disabled revision+1 in the owning YAML."""
        with self._lock():
            config = self._reload(expected_config_digest)
            grant = next((n for n in config.nodes if n.node_id == node_id), None)
            if type(expected_grant_revision) is not int or expected_grant_revision < 1 or grant is None:
                raise conflict(1, "Node grant revision is stale or already revoked")
            if not grant.enabled and grant.revision == expected_grant_revision + 1:
                return grant.revision
            if not grant.enabled or grant.revision != expected_grant_revision:
                raise conflict(1, "Node grant revision is stale or already revoked")
            candidate = copy.deepcopy(self._raw)
            candidate["nodes"][node_id]["enabled"] = False
            candidate["nodes"][node_id]["revision"] = expected_grant_revision + 1
            payload = yaml.safe_dump(candidate, sort_keys=False).encode("utf-8")
            # Same directory preserves every relative path during full validation.
            fd, name = tempfile.mkstemp(prefix=".node-grant-", suffix=".yaml", dir=self.path.parent)
            os.close(fd)
            staging = Path(name)
            try:
                atomic_write_bytes(staging, payload)
                load_shared_server_config(staging)
            finally:
                staging.unlink(missing_ok=True)
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != self._digest:
                raise conflict(1, "Server config changed before grant persistence")
            # Set before writing: even an exception after successful replace must
            # retain denial rather than restoring/retrying an old enabled grant.
            self._poisoned = True
            try:
                atomic_write_bytes(self.path, payload)
                current, raw, digest = self._read()
                if digest != hashlib.sha256(payload).hexdigest():
                    raise conflict(1, "Node grant persistence could not be confirmed")
            except Exception:
                raise conflict(1, "Node grant persistence is uncertain; reconcile config") from None
            self._config, self._raw, self._digest = current, raw, digest
            self._poisoned = False
            return expected_grant_revision + 1
