"""Trusted worker terminals come from one supervised, validated invocation."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.contracts.worker_protocol import WorkerExecutionIdentity
from audiagentic.components.agents.gateway.queue import worker
from audiagentic.components.providers import providers_api
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import process_creation_identity

# This is a real disposable child using the real protocol. The fixture alters
# envelopes, never production worker_host or provider/native execution code.
SCRIPT = r"""
import json, os, sys
from pathlib import Path
from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerHandshakeEnvelope, WorkerProcessEvidence, WorkerResultEnvelope, WorkerErrorEnvelope, decode_worker_message,
)
from audiagentic.foundation.system.managed_process import process_creation_identity

case = sys.argv[1]
request = decode_worker_message(sys.stdin.readline())
identity = request.identity
process = WorkerProcessEvidence(os.getpid(), process_creation_identity(os.getpid()), str(Path.cwd().resolve()))
handshake = WorkerHandshakeEnvelope(identity, process).to_mapping()
result = {
    "provider-id": request.execution_request["provider-id"],
    "model-id": request.execution_request["model-id"] or "resolved-model",
    "worker-id": identity.worker_id, "attempt-epoch": identity.attempt_epoch,
    "result-data": {"text": "PRIVATE terminal output", "events": [{"text": "PRIVATE nested output"}]},
}
terminal = WorkerResultEnvelope(identity, process, result).to_mapping()
if case == "provider-error":
    terminal = WorkerErrorEnvelope(
        identity, process, "EXT-PEXE-001", "providers", "controlled provider refusal",
    ).to_mapping()
elif case == "pid":
    handshake["pid"] += 1000
elif case == "birth":
    handshake["process-creation-identity"] = "wrong-birth"
elif case == "cwd":
    handshake["working-directory"] = str(Path.cwd().parent.resolve())
elif case == "manifest":
    handshake["manifest-id"] = "wrong-manifest"
elif case == "context":
    handshake["context-fingerprint"] = "b" * 64
elif case == "terminal-pid":
    terminal["pid"] += 1000
elif case == "terminal-birth":
    terminal["process-creation-identity"] = "wrong-birth"
elif case == "terminal-cwd":
    terminal["working-directory"] = str(Path.cwd().parent.resolve())
elif case == "terminal-manifest":
    terminal["manifest-id"] = "wrong-manifest"
elif case == "terminal-context":
    terminal["context-fingerprint"] = "b" * 64
elif case == "inner-worker":
    terminal["execution-result"]["worker-id"] = "wrong-worker"
elif case == "inner-attempt":
    terminal["execution-result"]["attempt-epoch"] += 1
elif case == "boolean-attempt":
    terminal["execution-result"]["attempt-epoch"] = True
elif case == "provider":
    terminal["execution-result"]["provider-id"] = "wrong-provider"
elif case == "model":
    terminal["execution-result"]["model-id"] = "wrong-model"
print(json.dumps(handshake), flush=True)
if case != "missing-terminal":
    print(json.dumps(terminal), flush=True)
"""


@pytest.fixture
def rig(tmp_path, monkeypatch):
    identity = WorkerExecutionIdentity(
        worker_id="worker", attempt_epoch=1, manifest_id="manifest",
        context_fingerprint="a" * 64, project_root=str(tmp_path.resolve()),
        component_profile="", provider_isolation_tier="full-isolation",
    )
    request = providers_api.ProviderExecutionRequest(
        tmp_path.resolve(), "fixture-provider", "fixture-model", None,
        {"prompt-body": "PRIVATE input"}, "worker", 1, "full-isolation",
    ).to_mapping()
    prepare = Mock(return_value={})
    monkeypatch.setattr(providers_api, "prepare_provider_execution_environment", prepare)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "empty-pi"))
    real_spawn = worker.spawn_supervised
    state = {"case": "valid", "invocations": 0, "supervision_exited": False}

    @contextmanager
    def spawn(command, **kwargs):
        state["invocations"] += 1
        state["home"] = Path(kwargs["env"]["HOME"])
        if state.get("on_spawn"):
            state["on_spawn"]()
        try:
            with real_spawn([command[0], "-c", SCRIPT, state["case"]], **kwargs) as child:
                state["pid"] = child.pid
                state["birth"] = process_creation_identity(child.pid)
                original_poll = child.poll
                def observe_exit():
                    state.setdefault("exit_checks", []).append(
                        (state["supervision_exited"], not state["home"].exists())
                    )
                    return None if state.get("exit_unknown") else original_poll()
                monkeypatch.setattr(child, "poll", observe_exit)
                yield child
        finally:
            state["supervision_exited"] = True
            if state.get("cleanup_warning"):
                import logging
                logging.getLogger(__name__).warning("controlled teardown uncertainty")
            if state.get("cleanup_error"):
                raise OSError("simulated supervised cleanup failure")

    monkeypatch.setattr(worker, "spawn_supervised", spawn)
    return identity, request, state, prepare


def verified(rig, **kwargs):
    identity, request, _, _ = rig
    return worker.execute_verified_isolated_provider_turn(
        identity=identity, execution_request=request, timeout_seconds=10,
        allowed_model_ids=kwargs.pop("allowed_model_ids", {"fixture-model"}), **kwargs,
    )


def test_verified_terminal_is_minted_only_after_supervised_and_private_cleanup(rig, monkeypatch):
    identity, _, state, _ = rig
    original = worker.VerifiedWorkerTerminal.__init__
    constructed = []
    def construct(self, **kwargs):
        assert state["supervision_exited"]
        assert not state["home"].exists()
        constructed.append(True)
        original(self, **kwargs)
    monkeypatch.setattr(worker.VerifiedWorkerTerminal, "__init__", construct)
    proof = verified(rig)
    assert type(proof) is worker.VerifiedWorkerTerminal
    assert proof.identity == identity
    assert proof.worker_exited is True
    assert proof.cleanup_proven is False
    assert proof.process.pid == state["pid"]
    assert proof.process.process_creation_identity == state["birth"]
    assert proof.process.working_directory == identity.project_root
    assert proof.result.provider_id == "fixture-provider"
    assert proof.result.worker_id == identity.worker_id
    assert proof.result.attempt_epoch == identity.attempt_epoch
    assert proof.result.model_id == "fixture-model"
    assert proof.result.result_data["text"] == "PRIVATE terminal output"
    assert "PRIVATE" not in repr(proof)
    assert constructed == [True]
    assert state["exit_checks"] == [(True, True)]
    assert state["invocations"] == 1


def test_evidence_cannot_be_constructed_or_replaced_by_a_mapping_or_flag(rig):
    proof = verified(rig)
    with pytest.raises(TypeError):
        worker.VerifiedWorkerTerminal(identity=proof.identity, process=proof.process, result=proof.result)
    assert not hasattr(worker.VerifiedWorkerTerminal, "from_mapping")
    with pytest.raises(TypeError):
        replace(proof, result=proof.result)
    with pytest.raises(FrozenInstanceError):
        proof.identity = proof.identity
    with pytest.raises(TypeError):
        proof.result.result_data["text"] = "fabricated output"
    with pytest.raises(TypeError):
        proof.result.result_data["events"][0]["text"] = "fabricated nested output"


@pytest.mark.parametrize("case,code", [
    ("pid", "CON-AGW-076"), ("birth", "CON-AGW-076"), ("cwd", "CON-AGW-076"),
    ("manifest", "CON-AGW-076"), ("context", "CON-AGW-076"),
    ("terminal-pid", "CON-AGW-079"), ("terminal-birth", "CON-AGW-079"),
    ("terminal-cwd", "CON-AGW-079"), ("terminal-manifest", "CON-AGW-079"),
    ("terminal-context", "CON-AGW-079"),
    ("inner-worker", "CON-AGW-074"), ("inner-attempt", "CON-AGW-074"),
    ("boolean-attempt", "CON-AGW-079"), ("provider", "CON-AGW-079"), ("model", "CON-AGW-079"),
])
def test_real_child_invalid_identity_or_result_is_rejected_once_and_cleaned(rig, case, code):
    _, _, state, _ = rig
    state["case"] = case
    with pytest.raises(AudiaGenticError, match=code):
        verified(rig)
    assert state["invocations"] == 1
    assert state["supervision_exited"]
    assert not state["home"].exists()


@pytest.mark.parametrize("api", ["ordinary", "verified"])
def test_input_worker_attempt_mismatch_rejected_before_any_spawn(rig, api):
    identity, request, state, prepare = rig
    request["worker-id"] = "other-worker"
    with pytest.raises(AudiaGenticError, match="CON-AGW-074"):
        if api == "ordinary":
            worker.execute_isolated_provider_turn(identity=identity, execution_request=request, timeout_seconds=10)
        else:
            verified(rig)
    assert state["invocations"] == 0
    prepare.assert_not_called()


@pytest.mark.parametrize("allowed", [set(), "fixture-model", {"other-model"}, [None]])
def test_invalid_or_unprepared_model_scope_is_rejected_before_spawn(rig, allowed):
    _, _, state, prepare = rig
    with pytest.raises(AudiaGenticError, match="CON-AGW-079"):
        verified(rig, allowed_model_ids=allowed)
    assert state["invocations"] == 0
    prepare.assert_not_called()


def test_allowed_models_are_frozen_before_invocation(rig):
    _, _, state, _ = rig
    allowed = {"fixture-model"}
    state["on_spawn"] = lambda: (allowed.clear(), allowed.add("wrong-model"))
    proof = verified(rig, allowed_model_ids=allowed)
    assert proof.result.model_id == "fixture-model"
    assert allowed == {"wrong-model"}
    assert state["invocations"] == 1


@pytest.mark.parametrize("api", ["ordinary", "verified"])
def test_alias_model_behavior_uses_single_implementation(rig, api):
    identity, request, state, _ = rig
    request["model-id"], request["model-alias"] = None, "friendly-alias"
    if api == "ordinary":
        result = worker.execute_isolated_provider_turn(
            identity=identity, execution_request=request, timeout_seconds=10,
        )
        assert type(result) is providers_api.ProviderExecutionResult
    else:
        result = verified(rig, allowed_model_ids={"resolved-model"}).result
    assert result.model_id == "resolved-model"
    assert state["invocations"] == 1
    assert not state["home"].exists()


def test_verified_alias_cannot_choose_an_unprepared_result_model(rig):
    _, request, state, _ = rig
    request["model-id"], request["model-alias"] = None, "friendly-alias"
    with pytest.raises(AudiaGenticError, match="CON-AGW-079"):
        verified(rig, allowed_model_ids={"other-model"})
    assert state["invocations"] == 1


def test_ordinary_result_shape_and_mutability_remain_unchanged(rig):
    identity, request, state, _ = rig
    result = worker.execute_isolated_provider_turn(
        identity=identity, execution_request=request, timeout_seconds=10,
    )
    assert type(result) is providers_api.ProviderExecutionResult
    assert result.to_mapping() == {
        "provider-id": "fixture-provider", "model-id": "fixture-model", "worker-id": "worker",
        "attempt-epoch": 1, "result-data": {
            "text": "PRIVATE terminal output", "events": [{"text": "PRIVATE nested output"}],
        },
    }
    result.result_data["text"] = "ordinary API stays mutable as before"
    assert state["invocations"] == 1


def test_no_evidence_can_escape_failed_cleanup(rig, monkeypatch):
    _, _, state, _ = rig
    state["cleanup_error"] = True
    constructor = Mock(side_effect=AssertionError("must not mint proof before successful cleanup"))
    monkeypatch.setattr(worker, "VerifiedWorkerTerminal", constructor)
    with pytest.raises(OSError, match="cleanup failure"):
        verified(rig)
    constructor.assert_not_called()
    assert state["invocations"] == 1
    assert not state["home"].exists()


def test_verified_worker_requires_observed_direct_child_exit(rig):
    _, _, state, _ = rig
    state["exit_unknown"] = True
    with pytest.raises(AudiaGenticError, match="CON-AGW-076"):
        verified(rig)
    assert state["invocations"] == 1
    assert state["supervision_exited"]
    assert not state["home"].exists()


def test_silent_best_effort_cleanup_never_becomes_descendant_closure_proof(rig, caplog):
    _, _, state, _ = rig
    state["cleanup_warning"] = True
    with caplog.at_level("WARNING"):
        proof = verified(rig)
    assert "controlled teardown uncertainty" in caplog.text
    assert proof.worker_exited is True
    assert proof.cleanup_proven is False
    assert state["invocations"] == 1


@contextmanager
def denied_home_cleanup(tmp_path, monkeypatch):
    home = tmp_path / "protected-worker-home"
    home.mkdir(mode=0o700)
    (home / "private-canary").write_text("credential-canary", encoding="utf-8")
    cleanup = Mock(side_effect=PermissionError(f"SECRET {home} credential-canary"))
    clock = SimpleNamespace(
        monotonic=Mock(side_effect=[0.0, 1.0, 5.0]),
        sleep=Mock(),
    )
    with monkeypatch.context() as patch:
        patch.setattr(worker, "tempfile", SimpleNamespace(mkdtemp=lambda **kwargs: str(home)))
        patch.setattr(worker, "shutil", SimpleNamespace(rmtree=cleanup, copy2=worker.shutil.copy2))
        patch.setattr(worker, "time", clock)
        yield home, cleanup, clock


@pytest.mark.parametrize("api", ["ordinary", "verified"])
def test_permission_denied_home_cleanup_preserves_valid_terminal(rig, tmp_path, monkeypatch, caplog, api):
    identity, request, state, _ = rig
    with denied_home_cleanup(tmp_path, monkeypatch) as (home, cleanup, clock):
        with caplog.at_level("WARNING"):
            if api == "ordinary":
                result = worker.execute_isolated_provider_turn(
                    identity=identity, execution_request=request, timeout_seconds=10,
                )
            else:
                proof = verified(rig)
                result = proof.result
                assert proof.worker_exited is True
                assert proof.cleanup_proven is False
                assert state["exit_checks"] == [(True, False)]
        assert result.result_data["text"] == "PRIVATE terminal output"
        assert home.is_dir()
        assert (home / "private-canary").read_text(encoding="utf-8") == "credential-canary"
        assert cleanup.call_count == 2
        clock.sleep.assert_called_once_with(0.05)
        assert any(getattr(record, "cleanup-deferred", False) for record in caplog.records)
        assert "deferred" in caplog.text
        assert str(home) not in caplog.text
        assert "credential-canary" not in caplog.text
        assert "SECRET" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
    assert state["invocations"] == 1


@pytest.mark.parametrize("api", ["ordinary", "verified"])
def test_permission_denied_home_cleanup_does_not_mask_provider_error(rig, tmp_path, monkeypatch, caplog, api):
    identity, request, state, _ = rig
    state["case"] = "provider-error"
    with denied_home_cleanup(tmp_path, monkeypatch) as (home, cleanup, clock):
        with caplog.at_level("WARNING"), pytest.raises(AudiaGenticError) as error:
            if api == "ordinary":
                worker.execute_isolated_provider_turn(
                    identity=identity, execution_request=request, timeout_seconds=10,
                )
            else:
                verified(rig)
        assert error.value.code == "EXT-PEXE-001"
        assert error.value.message == "controlled provider refusal"
        assert home.is_dir()
        assert cleanup.call_count == 2
        clock.sleep.assert_called_once_with(0.05)
        assert str(home) not in caplog.text
        assert "credential-canary" not in caplog.text
    assert state["invocations"] == 1


@pytest.mark.parametrize("missing", ["terminal", "exit"])
def test_deferred_home_cleanup_never_invents_terminal_or_worker_exit_proof(rig, tmp_path, monkeypatch, missing):
    _, _, state, _ = rig
    if missing == "terminal":
        state["case"] = "missing-terminal"
    else:
        state["exit_unknown"] = True
    constructor = Mock(side_effect=AssertionError("must not invent verified terminal evidence"))
    monkeypatch.setattr(worker, "VerifiedWorkerTerminal", constructor)
    expected = "INT-AGW-077" if missing == "terminal" else "CON-AGW-076"
    with denied_home_cleanup(tmp_path, monkeypatch) as (home, cleanup, clock):
        with pytest.raises(AudiaGenticError, match=expected):
            verified(rig)
        assert home.is_dir()
        assert cleanup.call_count == 2
    constructor.assert_not_called()
    assert state["invocations"] == 1
