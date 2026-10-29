"""Pure work wire data; parsing confers no acceptance, authorization or worker proof.

Role means receiving role. Channel authentication, replay ordering, pending
challenge/reply correlation and cursor authority remain caller responsibilities.
Effect messages alone derive generation from identity (the existing schema).
Historical receipt/artifact identities retain their original command scope while
frame headers and resume/ACK metadata always belong to the current channel.
Runtime must omit raw idempotency keys and send only admitted sanitized metadata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from .admission_contract import SourceWorkspaceIdentity
from .authority import NodeConnectionIdentity
from .contracts import CommandIdentity, Frame, _identifier, _integer, canonical_json, invalid
from .preparation import PreparationAttestation, PreparationBinding, PromptSemanticIdentity
from .receipts import Receipt, _digest, _log_id

MAX_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True, kw_only=True)
class WorkMessage:
    message_id: str
    sequence: int


@dataclass(frozen=True, kw_only=True)
class PrepareWork(WorkMessage):
    binding: PreparationBinding
    semantic: PromptSemanticIdentity
    agent_id: str
    worker_id: str
    attempt_epoch: int
    raw_prompt: str = field(repr=False)
    source_workspace: SourceWorkspaceIdentity
    caller_root: str = field(repr=False)
    source: str | None
    metadata: Mapping = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class PreparedReply(WorkMessage):
    in_reply_to: str
    attestation: PreparationAttestation


@dataclass(frozen=True, kw_only=True)
class PreparationRejected(WorkMessage):
    in_reply_to: str
    code: str


@dataclass(frozen=True, kw_only=True)
class CommandWork(WorkMessage):
    identity: CommandIdentity
    command_payload: Mapping = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class EffectAuthorize(WorkMessage):
    identity: CommandIdentity


@dataclass(frozen=True, kw_only=True)
class EffectAuthorized(EffectAuthorize):
    authorization_request_id: str
    authorization_id: str


@dataclass(frozen=True, kw_only=True)
class EffectDenied(EffectAuthorize):
    authorization_request_id: str
    code: str


@dataclass(frozen=True, kw_only=True)
class ReceiptWork(WorkMessage):
    log_incarnation_id: str
    receipt: Receipt


@dataclass(frozen=True, kw_only=True)
class ReceiptResume(WorkMessage):
    log_incarnation_id: str
    through_sequence: int
    through_receipt_sha256: str | None


@dataclass(frozen=True, kw_only=True)
class ReceiptReady(WorkMessage):
    log_incarnation_id: str
    through_sequence: int
    through_receipt_sha256: str | None


@dataclass(frozen=True, kw_only=True)
class ReceiptResumeReply(WorkMessage):
    in_reply_to: str
    log_incarnation_id: str
    after_sequence: int
    after_receipt_sha256: str | None


@dataclass(frozen=True, kw_only=True)
class ReceiptAckWork(WorkMessage):
    server_id: str
    log_incarnation_id: str
    through_sequence: int
    through_receipt_sha256: str


@dataclass(frozen=True, kw_only=True)
class ArtifactGet(WorkMessage):
    identity: CommandIdentity
    artifact_sha256: str
    offset: int
    limit: int


@dataclass(frozen=True, kw_only=True)
class ArtifactChunk(WorkMessage):
    in_reply_to: str
    identity: CommandIdentity
    artifact_sha256: str
    artifact_kind: str | None
    offset: int
    total_bytes: int
    data: bytes = field(repr=False)
    eof: bool


WorkFrame: TypeAlias = (
    PrepareWork
    | PreparedReply
    | PreparationRejected
    | CommandWork
    | EffectAuthorize
    | EffectAuthorized
    | EffectDenied
    | ReceiptWork
    | ReceiptResume
    | ReceiptReady
    | ReceiptResumeReply
    | ReceiptAckWork
    | ArtifactGet
    | ArtifactChunk
)


def _exact(value, names):
    if not isinstance(value, Mapping) or set(value) != set(names.split()):
        raise invalid(1, "Work message fields must match exactly")
    return value


def _text(value):
    if not isinstance(value, str):
        raise invalid(1, "Work text must be a string")
    return value


def _scope(value, current, *, historical=False):
    if value.node_id != current.node_id or (
        not historical
        and (value.node_epoch, value.gateway_owner_epoch, value.connection_generation)
        != (current.node_epoch, current.gateway_owner_epoch, current.connection_generation)
    ):
        raise invalid(1, "Work identity does not match current channel")
    return value


def _cursor(sequence, digest, *, minimum=0):
    _integer(sequence, minimum)
    if sequence == 0:
        if digest is not None:
            raise invalid(1, "Empty receipt cursor requires null digest")
    else:
        _digest(digest)


class _Wire:
    """One frame under parse: its payload plus the trusted channel it must match."""

    def __init__(self, frame, channel, max_artifact_bytes):
        self.frame, self.p, self.c, self.max_artifact_bytes = frame, frame.payload, channel, max_artifact_bytes
        self.effect = frame.type.startswith("effect-")
        self.common = dict(message_id=frame.message_id, sequence=frame.sequence)

    def exact(self, names):
        return _exact(self.p, names + ("" if self.effect else " connection-generation"))

    def identity(self, *, historical=False):
        return _scope(CommandIdentity.from_mapping(self.p["identity"]), self.c, historical=historical)


def _parse_prepare(w):
    p, c = w.p, w.c
    w.exact(
        "kind binding semantic agent-id worker-id attempt-epoch raw-prompt source metadata source-workspace caller-root"
    )
    metadata = p["metadata"]
    if (
        not isinstance(metadata, Mapping)
        or set(metadata) - {"schema_version", "correlation_id"}
        or any(v is not None and type(v) not in (str, int, float, bool) for v in metadata.values())
    ):
        raise invalid(1, "Work metadata must contain only admitted primitive fields")
    source = p["source"]
    if source is not None:
        _text(source)
    caller_root = p["caller-root"]
    if (not isinstance(caller_root, str) or not caller_root or len(caller_root) > 32768
            or any(ord(ch) < 32 for ch in caller_root)):
        raise invalid(1, "Prepare requires a bounded private caller locator")
    source_workspace = SourceWorkspaceIdentity.from_mapping(p["source-workspace"])
    binding = _scope(PreparationBinding.from_mapping(p["binding"]), c)
    if (source_workspace.source_node_id != binding.node_id
            or source_workspace.workspace_id != binding.workspace_id
            or source_workspace.access_mode != "read-write"):
        raise invalid(1, "Prepare source does not match same-node writable binding")
    return PrepareWork(
        **w.common,
        binding=binding,
        semantic=PromptSemanticIdentity.from_mapping(p["semantic"]),
        agent_id=_identifier(p["agent-id"]),
        worker_id=_identifier(p["worker-id"]),
        attempt_epoch=_integer(p["attempt-epoch"]),
        raw_prompt=_text(p["raw-prompt"]),
        source_workspace=source_workspace,
        caller_root=caller_root,
        source=source,
        metadata=metadata,
    )


def _parse_prepared(w):
    w.exact("kind in-reply-to attestation")
    attestation = PreparationAttestation.from_mapping(w.p["attestation"])
    _scope(attestation.binding, w.c)
    return PreparedReply(**w.common, in_reply_to=_identifier(w.p["in-reply-to"]), attestation=attestation)


def _parse_prepare_rejected(w):
    w.exact("kind in-reply-to code")
    return PreparationRejected(
        **w.common, in_reply_to=_identifier(w.p["in-reply-to"]), code=_identifier(w.p["code"])
    )


def _parse_command(w):
    w.exact("identity payload")
    command = w.identity()
    payload = _exact(
        w.p["payload"],
        "semantic attestation raw-prompt preparation-challenge preparation-request-id",
    )
    PromptSemanticIdentity.from_mapping(payload["semantic"])
    _scope(PreparationAttestation.from_mapping(payload["attestation"]).binding, w.c)
    _text(payload["raw-prompt"])
    _identifier(payload["preparation-challenge"])
    _identifier(payload["preparation-request-id"])
    if hashlib.sha256(canonical_json(payload)).hexdigest() != command.payload_sha256:
        raise invalid(1, "Command payload digest mismatch")
    return CommandWork(**w.common, identity=command, command_payload=payload)


def _parse_effect_authorize(w):
    w.exact("identity")
    return EffectAuthorize(**w.common, identity=w.identity())


def _parse_effect_authorized(w):
    w.exact("identity authorization-request-id authorization-id authorized")
    if w.p["authorized"] is not True:
        raise invalid(1, "Effect authorized must be true")
    return EffectAuthorized(
        **w.common,
        identity=w.identity(),
        authorization_request_id=_identifier(w.p["authorization-request-id"]),
        authorization_id=_identifier(w.p["authorization-id"]),
    )


def _parse_effect_denied(w):
    w.exact("identity authorization-request-id code")
    return EffectDenied(
        **w.common,
        identity=w.identity(),
        authorization_request_id=_identifier(w.p["authorization-request-id"]),
        code=_identifier(w.p["code"]),
    )


def _parse_receipt(w):
    p = w.p
    w.exact("log-incarnation-id receipt")
    r = _exact(p["receipt"], "identity state receipt-sequence output-sha256")
    i = _scope(CommandIdentity.from_mapping(r["identity"]), w.c, historical=True)
    if r["state"] not in ("prepared", "effect-intent", "native-accepted", "terminal"):
        raise invalid(1, "Invalid receipt stage")
    if r["state"] == "terminal":
        _digest(r["output-sha256"])
    elif r["output-sha256"] is not None:
        raise invalid(1, "Nonterminal receipt cannot carry output")
    return ReceiptWork(
        **w.common,
        log_incarnation_id=_log_id(p["log-incarnation-id"]),
        receipt=Receipt(i, r["state"], _integer(r["receipt-sequence"]), r["output-sha256"]),
    )


def _parse_receipt_ready(w):
    p = w.p
    w.exact("kind log-incarnation-id through-sequence through-receipt-sha256")
    _cursor(p["through-sequence"], p["through-receipt-sha256"])
    return ReceiptReady(
        **w.common,
        log_incarnation_id=_log_id(p["log-incarnation-id"]),
        through_sequence=p["through-sequence"],
        through_receipt_sha256=p["through-receipt-sha256"],
    )


def _parse_receipt_resume(w):
    p = w.p
    reply = w.frame.type == "reconcile-result"
    prefix = "after" if reply else "through"
    w.exact(
        f"kind log-incarnation-id {prefix}-sequence {prefix}-receipt-sha256"
        + (" in-reply-to" if reply else "")
    )
    sequence, digest = p[f"{prefix}-sequence"], p[f"{prefix}-receipt-sha256"]
    _cursor(sequence, digest)
    log = _log_id(p["log-incarnation-id"])
    if reply:
        return ReceiptResumeReply(
            **w.common,
            in_reply_to=_identifier(p["in-reply-to"]),
            log_incarnation_id=log,
            after_sequence=sequence,
            after_receipt_sha256=digest,
        )
    return ReceiptResume(
        **w.common, log_incarnation_id=log, through_sequence=sequence, through_receipt_sha256=digest
    )


def _parse_receipt_ack(w):
    p = w.p
    w.exact("kind server-id log-incarnation-id through-sequence through-receipt-sha256")
    _cursor(p["through-sequence"], p["through-receipt-sha256"], minimum=1)
    return ReceiptAckWork(
        **w.common,
        server_id=_identifier(p["server-id"]),
        log_incarnation_id=_log_id(p["log-incarnation-id"]),
        through_sequence=p["through-sequence"],
        through_receipt_sha256=p["through-receipt-sha256"],
    )


def _parse_artifact_get(w):
    p = w.p
    w.exact("kind identity artifact-sha256 offset limit")
    offset, limit = _integer(p["offset"], 0), _integer(p["limit"])
    if offset > w.max_artifact_bytes or limit > MAX_CHUNK_BYTES:
        raise invalid(1, "Artifact request exceeds trusted bounds")
    return ArtifactGet(
        **w.common,
        identity=w.identity(historical=True),
        artifact_sha256=_digest(p["artifact-sha256"]),
        offset=offset,
        limit=limit,
    )


def _decode_chunk(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_CHUNK_BYTES + 2) // 3):
        raise invalid(1, "Artifact chunk exceeds encoded bound")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise invalid(1, "Artifact chunk requires strict base64") from None
    if base64.b64encode(data).decode("ascii") != encoded or len(data) > MAX_CHUNK_BYTES:
        raise invalid(1, "Artifact chunk requires bounded canonical base64")
    return data


def _parse_artifact_chunk(w):
    p = w.p
    w.exact("kind in-reply-to identity artifact-sha256 artifact-kind offset total-bytes data eof")
    offset, total = _integer(p["offset"], 0), _integer(p["total-bytes"], 0)
    data = _decode_chunk(p["data"])
    end = offset + len(data)
    if (
        total > w.max_artifact_bytes
        or end > total
        or type(p["eof"]) is not bool
        or p["eof"] != (end == total)
        or (total > 0 and not data)
    ):
        raise invalid(1, "Artifact chunk progress/EOF does not match trusted bounds")
    if p["artifact-kind"] not in (None, "worker-terminal-result", "native-plaintext"):
        raise invalid(1, "Unknown artifact kind")
    return ArtifactChunk(
        **w.common,
        in_reply_to=_identifier(p["in-reply-to"]),
        identity=w.identity(historical=True),
        artifact_sha256=_digest(p["artifact-sha256"]),
        artifact_kind=p["artifact-kind"],
        offset=offset,
        total_bytes=total,
        data=data,
        eof=p["eof"],
    )


# (frame type, payload kind) -> (receiving role, allowed while draining, parser)
_ROUTES = {
    ("reconcile", "prepare"): ("node", False, _parse_prepare),
    ("reconcile-result", "prepared"): ("gateway", False, _parse_prepared),
    ("reconcile-result", "prepare-rejected"): ("gateway", False, _parse_prepare_rejected),
    ("command", None): ("node", False, _parse_command),
    ("effect-authorize", None): ("gateway", False, _parse_effect_authorize),
    ("effect-authorized", None): ("node", False, _parse_effect_authorized),
    ("effect-denied", None): ("node", False, _parse_effect_denied),
    ("receipt", None): ("gateway", True, _parse_receipt),
    ("reconcile", "receipt-resume"): ("gateway", True, _parse_receipt_resume),
    ("reconcile", "receipt-ready"): ("gateway", False, _parse_receipt_ready),
    ("reconcile-result", "receipt-resume"): ("node", True, _parse_receipt_resume),
    ("reconcile-result", "receipt-ack"): ("node", True, _parse_receipt_ack),
    ("reconcile", "artifact-get"): ("node", True, _parse_artifact_get),
    ("reconcile-result", "artifact-chunk"): ("gateway", True, _parse_artifact_chunk),
}


def parse_work_frame(
    frame: Frame,
    *,
    role: str,
    current_connection: NodeConnectionIdentity,
    capability: str,
    max_artifact_bytes: int,
) -> WorkFrame:
    """Decode untrusted wire data only; no I/O or stateful replay/authority checks.

    Caller must validate prepared replies against its retained binding/challenge,
    final commands against its separately accepted attestation, effect replies
    against the actual pending request, and artifacts against durable provenance.
    Neither a worker artifact kind nor parsed bytes establish worker proof.
    """
    if role not in ("gateway", "node") or capability not in ("active", "drain"):
        raise invalid(1, "Unknown work receiving role or capability")
    _integer(max_artifact_bytes)
    if type(frame) is not Frame or type(current_connection) is not NodeConnectionIdentity:
        raise invalid(1, "Work parsing requires frame and trusted channel identity")
    c = current_connection
    for value in (c.node_id, c.node_epoch, c.gateway_owner_epoch):
        _identifier(value)
    _integer(c.connection_generation)
    if (
        c.node_epoch == "unbound"
        or c.gateway_owner_epoch == "unbound"
        or (frame.node_id, frame.node_epoch, frame.gateway_owner_epoch)
        != (c.node_id, c.node_epoch, c.gateway_owner_epoch)
    ):
        raise invalid(1, "Work frame is outside the current bound channel")
    kind = frame.payload.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise invalid(1, "Invalid work variant")
    route = _ROUTES.get((frame.type, kind))
    if route is None or route[0] != role or (capability == "drain" and not route[1]):
        raise invalid(1, "Work variant is not permitted for receiving role/capability")
    wire = _Wire(frame, c, max_artifact_bytes)
    if not wire.effect and _integer(frame.payload.get("connection-generation")) != c.connection_generation:
        raise invalid(1, "Work generation does not match current channel")
    return route[2](wire)
