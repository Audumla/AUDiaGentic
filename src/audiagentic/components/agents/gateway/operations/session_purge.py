"""SESSION_PURGE executor: policy-driven, gateway-local session-lineage deletion (SH32-C).

Eligibility, the claim, the recorded plan and the deletion all live in ``session/purge_engine`` and
``session/purge_eligibility``; this executor only selects sessions, holds the operation to the machine
policy snapshot taken at creation, and reports bounded per-session dispositions (``purged``,
``blocked``, ``unchanged``; never payloads). A replay of the same operation resumes any session it had
already begun deleting. Remote provider conversations are never touched.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .archive import _root
from .retention_policy import load_retention_policy, policy_matches

SCOPE_NOTE = "gateway-local session lineage only; remote provider conversations are never touched"
MAX_REPORTED_DISPOSITIONS = 200


def _session_ids(operation: Mapping[str, Any]) -> list[str] | None:
    scope = operation.get("scope")
    raw = scope.get("session-ids") if isinstance(scope, Mapping) else None
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw or any(not isinstance(x, str) or not x for x in raw):
        raise AudiaGenticError("VAL-AGM-008", "agents", "gateway operation session-ids must be a non-empty list", {})
    return list(dict.fromkeys(raw))


class GatewaySessionPurgeExecutor:
    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        from audiagentic.components.agents.gateway.session import sessions_store
        from audiagentic.components.agents.gateway.session.purge_eligibility import session_purge_report
        from audiagentic.components.agents.gateway.session.purge_engine import purge_session_under_policy

        root = _root(operation)
        scope = operation.get("scope")
        snapshot = scope.get("retention-policy") if isinstance(scope, Mapping) else None
        policy = load_retention_policy()
        explicit = _session_ids(operation)
        if not policy.available or not policy.session_purge_enabled or not isinstance(snapshot, dict) \
                or not policy_matches(snapshot):
            return {"purged": 0, "blocked": len(explicit or []), "unchanged": 0,
                    "reason": "SESSION_PURGE_POLICY_UNAVAILABLE", "scope": SCOPE_NOTE}
        operation_id = str(operation.get("operation-id", ""))
        truncated = False
        if explicit is None:
            # Sessions this operation already began deleting come first (a replay resumes them); then
            # whatever is eligible now. Both are bounded by the policy's batch size.
            resuming = [
                str(record["session-id"]) for record in sessions_store.list_session_records(root)
                if (record.get("retention-claim") or {}).get("operation-id") == operation_id
                and (record.get("retention-claim") or {}).get("stage") == "deleting"
            ]
            candidates = list(dict.fromkeys([*resuming, *session_purge_report(root, policy=policy)["eligible"]]))
        else:
            candidates = explicit
        if len(candidates) > policy.max_batch_size:
            if explicit is not None:
                return {"purged": 0, "blocked": len(explicit), "unchanged": 0,
                        "reason": "SESSION_PURGE_BATCH_LIMIT", "scope": SCOPE_NOTE}
            candidates, truncated = candidates[: policy.max_batch_size], True
        counts = {"purged": 0, "blocked": 0, "unchanged": 0}
        dispositions: list[dict[str, Any]] = []
        for session_id in candidates:
            outcome = purge_session_under_policy(root, session_id, operation_id=operation_id, policy=policy)
            counts[outcome["outcome"]] += 1
            if len(dispositions) < MAX_REPORTED_DISPOSITIONS:
                dispositions.append(outcome)
        return {**counts, "dispositions": dispositions, "truncated": truncated,
                "policy-id": policy.policy_id, "policy-digest": policy.digest, "scope": SCOPE_NOTE}


__all__ = ["GatewaySessionPurgeExecutor"]
