from __future__ import annotations

from audiagentic.components.optional.coding_lsp import language_registry


def test_all_languages_loaded_from_config() -> None:
    langs = language_registry.all_languages()
    assert {"python", "typescript", "rust", "cpp"} <= set(langs)


def test_python_spec_fields() -> None:
    spec = language_registry.get_language("python")
    assert spec is not None
    assert spec.command == ("pyright-langserver", "--stdio")
    assert ".py" in spec.file_extensions
    assert spec.language_id == "python"
    assert spec.dependency is not None
    assert spec.dependency.id == "pyright"


def test_dependency_cfgs_scoped_to_languages() -> None:
    only_python = language_registry.dependency_cfgs(["python"])
    assert set(only_python) == {"pyright"}
    # a non-enabled language's server never enters the dep set
    assert "clangd" not in only_python


def test_dependency_ids_all() -> None:
    ids = set(language_registry.dependency_ids())
    assert {"pyright", "typescript-language-server", "rust-analyzer", "clangd"} <= ids


def test_server_spec_dict_shape() -> None:
    spec = language_registry.get_language("rust")
    d = language_registry.server_spec_dict(spec)
    assert d["command"] == ["rust-analyzer"]
    assert d["file_extensions"] == [".rs"]
    assert d["label"] == "Rust (rust-analyzer)"
