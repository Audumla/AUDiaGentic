from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.base_runner import default_build_prompt
from audiagentic.components.agents.gateway.queue.dispatch import _build_packet_ctx
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _legacy(ctx: dict, cfg: dict, *, provider_id: str, title: str) -> str:
    body = ctx.get("prompt-body")
    prompt = (
        f"AUDiaGentic {title} provider execution request. "
        f"job={ctx.get('job-id')} "
        f"packet={ctx.get('packet-id')} "
        f"provider={ctx.get('provider-id', provider_id)} "
        f"model={cfg.get('default-model')} "
        f"workflow={ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if body:
        prompt += f" Prompt body: {str(body).strip()}"
    return prompt.strip()


@pytest.mark.parametrize("body", [None, "", " ", "\n", "Implement café — résumé"])
def test_default_profile_is_byte_identical_to_legacy(body):
    ctx = {
        "job-id": "job-1", "packet-id": "packet-1", "provider-id": "pi",
        "workflow-profile": "standard", "prompt-body": body,
    }
    cfg = {"default-model": "qwen3.6-27b-0"}
    actual = default_build_prompt(ctx, cfg, provider_id="pi", title="Pi")
    expected = _legacy(ctx, cfg, provider_id="pi", title="Pi")
    assert actual.encode("utf-8") == expected.encode("utf-8")


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


def test_unknown_profile_fails_closed():
    with pytest.raises(AudiaGenticError, match="unknown prompt profile"):
        default_build_prompt(
            {"prompt-body": "x", "working-root": "."}, {"default-model": "m"},
            provider_id="pi", title="Pi", prompt_profile_id="revieew",
        )
