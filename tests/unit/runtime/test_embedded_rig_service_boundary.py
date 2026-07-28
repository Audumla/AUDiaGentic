from __future__ import annotations

from pathlib import Path


def test_embedded_rig_has_no_local_shared_process_registry_or_reaper() -> None:
    root = Path(__file__).parents[3] / "src" / "audiagentic" / "runtime" / "rig"
    assert not (root / "registry.py").exists()
    source = (root / "service.py").read_text(encoding="utf-8")
    forbidden = ("rig.json", "reap_orphan_rigs", "tasklist", "pgrep")
    assert not any(marker in source for marker in forbidden)
    assert "ManagedServiceLifecycle" in source
