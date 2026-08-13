"""Tests for canonical prompt Work admission and prompt rendering."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agent_jobs.prompt_launch import (
    _render_launch_prompt,
    launch_prompt_request,
)
from audiagentic.components.agent_jobs.prompt_parser import validate_prompt_launch_request
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _setup_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    config_dir = project_root / ".audiagentic" / "config"
    (config_dir / "providers").mkdir(parents=True)
    (config_dir / "project.yaml").write_text(
        "contract-version: v1\nproject-id: test-project\nprompt-launch:\n  allow-adhoc-target: true\n",
        encoding="utf-8",
    )
    (config_dir / "providers" / "codex.yaml").write_text(
        "install-mode: external-configured\naccess-mode: cli\ndefault-model: gpt-5.4-mini\n",
        encoding="utf-8",
    )
    return project_root


def _request(overrides: dict | None = None) -> dict:
    request = {
        "contract-version": "v1",
        "prompt-id": "prm_test_0001",
        "source": {
            "kind": "interactive-prompt",
            "surface": "cli",
            "provider-id": "codex",
            "session-id": None,
            "model-id": None,
            "model-alias": None,
        },
        "tag": "adhoc",
        "target": {"kind": "packet", "packet-id": "PKT-1"},
        "workflow-profile": "standard",
        "prompt-body": "Continue implementing the packet.\n",
        "context-id": "ctx_prompt_launch",
    }
    request.update(overrides or {})
    return request


class TestSchema:
    def test_prompt_body_alone_valid(self) -> None:
        assert validate_prompt_launch_request(_request()) == []

    def test_template_file_alone_valid(self) -> None:
        request = _request({"prompt-template-file": "prompts/t.md"})
        del request["prompt-body"]
        assert validate_prompt_launch_request(request) == []

    def test_both_rejected(self) -> None:
        assert validate_prompt_launch_request(
            _request({"prompt-template-file": "prompts/t.md"})
        ) != []

    def test_neither_rejected(self) -> None:
        request = _request()
        del request["prompt-body"]
        assert validate_prompt_launch_request(request) != []


def test_prompt_launch_requires_context(tmp_path: Path) -> None:
    project_root = _setup_project(tmp_path)
    request = _request()
    del request["context-id"]

    with pytest.raises(AudiaGenticError, match="require a context-id"):
        launch_prompt_request(project_root, request)


def test_prompt_launch_submits_deterministic_work_without_legacy_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = _setup_project(tmp_path)
    calls: list[dict] = []

    class Gateway:
        def submit_agent_work(self, root, context_id, message, **kwargs):
            calls.append({"root": root, "context_id": context_id, "message": message, **kwargs})
            return {"work_id": kwargs["work_id"], "context_id": context_id, "state": "active"}

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.client.get_gateway_client",
        lambda _root: Gateway(),
    )

    first = launch_prompt_request(project_root, _request())
    second = launch_prompt_request(project_root, _request())

    assert first["status"] == second["status"] == "submitted"
    assert first["work-id"] == second["work-id"]
    assert calls[0]["message"]["message_id"] == "prompt:prm_test_0001"
    assert calls[0]["message"]["inputs"]["prompt-provenance"]["surface"] == "cli"
    assert not (project_root / ".audiagentic" / "runtime" / "jobs").exists()


def test_inline_prompt_rendering_is_byte_identical(tmp_path: Path) -> None:
    project_root = _setup_project(tmp_path)
    body = "Continue implementing the packet.\n\n  Indented detail line.\n"
    prepared = _render_launch_prompt(
        project_root, _request({"prompt-body": body}), job_id="work_1", provider_id="codex", model_id="gpt-5.4-mini"
    )
    assert prepared["prompt-body"] == body
    assert "context-id" in prepared


def test_prompt_context_renders_without_persisting_context(tmp_path: Path) -> None:
    project_root = _setup_project(tmp_path)
    prepared = _render_launch_prompt(
        project_root,
        _request({"prompt-body": "Job {job.id} on {agent.provider_id}: {metadata.ticket}", "context": {"ticket": "TCK-42"}}),
        job_id="work_1",
        provider_id="codex",
        model_id="gpt-5.4-mini",
    )
    assert prepared["prompt-body"] == "Job work_1 on codex: TCK-42"
    assert "context" not in prepared


def test_missing_template_file_raises(tmp_path: Path) -> None:
    project_root = _setup_project(tmp_path)
    request = _request({"prompt-template-file": ".audiagentic/prompts/nope.md"})
    del request["prompt-body"]
    with pytest.raises(AudiaGenticError, match="template"):
        _render_launch_prompt(
            project_root, request, job_id="work_1", provider_id="codex", model_id="gpt-5.4-mini"
        )


def test_unresolved_placeholder_raises(tmp_path: Path) -> None:
    project_root = _setup_project(tmp_path)
    with pytest.raises(AudiaGenticError) as exc_info:
        _render_launch_prompt(
            project_root,
            _request({"prompt-body": "Missing {does.not.exist}"}),
            job_id="work_1",
            provider_id="codex",
            model_id="gpt-5.4-mini",
        )
    assert exc_info.value.code == "VAL-TPL-001"
