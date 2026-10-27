"""Correlated wire bytes publish canonical text; fake preparation is explicit."""
import asyncio
import base64
from types import SimpleNamespace

import pytest
import pytest_asyncio

from audiagentic.components.agents.agents_paths import gateway_final_response_path
from audiagentic.components.agents.gateway import output, store
from audiagentic.components.agents.gateway.node import artifact_reconciliation as module
from audiagentic.components.agents.gateway.node.artifact_reconciliation import (
    NodeTerminalReconciler,
)
from audiagentic.components.agents.gateway.node.receipts import Receipt
from audiagentic.components.agents.gateway.node.terminal_output import WorkerTerminalOutput
from audiagentic.components.agents.gateway.node.work_protocol import ArtifactGet
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred

from .test_gateway_node_admission_owner import admission as admission
from .test_gateway_node_runner import case as case
from .test_gateway_node_runner import effects, invoke


@pytest_asyncio.fixture
async def transfer(case):
    await invoke(case)
    current = await effects(case)
    attestation = case.preparation.attestation
    artifact = WorkerTerminalOutput(case.commands[0].identity, attestation.digest,
        attestation.provider_manifest_sha256, "a" * 64, attestation.provider_id, attestation.model_id,
        attestation.worker_id, attestation.attempt_epoch, "Exact Markdown λ\r\n" * 30, "text/markdown")
    terminal = Receipt(artifact.identity, "terminal", 3, artifact.digest)
    record = store.apply_owned_node_receipt(case.admission.root, current["request-id"],
        receipt=terminal.public_payload(), owner_epoch="owner", worker_id=current["worker-id"],
        attempt_epoch=current["attempt-epoch"], expected_revision=current["revision"])
    state = SimpleNamespace(raw=artifact.to_bytes(), artifact=artifact, record=record, calls=[], mutate=None,
        case=case, kind="worker-terminal-result", after_reply=None)
    async def respond(frame, work):
        assert type(work) is ArtifactGet
        state.calls.append(work)
        data = state.raw[work.offset:work.offset + work.limit]
        payload = {"kind": "artifact-chunk", "in-reply-to": frame.message_id,
            "identity": work.identity.to_mapping(), "artifact-sha256": work.artifact_sha256,
            "artifact-kind": state.kind, "offset": work.offset, "total-bytes": len(state.raw),
            "data": base64.b64encode(data).decode(), "eof": work.offset + len(data) == len(state.raw)}
        if state.mutate:
            state.mutate(payload, work)
        await case.node.send_work("reconcile-result", payload)
        if state.after_reply:
            await asyncio.to_thread(state.after_reply)
    case.node_work_handler = respond
    state.reconcile = NodeTerminalReconciler(case.config, case.admission.service, case.connections,
        asyncio.get_running_loop(), chunk_bytes=128, timeout_seconds=2)
    return state


@pytest.mark.asyncio
async def test_terminal_receipt_recovers_without_cursor_replay_and_returns_exact_text(transfer, monkeypatch):
    from audiagentic.components.agents.gateway.node.checkpoints import NodeReceiptCheckpoints
    def forbidden(*args, **kwargs):
        pytest.fail("publication must not depend on a fresh receipt/cursor change")
    monkeypatch.setattr(NodeReceiptCheckpoints, "resume_cursor", forbidden)
    case = transfer.case
    result = await asyncio.to_thread(transfer.reconcile, case.admission.root, transfer.record)
    assert result["state"] == "completed"
    assert output.read_final_response(case.admission.root, result["request-id"], result["response-artifact"]) == transfer.artifact.text
    assert result["response-artifact"]["media-type"] == "text/markdown; charset=utf-8"
    assert len(transfer.calls) > 1
    assert [call.offset for call in transfer.calls] == list(range(0, len(transfer.raw), 128))
    assert len(case.commands) == len(case.prepares) == 1
    count = len(transfer.calls)
    assert (await asyncio.to_thread(transfer.reconcile, case.admission.root, result))["state"] == "completed"
    assert len(transfer.calls) == count


@pytest.mark.asyncio
async def test_existing_runner_waiter_completes_bound_request_without_second_command(transfer):
    case = transfer.case
    case.runner.waiter = transfer.reconcile
    result = await asyncio.to_thread(case.runner, case.admission.root, case.record, reconcile_only=True)
    assert result["state"] == "completed"
    assert len(case.commands) == len(case.prepares) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [None, "native-plaintext"])
async def test_unqualified_artifact_kind_never_becomes_success(transfer, kind):
    transfer.kind = kind
    with pytest.raises(RecoveryDeferred) as failure:
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert failure.value.error.details["reason-code"] == "artifact-kind-unsupported"
    assert failure.value.side_effect_state == "terminal-evidence-seen"
    assert store.read_record(transfer.case.admission.root, transfer.record["request-id"])["state"] == "running"
    assert not gateway_final_response_path(transfer.case.admission.root, transfer.record["request-id"]).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["bytes", "offset", "total", "digest", "identity", "truncated"])
async def test_corrupt_or_mismatched_transfer_preserves_original_request(transfer, fault):
    def mutate(payload, work):
        if fault == "bytes":
            data = bytearray(base64.b64decode(payload["data"]))
            data[0] ^= 1
            payload["data"] = base64.b64encode(data).decode()
        elif fault == "offset":
            payload["offset"] += 1
        elif fault == "total":
            payload["total-bytes"] += 1 if work.offset else 0
        elif fault == "digest":
            payload["artifact-sha256"] = "f" * 64
        elif fault == "identity":
            payload["identity"] = {**payload["identity"], "command-id": "other"}
        else:
            payload["data"] = base64.b64encode(base64.b64decode(payload["data"])[:-1]).decode()
    transfer.mutate = mutate
    with pytest.raises(RecoveryDeferred):
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    result = store.read_record(transfer.case.admission.root, transfer.record["request-id"])
    assert result["state"] == "running" and result["node-dispatch"] == transfer.record["node-dispatch"]
    assert len(transfer.case.commands) == 1
    assert not gateway_final_response_path(transfer.case.admission.root, result["request-id"]).exists()


@pytest.mark.asyncio
async def test_read_budget_prevents_additional_full_artifact_read(transfer):
    case = transfer.case
    transfer.reconcile = NodeTerminalReconciler(case.config, case.admission.service, case.connections,
        asyncio.get_running_loop(), max_artifact_bytes=len(transfer.raw), chunk_bytes=128,
        max_read_budget_bytes=len(transfer.raw) * 2, timeout_seconds=2)
    with pytest.raises(RecoveryDeferred) as error:
        await asyncio.to_thread(transfer.reconcile, case.admission.root, transfer.record)
    assert error.value.error.details["reason-code"] == "artifact-read-budget-exhausted"
    assert len(transfer.calls) == 2


@pytest.mark.asyncio
async def test_replacement_mid_transfer_aborts_incomplete_download(transfer):
    def replace():
        transfer.case.connections.replace("node", "new-boot", transfer.case.gateway.websocket)
    transfer.after_reply = replace
    with pytest.raises(RecoveryDeferred):
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert store.read_record(transfer.case.admission.root, transfer.record["request-id"])["state"] == "running"
    assert len(transfer.calls) == 1


@pytest.mark.asyncio
async def test_verified_complete_bytes_survive_later_connection_replacement(transfer, monkeypatch):
    publish = module.publish_owned_node_terminal
    def replaced(*args, **kwargs):
        transfer.case.connections.replace("node", "new-boot", transfer.case.gateway.websocket)
        return publish(*args, **kwargs)
    monkeypatch.setattr(module, "publish_owned_node_terminal", replaced)
    result = await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert result["state"] == "completed"
    assert result["node-dispatch"]["identity"] == transfer.record["node-dispatch"]["identity"]


@pytest.mark.asyncio
async def test_owner_change_before_publication_rejects_old_writer(transfer, monkeypatch):
    from .test_gateway_node_checkpoints import _restart
    publish = module.publish_owned_node_terminal
    def changed(*args, **kwargs):
        _restart(transfer.case.admission.service, "replacement")
        return publish(*args, **kwargs)
    monkeypatch.setattr(module, "publish_owned_node_terminal", changed)
    with pytest.raises(RecoveryDeferred) as error:
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert error.value.error.details["reason-code"] == "owner-fence-changed"
    assert store.read_record(transfer.case.admission.root, transfer.record["request-id"])["state"] == "running"


@pytest.mark.asyncio
async def test_cancellation_winner_is_preserved_after_successful_transfer(transfer, monkeypatch):
    publish = module.publish_owned_node_terminal
    def cancelled(*args, **kwargs):
        current = store.read_record(transfer.case.admission.root, transfer.record["request-id"])
        store.transition_owned_terminal(transfer.case.admission.root, current["request-id"], "cancelled",
            owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
            expected_revision=current["revision"])
        return publish(*args, **kwargs)
    monkeypatch.setattr(module, "publish_owned_node_terminal", cancelled)
    with pytest.raises(RecoveryDeferred):
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert store.read_record(transfer.case.admission.root, transfer.record["request-id"])["state"] == "cancelled"


@pytest.mark.asyncio
async def test_waiter_error_stage_survives_runner_projection(transfer):
    case = transfer.case
    case.runner.waiter = transfer.reconcile
    transfer.kind = None
    with pytest.raises(RecoveryDeferred) as failure:
        await asyncio.to_thread(case.runner, case.admission.root, case.record, reconcile_only=True)
    assert failure.value.error.details["stage"] == "artifact"
    assert failure.value.error.details["reason-code"] == "artifact-kind-unsupported"


@pytest.mark.asyncio
async def test_other_managed_service_is_rejected_before_artifact_io(transfer):
    record = store.read_record(transfer.case.admission.root, transfer.record["request-id"])
    record["dispatch-service-root"] = str(transfer.case.admission.root / "other-service")
    store.write_record(transfer.case.admission.root, record)
    with pytest.raises(RecoveryDeferred):
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert not transfer.calls


@pytest.mark.asyncio
async def test_diagnostic_sink_failures_do_not_reverse_verified_publication(transfer, monkeypatch):
    from unittest.mock import Mock

    from audiagentic.components.agents.gateway import observability as journal
    from audiagentic.components.agents.gateway.node import observability

    timeline = Mock(side_effect=OSError("private sink failure"))
    observations = Mock(side_effect=OSError("private journal failure"))
    monkeypatch.setattr(store, "record_gateway_timeline", timeline)
    monkeypatch.setattr(journal, "append_observation", observations)
    monkeypatch.setattr(observability.logger, "warning", Mock(side_effect=OSError("logger failed")))
    before = observability.node_observation_failure_count()

    result = await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)

    assert result["state"] == "completed"
    assert output.read_final_response(transfer.case.admission.root, result["request-id"],
        result["response-artifact"]) == transfer.artifact.text
    assert timeline.call_count >= 2 and observations.call_count >= 2
    assert observability.node_observation_failure_count() >= before + 4


@pytest.mark.asyncio
async def test_multichunk_transfer_uses_decreasing_remaining_deadline(transfer, monkeypatch):
    connection = transfer.case.gateway
    request = connection.request_work
    budgets = []

    async def delayed(*args, **kwargs):
        budgets.append(kwargs["timeout"])
        await asyncio.sleep(0.002)
        return await request(*args, **kwargs)

    monkeypatch.setattr(connection, "request_work", delayed)
    result = await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert result["state"] == "completed"
    assert len(budgets) > 1
    assert all(0 < later < earlier for earlier, later in zip(budgets, budgets[1:]))


@pytest.mark.asyncio
async def test_transfer_deadline_defers_without_closing_receiver_or_replaying(transfer, monkeypatch):
    connection = transfer.case.gateway
    request = connection.request_work
    transfer.reconcile.timeout = 0.02

    async def delayed(*args, **kwargs):
        await asyncio.sleep(0.04)
        return await request(*args, **kwargs)

    monkeypatch.setattr(connection, "request_work", delayed)
    with pytest.raises(RecoveryDeferred) as failure:
        await asyncio.to_thread(transfer.reconcile, transfer.case.admission.root, transfer.record)
    assert failure.value.error.details["reason-code"] == "transport-timeout"
    assert failure.value.side_effect_state == "terminal-evidence-seen"
    assert connection.close_reason is None and connection.failure is None
    assert store.read_record(transfer.case.admission.root, transfer.record["request-id"])["state"] == "running"
    assert len(transfer.case.commands) == len(transfer.case.prepares) == 1
