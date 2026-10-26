"""No native calls: exercise entry point and failure-path process cleanup."""

import importlib.util
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("qualify_native.py")


def load_driver():
    spec = importlib.util.spec_from_file_location("shared_native_qualification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_help_is_standalone_and_explicit():
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    for option in (
        "--wheel",
        "--installed-package",
        "--catalog",
        "--native-profile",
        "--provider",
        "--access-mode",
        "--output",
    ):
        assert option in result.stdout


def test_missing_inputs_refuse_without_starting_service():
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2
    assert "required" in result.stderr


def test_exception_cleans_spawned_process_and_cleanup_is_idempotent():
    driver = load_driver()
    with pytest.raises(RuntimeError, match="injected failure"):
        with ExitStack() as resources:
            process = driver.spawn(
                resources, [sys.executable, "-c", "import time; time.sleep(120)"]
            )
            assert process.poll() is None
            raise RuntimeError("injected failure")
    assert process.poll() is not None
    driver.stop_tree(process)


def test_exception_cleans_descendant_process(tmp_path):
    import json
    import time

    import psutil

    driver = load_driver()
    pid_file = tmp_path / "descendant.json"
    command = (
        "import subprocess,sys,time,json; "
        "from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        "Path(sys.argv[1]).write_text(json.dumps(p.pid)); time.sleep(120)"
    )
    descendant = None
    try:
        with pytest.raises(RuntimeError, match="injected failure"):
            with ExitStack() as resources:
                driver.spawn(resources, [sys.executable, "-c", command, str(pid_file)])
                deadline = time.monotonic() + 10
                while not pid_file.exists():
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
                descendant = psutil.Process(json.loads(pid_file.read_text()))
                raise RuntimeError("injected failure")
        _, alive = psutil.wait_procs([descendant], timeout=5)
        assert not alive
    finally:
        if descendant is not None and descendant.is_running():
            descendant.kill()
            descendant.wait(timeout=5)


def test_cleanup_contains_descendants_after_direct_child_exits(tmp_path):
    import json

    import psutil

    driver = load_driver()
    pid_file = tmp_path / "survivor.json"
    command = (
        "import subprocess,sys,json; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        "Path(sys.argv[1]).write_text(json.dumps(p.pid))"
    )
    descendant = None
    try:
        with ExitStack() as resources:
            process = driver.spawn(resources, [sys.executable, "-c", command, str(pid_file)])
            process.wait(timeout=10)
            descendant = psutil.Process(json.loads(pid_file.read_text()))
            assert descendant.is_running()
        _, alive = psutil.wait_procs([descendant], timeout=5)
        assert not alive
    finally:
        if descendant is not None and descendant.is_running():
            descendant.kill()
            descendant.wait(timeout=5)


@pytest.mark.parametrize("surface", ["codex-acp", "codex-cli", "", "other"])
def test_cli_clone_rejects_every_surface_override(surface):
    driver = load_driver()
    source = {
        "profile_id": "qualification-codex-cli",
        "provider_id": "codex",
        "surface_id": surface,
    }
    with pytest.raises(ValueError, match="no surface override"):
        driver.clone_cli_profile(source, provider="codex", access_mode="cli")
    assert source["surface_id"] == surface


def test_cli_clone_preserves_source_and_uses_fresh_no_surface_id():
    driver = load_driver()
    source = {
        "profile_id": "qualification-codex-cli",
        "provider_id": "codex",
        "surface_id": None,
        "is_default": True,
        "parameters": {"temperature": 0.1},
    }
    first = driver.clone_cli_profile(source, provider="codex", access_mode="cli")
    second = driver.clone_cli_profile(source, provider="codex", access_mode="cli")
    assert first["surface_id"] is None and second["surface_id"] is None
    assert len({source["profile_id"], first["profile_id"], second["profile_id"]}) == 3
    assert first["is_default"] is False and source["is_default"] is True
    first["parameters"]["temperature"] = 1
    assert source["parameters"]["temperature"] == 0.1


@pytest.mark.parametrize("provider,mode", [("other", "cli"), ("codex", "acp")])
def test_cli_clone_requires_explicit_matching_selection(provider, mode):
    with pytest.raises(ValueError, match="explicit codex CLI"):
        load_driver().clone_cli_profile(
            {"provider_id": "codex", "surface_id": None}, provider=provider, access_mode=mode
        )


def test_child_submits_generated_profile_id_without_keep_alive(tmp_path, monkeypatch, capsys):
    import json
    import ssl

    from audiagentic.components.agents.gateway import remote_client

    profile = load_driver().clone_cli_profile(
        {"provider_id": "codex", "surface_id": None}, provider="codex", access_mode="cli"
    )
    (tmp_path / "client-config.json").write_text(
        json.dumps({"server-id": "test-server", "execution-profile-id": profile["profile_id"]})
    )
    (tmp_path / "alice.token").write_text("test-token")
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def submit_execution_request(self, root, **kwargs):
            captured.update(kwargs)
            return {"request-id": "test-request"}

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", FakeClient)
    monkeypatch.setattr(ssl, "create_default_context", lambda **kwargs: None)
    monkeypatch.setattr(
        sys, "argv", ["child", str(tmp_path), str(tmp_path), "https://localhost", "alice", "submit"]
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "qualification_child", SCRIPT.with_name("shared_native_client.py")
    )
    child = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(child)
    child.main()
    assert captured["execution_profile_id"] == profile["profile_id"]
    assert captured["session_keep_alive"] is False
    assert captured["closed"] is True
    assert json.loads(capsys.readouterr().out)["request-id"] == "test-request"
