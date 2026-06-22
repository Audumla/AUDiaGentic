from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.adapters.opencode.language_servers import (
    read_language_servers_opencode,
    remove_language_servers_opencode,
    write_language_servers_opencode,
)
from audiagentic.components.providers.adapters.qwen.language_servers import (
    read_language_servers_qwen,
    remove_language_servers_qwen,
    write_language_servers_qwen,
)
from audiagentic.components.providers.descriptors.base import LanguageServerEntry

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
    # opencode keys its built-in Python server "pyright", not "python"
    assert "python" not in data["lsp"]
    assert data["lsp"]["pyright"]["command"] == ["pyright-langserver", "--stdio"]
    assert data["lsp"]["pyright"]["extensions"] == [".py", ".pyi"]
    assert data["lsp"]["pyright"]["initialization"] == {"python": {"analysis": "basic"}}

    # read maps the opencode key back to our language id
    back = read_language_servers_opencode(path)
    assert "pyright" not in back
    assert back["python"].command == ["pyright-langserver", "--stdio"]
    assert back["python"].file_extensions == [".py", ".pyi"]

    # remove by our language id finds the mapped opencode key
    assert remove_language_servers_opencode(path, "python") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    # the empty container is dropped entirely, not left as "lsp": {}
    assert "lsp" not in data
    assert data["mcp"] == {"ag-lsp": {"command": "x"}}


def test_opencode_maps_cpp_to_clangd(tmp_path: Path) -> None:
    path = tmp_path / ".opencode" / "opencode.json"
    path.parent.mkdir(parents=True)
    cpp = LanguageServerEntry(language="cpp", command=["clangd"], file_extensions=[".cpp", ".h"])

    write_language_servers_opencode(path, {"cpp": cpp})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "cpp" not in data["lsp"]
    assert data["lsp"]["clangd"]["command"] == ["clangd"]
    assert read_language_servers_opencode(path)["cpp"].command == ["clangd"]
    assert remove_language_servers_opencode(path, "cpp") is True


def test_opencode_passthrough_when_key_matches(tmp_path: Path) -> None:
    # typescript and rust already match opencode's built-in keys — no mapping.
    path = tmp_path / ".opencode" / "opencode.json"
    path.parent.mkdir(parents=True)
    ts = LanguageServerEntry(
        language="typescript",
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx"],
    )
    write_language_servers_opencode(path, {"typescript": ts})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "typescript" in data["lsp"]
    assert read_language_servers_opencode(path)["typescript"].file_extensions == [".ts", ".tsx"]


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


def test_qwen_removes_dedicated_file_when_empty(tmp_path: Path) -> None:
    # The qwen LS config is a dedicated file keyed at the root; removing the last
    # language deletes the file rather than leaving an empty "{}".
    path = tmp_path / ".lsp.json"
    write_language_servers_qwen(path, {"python": _PY})
    assert path.exists()

    assert remove_language_servers_qwen(path, "python") is True
    assert not path.exists()


def test_qwen_skips_empty_command(tmp_path: Path) -> None:
    path = tmp_path / ".lsp.json"
    empty = LanguageServerEntry(language="bad", command=[], file_extensions=[".x"])
    write_language_servers_qwen(path, {"bad": empty})
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assert "bad" not in data
