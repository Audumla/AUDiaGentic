"""Private worker-terminal output artifact, not serializable worker proof.

The receipt digest commits these canonical bytes. Parsers verify exact bytes and
command correlation before extracting text; a historical plaintext native output
is never interpreted as this envelope. Root/process/native references stay local.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.digest import is_sha256_hex

from .contracts import (
    CommandIdentity,
    _constant,
    _identifier,
    _integer,
    _pairs,
    canonical_json,
    conflict,
    invalid,
)

_MEDIA_TYPES = frozenset(
    {"text/plain", "text/markdown", "text/plain; charset=utf-8", "text/markdown; charset=utf-8"}
)


def _sha(value: Any) -> str:
    if not is_sha256_hex(value):
        raise invalid(1, "Worker terminal metadata requires lowercase SHA256")
    return value


def _model(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise invalid(1, "Worker terminal model identity is invalid")
    return value


@dataclass(frozen=True)
class WorkerTerminalOutput:
    identity: CommandIdentity
    attestation_sha256: str
    private_bundle_sha256: str
    worker_identity_sha256: str
    provider_id: str
    model_id: str
    worker_id: str
    attempt_epoch: int
    text: str = field(repr=False)
    media_type: str = "text/plain; charset=utf-8"

    def __post_init__(self):
        if type(self.identity) is not CommandIdentity:
            raise invalid(1, "Worker terminal artifact requires typed command identity")
        for digest in (
            self.attestation_sha256,
            self.private_bundle_sha256,
            self.worker_identity_sha256,
        ):
            _sha(digest)
        _identifier(self.provider_id)
        _identifier(self.worker_id)
        _model(self.model_id)
        _integer(self.attempt_epoch)
        if not isinstance(self.text, str):
            raise invalid(1, "Worker terminal output must be text")
        try:
            self.text.encode("utf-8")
        except UnicodeError:
            raise invalid(1, "Worker terminal output must be valid UTF-8") from None
        if not isinstance(self.media_type, str) or self.media_type not in _MEDIA_TYPES:
            raise invalid(1, "Worker terminal output media type is unsupported")

    def to_bytes(self) -> bytes:
        return canonical_json(
            {
                "version": 1,
                "kind": "worker-terminal-result",
                "identity": self.identity.to_mapping(),
                "attestation-sha256": self.attestation_sha256,
                "private-bundle-sha256": self.private_bundle_sha256,
                "worker-identity-sha256": self.worker_identity_sha256,
                "outcome": {
                    "status": "success",
                    "provider-id": self.provider_id,
                    "model-id": self.model_id,
                    "worker-id": self.worker_id,
                    "attempt-epoch": self.attempt_epoch,
                },
                "output": {"text": self.text, "media_type": self.media_type},
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


def parse_worker_terminal_output(
    raw: bytes, *, expected_identity: CommandIdentity, expected_sha256: str
) -> WorkerTerminalOutput:
    """Verify receipt-owned artifact hash, exact schema and canonical bytes.

    Call only with a trusted worker artifact-kind descriptor, never by guessing
    from JSON-looking provider text. This extracts verified storage content; it
    does NOT mint VerifiedWorkerTerminal
    or authorize a new terminal transition from peer JSON.
    """
    _sha(expected_sha256)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise conflict(1, "Worker terminal artifact hash does not match its receipt")
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise invalid(1, "Worker terminal artifact is invalid UTF-8 JSON") from None
    fields = {
        "version",
        "kind",
        "identity",
        "attestation-sha256",
        "private-bundle-sha256",
        "worker-identity-sha256",
        "outcome",
        "output",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise invalid(1, "Worker terminal artifact fields must match exactly")
    outcome, output = payload["outcome"], payload["output"]
    if (
        type(payload["version"]) is not int
        or payload["version"] != 1
        or payload["kind"] != "worker-terminal-result"
        or not isinstance(outcome, dict)
        or set(outcome) != {"status", "provider-id", "model-id", "worker-id", "attempt-epoch"}
        or outcome["status"] != "success"
        or not isinstance(output, dict)
        or set(output) != {"text", "media_type"}
    ):
        raise invalid(1, "Worker terminal artifact kind or outcome is unsupported")
    identity = CommandIdentity.from_mapping(payload["identity"])
    if type(expected_identity) is not CommandIdentity or identity != expected_identity:
        raise conflict(1, "Worker terminal artifact belongs to another command")
    result = WorkerTerminalOutput(
        identity,
        payload["attestation-sha256"],
        payload["private-bundle-sha256"],
        payload["worker-identity-sha256"],
        outcome["provider-id"],
        outcome["model-id"],
        outcome["worker-id"],
        outcome["attempt-epoch"],
        output["text"],
        output["media_type"],
    )
    if result.to_bytes() != raw:
        raise conflict(1, "Worker terminal artifact is not canonical JSON")
    return result


def build_worker_terminal_output(
    identity, *, preparation, proof, stored_payload: bytes
) -> WorkerTerminalOutput:
    """Correlate locally minted worker proof with the exact durable preparation.

    No peer JSON/WorkerResultEnvelope is a proof. The private bundle is consumed
    only for correlation; roots, request packets and process refs aren't exported.
    """
    from audiagentic.components.agents.contracts.execution_context import (
        MANIFEST_SCHEMA_VERSION,
        ExecutionManifest,
        canonicalize_project_root,
        compute_context_fingerprint,
        compute_prompt_digest,
    )
    from audiagentic.components.agents.contracts.worker_protocol import (
        WorkerExecuteEnvelope,
        WorkerExecutionIdentity,
    )
    from audiagentic.components.agents.gateway.queue.worker import VerifiedWorkerTerminal

    from .preparation import RetainedNodePreparation, validate_final_command_payload

    if (
        type(preparation) is not RetainedNodePreparation
        or type(proof) is not VerifiedWorkerTerminal
    ):
        raise invalid(
            1, "Worker terminal requires retained preparation and trusted local worker proof"
        )
    preparation.__post_init__()
    attestation = preparation.attestation
    try:
        payload = json.loads(
            stored_payload.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        bundle = json.loads(
            preparation._provider_manifest.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except (AttributeError, ValueError, UnicodeError, RecursionError):
        raise invalid(1, "Stored worker preparation is invalid canonical JSON") from None
    if canonical_json(payload) != stored_payload:
        raise conflict(1, "Stored final command payload is not canonical")
    validate_final_command_payload(payload, identity, accepted_attestation=attestation)
    if (
        not isinstance(bundle, dict)
        or set(bundle)
        != {"version", "kind", "worker-identity", "execution-manifest", "provider-request"}
        or type(bundle["version"]) is not int
        or bundle["version"] != 1
        or bundle["kind"] != "node-worker-preparation"
        or canonical_json(bundle) != preparation._provider_manifest
    ):
        raise invalid(1, "Private worker preparation bundle schema is unsupported")
    try:
        expected = WorkerExecutionIdentity.from_mapping(
            bundle["worker-identity"], tier_field="provider-isolation-tier"
        )
        request = WorkerExecuteEnvelope(expected, bundle["provider-request"]).execution_request
        manifest = ExecutionManifest.from_mapping(bundle["execution-manifest"])
    except (KeyError, TypeError, ValueError):
        raise invalid(1, "Private worker preparation bundle is incomplete") from None
    if (
        canonical_json(expected.to_mapping(tier_field="provider-isolation-tier"))
        != canonical_json(bundle["worker-identity"])
        or canonical_json(manifest.to_mapping()) != canonical_json(bundle["execution-manifest"])
        or type(bundle["execution-manifest"]["schema_version"]) is not int
        or bundle["execution-manifest"]["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
        raise invalid(1, "Private worker identities require exact canonical contracts")
    packet = request["packet-data"]
    model = attestation.model_id
    if (
        proof.worker_exited is not True
        or proof.identity != expected
        or proof.process.working_directory != expected.project_root
        or expected.worker_id != attestation.worker_id
        or expected.attempt_epoch != attestation.attempt_epoch
        or expected.manifest_id != attestation.manifest_id
        or expected.context_fingerprint != attestation.context_fingerprint
        or expected.provider_isolation_tier != "full-isolation"
        or manifest.manifest_id != expected.manifest_id
        or manifest.context_fingerprint != expected.context_fingerprint
        or compute_context_fingerprint(manifest.identity) != expected.context_fingerprint
        or manifest.request_id != identity.request_id
        or manifest.identity.project_root
        != canonicalize_project_root(expected.project_root).fingerprint
        or manifest.identity.component_profile != expected.component_profile
        or manifest.identity.provider_isolation_tier != expected.provider_isolation_tier
        or manifest.identity.execution_profile_id != identity.execution_profile_id
        or manifest.identity.provider_id != attestation.provider_id
        or manifest.identity.agent_runtime_digest != attestation.runtime_digest
        or manifest.prompt_digest != compute_prompt_digest(payload["raw-prompt"])
        or not isinstance(model, str)
        or not model
        or manifest.identity.model_id != model
        or request["model-id"] != model
        or request["model-alias"] != attestation.model_alias
        or request["provider-id"] != attestation.provider_id
        or type(request["attempt-epoch"]) is not int
        or not isinstance(packet, dict)
        or packet.get("request-id") != identity.request_id
        or packet.get("working-root") != expected.project_root
        or packet.get("prompt-body") != preparation._rendered_prompt
    ):
        raise conflict(1, "Worker terminal identity does not match exact retained preparation")
    result = proof.result
    if (
        result.provider_id != attestation.provider_id
        or result.worker_id != attestation.worker_id
        or type(result.attempt_epoch) is not int
        or result.attempt_epoch != attestation.attempt_epoch
        or result.model_id != model
    ):
        raise conflict(
            1, "Worker terminal outcome differs from prepared provider, model or attempt"
        )
    text = result.result_data.get("output")
    if not isinstance(text, str):
        raise invalid(1, "Verified worker result requires a standard text output field")
    media_type = result.result_data.get("final_media_type", "text/plain; charset=utf-8")
    return WorkerTerminalOutput(
        identity,
        attestation.digest,
        attestation.provider_manifest_sha256,
        hashlib.sha256(
            canonical_json(expected.to_mapping(tier_field="provider-isolation-tier"))
        ).hexdigest(),
        result.provider_id,
        result.model_id,
        result.worker_id,
        result.attempt_epoch,
        text,
        media_type,
    )
