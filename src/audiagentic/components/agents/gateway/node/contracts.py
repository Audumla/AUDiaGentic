"""Frozen v1 node frames. Channel authentication remains the calling owner's job."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory

invalid = make_error_factory("VAL", "AGND", "agents-node")
conflict = make_error_factory("CON", "AGND", "agents-node")
MAX_FRAME_BYTES = 1024 * 1024
_TYPES = frozenset(
    {
        "hello",
        "welcome",
        "heartbeat",
        "command",
        "effect-authorize",
        "effect-authorized",
        "effect-denied",
        "receipt",
        "reconcile",
        "reconcile-result",
        "revoke",
        "error",
    }
)
_PRIVATE_KEYS = frozenset(
    {
        "native-ref",
        "native-reference",
        "native-locator",
        "native_ref",
        "native_reference",
        "native_locator",
        "native-correlation",
        "native_correlation",
    }
)


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value):
        raise invalid(1, "Invalid node contract identifier")
    return value


def _integer(value: Any, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise invalid(1, "Invalid node contract integer")
    return value


def _freeze(value: Any, depth: int = 0) -> Any:
    if depth > 64:
        raise invalid(1, "Node payload nesting exceeds the supported bound")
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) or k in _PRIVATE_KEYS for k in value):
            raise invalid(1, "Invalid or private node payload field")
        return MappingProxyType({k: _freeze(v, depth + 1) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v, depth + 1) for v in value)
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise invalid(1, "Node payload must contain finite JSON values")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _plain(_freeze(value)),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise invalid(1, "Node contract is not valid UTF-8 JSON") from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise invalid(1, "Duplicate node JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise invalid(1, "Non-finite node JSON value")


@dataclass(frozen=True)
class CommandIdentity:
    command_id: str
    request_id: str
    node_id: str
    node_epoch: str
    gateway_owner_epoch: str
    connection_generation: int
    workspace_id: str
    grant_revision: int
    binding_generation: int
    payload_sha256: str
    execution_profile_id: str

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {"connection_generation", "grant_revision", "binding_generation"}:
                _integer(value)
            elif field.name == "payload_sha256":
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise invalid(1, "Invalid command payload digest")
            else:
                _identifier(value)

    def to_mapping(self) -> dict[str, Any]:
        return {f.name.replace("_", "-"): getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CommandIdentity:
        names = {f.name.replace("_", "-") for f in fields(cls)}
        if not isinstance(value, Mapping) or set(value) != names:
            raise invalid(1, "Invalid command identity fields")
        return cls(**{k.replace("-", "_"): v for k, v in value.items()})

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_mapping())).hexdigest()


@dataclass(frozen=True)
class Frame:
    version: int
    type: str
    message_id: str
    node_id: str
    node_epoch: str
    gateway_owner_epoch: str
    sequence: int
    payload: Mapping[str, Any]

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise invalid(1, "Unsupported node frame version")
        if not isinstance(self.type, str) or self.type not in _TYPES:
            raise invalid(1, "Unsupported node frame type")
        for value in (self.message_id, self.node_id, self.node_epoch, self.gateway_owner_epoch):
            _identifier(value)
        _integer(self.sequence)
        if not isinstance(self.payload, Mapping):
            raise invalid(1, "Node frame payload must be an object")
        object.__setattr__(self, "payload", _freeze(self.payload))
        if len(self.to_bytes()) > MAX_FRAME_BYTES:
            raise invalid(1, "Node frame exceeds 1 MiB")

    def to_bytes(self) -> bytes:
        return canonical_json(
            {f.name.replace("_", "-"): getattr(self, f.name) for f in fields(self)}
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> Frame:
        if not isinstance(raw, bytes) or len(raw) > MAX_FRAME_BYTES:
            raise invalid(1, "Node frame must be at most 1 MiB of UTF-8 JSON")
        try:
            value = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
            )
        except (ValueError, UnicodeError, RecursionError):
            raise invalid(1, "Invalid node JSON frame") from None
        names = {f.name.replace("_", "-") for f in fields(cls)}
        if not isinstance(value, dict) or set(value) != names:
            raise invalid(1, "Invalid node frame fields")
        return cls(**{k.replace("-", "_"): v for k, v in value.items()})


def validate_effect_authorization(
    identity: CommandIdentity, request: Frame, reply: Frame, *, connection_generation: int
) -> str:
    """Validate correlation on an already authenticated, currently live channel.

    This does not authenticate a peer or create an offline grant. The caller
    must serialize authorization/revocation and pass the live connection generation.
    """
    _integer(connection_generation)
    expected = identity.to_mapping()
    if (
        identity.connection_generation != connection_generation
        or request.type != "effect-authorize"
        or reply.type != "effect-authorized"
        or set(request.payload) != {"identity"}
        or set(reply.payload)
        != {"identity", "authorization-request-id", "authorization-id", "authorized"}
        or request.payload["identity"] != expected
        or reply.payload["identity"] != expected
        or reply.payload["authorization-request-id"] != request.message_id
        or reply.payload["authorized"] is not True
        or any(
            (f.node_id, f.node_epoch, f.gateway_owner_epoch)
            != (identity.node_id, identity.node_epoch, identity.gateway_owner_epoch)
            for f in (request, reply)
        )
    ):
        raise conflict(1, "Effect authorization does not match the live command and request")
    return _identifier(reply.payload["authorization-id"])
