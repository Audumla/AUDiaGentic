"""MO11 describe_provider composition tests."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.execution import describe_execution_support


def test_describe_execution_support_modes() -> None:
    # hand-written adapter module exists
    assert describe_execution_support("codex")["mode"] == "adapter"
    # declared stub execution block, no adapter module
    aider = describe_execution_support("aider")
    assert aider["mode"] == "stub"
    assert "execution bridge" in aider.get("message", "").lower() or aider.get("declared") == "stub"
    # unsupported declaration
    assert describe_execution_support("roo")["mode"] in {"adapter", "unsupported"}
    # unknown provider
    assert describe_execution_support("no-such-provider")["mode"] == "none"


def test_describe_provider_unknown() -> None:
    result = providers_api.describe_provider(Path("."), "no-such-provider")
    assert result == {
        "provider_id": "no-such-provider",
        "ok": False,
        "reason": "unknown-provider",
    }


def test_describe_provider_full_composition(tmp_path: Path) -> None:
    result = providers_api.describe_provider(tmp_path, "opencode")
    assert result["ok"] is True
    assert result["descriptor"]["provider_id"] == "opencode"
    assert result["execution"]["mode"] in {"adapter", "descriptor"}
    # models section is the mutation-free MO10 read surface
    assert result["models"]["provider_id"] == "opencode"
    assert "ok" in result["models"]
    # config surfaces serialize with the pinned shape
    surfaces = {surface["kind"]: surface for surface in result["config_surfaces"]}
    assert set(surfaces) == {"mcp", "language-servers", "model-endpoints"}
    mcp_surface = surfaces["mcp"]
    assert mcp_surface["configured"] is True
    assert mcp_surface["resolved_path"].endswith("opencode.json")
    assert mcp_surface["path_scope"] in {"project", "home", "absolute"}
    # model-endpoints now declared for opencode (model_config in descriptor)
    assert surfaces["model-endpoints"]["configured"] is True
    # managed registries report names/counts only
    registries = {block["registry"]: block for block in result["managed"]}
    assert set(registries) == {"managed-mcp-servers", "managed-model-endpoints"}
    assert registries["managed-model-endpoints"]["ok"] is True
    assert registries["managed-model-endpoints"]["count"] == 0
    # agents boundary: pointer only, no profile join
    assert result["related_tools"] == ["agent_list_profiles"]
    assert "profiles" not in result


def test_describe_provider_corrupt_registry_surfaces_error(tmp_path: Path) -> None:
    registry_path = (
        tmp_path / ".audiagentic" / "runtime" / "providers" / "managed-model-endpoints.json"
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{corrupt", encoding="utf-8")

    result = providers_api.describe_provider(tmp_path, "opencode")
    registries = {block["registry"]: block for block in result["managed"]}
    assert registries["managed-model-endpoints"]["ok"] is False
    assert registries["managed-model-endpoints"]["error_code"] == "CON-MCFG-001"


def test_describe_provider_no_callable_reprs_or_secrets(tmp_path: Path) -> None:
    result = providers_api.describe_provider(tmp_path, "codex")
    text = json.dumps(result, default=str)
    assert "<function" not in text
    assert "<bound method" not in text
    assert "lambda" not in text


def test_describe_provider_is_read_only(tmp_path: Path) -> None:
    providers_api.describe_provider(tmp_path, "opencode")
    # the only artifact allowed is nothing: no config, no registries, no caches
    created = [
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    ]
    assert created == []
