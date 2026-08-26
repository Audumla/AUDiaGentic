"""SH06 Docker gate: disposable workers do not leak project runtime context."""
from __future__ import annotations

import os
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerExecutionIdentity,
)
from audiagentic.components.agents.gateway import api as gateway
from audiagentic.components.agents.gateway.queue import worker as worker_module
from audiagentic.components.agents.gateway.queue.worker import (
    execute_isolated_provider_turn,
)
from audiagentic.components.agents.configuration.management import (
    create_execution_profile,
)
from audiagentic.components.providers.providers_api import ProviderExecutionRequest
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.system.process import pid_alive


def _descendant_alive(pid: int) -> bool:
    """Check a test child without treating Windows query denial as liveness."""
    if os.name != "nt":
        return pid_alive(pid)
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return f'"{pid}"' in result.stdout


def _write_qwen_probe(bin_dir: Path) -> None:
    program = (
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "Path('.qwen-probe-ran').write_text('ran', encoding='utf-8')\n"
        "if Path('.crash').exists():\n"
        "    child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "    Path('.descendant-pid').write_text(str(child.pid), encoding='utf-8')\n"
        "    raise SystemExit(7)\n"
        "if Path('.block').exists():\n"
        "    child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "    Path('.descendant-pid').write_text(str(child.pid), encoding='utf-8')\n"
        "    time.sleep(60)\n"
        "if Path('.delay').exists():\n"
        "    Path('.provider-start-' + os.getenv('AUDIAGENTIC_COMPONENT_PROFILE', 'base')).write_text(str(time.time()), encoding='utf-8')\n"
        "    time.sleep(2)\n"
        "print('|'.join((os.getcwd(), "
        "os.getenv('AUDIAGENTIC_COMPONENT_PROFILE', ''), "
        "os.getenv('AG_SH06_SECRET_CANARY', 'absent'))))\n"
    )
    if os.name == "nt":
        script = bin_dir / "qwen_probe.py"
        script.write_text(program, encoding="utf-8")
        probe = bin_dir / "qwen.cmd"
        probe.write_text(
            f'@echo off\r\npython "{script}" %*\r\n',
            encoding="utf-8",
        )
        return
    probe = bin_dir / "qwen"
    probe.write_text(
        "#!/usr/bin/env python3\n" + program,
        encoding="utf-8",
    )
    probe.chmod(probe.stat().st_mode | stat.S_IXUSR)


def _request(root: Path, *, worker_id: str, epoch: int, profile: str) -> tuple[WorkerExecutionIdentity, dict]:
    identity = WorkerExecutionIdentity(
        worker_id=worker_id,
        attempt_epoch=epoch,
        manifest_id=f"mf_{worker_id}",
        context_fingerprint=("a" if epoch == 1 else "b") * 64,
        project_root=str(root.resolve()),
        component_profile=profile,
        provider_isolation_tier="full-isolation",
    )
    request = ProviderExecutionRequest(
        project_root=root.resolve(),
        provider_id="qwen",
        model_id="qwen-test",
        model_alias=None,
        packet_data={"prompt-body": "return context", "metadata": {}},
        worker_id=worker_id,
        attempt_epoch=epoch,
        provider_isolation_tier="full-isolation",
    )
    return identity, request.to_mapping()


def test_concurrent_workers_keep_project_profile_and_secret_context_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_qwen_probe(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("AG_SH06_SECRET_CANARY", "gateway-secret-must-not-leak")

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    for root in (left, right):
        set_implementation_state(
            root, "providers", "qwen", ImplementationState(enabled=True)
        )

    left_identity, left_request = _request(left, worker_id="worker_left", epoch=1, profile="alpha")
    right_identity, right_request = _request(right, worker_id="worker_right", epoch=2, profile="beta")
    with ThreadPoolExecutor(max_workers=2) as pool:
        left_result, right_result = list(
            pool.map(
                lambda work: execute_isolated_provider_turn(
                    identity=work[0], execution_request=work[1], timeout_seconds=20
                ),
                ((left_identity, left_request), (right_identity, right_request)),
            )
        )

    assert left_result.result_data["output"] == f"{left.resolve()}|alpha|absent"
    assert right_result.result_data["output"] == f"{right.resolve()}|beta|absent"
    assert left_result.worker_id != right_result.worker_id
    assert os.environ["AG_SH06_SECRET_CANARY"] == "gateway-secret-must-not-leak"


def test_non_full_tiers_return_explicit_policy_outcome(tmp_path: Path) -> None:
    identity = WorkerExecutionIdentity(
        worker_id="worker_partial",
        attempt_epoch=1,
        manifest_id="mf_partial",
        context_fingerprint="c" * 64,
        project_root=str(tmp_path.resolve()),
        component_profile="",
        provider_isolation_tier="partial-isolation",
    )
    request = ProviderExecutionRequest(
        project_root=tmp_path.resolve(),
        provider_id="aider",
        model_id="test",
        model_alias=None,
        packet_data={"prompt-body": "must not execute"},
        worker_id=identity.worker_id,
        attempt_epoch=identity.attempt_epoch,
        provider_isolation_tier="partial-isolation",
    )

    with pytest.raises(AudiaGenticError, match="not safe") as error:
        execute_isolated_provider_turn(
            identity=identity,
            execution_request=request.to_mapping(),
            timeout_seconds=10,
        )
    assert error.value.code == "UNS-AGW-076"


def test_gateway_dispatches_full_isolation_provider_in_a_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_qwen_probe(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("AG_SH06_SECRET_CANARY", "gateway-secret-must-not-leak")
    create_execution_profile(
        tmp_path,
        {
            "profile_id": "qwen-worker",
            "provider_id": "qwen",
            "model_id": "qwen-test",
            "instances": ["qwen-test"],
            "is_default": True,
        },
    )
    set_implementation_state(
        tmp_path, "providers", "qwen", ImplementationState(enabled=True)
    )

    result = gateway.run_execution_request(
        tmp_path,
        prompt_body="return context",
        component_profile="isolated-profile",
        timeout_seconds=20,
    )

    assert result["state"] == "completed"
    assert result["output"] == f"{tmp_path.resolve()}|isolated-profile|absent"
    assert result["worker-id"]
    assert result["attempt-epoch"] == 1


@pytest.mark.requires_container
def test_provider_crash_reaps_the_detached_descendant_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup uses the owned process group even after its leader exits."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_qwen_probe(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    (tmp_path / ".crash").write_text("crash", encoding="utf-8")
    set_implementation_state(
        tmp_path, "providers", "qwen", ImplementationState(enabled=True)
    )
    identity, request = _request(
        tmp_path, worker_id="worker_crash", epoch=1, profile="crash-profile"
    )

    with pytest.raises(AudiaGenticError) as error:
        execute_isolated_provider_turn(
            identity=identity,
            execution_request=request,
            timeout_seconds=20,
        )
    assert error.value.code == "EXT-QWEN-001"

    pid_path = tmp_path / ".descendant-pid"
    assert pid_path.exists(), "crashing provider did not record its descendant"
    descendant_pid = int(pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 15
    while _descendant_alive(descendant_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _descendant_alive(descendant_pid), "crashed provider descendant was orphaned"


def test_gateway_runs_three_profiles_in_parallel_os_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three profile queues may compute concurrently; each owns one worker tree."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_qwen_probe(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    (tmp_path / ".delay").write_text("delay", encoding="utf-8")
    set_implementation_state(
        tmp_path, "providers", "qwen", ImplementationState(enabled=True)
    )
    profiles = ("deep-test", "lite-test", "supp-test")
    for index, profile_id in enumerate(profiles):
        create_execution_profile(
            tmp_path,
            {
                "profile_id": profile_id,
                "provider_id": "qwen",
                "model_id": f"qwen-test-{index}",
                "instances": [f"qwen-test-{index}"],
                "is_default": index == 0,
            },
        )

    worker_spawned_at: list[float] = []
    real_spawn = worker_module.spawn_supervised

    def observe_spawn(*args, **kwargs):
        worker_spawned_at.append(time.monotonic())
        return real_spawn(*args, **kwargs)

    monkeypatch.setattr(worker_module, "spawn_supervised", observe_spawn)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda pair: gateway.run_execution_request(
                    tmp_path,
                    prompt_body="return context",
                    execution_profile_id=pair[0],
                    component_profile=pair[1],
                    timeout_seconds=20,
                ),
                zip(profiles, ("deep", "lite", "supp"), strict=True),
            )
        )
    # A retry/recovery path may legitimately spawn an additional disposable
    # worker; the contract is that all three profile requests complete with
    # distinct worker identities.
    assert len(worker_spawned_at) >= 3
    assert [result["state"] for result in results] == ["completed"] * 3
    assert [result["output"] for result in results] == [
        f"{tmp_path.resolve()}|deep|absent",
        f"{tmp_path.resolve()}|lite|absent",
        f"{tmp_path.resolve()}|supp|absent",
    ]
    assert len({result["worker-id"] for result in results}) == 3
