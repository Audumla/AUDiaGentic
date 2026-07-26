"""Provider-layer recipe steps: managed-mcp composes the shielded family."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import audiagentic.components.providers  # noqa: F401 — registers the managed-mcp step
from audiagentic.foundation.steps.factory import registered_types, step_schema
from audiagentic.foundation.toolchains.recipe_execution import execute_recipe_mode


def test_managed_steps_registered_with_schema():
    for name in ("managed-mcp", "managed-hooks", "managed-plugin"):
        assert name in registered_types(), name
        assert step_schema(name) is not None, name


def test_managed_hooks_step_composes_family(tmp_path):
    recipe = tmp_path / "hooks.yaml"
    recipe.write_text(
        """
recipe-id: demo-hooks
recipe-version: "1.0.0"
parameters: []
lifecycle:
  install-steps:
    - type: managed-hooks
      id: hooks
      provider: codex
      ownership-scope: hindsight
      entries:
        - {managed-id: "hindsight/sessionstart", event: SessionStart, command: "python s.py", timeout: 5}
        - {managed-id: "hindsight/stop", event: Stop, command: "python r.py", timeout: 30}
""",
        encoding="utf-8",
    )
    seen: list[tuple] = []

    def fake(project_root, provider_id, *, mode, request):
        seen.append((provider_id, mode, request.ownership_scope,
                     tuple((e.event, e.command) for e in request.entries)))
        return type("R", (), {"ok": True, "error_code": None})()

    with mock.patch("audiagentic.components.providers.providers_api.manage_hook_entries", fake):
        result = execute_recipe_mode(recipe, {}, "apply", context={"project_root": str(tmp_path)})

    assert result.success
    assert seen == [("codex", "apply", "hindsight",
                     (("SessionStart", "python s.py"), ("Stop", "python r.py")))]


def test_managed_plugin_step_composes_family(tmp_path):
    recipe = tmp_path / "plugin.yaml"
    recipe.write_text(
        """
recipe-id: demo-plugin
recipe-version: "1.0.0"
parameters: []
lifecycle:
  install-steps:
    - type: managed-plugin
      id: plugin
      provider: opencode
      entry-id: ag-hindsight
      ownership-scope: hindsight
""",
        encoding="utf-8",
    )
    seen: list[tuple] = []

    def fake(project_root, provider_id, *, mode, request):
        seen.append((provider_id, mode, request.entry_id, request.ownership_scope))
        return type("R", (), {"ok": True, "error_code": None})()

    with mock.patch("audiagentic.components.providers.providers_api.manage_plugin_entry", fake):
        result = execute_recipe_mode(recipe, {}, "apply", context={"project_root": str(tmp_path)})

    assert result.success
    assert seen == [("opencode", "apply", "ag-hindsight", "hindsight")]


def _write_recipe(tmp_path: Path, host_path: Path) -> Path:
    recipe = tmp_path / "integration.yaml"
    recipe.write_text(
        f"""
recipe-id: demo-hindsight
recipe-version: "1.0.0"
parameters:
  - {{name: URL, required: true}}
  - {{name: BANK_ID, default: audiagentic}}
lifecycle:
  install-steps:
    - type: managed-mcp
      id: entry
      provider: pi
      managed-id: ag-hindsight
      ownership-scope: "memory/hindsight/hindsight"
      name: hindsight
      url: "{{URL}}/mcp"
      transport: http
      headers: {{X-Bank-Id: "{{BANK_ID}}"}}
  configure-steps:
    - type: config-set
      id: host
      path: "{host_path.as_posix()}"
      key-path: [host]
      value: {{enabled: true}}
  uninstall-steps:
    - type: managed-mcp
      id: entry-prune
      provider: pi
      managed-id: ag-hindsight
      ownership-scope: "memory/hindsight/hindsight"
      name: hindsight
      url: "{{URL}}/mcp"
      transport: http
      mode: prune
""",
        encoding="utf-8",
    )
    return recipe


def test_recipe_composes_managed_family_and_owned_file(tmp_path):
    host = tmp_path / "host.json"
    recipe = _write_recipe(tmp_path, host)

    calls: list[tuple] = []

    def fake_manage(project_root, provider_id, *, mode, request):
        calls.append((provider_id, mode, request.ownership_scope,
                      tuple(e.managed_id for e in request.entries),
                      request.entries[0].url if request.entries else None))
        return type("R", (), {"ok": True, "error_code": None})()

    with mock.patch(
        "audiagentic.components.providers.providers_api.manage_mcp_entries", fake_manage,
    ):
        result = execute_recipe_mode(
            recipe, {"URL": "http://hs:1"}, "apply", context={"project_root": str(tmp_path)},
        )

    assert result.success
    # provider-owned config went through the shielded family (not a raw write)
    assert calls == [("pi", "apply", "memory/hindsight/hindsight", ("ag-hindsight",), "http://hs:1/mcp")]
    # capability-owned file was written directly
    assert json.loads(host.read_text(encoding="utf-8")) == {"host": {"enabled": True}}


def test_managed_mcp_prune_mode_removes_entry(tmp_path):
    host = tmp_path / "host.json"
    recipe = _write_recipe(tmp_path, host)

    modes: list[str] = []

    def fake_manage(project_root, provider_id, *, mode, request):
        modes.append(mode)
        return type("R", (), {"ok": True, "error_code": None})()

    with mock.patch(
        "audiagentic.components.providers.providers_api.manage_mcp_entries", fake_manage,
    ):
        result = execute_recipe_mode(
            recipe, {"URL": "http://hs:1"}, "prune", context={"project_root": str(tmp_path)},
        )

    assert result.success
    assert modes == ["prune"]


def test_managed_mcp_requires_project_root_in_context(tmp_path):
    host = tmp_path / "host.json"
    recipe = _write_recipe(tmp_path, host)

    result = execute_recipe_mode(recipe, {"URL": "http://hs:1"}, "apply")  # no context
    assert not result.success
