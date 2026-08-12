from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.gateway.queue.contention import (
    capture_contention_sample,
    contention_summary,
)


def test_contention_sample_persists_and_summarizes(tmp_path: Path) -> None:
    sample = capture_contention_sample(
        tmp_path,
        per_profile={
            "profile-a": {
                "pending": 2,
                "running": 1,
                "active_running": 1,
                "idle": 0,
                "virtual_capacity": 1,
            }
        },
        ingress_pending=3,
    )

    assert sample.per_resource["profile:profile-a"]["pending"] == 2
    files = list((tmp_path / "contention").glob("*.ndjson"))
    assert len(files) == 1
    summary = contention_summary(tmp_path)
    assert summary["samples"] == 1
    assert summary["resources"]["profile:profile-a"]["max_pending"] == 2
