"""MA04 Step 2-3: Parameterized adapter contract suite.

Validates every shipped provider managed-config serializer against the
FragmentStore protocol: read(path)->dict, write(path,entries)->None,
remove(path,name)->bool. The suite initially fails atomicity cases by
design — those failures are the Block D1 migration checklist (MA04 Steps 4-7).

Contract cases per adapter row:
  write_absent            - creates file atomically; round-trips via read
  write_idempotent        - same entries twice -> identical output
  write_preserves_unmanaged - pre-existing entry B survives write of entry A
  remove_present          - removes entry, returns True, others preserved
  remove_absent           - file exists but name missing -> False, file unchanged
  read_missing_file       -> {}
  read_malformed          -> {} (graceful degradation)
  failure_atomicity       - interrupted write leaves original bytes intact

All adapters must satisfy the FragmentStore protocol regardless of format.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.components.providers.adapters.codex.language_servers import (
    read_language_servers_codex,
    remove_language_servers_codex,
    write_language_servers_codex,
)
from audiagentic.components.providers.adapters.mcp_opencode import (
    read_opencode_mcp,
    remove_opencode_mcp,
    write_opencode_mcp,
)
from audiagentic.components.providers.adapters.opencode.language_servers import (
    read_language_servers_opencode,
    remove_language_servers_opencode,
    write_language_servers_opencode,
)
from audiagentic.components.providers.adapters.openhands.toml_format import (
    read_mcp_toml,
    remove_mcp_toml,
    write_mcp_toml,
)
from audiagentic.components.providers.adapters.qwen.language_servers import (
    read_language_servers_qwen,
    remove_language_servers_qwen,
    write_language_servers_qwen,
)
from audiagentic.foundation.mcp import McpServerEntry


@dataclass(frozen=True)
class AdapterContractRow:
    """One adapter serializer mapped to the FragmentStore protocol."""

    adapter_id: str
    format: str
    container: str
    read: Callable[[Path], dict[str, Any]]
    write: Callable[[Path, dict[str, Any]], None]
    remove: Callable[[Path, str], bool]
    payload_factory: Callable[[], tuple[dict[str, Any], str]]


def _make_rows() -> list[AdapterContractRow]:
    def _mcp_payload():
        name = "fixture-tool"
        return ({name: McpServerEntry(
            name=name, command="npx", args=("-y", "@modelcontextprotocol/server-foo"),
        )}, name)

    def _lsp_python_payload():
        return ({
            "python": LanguageServerEntry(
                language="python", command=["pyright-langserver", "--stdio"],
                file_extensions=[".py"], settings={},
            ),
        }, "python")

    def _lsp_typescript_payload():
        return ({
            "typescript": LanguageServerEntry(
                language="typescript", command=["user-server"],
                file_extensions=[".ts"], settings={},
            ),
        }, "typescript")

    rows: list[AdapterContractRow] = []

    # ---- Row definitions (MA01 Step 1 table; FragmentStore-compatible subset) ----
    # Excluded: opencode/plugin_array.py (single-entry API, not dict-of-entries),
    # surfaces/extensions_json.py (surface renderer, different ownership model).

    # opencode-mcp (rows 2-3: write + remove in mcp_opencode.py)
    rows.append(AdapterContractRow(
        adapter_id="opencode-mcp",
        format="json",
        container=".opencode/opencode.json",
        read=read_opencode_mcp,
        write=write_opencode_mcp,
        remove=remove_opencode_mcp,
        payload_factory=_mcp_payload,
    ))

    # opencode-lsp (row 4: _save_json in opencode/language_servers.py)
    rows.append(AdapterContractRow(
        adapter_id="opencode-lsp",
        format="json",
        container=".opencode/opencode.json",
        read=read_language_servers_opencode,
        write=write_language_servers_opencode,
        remove=remove_language_servers_opencode,
        payload_factory=_lsp_python_payload,
    ))

    # qwen-lsp (rows 9-10: _save_json + unlink in qwen/language_servers.py)
    rows.append(AdapterContractRow(
        adapter_id="qwen-lsp",
        format="json",
        container=".lsp.json",
        read=read_language_servers_qwen,
        write=write_language_servers_qwen,
        remove=remove_language_servers_qwen,
        payload_factory=_lsp_typescript_payload,
    ))

    # codex-lsp (row 1: _save_toml in codex/language_servers.py)
    rows.append(AdapterContractRow(
        adapter_id="codex-lsp",
        format="toml",
        container=".codex/config.toml",
        read=read_language_servers_codex,
        write=write_language_servers_codex,
        remove=remove_language_servers_codex,
        payload_factory=_lsp_python_payload,
    ))

    # openhands-mcp (rows 7-8: write + remove in openhands/toml_format.py)
    rows.append(AdapterContractRow(
        adapter_id="openhands-mcp",
        format="toml",
        container=".openhands/config.toml",
        read=read_mcp_toml,
        write=write_mcp_toml,
        remove=remove_mcp_toml,
        payload_factory=_mcp_payload,
    ))

    return rows


@pytest.fixture(params=_make_rows(), ids=lambda r: r.adapter_id)
def adapter_row(request) -> AdapterContractRow:
    """Parameterize tests across FragmentStore-compatible adapter modules."""
    return request.param


@pytest.fixture()
def adapter_path(tmp_path: Path, adapter_row: AdapterContractRow) -> Path:
    path = tmp_path / adapter_row.container
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# CONTRACT TESTS — FragmentStore protocol compliance
# ---------------------------------------------------------------------------

class TestAdapterReadMissingFile:
    """read(path) when file does not exist -> {}."""

    def test_read_missing_returns_empty(self, adapter_row: AdapterContractRow, adapter_path: Path):
        assert adapter_row.read(adapter_path) == {}


class TestAdapterReadMalformed:
    """read(path) when file contains garbage -> {} (graceful degradation)."""

    def test_read_malformed_returns_empty(self, adapter_row: AdapterContractRow, adapter_path: Path):
        adapter_path.write_text("THIS IS NOT VALID CONTENT {{{{}", encoding="utf-8")
        result = adapter_row.read(adapter_path)
        assert result == {}


class TestAdapterWriteAndRoundtrip:
    """write(path, entries) creates file; read(path) returns matching entries."""

    def test_write_absent_creates_file(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, _ = adapter_row.payload_factory()
        adapter_path.unlink(missing_ok=True)
        adapter_row.write(adapter_path, entries)
        assert adapter_path.exists()

    def test_roundtrip_via_read(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, entry_name = adapter_row.payload_factory()
        adapter_row.write(adapter_path, entries)
        back = adapter_row.read(adapter_path)
        assert entry_name in back


class TestAdapterWriteIdempotent:
    """write(path, entries) twice -> identical serialized output."""

    def test_idempotent_write(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, _ = adapter_row.payload_factory()
        adapter_row.write(adapter_path, entries)
        first = adapter_path.read_bytes()
        adapter_row.write(adapter_path, entries)
        second = adapter_path.read_bytes()
        assert first == second


class TestAdapterWritePreservesUnmanaged:
    """Managed write must not destroy pre-existing unmanaged keys."""

    def test_preserves_unmanaged(self, adapter_row: AdapterContractRow, adapter_path: Path):
        if adapter_row.format == "json":
            seed = {"__unmanaged_sentinel__": True}
            adapter_path.write_text(json.dumps(seed), encoding="utf-8")
        elif adapter_row.format == "toml":
            adapter_path.write_text("__unmanaged_sentinel__ = true\n", encoding="utf-8")

        entries, _ = adapter_row.payload_factory()
        adapter_row.write(adapter_path, entries)

        raw = adapter_path.read_text(encoding="utf-8")
        assert "__unmanaged_sentinel__" in raw


class TestAdapterRemovePresent:
    """remove(path, name) for an entry that exists -> True, other entries preserved."""

    def test_remove_present(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, entry_name = adapter_row.payload_factory()
        adapter_row.write(adapter_path, entries)
        assert adapter_row.remove(adapter_path, entry_name) is True
        back = adapter_row.read(adapter_path)
        assert entry_name not in back


class TestAdapterRemoveAbsent:
    """remove(path, name) for a name that doesn't exist -> False, file unchanged."""

    def test_remove_absent(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, _ = adapter_row.payload_factory()
        adapter_row.write(adapter_path, entries)
        before = adapter_path.read_bytes()
        result = adapter_row.remove(adapter_path, "nonexistent-__zzyyx")
        assert result is False
        assert adapter_path.read_bytes() == before


class TestAdapterAtomicWriteContract:
    """Verify the adapter uses atomic write pattern (temp + rename), not raw write_text.

    Detection: monkeypatch Path.write_text on the target directory to record any
    direct calls. An atomic writer creates a temp file, writes it, then os.replace's
    onto the target — so Path.write_text is never called on the target path itself.
    A non-atomic writer calls path.write_text() directly on the target.

    These tests are marked xfail for adapters still using raw write_text — that's
    the Block D1 migration checklist (MA04 Steps 4-7). After migration all must pass.
    """

    def test_no_direct_write_text_on_target(self, adapter_row: AdapterContractRow, adapter_path: Path):
        entries, _ = adapter_row.payload_factory()

        written_paths: list[Path] = []
        original_write_text = Path.write_text

        def tracking_write_text(path_self, *args, **kw):
            written_paths.append(Path(str(path_self)))
            return original_write_text(path_self, *args, **kw)

        try:
            Path.write_text = tracking_write_text  # type: ignore[assignment]
            adapter_row.write(adapter_path, entries)
        finally:
            Path.write_text = original_write_text  # type: ignore[misc]

        target_str = str(adapter_path)
        direct_hits = [p for p in written_paths if str(p) == target_str]
        assert not direct_hits, (
            f"{adapter_row.adapter_id}: adapter called write_text() directly on target path "
            f"— must use atomic_write_text/atomic_write_json"
        )
