from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.foundation.lifecycle.baseline_sync import sync_managed_baseline
from audiagentic.foundation.lifecycle.components import install_component
from audiagentic.foundation.lifecycle.detector import detect_installed_state
from audiagentic.foundation.lifecycle.fresh_install import apply_fresh_install
from audiagentic.foundation.lifecycle.uninstall import apply_uninstall


def test_install_detect_uninstall_roundtrip(tmp_path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-roundtrip")
    try:
        assert detect_installed_state(sandbox.repo).state == "none"

        install_result = apply_fresh_install(sandbox.repo)
        assert install_result["status"] == "success"
        assert detect_installed_state(sandbox.repo).state == "installed"

        uninstall_result = apply_uninstall(sandbox.repo)
        assert uninstall_result["status"] == "success"
        assert detect_installed_state(sandbox.repo).state == "installed"
        assert (sandbox.repo / ".audiagentic" / "components" / "project.yaml").exists()
        assert (sandbox.repo / ".audiagentic" / "config" / "project.yaml").is_file()
    finally:
        sandbox.cleanup()


def test_sync_preserves_config_and_prompt_overrides(tmp_path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "lifecycle-sync")
    try:
        apply_fresh_install(sandbox.repo)
        install_component("providers", sandbox.repo)

        provider_path = sandbox.repo / ".audiagentic" / "config" / "providers" / "custom.yaml"
        provider_path.parent.mkdir(parents=True, exist_ok=True)
        provider_path.write_text(
            "provider-id: custom\ninstall-mode: toolchain\naccess-mode: none\nauth-ref: env:CUSTOM_KEY\n",
            encoding="utf-8",
        )

        prompt_path = sandbox.repo / ".audiagentic" / "prompts" / "custom" / "default.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("custom prompt override", encoding="utf-8")

        result = sync_managed_baseline(sandbox.repo)

        assert ".audiagentic/config/providers" in result["preserved-files"]
        assert "custom" in provider_path.read_text(encoding="utf-8")
        assert prompt_path.read_text(encoding="utf-8") == "custom prompt override"
        assert ".audiagentic/prompts/custom/default.md" not in result["refreshed-files"]
    finally:
        sandbox.cleanup()
