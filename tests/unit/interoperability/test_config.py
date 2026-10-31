from __future__ import annotations

from pathlib import Path

import yaml


def test_event_config_imports_and_loads(tmp_path: Path) -> None:
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "events": {"event_store": {"enabled": False}, "replay": {"dispatch_on_replay": True}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from audiagentic.foundation.event.event_config import load_event_config

    config = load_event_config(tmp_path)
    assert config.event_store.enabled is False
    assert config.replay.dispatch_on_replay is True
