"""Machine-scope gateway settings for a test (the explicit settings file scope)."""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

_COUNTER = itertools.count()


def use_gateway_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **gateway: Any) -> Path:
    """Write ``gateway:`` settings to a fresh file and make it the explicit settings scope.

    A new file name per call keeps the settings cache from serving a stale result.
    """
    path = tmp_path / f"gateway-settings-{next(_COUNTER)}.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "gateway": gateway}), encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(path))
    return path
