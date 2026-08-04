"""Agent Execution Gateway request/result contract and persisted state store.

Owns the gateway's own record shape and lifecycle — deliberately not built on
agent_jobs.records.JobRecord (packet/workflow-profile/approvals/review-policy
do not fit a gateway request; see AG07 notes for the reuse-vs-parallel
decision). Reuses only the generic, already-shared primitives: atomic JSON
persistence (foundation.io), schema validation (foundation.contracts.schema_registry,
same "<stem>.schema.json" convention as job-record), and the workflow transition
engine (foundation.workflow) driven by this component's own workflows.yaml.

SH02: records now carry ExecutionManifest fields (manifest_id, context_fingerprint,
prompt_digest). The raw prompt_body is NEVER persisted — only its digest survives.
The in-memory record dict may temporarily carry prompt-body for dispatch use, but
write_record redacts it before persistence.

This is a package split (SH18): _shared (constants), _admission (idempotency + admit),
_records (CRUD + validation), _transitions (state-change operations). All symbols
are re-exported here so existing ``import agents_gateway_store as store`` callers
stay unchanged.
"""

from audiagentic.components.agents.gateway.store._admission import (
    _intent_digest,
    active_work_path,
    admit_record,
    clear_active_work,
    generate_request_id,
    hash_idempotency_key,
    record_active_work,
)
from audiagentic.components.agents.gateway.store._records import (
    _redact_error,
    build_record,
    latest_transition_projection,
    list_records,
    project_public_status,
    read_public_status,
    read_record,
    write_record,
)
from audiagentic.components.agents.gateway.store._shared import (
    ACTIVE_WORK_DIR,
    TERMINAL_STATES,
    record_gateway_timeline,
)
from audiagentic.components.agents.gateway.store._transitions import (
    CANCEL_ACK_ACTORS,
    acknowledge_cancel,
    append_attempt,
    append_owned_attempt,
    cancel_queued_or_mark_requested,
    claim_dispatch,
    link_replay,
    mark_cancel_requested,
    release_stale_claim,
    start_attempt,
    start_owned_attempt,
    transition_owned_terminal,
    transition_record,
    transition_recovered_terminal,
    update_owned_running_session,
)

__all__ = [
    # _shared
    "ACTIVE_WORK_DIR",
    "TERMINAL_STATES",
    # _admission
    "_intent_digest",
    "active_work_path",
    "admit_record",
    "clear_active_work",
    "generate_request_id",
    "hash_idempotency_key",
    "record_active_work",
    "record_gateway_timeline",
    # _records
    "_redact_error",
    "build_record",
    "latest_transition_projection",
    "list_records",
    "project_public_status",
    "read_public_status",
    "read_record",
    "write_record",
    # _transitions
    "CANCEL_ACK_ACTORS",
    "acknowledge_cancel",
    "append_attempt",
    "append_owned_attempt",
    "cancel_queued_or_mark_requested",
    "claim_dispatch",
    "link_replay",
    "mark_cancel_requested",
    "release_stale_claim",
    "start_attempt",
    "start_owned_attempt",
    "transition_owned_terminal",
    "transition_record",
    "transition_recovered_terminal",
    "update_owned_running_session",
]
