"""Pure wire validation; these tests deliberately confer no runtime authority."""

import base64
import hashlib
from dataclasses import replace

import pytest

from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.contracts import (
    CommandIdentity,
    Frame,
    canonical_json,
    validate_effect_authorization,
)
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    build_final_command_payload,
    prepare_node_command,
    validate_final_command_payload,
)
from audiagentic.components.agents.gateway.node.work_protocol import (
    MAX_CHUNK_BYTES,
    ArtifactChunk,
    ArtifactGet,
    CommandWork,
    EffectAuthorize,
    EffectAuthorized,
    EffectDenied,
    PreparationRejected,
    PreparedReply,
    PrepareWork,
    ReceiptAckWork,
    ReceiptReady,
    ReceiptResume,
    ReceiptResumeReply,
    ReceiptWork,
    parse_work_frame,
)

C = NodeConnectionIdentity("node", "epoch", "gateway", 2)
SHA = "a" * 64
LOG = "00000000-0000-4000-8000-00000000abcd"
SECRET = "private raw prompt sentinel"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def messages():
    binding = PreparationBinding(
        "command",
        "request",
        C.node_id,
        C.node_epoch,
        C.gateway_owner_epoch,
        C.connection_generation,
        "workspace",
        1,
        1,
        "challenge",
        "prepare-message",
    )
    semantic = PromptSemanticIdentity(SHA, SHA, "prompt", "profile", 1, SHA, digest(SECRET))
    retained = prepare_node_command(
        binding=binding,
        semantic=semantic,
        raw_prompt=SECRET,
        rendered_prompt="rendered",
        manifest_id="manifest",
        context_fingerprint=SHA,
        runtime_digest=SHA,
        provider_manifest=b"private manifest",
        worker_id="worker",
        attempt_epoch=1,
        provider_id="provider",
        model_id="model",
        model_alias=None,
    )
    payload = build_final_command_payload(retained, SECRET)
    identity = CommandIdentity(
        "command",
        "request",
        C.node_id,
        C.node_epoch,
        C.gateway_owner_epoch,
        C.connection_generation,
        "workspace",
        1,
        1,
        hashlib.sha256(canonical_json(payload)).hexdigest(),
        "profile",
    )
    old = replace(
        identity, node_epoch="old", gateway_owner_epoch="old-gateway", connection_generation=1
    )
    # name: (frame type, receiving role, drain allowed, payload, expected DTO)
    return {
        "ready": (
            "reconcile", "gateway", False,
            {"kind": "receipt-ready", "log-incarnation-id": LOG,
             "through-sequence": 0, "through-receipt-sha256": None},
            ReceiptReady,
        ),
        "prepare": (
            "reconcile",
            "node",
            False,
            {
                "kind": "prepare",
                "binding": binding.to_mapping(),
                "semantic": semantic.to_mapping(),
                "agent-id": "agent",
                "worker-id": "worker",
                "attempt-epoch": 1,
                "raw-prompt": SECRET,
                "source-workspace": {"version": 1, "source-node-id": "node", "workspace-id": "workspace",
                                     "access-mode": "read-write", "binding-sha256": SHA},
                "caller-root": "/private/recipient-workspace",
                "source": None,
                "metadata": {},
                "timeout-seconds": None,
            },
            PrepareWork,
        ),
        "prepared": (
            "reconcile-result",
            "gateway",
            False,
            {
                "kind": "prepared",
                "in-reply-to": "prepare-message",
                "attestation": retained.attestation.to_mapping(),
            },
            PreparedReply,
        ),
        "rejected": (
            "reconcile-result",
            "gateway",
            False,
            {
                "kind": "prepare-rejected",
                "in-reply-to": "prepare-message",
                "code": "VAL-AGND-001",
            },
            PreparationRejected,
        ),
        "command": (
            "command",
            "node",
            False,
            {"identity": identity.to_mapping(), "payload": payload},
            CommandWork,
        ),
        "authorize": (
            "effect-authorize",
            "gateway",
            False,
            {"identity": identity.to_mapping()},
            EffectAuthorize,
        ),
        "authorized": (
            "effect-authorized",
            "node",
            False,
            {
                "identity": identity.to_mapping(),
                "authorization-request-id": "message",
                "authorization-id": "authorization",
                "authorized": True,
            },
            EffectAuthorized,
        ),
        "denied": (
            "effect-denied",
            "node",
            False,
            {
                "identity": identity.to_mapping(),
                "authorization-request-id": "message",
                "code": "CON-AGND-001",
            },
            EffectDenied,
        ),
        "receipt": (
            "receipt",
            "gateway",
            True,
            {
                "log-incarnation-id": LOG,
                "receipt": {
                    "identity": old.to_mapping(),
                    "state": "terminal",
                    "receipt-sequence": 3,
                    "output-sha256": SHA,
                },
            },
            ReceiptWork,
        ),
        "resume": (
            "reconcile",
            "gateway",
            True,
            {
                "kind": "receipt-resume",
                "log-incarnation-id": LOG,
                "through-sequence": 0,
                "through-receipt-sha256": None,
            },
            ReceiptResume,
        ),
        "resume-reply": (
            "reconcile-result",
            "node",
            True,
            {
                "kind": "receipt-resume",
                "in-reply-to": "resume",
                "log-incarnation-id": LOG,
                "after-sequence": 3,
                "after-receipt-sha256": SHA,
            },
            ReceiptResumeReply,
        ),
        "ack": (
            "reconcile-result",
            "node",
            True,
            {
                "kind": "receipt-ack",
                "server-id": "server",
                "log-incarnation-id": LOG,
                "through-sequence": 3,
                "through-receipt-sha256": SHA,
            },
            ReceiptAckWork,
        ),
        "get": (
            "reconcile",
            "node",
            True,
            {
                "kind": "artifact-get",
                "identity": old.to_mapping(),
                "artifact-sha256": SHA,
                "offset": 0,
                "limit": MAX_CHUNK_BYTES,
            },
            ArtifactGet,
        ),
        "chunk": (
            "reconcile-result",
            "gateway",
            True,
            {
                "kind": "artifact-chunk",
                "in-reply-to": "get",
                "identity": old.to_mapping(),
                "artifact-sha256": SHA,
                "artifact-kind": "worker-terminal-result",
                "offset": 0,
                "total-bytes": 13,
                "data": base64.b64encode(b"private chunk").decode(),
                "eof": True,
            },
            ArtifactChunk,
        ),
    }


def frame(spec, payload=None, **changes):
    kind, _, _, original, _ = spec
    p = dict(original if payload is None else payload)
    if not kind.startswith("effect-"):
        p.setdefault("connection-generation", C.connection_generation)
    values = dict(
        version=1,
        type=kind,
        message_id="message",
        node_id=C.node_id,
        node_epoch=C.node_epoch,
        gateway_owner_epoch=C.gateway_owner_epoch,
        sequence=1,
        payload=p,
    )
    values.update(changes)
    return Frame(**values)


def parse(spec, payload=None, **options):
    kwargs = dict(role=spec[1], current_connection=C, capability="active", max_artifact_bytes=2**20)
    kwargs.update(options)
    return parse_work_frame(Frame.from_bytes(frame(spec, payload).to_bytes()), **kwargs)


NAMES = [
    "ready",
    "prepare",
    "prepared",
    "rejected",
    "command",
    "authorize",
    "authorized",
    "denied",
    "receipt",
    "resume",
    "resume-reply",
    "ack",
    "get",
    "chunk",
]


@pytest.mark.parametrize("name", NAMES)
def test_roundtrip_role_and_drain(messages, name):
    spec = messages[name]
    assert type(parse(spec)) is spec[4]
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, role="gateway" if spec[1] == "node" else "node")
    if spec[2]:
        assert type(parse(spec, capability="drain")) is spec[4]
    else:
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, capability="drain")


@pytest.mark.parametrize("name", NAMES)
def test_exact_outer_fields_and_current_scope(messages, name):
    spec = messages[name]
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "unexpected": None})
    for field in ("node_id", "node_epoch", "gateway_owner_epoch"):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse_work_frame(
                frame(spec, **{field: "other"}),
                role=spec[1],
                current_connection=C,
                capability="active",
                max_artifact_bytes=2**20,
            )
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, current_connection=replace(C, connection_generation=3))


@pytest.mark.parametrize("name", NAMES)
def test_missing_fields_rejected(messages, name):
    spec = messages[name]
    for key in spec[3]:
        p = dict(spec[3])
        del p[key]
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, p)


@pytest.mark.parametrize("sequence,sha", [(False, None), (-1, None), (0, SHA), (1, None),
                                       (1, "bad"), (1, SHA.upper())])
def test_receipt_ready_requires_exact_cursor(messages, sequence, sha):
    spec = messages["ready"]
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "through-sequence": sequence, "through-receipt-sha256": sha})


def test_receipt_ready_accepts_durable_nonempty_cursor_not_command_identity(messages):
    spec = messages["ready"]
    ready = parse(spec, {**spec[3], "through-sequence": 4, "through-receipt-sha256": SHA})
    assert (ready.log_incarnation_id, ready.through_sequence, ready.through_receipt_sha256) == (LOG, 4, SHA)
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "identity": {}})
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "log-incarnation-id": "bad"})


def test_effect_exception_matches_existing_schema_and_real_pair(messages):
    request, reply = frame(messages["authorize"]), frame(messages["authorized"])
    identity = parse(messages["authorize"]).identity
    assert (
        validate_effect_authorization(identity, request, reply, connection_generation=2)
        == "authorization"
    )
    for name in ("authorize", "authorized", "denied"):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(messages[name], {**messages[name][3], "connection-generation": 2})
    for value in (False, 1, "true", None):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(messages["authorized"], {**messages["authorized"][3], "authorized": value})


def test_sensitive_data_frozen_and_not_in_repr(messages):
    prepared, command, chunk = (parse(messages[n]) for n in ("prepare", "command", "chunk"))
    assert SECRET not in repr(prepared) + repr(command)
    assert "private chunk" not in repr(chunk)
    assert chunk.data == b"private chunk"
    with pytest.raises(TypeError):
        command.command_payload["raw-prompt"] = "different"
    with pytest.raises(TypeError):
        prepared.metadata["anything"] = 1


def test_command_digest_and_separately_accepted_attestation(messages):
    spec = messages["command"]
    command = parse(spec)
    accepted = parse(messages["prepared"]).attestation
    assert (
        validate_final_command_payload(
            command.command_payload, command.identity, accepted_attestation=accepted
        )
        == accepted
    )
    for update in ({"raw-prompt": "substitution"}, {"root": "private"}, {"attestation": {}}):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, {**spec[3], "payload": {**spec[3]["payload"], **update}})
    # Parsing data is not pending-exchange acceptance: a well-shaped replacement
    # attestation parses, but the actual acceptance owner rejects it.
    changed = {
        **spec[3]["payload"],
        "attestation": {**accepted.to_mapping(), "worker-id": "other-worker"},
    }
    other = replace(
        command.identity, payload_sha256=hashlib.sha256(canonical_json(changed)).hexdigest()
    )
    wire = parse(spec, {"identity": other.to_mapping(), "payload": changed})
    with pytest.raises(Exception, match="CON-AGND-001"):
        validate_final_command_payload(
            wire.command_payload, wire.identity, accepted_attestation=accepted
        )


@pytest.mark.parametrize(
    "name,key,nested",
    [
        ("prepare", "binding", "connection-generation"),
        ("prepare", "semantic", "expanded-prompt-version"),
        ("prepared", "attestation", "attempt-epoch"),
        ("command", "identity", "grant-revision"),
    ],
)
def test_nested_exact_fields_and_integer_booleans(messages, name, key, nested):
    spec = messages[name]
    for update in ({"extra": 1}, {nested: True}):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, {**spec[3], key: {**spec[3][key], **update}})


@pytest.mark.parametrize(
    "updates",
    [
        {"timeout-seconds": True},
        {"timeout-seconds": 0},
        {"timeout-seconds": -1},
        {"source": {}},
        {"metadata": {"raw-prompt": "x"}},
        {"metadata": {"idempotency_key": "must-not-cross-wire"}},
        {"metadata": {"caller-title": "gateway-only-audit"}},
        {"caller-root": ""},
        {"caller-root": "bad\npath"},
        {"caller-root": "x" * 32769},
        {"metadata": {"correlation_id": {"nested": 1}}},
        {"metadata": []},
        {"agent-id": "bad id"},
        {"worker-id": False},
        {"attempt-epoch": True},
    ],
)
def test_prepare_options_reject(messages, updates):
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(messages["prepare"], {**messages["prepare"][3], **updates})


def test_prepare_optional_values_and_primitive_metadata(messages):
    p = {
        **messages["prepare"][3],
        "source": "api",
        "timeout-seconds": 1.5,
        "metadata": {
            "schema_version": 1,
            "correlation_id": "correlation",
        },
    }
    assert parse(messages["prepare"], p).timeout_seconds == 1.5


@pytest.mark.parametrize("field,value", [("source-node-id", "foreign"), ("workspace-id", "other"),
                                       ("access-mode", "read-only"), ("binding-sha256", "invalid")])
def test_prepare_source_scope_rejects_before_runtime(messages, field, value):
    p = dict(messages["prepare"][3])
    p["source-workspace"] = {**p["source-workspace"], field: value}
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(messages["prepare"], p)


def test_prepare_locator_is_not_in_repr(messages):
    p = messages["prepare"][3]
    assert p["caller-root"] not in repr(parse(messages["prepare"], p))


@pytest.mark.parametrize("name,prefix", [("resume", "through"), ("resume-reply", "after")])
@pytest.mark.parametrize(
    "sequence,sha,valid",
    [
        (0, None, True),
        (1, SHA, True),
        (0, SHA, False),
        (1, None, False),
        (True, SHA, False),
        (-1, None, False),
        (1, "A" * 64, False),
    ],
)
def test_resume_cursor(messages, name, prefix, sequence, sha, valid):
    spec = messages[name]
    p = {**spec[3], f"{prefix}-sequence": sequence, f"{prefix}-receipt-sha256": sha}
    if valid:
        parse(spec, p, capability="drain")
    else:
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, p)


def test_historical_receipt_is_data_under_new_channel(messages):
    receipt = parse(messages["receipt"], capability="drain").receipt
    assert receipt.identity.node_epoch == "old" and receipt.identity.connection_generation == 1
    for state in ("prepared", "effect-intent", "native-accepted"):
        parse(
            messages["receipt"],
            {
                **messages["receipt"][3],
                "receipt": {
                    **messages["receipt"][3]["receipt"],
                    "state": state,
                    "output-sha256": None,
                },
            },
        )
    for update in (
        {"state": "unknown"},
        {"receipt-sequence": True},
        {"extra": 1},
        {"output-sha256": None},
    ):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(
                messages["receipt"],
                {
                    **messages["receipt"][3],
                    "receipt": {**messages["receipt"][3]["receipt"], **update},
                },
            )
    old = receipt.identity
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(messages["authorize"], {"identity": old.to_mapping()})
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(
            messages["receipt"],
            {
                **messages["receipt"][3],
                "receipt": {
                    **messages["receipt"][3]["receipt"],
                    "identity": replace(old, node_id="other").to_mapping(),
                },
            },
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"data": "cHJpdmF0ZSBjaHVuaw==\n"},
        {"data": "Zh=="},
        {"data": "_w=="},
        {"data": "é"},
        {"data": "Zg"},
        {"data": "!!!!"},
        {"data": ""},
        {"offset": True},
        {"offset": -1},
        {"offset": 1},
        {"total-bytes": True},
        {"total-bytes": 2**21},
        {"eof": 1},
        {"eof": False},
        {"artifact-kind": "unknown"},
        {"artifact-kind": {}},
        {"artifact-sha256": "f"},
    ],
)
def test_chunk_adversarial(messages, updates):
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(messages["chunk"], {**messages["chunk"][3], **updates})


@pytest.mark.parametrize("kind", [None, "native-plaintext", "worker-terminal-result"])
def test_artifact_kinds_remain_untrusted_bytes_and_empty_is_valid(messages, kind):
    spec = messages["chunk"]
    result = parse(spec, {**spec[3], "artifact-kind": kind})
    assert type(result) is ArtifactChunk and result.data == b"private chunk"
    empty = parse(spec, {**spec[3], "data": "", "offset": 0, "total-bytes": 0, "eof": True})
    assert empty.data == b""


def test_artifact_chunk_bounds_and_progress(messages):
    spec = messages["chunk"]
    for count in (MAX_CHUNK_BYTES, MAX_CHUNK_BYTES + 1):
        p = {**spec[3], "data": base64.b64encode(b"x" * count).decode(), "total-bytes": count}
        if count == MAX_CHUNK_BYTES:
            assert len(parse(spec, p).data) == count
        else:
            with pytest.raises(Exception, match="VAL-AGND-001"):
                parse(spec, p)
    p = {**spec[3], "offset": 5, "total-bytes": 30, "eof": False}
    assert parse(spec, p).offset == 5
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, max_artifact_bytes=12)
    for updates in (
        {"offset": True},
        {"limit": 0},
        {"limit": MAX_CHUNK_BYTES + 1},
        {"offset": 2**21},
    ):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(messages["get"], {**messages["get"][3], **updates})


@pytest.mark.parametrize("name", ["receipt", "resume", "resume-reply", "ack"])
def test_log_ids_and_ack_schema(messages, name):
    for log in ("notuuid", LOG.upper(), LOG.replace("-4000-", "-1000-"), None):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(messages[name], {**messages[name][3], "log-incarnation-id": log})
    if name == "ack":
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(
                messages[name],
                {**messages[name][3], "through-sequence": 0, "through-receipt-sha256": None},
            )


def test_invalid_channel_options_control_types_and_replay_boundary(messages):
    spec = messages["prepare"]
    for opts in (
        {"role": "sender"},
        {"capability": "unknown"},
        {"max_artifact_bytes": True},
        {"current_connection": replace(C, node_epoch="unbound")},
        {"current_connection": replace(C, connection_generation=True)},
    ):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, **opts)
    for value in (True, 1, 3, None):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse(spec, {**spec[3], "connection-generation": value})
    for t in ("heartbeat", "hello", "revoke", "error"):
        with pytest.raises(Exception, match="VAL-AGND-001"):
            parse_work_frame(
                frame(spec, type=t),
                role="node",
                current_connection=C,
                capability="active",
                max_artifact_bytes=1,
            )
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "kind": {}})
    # Stateless decode never advances a cursor, mints authorization or ACKs ACKs.
    assert parse(messages["ack"]) == parse(messages["ack"])
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], "kind": "not-a-variant"})


def test_frame_byte_bound_precedes_work_parsing(messages):
    with pytest.raises(Exception, match="VAL-AGND-001"):
        frame(messages["prepare"], {**messages["prepare"][3], "raw-prompt": "x" * 2**20})


@pytest.mark.parametrize("sequence", [True, 0, -1, "1"])
def test_frame_sequence_is_not_boolean_or_nonpositive(messages, sequence):
    with pytest.raises(Exception, match="VAL-AGND-001"):
        frame(messages["receipt"], sequence=sequence)


@pytest.mark.parametrize("name", ["prepare", "prepared"])
def test_nested_binding_bad_scope_and_private_manifest_rejected(messages, name):
    spec = messages[name]
    key = "binding" if name == "prepare" else "attestation"
    nested = dict(spec[3][key])
    if name == "prepared":
        nested["binding"] = {**nested["binding"], "node-epoch": "old"}
    else:
        nested["node-epoch"] = "old"
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], key: nested})
    with pytest.raises(Exception, match="VAL-AGND-001"):
        parse(spec, {**spec[3], key: {**spec[3][key], "provider-manifest": "private"}})
