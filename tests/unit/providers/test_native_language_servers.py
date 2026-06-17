from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.optional.providers.adapters.opencode.language_servers import (
    read_language_servers_opencode,
    remove_language_servers_opencode,
    write_language_servers_opencode,
)
from audiagentic.components.optional.providers.adapters.qwen.language_servers import (
    read_language_servers_qwen,
    remove_language_servers_qwen,
    write_language_servers_qwen,
)
from audiagentic.components.optional.providers.descriptors.base import LanguageServerEntry

_PY = LanguageServerEntry(
    language="python",
    command=["pyright-langserver", "--stdio"],
    file_extensions=[".py", ".pyi"],
    settings={"python": {"analysis": "basic"}},
)


def test_opencode_roundtrip_and_preserves_mcp(tmp_path: Path) -> None:
    path = tmp_path / ".opencode" / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcp": {"ag-lsp": {"command": "x"}}}), encoding="utf-8")

    write_language_servers_opencode(path, {"python": _PY})

    data = json.loads(path.read_text(encoding="utf-8"))
    # existing mcp block preserved
    assert data["mcp"] == {"ag-lsp": {"command": "x"}}
    assert data["lsp"]["python"]["command"] == ["pyright-langserver", "--stdio"]
    assert data["lsp"]["python"]["extensions"] == [".py", ".pyi"]
    assert data["lsp"]["python"]["initialization"] == {"python": {"analysis": "basic"}}

    back = read_language_servers_opencode(path)
    assert back["python"].command == ["pyright-langserver", "--stdio"]
    assert back["python"].file_extensions == [".py", ".pyi"]

    assert remove_language_servers_opencode(path, "python") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["lsp"] == {}
    assert data["mcp"] == {"ag-lsp": {"command": "x"}}


def test_qwen_roundtrip_string_command_split(tmp_path: Path) -> None:
    path = tmp_path / ".lsp.json"
    path.write_text(json.dumps({"typescript": {"command": "user-server"}}), encoding="utf-8")

    write_language_servers_qwen(path, {"python": _PY})

    data = json.loads(path.read_text(encoding="utf-8"))
    # user-added language preserved
    assert data["typescript"] == {"command": "user-server"}
    # command split into string + args
    assert data["python"]["command"] == "pyright-langserver"
    assert data["python"]["args"] == ["--stdio"]
    assert data["python"]["extensionToLanguage"] == {".py": "python", ".pyi": "python"}

    back = read_language_servers_qwen(path)
    assert back["python"].command == ["pyright-langserver", "--stdio"]
    assert set(back["python"].file_extensions) == {".py", ".pyi"}

    assert remove_language_servers_qwen(path, "python") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "python" not in data
    assert data["typescript"] == {"command": "user-server"}


def test_qwen_skips_empty_command(tmp_path: Path) -> None:
    path = tmp_path / ".lsp.json"
    empty = LanguageServerEntry(language="bad", command=[], file_extensions=[".x"])
    write_language_servers_qwen(path, {"bad": empty})
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assert "bad" not in data
