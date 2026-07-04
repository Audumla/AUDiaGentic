"""Clean-room LSP auto-install integration tests.

Runs inside the Docker container built from tests/docker/Dockerfile.lsp-install-test.
Validates the real first-touch path:

  1. project has coding-lsp installed/enabled, but target language is not enabled
  2. no target language-server binary is present on PATH
  3. first LSP call against a matching file auto-enables the language
  4. missing dependency installs silently from the language recipe
  5. the language server initializes and returns capabilities

This closes the gap between dependency-workflow tests and the baked-server MCP
suite by proving cold-start behavior in a sandboxed container.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from audiagentic.components.coding_lsp import lsp_api, lsp_config_api
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.features.state import get_feature_state
from audiagentic.foundation.lifecycle.components import enable_component, install_component

pytestmark = [pytest.mark.mutates_host, pytest.mark.slow]


AUTO_INSTALL_CASES = [
    (
        "json",
        "sample.json",
        '{\n  "name": "auto-install",\n  "value": 1\n}\n',
        "vscode-json-language-server",
        {"hover", "completion", "documentSymbol"},
    ),
    (
        "yaml",
        "docker-compose.yml",
        "services:\n  api:\n    image: nginx:latest\n",
        "yaml-language-server",
        {"hover", "completion", "documentSymbol"},
    ),
    (
        "toml",
        "pyproject.toml",
        '[project]\nname = "auto-install"\nversion = "0.1.0"\n',
        "taplo",
        {"hover", "completion", "documentSymbol"},
    ),
    (
        "make",
        "Makefile",
        "all:\n\t@echo hello\n",
        "make-ls",
        {"hover", "documentSymbol"},
    ),
]


def _wait_for_capabilities(sample: Path, timeout_s: float = 180.0) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last: dict[str, object] = {}
    while time.time() < deadline:
        last = lsp_api.server_capabilities(str(sample))
        if "error" not in last and last.get("supported"):
            return last
        time.sleep(1.0)
    return last


@pytest.fixture(scope="module")
def auto_install_project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("lsp-auto-install-project")
    (root / ".audiagentic").mkdir(parents=True, exist_ok=True)

    register_all_components()

    result = install_component("coding-lsp", root)
    assert result["ok"], f"install coding-lsp failed: {result}"
    result = enable_component("coding-lsp", root)
    assert result["ok"], f"enable coding-lsp failed: {result}"
    return root


@pytest.mark.timeout(900)
@pytest.mark.parametrize(
    ("language", "filename", "content", "binary", "expected_caps"),
    AUTO_INSTALL_CASES,
)
def test_first_lsp_touch_auto_installs_and_initializes(
    auto_install_project: Path,
    language: str,
    filename: str,
    content: str,
    binary: str,
    expected_caps: set[str],
) -> None:
    sample = auto_install_project / filename
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text(content, encoding="utf-8")

    state_before = get_feature_state(auto_install_project, "coding-lsp", "language", language)
    assert state_before.enabled is False, f"{language} unexpectedly pre-enabled"
    assert shutil.which(binary) is None, f"{binary} unexpectedly present before auto-install"

    result = _wait_for_capabilities(sample)
    assert "error" not in result, f"server_capabilities failed for {language}: {result}"
    supported = set(result.get("supported", []))
    assert supported, f"no capabilities reported for {language}: {result}"
    assert supported & expected_caps, (
        f"{language} missing expected capabilities. got={supported} expected_any={expected_caps}"
    )

    state_after = get_feature_state(auto_install_project, "coding-lsp", "language", language)
    assert state_after.enabled is True, f"{language} was not auto-enabled"
    assert shutil.which(binary) is not None, f"{binary} not installed after first LSP touch"

    missing = lsp_config_api.missing_configured_dependencies(auto_install_project)
    assert not missing, f"missing configured dependencies after auto-install: {missing}"
