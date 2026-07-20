import json
from pathlib import Path

from audiagentic.runtime.harness.pi.request_runtime import (
    cleanup_request_runtime,
    create_request_runtime,
    quarantine_request_runtime,
)


def test_request_runtime_is_local_but_keeps_project_cwd_and_mcp_explicit(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    target = tmp_path / "harness"
    project.mkdir()
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.request_runtime.materialize_agent_config",
        lambda target, harness_cfg, project_root=None: (target / "agent" / "models.json").write_text("{}"),
    )

    runtime = create_request_runtime(target, project, "req-1", {"rig": {"model": "m"}})
    manifest = json.loads(runtime.manifest_path.read_text())
    assert runtime.agent_dir == target / "requests" / "req-1" / "agent"
    assert runtime.session_dir != project / ".audiagentic" / "sessions"
    assert manifest["cwd"] == str(project)
    assert manifest["project-mcp-path"] == str(project / ".audiagentic" / "mcp.json")
    assert runtime.environment()["PI_CODING_AGENT_DIR"] == str(runtime.agent_dir)

    quarantine = quarantine_request_runtime(runtime, tmp_path / "quarantine")
    assert (quarantine / "manifest.json").exists()
    cleanup_request_runtime(runtime)


def test_request_runtime_cleanup_is_idempotent(tmp_path: Path) -> None:
    from audiagentic.runtime.harness.pi.request_runtime import PiRequestRuntime

    runtime = PiRequestRuntime("missing", tmp_path / "missing", *(tmp_path / name for name in ("agent", "sessions", "tmp", "cache")), tmp_path, tmp_path / "mcp.json")
    cleanup_request_runtime(runtime)
    cleanup_request_runtime(runtime)


def test_request_runtime_can_use_gateway_owned_root(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.runtime.harness.pi.request_runtime import create_request_runtime

    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.request_runtime.materialize_agent_config",
        lambda target, harness_cfg, project_root=None: None,
    )
    root = tmp_path / "gateway-request" / "runtime" / "pi"
    runtime = create_request_runtime(tmp_path / "harness", tmp_path / "project", "req-2", {}, runtime_root=root)
    assert runtime.root == root
    assert runtime.agent_dir.is_dir()
    assert runtime.session_dir.is_dir()
