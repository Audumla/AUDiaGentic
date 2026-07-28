"""Docker-gated real llama.cpp recipe and model-load acceptance test."""
from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.opt_in, pytest.mark.timeout(240)]


def test_recipe_provisions_and_managed_rig_loads_smoke_model(tmp_path, monkeypatch) -> None:
    if os.environ.get("AUDIAGENTIC_RIG_RECIPE_DOCKER") != "1":
        pytest.skip("opt-in Docker gate; set AUDIAGENTIC_RIG_RECIPE_DOCKER=1")

    from audiagentic.runtime.harness.provisioning import provision_embedded_rig
    from audiagentic.runtime.rig.http import require_models_endpoint
    from audiagentic.runtime.rig.service import release_embedded_rig, start_or_attach_embedded_rig

    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / ".audiagentic"))
    runtime = tmp_path / ".audiagentic" / "harness"
    provision_embedded_rig(runtime, tmp_path)
    attachment = start_or_attach_embedded_rig(
        profile_name="qwen3.5-0.8b", rig_port=42001, model_id="audiagentic-rig"
    )
    try:
        probe = require_models_endpoint(attachment.endpoint, timeout=30)
        assert probe.first_model_id == "qwen3.5-0.8b"
    finally:
        release_embedded_rig(attachment)
