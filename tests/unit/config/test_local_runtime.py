from __future__ import annotations

import pytest

from audiagentic.foundation.config.harness import require_harness_rig_port
from audiagentic.foundation.config.local_runtime import local_provider_base_url, local_rig_host


def test_local_runtime_env_overrides(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_RIG_HOST", "rig.internal")
    monkeypatch.setenv("AUDIAGENTIC_RIG_PORT", "43123")
    assert local_rig_host() == "rig.internal"
    assert require_harness_rig_port({"rig": {"port": 42001}}) == 43123


def test_local_provider_explicit_config_wins(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL", "http://env:9000")
    assert local_provider_base_url("http://config:8000/") == "http://config:8000"


@pytest.mark.parametrize("name,value", [("AUDIAGENTIC_RIG_PORT", "0"), ("AUDIAGENTIC_RIG_PORT", "bad")])
def test_invalid_local_runtime_env_fails_closed(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(Exception):
        require_harness_rig_port({"rig": {"port": 42001}})
