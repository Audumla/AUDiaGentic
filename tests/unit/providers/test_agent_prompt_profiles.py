from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.gateway.queue.dispatch import _build_packet_ctx
from audiagentic.components.providers.adapters.base_runner import default_build_prompt
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _admitted(ctx: dict, cfg: dict, *, provider_id: str, title: str) -> str:
    return (
        f"Execution request for {title}. request={ctx.get('request-id')} "
        f"provider={ctx.get('provider-id', provider_id)} model={cfg.get('default-model')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible. "
        f"Prompt body: {str(ctx['prompt-body']).strip()}"
    ).strip()


def test_provider_uses_exact_admitted_prompt_bytes():
    body = "Implement café — résumé"
    ctx = {
        "job-id": "job-1", "packet-id": "packet-1", "provider-id": "pi",
        "workflow-profile": "standard", "prompt-body": body,
    }
    cfg = {"default-model": "qwen3.6-27b-0"}
    actual = default_build_prompt(ctx, cfg, provider_id="pi", title="Pi")
    expected = _admitted(ctx, cfg, provider_id="pi", title="Pi")
    assert actual.encode("utf-8") == expected.encode("utf-8")


def test_provider_prompt_uses_packet_model_over_provider_default():
    ctx = {
        "request-id": "req-1",
        "provider-id": "pi",
        "model-id": "packet-model",
        "prompt-body": "Review this",
    }
    actual = default_build_prompt(
        ctx,
        {"default-model": "stale-provider-default"},
        provider_id="pi",
        title="Pi",
    )
    assert "model=packet-model" in actual
    assert "stale-provider-default" not in actual


def test_context_override_is_provider_local_projection():
    actual = default_build_prompt(
        {"request-id": "req-1", "prompt-body": "admitted"},
        {"default-model": "model"},
        provider_id="pi",
        title="Pi",
        context_overrides={"prompt-body": "normalized"},
    )
    assert actual.endswith("Prompt body: normalized")
    assert "admitted" not in actual


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
    expected = _admitted(packet, {"default-model": None}, provider_id="pi", title="Pi")
    assert actual.encode("utf-8") == expected.encode("utf-8")


def test_provider_does_not_consult_project_prompt_template_override(tmp_path):
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
    assert actual.endswith("Prompt body: Review this")
    assert "MALICIOUS" not in actual


def test_component_context_is_available_to_prompt_templates() -> None:
    config = global_agents_config_path().parent
    templates = config / "agent-templates"
    (templates / "context.md").write_text("unused", encoding="utf-8")
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
    assert actual.endswith("Prompt body: Review this")


def test_legacy_profile_argument_is_ignored():
    assert default_build_prompt(
        {"prompt-body": "x", "working-root": "."}, {"default-model": "m"},
        provider_id="pi", title="Pi", prompt_profile_id="revieew",
    ).endswith("Prompt body: x")
