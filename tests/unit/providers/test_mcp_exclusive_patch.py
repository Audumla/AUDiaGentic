from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.pi.mcp_exclusive_patch import (
    _MARKER,
    apply_mcp_exclusive_patch,
)

_CONFIG_SOURCE = """
export function getConfigSources(overridePath?: string): ConfigSource[] {
  return [];
}
"""

_INDEX_SOURCE = """
pi.registerFlag("mcp-config", {
  description: "MCP config override",
  type: "string",
});
"""


def _write_adapter(root: Path, *, version: str | None) -> Path:
    adapter_dir = root / "pi-mcp-adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "config.ts").write_text(_CONFIG_SOURCE, encoding="utf-8")
    (adapter_dir / "index.ts").write_text(_INDEX_SOURCE, encoding="utf-8")
    if version is not None:
        (adapter_dir / "package.json").write_text(
            json.dumps({"name": "pi-mcp-adapter", "version": version}),
            encoding="utf-8",
        )
    return root


@pytest.mark.parametrize("version", ["2.10.0", "2.10.5", "2.99.0"])
def test_supported_versions_patch_successfully(tmp_path: Path, version: str) -> None:
    root = _write_adapter(tmp_path, version=version)

    assert apply_mcp_exclusive_patch(root) is True
    assert _MARKER in (root / "pi-mcp-adapter" / "config.ts").read_text(encoding="utf-8")
    assert _MARKER in (root / "pi-mcp-adapter" / "index.ts").read_text(encoding="utf-8")


@pytest.mark.parametrize("version", ["2.9.9", "1.0.0", "3.0.0"])
def test_unsupported_versions_refuse_to_patch(tmp_path: Path, version: str) -> None:
    root = _write_adapter(tmp_path, version=version)

    assert apply_mcp_exclusive_patch(root) is False
    assert _MARKER not in (root / "pi-mcp-adapter" / "config.ts").read_text(encoding="utf-8")
    assert _MARKER not in (root / "pi-mcp-adapter" / "index.ts").read_text(encoding="utf-8")


def test_missing_version_refuses_to_patch(tmp_path: Path) -> None:
    root = _write_adapter(tmp_path, version=None)

    assert apply_mcp_exclusive_patch(root) is False
    assert _MARKER not in (root / "pi-mcp-adapter" / "config.ts").read_text(encoding="utf-8")


def test_idempotent_on_repeated_apply(tmp_path: Path) -> None:
    root = _write_adapter(tmp_path, version="2.10.0")

    assert apply_mcp_exclusive_patch(root) is True
    first_config = (root / "pi-mcp-adapter" / "config.ts").read_text(encoding="utf-8")
    first_index = (root / "pi-mcp-adapter" / "index.ts").read_text(encoding="utf-8")

    assert apply_mcp_exclusive_patch(root) is True
    assert (root / "pi-mcp-adapter" / "config.ts").read_text(encoding="utf-8") == first_config
    assert (root / "pi-mcp-adapter" / "index.ts").read_text(encoding="utf-8") == first_index


def test_missing_anchor_fails_closed_on_both_files(tmp_path: Path) -> None:
    root = _write_adapter(tmp_path, version="2.10.0")
    (root / "pi-mcp-adapter" / "config.ts").write_text("// no matching anchor here\n", encoding="utf-8")

    assert apply_mcp_exclusive_patch(root) is False
    assert _MARKER not in (root / "pi-mcp-adapter" / "index.ts").read_text(encoding="utf-8")
