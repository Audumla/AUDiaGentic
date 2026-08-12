"""CC58: shared lint config projection to native tool files + VS Code settings."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from audiagentic.components.coding_lsp.lint_projection import (
    project_all_lint_config,
    project_python_lint_config,
    project_typescript_lint_config,
    project_vscode_yaml_settings,
    project_yaml_lint_config,
)
from audiagentic.foundation.paths.names import project_linting_dir


def _write_linting_source(project_root: Path, filename: str, data: dict) -> None:
    source_dir = project_linting_dir(project_root)
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / filename).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_project_python_lint_config_writes_native_files(tmp_path: Path):
    _write_linting_source(
        tmp_path,
        "python.yaml",
        {
            "ruff": {
                "src": ["src"],
                "line-length": 100,
                "lint": {"select": ["E", "F"], "ignore": ["E501"]},
            },
            "pyright": {"pythonVersion": "3.10", "typeCheckingMode": "basic"},
        },
    )

    result = project_python_lint_config(tmp_path)

    assert result["ok"] is True
    ruff_toml = (tmp_path / "ruff.toml").read_text(encoding="utf-8")
    assert 'src = ["src"]' in ruff_toml
    assert "line-length = 100" in ruff_toml
    assert "[lint]" in ruff_toml
    assert 'select = ["E", "F"]' in ruff_toml

    pyright_config = json.loads((tmp_path / "pyrightconfig.json").read_text(encoding="utf-8"))
    assert pyright_config == {"pythonVersion": "3.10", "typeCheckingMode": "basic"}


def test_project_python_lint_config_no_source_is_noop(tmp_path: Path):
    result = project_python_lint_config(tmp_path)
    assert result == {"ok": True, "written": []}
    assert not (tmp_path / "ruff.toml").exists()
    assert not (tmp_path / "pyrightconfig.json").exists()


def test_project_yaml_lint_config_writes_yamllint_ignore_rule(tmp_path: Path):
    _write_linting_source(
        tmp_path,
        "yaml.yaml",
        {
            "yaml-language-server": {
                "validate": True,
                "error-rules": [
                    {
                        "key": "line-length",
                        "severity": "ignore",
                        "pattern": "src/audiagentic/config/providers/*.yaml",
                    }
                ],
            }
        },
    )

    result = project_yaml_lint_config(tmp_path)

    assert result["ok"] is True
    yamllint_config = yaml.safe_load((tmp_path / ".yamllint").read_text(encoding="utf-8"))
    assert yamllint_config["rules"]["line-length"]["ignore"] == (
        "src/audiagentic/config/providers/*.yaml"
    )


def test_project_yaml_lint_config_no_error_rules_is_noop(tmp_path: Path):
    _write_linting_source(tmp_path, "yaml.yaml", {"yaml-language-server": {"validate": True}})
    result = project_yaml_lint_config(tmp_path)
    assert result == {"ok": True, "written": []}
    assert not (tmp_path / ".yamllint").exists()


def test_project_vscode_yaml_settings_writes_managed_keys(tmp_path: Path):
    _write_linting_source(
        tmp_path,
        "yaml.yaml",
        {
            "yaml-language-server": {
                "validate": True,
                "completion": True,
                "schema": [{"http://json.schemastore.org/mcp.json": "/**/mcp.json"}],
                "settings": {"yaml": {"customTags": ["!reference sequence"]}},
            }
        },
    )

    result = project_vscode_yaml_settings(tmp_path)

    assert result["ok"] is True
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["yaml.validate"] is True
    assert settings["yaml.completion"] is True
    assert settings["yaml.schemas"] == {"http://json.schemastore.org/mcp.json": "/**/mcp.json"}
    assert settings["yaml.customTags"] == ["!reference sequence"]


def test_project_vscode_yaml_settings_preserves_unmanaged_keys(tmp_path: Path):
    settings_path = tmp_path / ".vscode" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"editor.tabSize": 2}), encoding="utf-8")
    _write_linting_source(
        tmp_path, "yaml.yaml", {"yaml-language-server": {"validate": True}}
    )

    project_vscode_yaml_settings(tmp_path)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["editor.tabSize"] == 2
    assert settings["yaml.validate"] is True


def test_project_typescript_lint_config_writes_tsconfig_and_prettier(tmp_path: Path):
    _write_linting_source(
        tmp_path,
        "typescript.yaml",
        {
            "typescript": {
                "compilerOptions": {"target": "ES2022", "strict": True},
                "format": {
                    "tabSize": 2,
                    "insertSpaces": True,
                    "semi": True,
                    "singleQuote": False,
                    "trailingComma": "es5",
                },
            }
        },
    )

    result = project_typescript_lint_config(tmp_path)

    assert result["ok"] is True
    tsconfig = json.loads((tmp_path / "tsconfig.json").read_text(encoding="utf-8"))
    assert tsconfig["compilerOptions"] == {"target": "ES2022", "strict": True}

    prettier = json.loads((tmp_path / ".prettierrc.json").read_text(encoding="utf-8"))
    assert prettier == {"semi": True, "singleQuote": False, "trailingComma": "es5"}
    # tabSize/insertSpaces are editor-generic, not prettier's own option names --
    # they go to .editorconfig instead, not duplicated here.
    assert "tabSize" not in prettier
    assert "insertSpaces" not in prettier

    editorconfig = (tmp_path / ".editorconfig").read_text(encoding="utf-8")
    assert "root = true" in editorconfig
    assert "[*.{ts,tsx}]" in editorconfig
    assert "indent_style = space" in editorconfig
    assert "indent_size = 2" in editorconfig


def test_project_typescript_lint_config_preserves_existing_tsconfig_keys(tmp_path: Path):
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"include": ["src/**/*.ts"], "compilerOptions": {"strict": False}}),
        encoding="utf-8",
    )
    _write_linting_source(
        tmp_path,
        "typescript.yaml",
        {"typescript": {"compilerOptions": {"strict": True, "target": "ES2022"}}},
    )

    project_typescript_lint_config(tmp_path)

    tsconfig = json.loads((tmp_path / "tsconfig.json").read_text(encoding="utf-8"))
    assert tsconfig["include"] == ["src/**/*.ts"]
    assert tsconfig["compilerOptions"] == {"strict": True, "target": "ES2022"}


def test_project_typescript_lint_config_preserves_other_editorconfig_sections(tmp_path: Path):
    (tmp_path / ".editorconfig").write_text(
        "root = true\n\n[*.py]\nindent_style = space\nindent_size = 4\n",
        encoding="utf-8",
    )
    _write_linting_source(
        tmp_path,
        "typescript.yaml",
        {"typescript": {"format": {"tabSize": 2, "insertSpaces": True}}},
    )

    project_typescript_lint_config(tmp_path)

    editorconfig = (tmp_path / ".editorconfig").read_text(encoding="utf-8")
    assert "[*.py]" in editorconfig
    assert "indent_size = 4" in editorconfig
    assert "[*.{ts,tsx}]" in editorconfig
    assert "indent_size = 2" in editorconfig
    assert editorconfig.count("root = true") == 1


def test_project_typescript_lint_config_no_source_is_noop(tmp_path: Path):
    result = project_typescript_lint_config(tmp_path)
    assert result == {"ok": True, "written": []}
    assert not (tmp_path / "tsconfig.json").exists()


def test_project_all_lint_config_aggregates_all_targets(tmp_path: Path):
    _write_linting_source(tmp_path, "python.yaml", {"ruff": {"line-length": 100}})
    _write_linting_source(
        tmp_path,
        "typescript.yaml",
        {"typescript": {"compilerOptions": {"strict": True}}},
    )
    _write_linting_source(
        tmp_path,
        "yaml.yaml",
        {
            "yaml-language-server": {
                "validate": True,
                "error-rules": [
                    {"key": "line-length", "severity": "ignore", "pattern": "*.yaml"}
                ],
            }
        },
    )

    result = project_all_lint_config(tmp_path)

    assert result["ok"] is True
    assert (tmp_path / "ruff.toml").exists()
    assert (tmp_path / "tsconfig.json").exists()
    assert (tmp_path / ".yamllint").exists()
    assert (tmp_path / ".vscode" / "settings.json").exists()
