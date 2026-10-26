"""Strict node wire contracts; no network or provider effects."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from audiagentic.components.agents.gateway.node.contracts import (
    MAX_FRAME_BYTES,
    CommandIdentity,
    Frame,
    validate_effect_authorization,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def identity(**changes):
    values = dict(
        command_id="cmd-1",
        request_id="req-1",
        node_id="node-1",
        node_epoch="boot-1",
        gateway_owner_epoch="gateway-1",
        connection_generation=1,
        workspace_id="workspace-1",
        grant_revision=1,
        binding_generation=1,
        payload_sha256=hashlib.sha256(b"payload").hexdigest(),
        execution_profile_id="profile-1",
    )
    return CommandIdentity(**(values | changes))


def frame(kind="command", payload=None, **changes):
    return Frame(
        **(
            dict(
                version=1,
                type=kind,
                message_id="msg-1",
                node_id="node-1",
                node_epoch="boot-1",
                gateway_owner_epoch="gateway-1",
                sequence=1,
                payload={} if payload is None else payload,
            )
            | changes
        )
    )


def authorization(command=None):
    command = command or identity()
    request = frame("effect-authorize", {"identity": command.to_mapping()}, message_id="auth-1")
    reply = frame(
        "effect-authorized",
        {
            "identity": command.to_mapping(),
            "authorization-request-id": "auth-1",
            "authorization-id": "grant-1",
            "authorized": True,
        },
        message_id="reply-1",
    )
    return request, reply


def test_frame_roundtrip_and_recursive_freeze():
    original = {"nested": [{"value": 1}]}
    frozen = frame(payload=original)
    original["nested"][0]["value"] = 2
    assert frozen.payload["nested"][0]["value"] == 1
    assert Frame.from_bytes(frozen.to_bytes()) == frozen
    with pytest.raises(TypeError):
        frozen.payload["nested"][0]["value"] = 3
    with pytest.raises(FrozenInstanceError):
        frozen.sequence = 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 2),
        ("sequence", True),
        ("sequence", 0),
        ("sequence", 2**63),
        ("type", "future"),
        ("node_id", "../node"),
        ("payload", []),
        ("payload", {"value": float("nan")}),
        ("payload", {"value": float("inf")}),
        ("payload", {"value": object()}),
        ("payload", {"nested": {"native-ref": "private"}}),
    ],
)
def test_invalid_frame_fields(field, value):
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        frame(**{field: value})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":1}',
        b'{"a":{"x":1,"x":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b"[]",
        b"null",
        b"\xff",
        b"{",
        b" " * (MAX_FRAME_BYTES + 1),
    ],
    ids=lambda raw: f"wire-{len(raw)}",
)
def test_invalid_wire_bytes(raw):
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        Frame.from_bytes(raw)


def test_exact_frame_size_and_unknown_fields():
    overhead = len(frame(payload={"text": ""}).to_bytes())
    exact = frame(payload={"text": "a" * (MAX_FRAME_BYTES - overhead)})
    assert len(exact.to_bytes()) == MAX_FRAME_BYTES
    assert Frame.from_bytes(exact.to_bytes()) == exact
    with pytest.raises(AudiaGenticError):
        frame(payload={"text": "a" * (MAX_FRAME_BYTES - overhead + 1)})
    data = json.loads(frame().to_bytes())
    data["extra"] = 1
    with pytest.raises(AudiaGenticError):
        Frame.from_bytes(json.dumps(data).encode())
    del data["extra"]
    del data["node-id"]
    with pytest.raises(AudiaGenticError):
        Frame.from_bytes(json.dumps(data).encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("connection_generation", True),
        ("grant_revision", False),
        ("binding_generation", -1),
        ("connection_generation", 1.0),
        ("payload_sha256", "A" * 64),
        ("payload_sha256", "0" * 63),
        ("node_epoch", ""),
        ("workspace_id", "../root"),
    ],
)
def test_command_identity_validation(field, value):
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        identity(**{field: value})


def test_identity_exact_fields_and_frozen():
    command = identity()
    assert CommandIdentity.from_mapping(command.to_mapping()) == command
    assert len(command.digest) == 64
    with pytest.raises(FrozenInstanceError):
        command.request_id = "other"
    with pytest.raises(AudiaGenticError):
        CommandIdentity.from_mapping(command.to_mapping() | {"native-ref": "private"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("command_id", "other"),
        ("request_id", "other"),
        ("node_id", "other"),
        ("node_epoch", "other"),
        ("gateway_owner_epoch", "other"),
        ("connection_generation", 2),
        ("workspace_id", "other"),
        ("grant_revision", 2),
        ("binding_generation", 2),
        ("payload_sha256", "0" * 64),
        ("execution_profile_id", "other"),
    ],
)
def test_reply_must_match_every_command_identity_field(field, value):
    command = identity()
    request, reply = authorization(command)
    reply = replace(
        reply,
        payload=dict(reply.payload) | {"identity": replace(command, **{field: value}).to_mapping()},
    )
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        validate_effect_authorization(command, request, reply, connection_generation=1)


@pytest.mark.parametrize(
    "change",
    [
        "request-id",
        "denied",
        "truthy",
        "connection",
        "request-type",
        "reply-type",
        "request-scope",
        "reply-scope",
        "extra",
    ],
)
def test_authorization_requires_exact_exchange_and_live_connection(change):
    command = identity()
    request, reply = authorization(command)
    generation = 1
    if change == "request-id":
        reply = replace(reply, payload=dict(reply.payload) | {"authorization-request-id": "other"})
    elif change in {"denied", "truthy"}:
        reply = replace(
            reply, payload=dict(reply.payload) | {"authorized": 1 if change == "truthy" else False}
        )
    elif change == "connection":
        generation = 2
    elif change == "request-type":
        request = replace(request, type="command")
    elif change == "reply-type":
        reply = replace(reply, type="receipt")
    elif change == "request-scope":
        request = replace(request, gateway_owner_epoch="old")
    elif change == "reply-scope":
        reply = replace(reply, node_epoch="old")
    else:
        reply = replace(reply, payload=dict(reply.payload) | {"offline-lease": True})
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        validate_effect_authorization(command, request, reply, connection_generation=generation)


def test_current_authorization_is_accepted():
    command = identity()
    request, reply = authorization(command)
    validate_effect_authorization(command, request, reply, connection_generation=1)


@pytest.mark.parametrize(
    "kind",
    [
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
    ],
)
def test_canonical_channel_types_roundtrip(kind):
    value = frame(kind)
    assert Frame.from_bytes(value.to_bytes()) == value


@pytest.mark.parametrize("kind", ["receipt-query", "greeting", "authorization-result"])
def test_no_legacy_or_duplicate_channel_synonyms(kind):
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        frame(kind)


@pytest.mark.parametrize(
    "key",
    [
        "native-ref",
        "native-reference",
        "native-locator",
        "native-correlation",
        "native_ref",
        "native_reference",
        "native_locator",
        "native_correlation",
    ],
)
def test_native_correlation_never_crosses_wire(key):
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        frame("reconcile-result", {"nested": [{key: "private-node-only"}]})


def test_effect_denial_is_valid_wire_but_never_authorizes_intent():
    command = identity()
    request, reply = authorization(command)
    denied = replace(
        reply, type="effect-denied", payload=dict(reply.payload) | {"authorized": False}
    )
    assert Frame.from_bytes(denied.to_bytes()) == denied
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        validate_effect_authorization(command, request, denied, connection_generation=1)


@pytest.mark.parametrize(
    "value", [None, "", "../grant", "grant with space", True, 1, [], {}, "x" * 201]
)
def test_effect_authorization_requires_valid_exact_authorization_id(value):
    command = identity()
    request, reply = authorization(command)
    malformed = replace(reply, payload=dict(reply.payload) | {"authorization-id": value})
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        validate_effect_authorization(command, request, malformed, connection_generation=1)


def test_missing_authorization_id_is_not_a_legacy_authorization():
    request, reply = authorization()
    payload = dict(reply.payload)
    del payload["authorization-id"]
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        validate_effect_authorization(
            identity(), request, replace(reply, payload=payload), connection_generation=1
        )
