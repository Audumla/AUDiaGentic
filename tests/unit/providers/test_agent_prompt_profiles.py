from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.base_runner import default_build_prompt
from audiagentic.components.agents.gateway.queue.dispatch import _build_packet_ctx
from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _legacy(ctx: dict, cfg: dict, *, provider_id: str, title: str) -> str:
    body = ctx.get("prompt-body")
    prompt = (
        f"Execution request for {title}. "
        f"request={ctx.get('request-id')} "
        f"provider={ctx.get('provider-id', provider_id)} "
        f"model={cfg.get('default-model')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if body:
        prompt += f" Prompt body: {str(body).strip()}"
    return prompt.strip()


def test_default_profile_is_byte_identical_to_legacy():
    body = "Implement café — résumé"
    ctx = {
        "job-id": "job-1", "packet-id": "packet-1", "provider-id": "pi",
        "workflow-profile": "standard", "prompt-body": body,
    }
    cfg = {"default-model": "qwen3.6-27b-0"}
    actual = default_build_prompt(ctx, cfg, provider_id="pi", title="Pi")
    expected = _legacy(ctx, cfg, provider_id="pi", title="Pi")
    assert actual.encode("utf-8") == expected.encode("utf-8")


@pytest.mark.parametrize("body", [None, "", " ", "\n"])
def test_empty_prompt_body_is_rejected(body):
    with pytest.raises(AudiaGenticError, match="non-empty prompt body"):
        default_build_prompt(
            {"prompt-body": body, "working-root": "."},
            {"default-model": "m"}, provider_id="pi", title="Pi",
        )


def test_gateway_minimum_packet_preserves_none_coercion():
    packet = _build_packet_ctx(
        Path("."),
        {"request-id": "r", "prompt-body": "x"},
        {"profile_id": "p", "provider_id": "pi", "params": {}},
        {"model-id": None},
        dispatch_prompt="x",
    )
    actual = default_build_prompt(packet, {"default-model": None}, provider_id="pi", title="Pi")
    expected = _legacy(packet, {"default-model": None}, provider_id="pi", title="Pi")
    assert actual.encode("utf-8") == expected.encode("utf-8")


def test_review_profile_is_selected_without_project_override(tmp_path):
    override = tmp_path / ".audiagentic" / "prompts" / "prompt-profile"
    override.mkdir(parents=True)
    (override / "review-with-body.md").write_text("MALICIOUS {prompt-body}", encoding="utf-8")
    ctx = {
        "job-id": "job-1", "packet-id": "packet-1", "provider-id": "pi",
        "workflow-profile": "standard", "prompt-body": "Review this",
        "working-root": str(tmp_path),
    }
    actual = default_build_prompt(
        ctx, {"default-model": "model"}, provider_id="pi", title="Pi",
        prompt_profile_id="review",
    )
    assert "Review the supplied work carefully" in actual
    assert "MALICIOUS" not in actual
    assert actual.endswith("Prompt body: Review this")
    assert "Review this" in actual


def test_component_context_is_available_to_prompt_templates() -> None:
    config = global_agents_config_path().parent
    templates = config / "agent-templates"
    (templates / "context.md").write_text(
        "{project.name}|{source_control.repository}|{source_control.branch}|{source_control.commit_short}|{session.model}|{prompt-body}",
        encoding="utf-8",
    )
    global_agents_config_path().write_text(
        """contract-version: v2
prompt_profiles:
  default:
    template_with_body: agent-templates/context.md
""",
        encoding="utf-8",
    )
    actual = default_build_prompt(
        {
            "prompt-body": "Review this",
            "template-context": {
                "project": {"name": "AUDiaGentic"},
                "source_control": {
                    "repository": "AUDiaGentic",
                    "branch": "main",
                    "commit_short": "0123456789ab",
                },
                "session": {"model": "qwen"},
            },
        },
        {"default-model": "model"}, provider_id="pi", title="Pi",
    )
    assert actual == "AUDiaGentic|AUDiaGentic|main|0123456789ab|qwen|Review this"


def test_unknown_profile_fails_closed():
    with pytest.raises(AudiaGenticError, match="unknown prompt profile"):
        default_build_prompt(
            {"prompt-body": "x", "working-root": "."}, {"default-model": "m"},
            provider_id="pi", title="Pi", prompt_profile_id="revieew",
        )
