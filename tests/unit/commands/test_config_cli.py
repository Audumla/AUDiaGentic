from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from audiagentic.commands import bootstrap


class _SurfaceResult:
    def __init__(self, **values: object) -> None:
        self.values = values

    def to_mapping(self) -> dict[str, object]:
        return self.values


def _patch_config_dependencies(monkeypatch, *, provider_errors=None):
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(bootstrap, "global_harness_runtime", lambda: Path("runtime"))
    monkeypatch.setattr(
        bootstrap,
        "refresh_materialized_agent_config",
        lambda target, project_root=None: calls.append(("materialize", target)),
    )
    monkeypatch.setattr(
        bootstrap,
        "request_runtime_reload",
        lambda project_root, reason: calls.append(("reload", reason)),
    )
    monkeypatch.setattr(
        bootstrap,
        "cleanup_runtime",
        lambda target: calls.append(("cleanup", target)) or 0,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        lambda project_root, mode: _SurfaceResult(ok=True, mode=mode),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.mcp.mcp_sync.sync_all_provider_mcp_servers",
        lambda project_root: provider_errors or [],
    )
    return calls


def test_config_refresh_applies_surfaces_and_provider_configs(monkeypatch, tmp_path):
    calls = _patch_config_dependencies(monkeypatch)

    assert bootstrap.cmd_config_sync(Namespace(config_cmd="refresh"), tmp_path) == 0
    assert ("materialize", Path("runtime")) in calls
    assert ("reload", "config-apply") in calls


def test_config_sync_alias_uses_refresh_path(monkeypatch, tmp_path):
    calls = _patch_config_dependencies(monkeypatch)

    assert bootstrap.cmd_config_sync(Namespace(config_cmd="sync"), tmp_path) == 0
    assert ("materialize", Path("runtime")) in calls


def test_config_clean_prunes_surfaces_and_runtime(monkeypatch, tmp_path):
    calls = _patch_config_dependencies(monkeypatch)

    assert bootstrap.cmd_config_sync(Namespace(config_cmd="clean"), tmp_path) == 0
    assert ("cleanup", Path("runtime")) in calls
    assert ("reload", "config-prune") in calls


def test_config_refresh_fails_when_provider_sync_reports_errors(monkeypatch, tmp_path):
    _patch_config_dependencies(monkeypatch, provider_errors=[{"component": "agents", "error": "broken"}])

    assert bootstrap.cmd_config_sync(Namespace(config_cmd="refresh"), tmp_path) == 1
