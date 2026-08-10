"""Project shared lint config (.audiagentic/config/linting/) to native tool files.

Two different kinds of output, kept deliberately separate (CC58):

1. Native tool config -- ruff.toml, pyrightconfig.json, .yamllint,
   tsconfig.json, .prettierrc.json, .editorconfig -- read directly by
   ruff/pyright/yamllint/tsc/typescript-language-server/prettier themselves
   (and, through them, by both AUDiaGentic's LSP-managed harness sessions and
   VS Code's own built-in/Pylance/ruff/Prettier support). .editorconfig in
   particular is a real cross-editor standard, not a VS Code convention.
   Nothing in this category is VS Code-specific.
2. .vscode/settings.json glue -- the one part that genuinely only applies to
   VS Code (yaml-language-server settings the redhat.vscode-yaml extension
   reads from workspace settings). This delegates to
   providers.surfaces.host_settings, the same host-adapter-routed module
   extensions_json.py uses, so no editor path literals live here either.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import (
    atomic_write_json,
    atomic_write_text,
    load_json_file,
    load_yaml_file,
    save_yaml_file,
)
from audiagentic.foundation.paths.names import project_linting_dir

logger = logging.getLogger(__name__)

# Prettier's own real option names (verified against prettier's documented
# config schema) -- deliberately excludes tabWidth/useTabs, which we project
# to .editorconfig instead so there's one source of truth for indentation,
# not two that can drift.
_PRETTIER_KEYS = frozenset(
    {"semi", "singleQuote", "trailingComma", "printWidth", "bracketSpacing", "arrowParens"}
)

_TS_EDITORCONFIG_HEADER = "*.{ts,tsx}"


def _load_lint_source(project_root: Path, filename: str) -> dict[str, Any]:
    return load_yaml_file(project_linting_dir(project_root) / filename)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value)!r}")


def _render_toml(data: dict[str, Any]) -> str:
    """Render a flat dict + one level of nested tables into TOML text.

    Purpose-built for ruff.toml's shape (top-level scalars/arrays plus a
    handful of one-level-deep sub-tables like [lint]) -- not a general TOML
    serializer.
    """
    top_lines: list[str] = []
    table_blocks: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            table_lines = [f"[{key}]"]
            for sub_key, sub_value in value.items():
                table_lines.append(f"{sub_key} = {_toml_scalar(sub_value)}")
            table_blocks.append("\n".join(table_lines))
        else:
            top_lines.append(f"{key} = {_toml_scalar(value)}")
    sections = [s for s in ("\n".join(top_lines), *table_blocks) if s]
    return "\n\n".join(sections) + "\n"


def project_python_lint_config(project_root: Path) -> dict[str, Any]:
    """Project python.yaml's ruff/pyright blocks to ruff.toml + pyrightconfig.json."""
    source = _load_lint_source(project_root, "python.yaml")
    written: list[str] = []

    ruff = source.get("ruff")
    if isinstance(ruff, dict) and ruff:
        ruff_path = project_root / "ruff.toml"
        atomic_write_text(ruff_path, _render_toml(ruff))
        written.append(str(ruff_path))

    pyright = source.get("pyright")
    if isinstance(pyright, dict) and pyright:
        pyright_path = project_root / "pyrightconfig.json"
        atomic_write_json(pyright_path, pyright, sort_keys=False)
        written.append(str(pyright_path))

    return {"ok": True, "written": written}


def project_yaml_lint_config(project_root: Path) -> dict[str, Any]:
    """Project yaml.yaml's error-rules to a native .yamllint file.

    yaml-language-server has no "line-length" concept of its own (verified
    against the installed package -- it isn't in yamlSettings.d.ts /
    settingsHandlers.js); line-length is a yamllint rule, and yamllint
    supports scoping a rule off for specific files via a per-rule ``ignore``
    glob. That's what "suppress line-length for provider YAML descriptors"
    actually maps to.
    """
    source = _load_lint_source(project_root, "yaml.yaml")
    error_rules = source.get("yaml-language-server", {}).get("error-rules", [])
    if not isinstance(error_rules, list) or not error_rules:
        return {"ok": True, "written": []}

    rules: dict[str, Any] = {}
    for rule in error_rules:
        if not isinstance(rule, dict):
            continue
        key = rule.get("key")
        pattern = rule.get("pattern")
        if not isinstance(key, str) or not isinstance(pattern, str):
            continue
        if rule.get("severity") == "ignore":
            rules[key] = {"ignore": pattern}

    if not rules:
        return {"ok": True, "written": []}

    yamllint_path = project_root / ".yamllint"
    save_yaml_file(yamllint_path, {"rules": rules}, atomic=True)
    return {"ok": True, "written": [str(yamllint_path)]}


def _merge_editorconfig_section(existing_text: str, header: str, body_lines: list[str]) -> str:
    """Insert or replace a bracketed [header] section, preserving all other sections.

    EditorConfig is a real cross-editor standard (VS Code, IntelliJ, vim,
    emacs all read it natively) -- not a VS Code-only file -- so indentation
    settings live here rather than in .vscode/settings.json.
    """
    lines = existing_text.splitlines()
    new_section = [f"[{header}]", *body_lines]

    start: int | None = None
    end = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"[{header}]":
            start = i
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = i
            break

    if start is None:
        result = [*lines, *([""] if lines and lines[-1].strip() else []), *new_section]
    else:
        result = [*lines[:start], *new_section, *lines[end:]]

    if not any(line.strip().startswith("root") for line in result):
        result = ["root = true", "", *result]

    return "\n".join(result).rstrip() + "\n"


def project_typescript_lint_config(project_root: Path) -> dict[str, Any]:
    """Project typescript.yaml to tsconfig.json + .prettierrc.json + .editorconfig.

    All three are native tool config -- tsc/typescript-language-server read
    tsconfig.json directly, prettier reads .prettierrc.json directly, and
    .editorconfig is a cross-editor standard -- so none of this is gated
    behind a VS Code-only path, same as the python projection above.
    tsconfig.json and .prettierrc.json are merged (only the managed keys are
    overwritten) since a real TS project commonly hand-extends tsconfig.json
    with include/exclude/references that must survive re-projection.
    """
    source = _load_lint_source(project_root, "typescript.yaml")
    ts = source.get("typescript")
    written: list[str] = []
    if not isinstance(ts, dict) or not ts:
        return {"ok": True, "written": written}

    compiler_options = ts.get("compilerOptions")
    if isinstance(compiler_options, dict) and compiler_options:
        tsconfig_path = project_root / "tsconfig.json"
        existing = load_json_file(tsconfig_path)
        existing["compilerOptions"] = compiler_options
        atomic_write_json(tsconfig_path, existing, sort_keys=False)
        written.append(str(tsconfig_path))

    format_block = ts.get("format")
    if isinstance(format_block, dict) and format_block:
        prettier_updates = {k: v for k, v in format_block.items() if k in _PRETTIER_KEYS}
        if prettier_updates:
            prettier_path = project_root / ".prettierrc.json"
            existing_prettier = load_json_file(prettier_path)
            existing_prettier.update(prettier_updates)
            atomic_write_json(prettier_path, existing_prettier, sort_keys=True)
            written.append(str(prettier_path))

        indent_size = format_block.get("tabSize")
        insert_spaces = format_block.get("insertSpaces")
        if indent_size is not None or insert_spaces is not None:
            body_lines: list[str] = []
            if insert_spaces is not None:
                body_lines.append(f"indent_style = {'space' if insert_spaces else 'tab'}")
            if indent_size is not None:
                body_lines.append(f"indent_size = {indent_size}")
            editorconfig_path = project_root / ".editorconfig"
            existing_text = (
                editorconfig_path.read_text(encoding="utf-8")
                if editorconfig_path.exists()
                else ""
            )
            new_text = _merge_editorconfig_section(
                existing_text, _TS_EDITORCONFIG_HEADER, body_lines
            )
            atomic_write_text(editorconfig_path, new_text)
            written.append(str(editorconfig_path))

    return {"ok": True, "written": written}


def project_vscode_yaml_settings(project_root: Path) -> dict[str, Any]:
    """Project yaml.yaml's yaml-language-server block to .vscode/settings.json.

    VS Code-only: the redhat.vscode-yaml extension reads these exact
    "yaml.*" workspace settings keys (validate, completion, schemas,
    customTags -- confirmed against the installed yaml-language-server
    package's settingsHandlers.js). The CLI harness gets the equivalent
    values through its own LSP initialization path, not this file.
    """
    source = _load_lint_source(project_root, "yaml.yaml")
    lsp_settings = source.get("yaml-language-server", {})
    if not isinstance(lsp_settings, dict) or not lsp_settings:
        return {"ok": True, "written": []}

    updates: dict[str, Any] = {}
    if "validate" in lsp_settings:
        updates["yaml.validate"] = lsp_settings["validate"]
    if "completion" in lsp_settings:
        updates["yaml.completion"] = lsp_settings["completion"]

    schema_list = lsp_settings.get("schema")
    if isinstance(schema_list, list) and schema_list:
        schemas: dict[str, Any] = {}
        for entry in schema_list:
            if isinstance(entry, dict):
                schemas.update(entry)
        if schemas:
            updates["yaml.schemas"] = schemas

    custom_tags = lsp_settings.get("settings", {}).get("yaml", {}).get("customTags")
    if custom_tags is not None:
        updates["yaml.customTags"] = custom_tags

    if not updates:
        return {"ok": True, "written": []}

    from audiagentic.components.providers.surfaces.host_settings import write_host_settings

    path = write_host_settings(project_root, updates, host_id="vscode")
    return {"ok": True, "written": [str(path)], "keys": sorted(updates.keys())}


def project_all_lint_config(project_root: Path) -> dict[str, Any]:
    """Project every shared lint source to its native/host targets.

    Idempotent -- safe to re-run any time the shared linting YAML changes,
    not just at install time.
    """
    results = {
        "python": project_python_lint_config(project_root),
        "typescript": project_typescript_lint_config(project_root),
        "yaml-native": project_yaml_lint_config(project_root),
        "yaml-vscode": project_vscode_yaml_settings(project_root),
    }
    ok = all(result.get("ok", False) for result in results.values())
    return {"ok": ok, "results": results}


__all__ = [
    "project_python_lint_config",
    "project_typescript_lint_config",
    "project_yaml_lint_config",
    "project_vscode_yaml_settings",
    "project_all_lint_config",
]
