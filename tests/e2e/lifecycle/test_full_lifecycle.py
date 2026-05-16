from __future__ import annotations

from tests.helpers import sandbox as sandbox_helper

from audiagentic.runtime.lifecycle.baseline_sync import sync_managed_baseline
from audiagentic.runtime.lifecycle.detector import detect_installed_state
from audiagentic.runtime.lifecycle.fresh_install import apply_fresh_install
from audiagentic.runtime.lifecycle.uninstall import apply_uninstall


def test_install_detect_uninstall_roundtrip(tmp_path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-roundtrip")
    try:
        assert detect_installed_state(sandbox.repo).state == "none"

        install_result = apply_fresh_install(sandbox.repo)
        assert install_result["status"] == "success"
        assert detect_installed_state(sandbox.repo).state == "installed"

        uninstall_result = apply_uninstall(sandbox.repo)
        assert uninstall_result["status"] == "success"
        assert detect_installed_state(sandbox.repo).state == "invalid"
        assert not (sandbox.repo / ".audiagentic" / "components" / "core-lifecycle.yaml").exists()
        assert (sandbox.repo / ".audiagentic" / "config" / "project.yaml").is_file()
    finally:
        sandbox.cleanup()


def test_sync_preserves_config_and_refreshes_managed_prompt(tmp_path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-sync")
    try:
        apply_fresh_install(sandbox.repo)

        provider_path = sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml"
        provider_path.write_text("contract-version: v1\nproviders:\n  custom: {}\n", encoding="utf-8")

        prompt_path = sandbox.repo / ".audiagentic" / "prompts" / "ag-review" / "default.md"
        prompt_path.write_text("corrupted managed prompt", encoding="utf-8")

        result = sync_managed_baseline(sandbox.repo)

        assert ".audiagentic/config/runtime/providers.yaml" in result["preserved-files"]
        assert "custom" in provider_path.read_text(encoding="utf-8")
        assert "corrupted managed prompt" not in prompt_path.read_text(encoding="utf-8")
        assert ".audiagentic/prompts/ag-review/default.md" in result["refreshed-files"]
    finally:
        sandbox.cleanup()
