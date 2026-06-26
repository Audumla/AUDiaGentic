from __future__ import annotations

import json

from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.config_reader import load_config
from audiagentic.foundation.toolchains.managed_block import apply_managed_block


def test_register_and_prune_files(tmp_path):
    owned = tmp_path / "owned.txt"
    owned.write_text("x", encoding="utf-8")
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", files=[owned])

    report = reg.prune("r1")
    assert report.ok
    assert not owned.exists()
    assert owned.as_posix() in report.removed_files
    # registry entry cleared after successful prune
    assert "r1" not in reg.recipes()


def test_prune_skips_missing_artifacts(tmp_path):
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", files=[tmp_path / "gone.txt"])
    report = reg.prune("r1")
    assert report.ok
    assert any("absent" in s for s in report.skipped)


def test_dry_run_does_not_mutate(tmp_path):
    owned = tmp_path / "owned.txt"
    owned.write_text("x", encoding="utf-8")
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", files=[owned])

    report = reg.prune("r1", dry_run=True)
    assert owned.exists()  # untouched
    assert owned.as_posix() in report.removed_files
    assert "r1" in reg.recipes()  # entry retained


def test_prune_config_keys(tmp_path):
    cfg = tmp_path / "mcp.json"
    change = ConfigPatcher(cfg).add_mcp_entry("hindsight", {"command": "h"})
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", changes=[change])

    reg.prune("r1")
    assert "mcpServers" not in load_config(cfg)


def test_prune_managed_blocks(tmp_path):
    f = tmp_path / "rc"
    f.write_text("export A=1\n", encoding="utf-8")
    block = apply_managed_block(f, "hook", "export HOOK=1")
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", blocks=[block])

    reg.prune("r1")
    text = f.read_text(encoding="utf-8")
    assert "HOOK" not in text
    assert "export A=1" in text  # user content preserved


def test_collision_detection_warns(tmp_path):
    shared = tmp_path / "shared.txt"
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", files=[shared])
    collisions = reg.register("r2", files=[shared])
    assert collisions
    assert "already owned by r1" in collisions[0]


def test_sidecar_is_json_under_runtime(tmp_path):
    reg = ArtifactRegistry(tmp_path)
    reg.register("r1", files=[tmp_path / "a"])
    sidecar = tmp_path / ".audiagentic" / "config" / "runtime" / "toolchain" / "artifacts.json"
    assert sidecar.exists()
    json.loads(sidecar.read_text(encoding="utf-8"))  # valid JSON
