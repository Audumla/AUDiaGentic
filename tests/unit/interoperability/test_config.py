from __future__ import annotations

from pathlib import Path

import yaml


def test_interoperability_config_imports_and_loads(tmp_path: Path) -> None:
    config_dir = tmp_path / ".audiagentic" / "interoperability"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("config.yaml").write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "event_store": {"enabled": False},
                    "replay": {"dispatch_on_replay": True},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from audiagentic.interoperability.config import load_config

    config = load_config(tmp_path)
    assert config.event_store.enabled is False
    assert config.replay.dispatch_on_replay is True
