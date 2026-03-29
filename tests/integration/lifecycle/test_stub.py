from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for path in (str(ROOT), str(ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

import tools.lifecycle_stub as lifecycle_stub
import tools.seed_example_project as seed_example_project
from tests.helpers import sandbox as sandbox_helper


def _read_checkpoint(project_root: Path, name: str) -> dict:
    path = project_root / ".audiagentic" / "runtime" / "lifecycle" / "checkpoints" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_stub_writes_expected_checkpoints(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-stub")
    try:
        seed_example_project.seed_example_project(sandbox.repo, overwrite=True)
        payload = lifecycle_stub.run_stub("plan", sandbox.repo)
        assert payload["mode"] == "plan"
        checkpoint = _read_checkpoint(sandbox.repo, "detected")
        assert checkpoint["phase"] == "detected"
        assert checkpoint["payload"] == payload
    finally:
        sandbox.cleanup()


def test_stub_apply_writes_multiple_checkpoints(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-apply")
    try:
        seed_example_project.seed_example_project(sandbox.repo, overwrite=True)
        payload = lifecycle_stub.run_stub("apply", sandbox.repo)
        assert payload["mode"] == "apply"
        _ = _read_checkpoint(sandbox.repo, "planned")
        _ = _read_checkpoint(sandbox.repo, "pre-destructive")
    finally:
        sandbox.cleanup()


def test_stub_idempotent_plan(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-idempotent")
    try:
        seed_example_project.seed_example_project(sandbox.repo, overwrite=True)
        first = lifecycle_stub.run_stub("plan", sandbox.repo)
        second = lifecycle_stub.run_stub("plan", sandbox.repo)
        assert first == second
        checkpoint = _read_checkpoint(sandbox.repo, "detected")
        assert checkpoint["payload"] == second
    finally:
        sandbox.cleanup()


def test_stub_rejects_invalid_mode_without_writing(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-invalid")
    try:
        seed_example_project.seed_example_project(sandbox.repo, overwrite=True)
        try:
            lifecycle_stub.run_stub("bad-mode", sandbox.repo)
        except Exception:
            checkpoint_dir = sandbox.repo / ".audiagentic" / "runtime" / "lifecycle" / "checkpoints"
            assert not checkpoint_dir.exists() or not any(checkpoint_dir.iterdir())
        else:
            raise AssertionError("expected error")
    finally:
        sandbox.cleanup()
