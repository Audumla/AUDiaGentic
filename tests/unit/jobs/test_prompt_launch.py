"""Tests for direct-launch prompt context + template rendering (EDJ25)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agent_jobs.prompt_launch import (
    launch_prompt_request,
    prompt_launch_path,
)
from audiagentic.components.agent_jobs.prompt_parser import (
    validate_prompt_launch_request,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _setup_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    config_dir = project_root / ".audiagentic" / "config"
    (config_dir / "providers").mkdir(parents=True)
    (config_dir / "project.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "project-id: test-project",
                "prompt-launch:",
                "  allow-adhoc-target: true",
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "providers" / "codex.yaml").write_text(
        "\n".join(
            [
                "install-mode: external-configured",
                "access-mode: cli",
                "default-model: gpt-5.4-mini",
            ]
        ),
        encoding="utf-8",
    )
    return project_root


def _request(overrides: dict | None = None) -> dict:
    base = {
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
    }
    if overrides:
        base.update(overrides)
    return base


def _persisted_launch_request(project_root: Path, job_id: str) -> dict:
    return json.loads(
        prompt_launch_path(project_root, job_id).read_text(encoding="utf-8")
    )


class TestSchemaXor:
    """Exactly one of prompt-body / prompt-template-file is required."""

    def test_prompt_body_alone_valid(self) -> None:
        assert validate_prompt_launch_request(_request()) == []

    def test_template_file_alone_valid(self) -> None:
        request = _request({"prompt-template-file": "prompts/t.md"})
        del request["prompt-body"]
        assert validate_prompt_launch_request(request) == []

    def test_both_rejected(self) -> None:
        request = _request({"prompt-template-file": "prompts/t.md"})
        assert validate_prompt_launch_request(request) != []

    def test_neither_rejected(self) -> None:
        request = _request()
        del request["prompt-body"]
        assert validate_prompt_launch_request(request) != []

    def test_execution_profile_id_and_context_accepted(self) -> None:
        request = _request(
            {"execution-profile-id": "codex-default", "context": {"anything": {"goes": 1}}}
        )
        assert validate_prompt_launch_request(request) == []


class TestInlinePassthrough:
    """Compatibility keystone: template-free inline text is byte-identical."""

    def test_no_placeholder_body_unchanged(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        body = "Continue implementing the packet.\n\n  Indented detail line.\n"
        result = launch_prompt_request(project_root, _request({"prompt-body": body}))

        assert result["status"] == "created"
        persisted = _persisted_launch_request(project_root, result["job-id"])
        assert persisted["prompt-body"] == body, "template-free body must be byte-identical"


class TestInlineRendering:
    def test_placeholders_render_with_caller_context(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        request = _request(
            {
                "prompt-body": "Job {job.id} on {agent.provider_id}: {metadata.ticket}",
                "context": {"ticket": "TCK-42"},
            }
        )
        result = launch_prompt_request(project_root, request)

        assert result["status"] == "created"
        job_id = result["job-id"]
        persisted = _persisted_launch_request(project_root, job_id)
        assert persisted["prompt-body"] == f"Job {job_id} on codex: TCK-42"

    def test_caller_context_not_persisted(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        request = _request(
            {"prompt-body": "Ticket {metadata.ticket}", "context": {"ticket": "TCK-1"}}
        )
        result = launch_prompt_request(project_root, request)

        persisted = _persisted_launch_request(project_root, result["job-id"])
        assert "context" not in persisted

    def test_unresolved_placeholder_raises_VAL_TPL_001(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        request = _request({"prompt-body": "Missing {does.not.exist}"})
        with pytest.raises(AudiaGenticError) as exc_info:
            launch_prompt_request(project_root, request)
        assert exc_info.value.code == "VAL-TPL-001"


class TestFileTemplateRendering:
    def test_template_file_renders_through_shared_context(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        tmpl_dir = project_root / ".audiagentic" / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "launch.md").write_text(
            "Implement for job {job.id} in project {project.id}.\n", encoding="utf-8"
        )

        request = _request({"prompt-template-file": ".audiagentic/prompts/launch.md"})
        del request["prompt-body"]
        result = launch_prompt_request(project_root, request)

        assert result["status"] == "created"
        job_id = result["job-id"]
        persisted = _persisted_launch_request(project_root, job_id)
        assert persisted["prompt-body"] == (
            f"Implement for job {job_id} in project test-project."
        )

    def test_missing_template_file_raises_IO_PTMPL_001(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        request = _request({"prompt-template-file": ".audiagentic/prompts/nope.md"})
        del request["prompt-body"]
        with pytest.raises(AudiaGenticError) as exc_info:
            launch_prompt_request(project_root, request)
        assert exc_info.value.code == "IO-PTMPL-001"

    def test_containment_escape_raises_IO_PATH_001(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        request = _request({"prompt-template-file": "../../../etc/passwd"})
        del request["prompt-body"]
        with pytest.raises(AudiaGenticError) as exc_info:
            launch_prompt_request(project_root, request)
        assert exc_info.value.code == "IO-PATH-001"


class TestSessionData:
    def test_session_data_available_to_templates(self, tmp_path: Path) -> None:
        project_root = _setup_project(tmp_path)
        # Seed a session input record under the jobs runtime tree
        job_dir = project_root / ".audiagentic" / "runtime" / "jobs" / "job_prior"
        job_dir.mkdir(parents=True)
        (job_dir / "input.ndjson").write_text(
            json.dumps({"job-id": "job_prior", "note": "prior input"}) + "\n",
            encoding="utf-8",
        )

        request = _request({"prompt-body": "Session {session.session_id}"})
        request["source"]["session-id"] = "sess-77"
        result = launch_prompt_request(project_root, request)

        persisted = _persisted_launch_request(project_root, result["job-id"])
        assert persisted["prompt-body"] == "Session sess-77"
