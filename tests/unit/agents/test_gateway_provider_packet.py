"""Provider packet extraction preserves existing mapping without runtime work."""
import json
import logging
from pathlib import Path
from types import MappingProxyType

import pytest

from audiagentic.components.agents.gateway.admission.packet import build_provider_packet
from audiagentic.components.agents.gateway.queue.dispatch import _build_packet_ctx


def inputs(root):
    return {
        "execution_root": root,
        "request_id": "request-123",
        "profile": {"profile_id": "profile", "provider_id": "provider", "model_alias": "alias",
                    "params": {"temperature": 0.2, "stream-controls": {"include-progress": True}}},
        "prompt_profile_id": "prompt", "prompt_template_name": "prompt-definition:prompt",
        "prompt_template_digest": "a" * 64, "prompt_definition_fingerprint": "b" * 64,
        "model_id": "model", "dispatch_prompt": "PRIVATE prompt\r\n λ",
        "source": "node", "metadata": {"correlation_id": "correlation"},
        "template_context": {"project": {"name": "sample"}},
    }


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_ordinary_mapping_golden_bytes_match_wrapper(tmp_path):
    args = inputs(tmp_path)
    expected = {
        "request-id": "request-123", "job-id": "request-123", "execution-profile-id": "profile",
        "prompt-profile-id": "prompt", "prompt-template-name": "prompt-definition:prompt",
        "prompt-template-digest": "a" * 64, "prompt-definition-fingerprint": "b" * 64,
        "provider-id": "provider", "model-id": "model", "model-alias": "alias",
        "prompt-body": "PRIVATE prompt\r\n λ",
        "params": {"temperature": 0.2, "stream-controls": {"include-progress": True}},
        "working-root": str(tmp_path.resolve()), "stream-controls": {"include-progress": True},
        "source": "node", "metadata": {"correlation_id": "correlation"},
        "template-context": {"project": {"name": "sample"}},
    }
    record = {
        "request-id": args["request_id"], "prompt-profile-id": args["prompt_profile_id"],
        "prompt-template-name": args["prompt_template_name"],
        "prompt-template-digest": args["prompt_template_digest"],
        "prompt-definition-fingerprint": args["prompt_definition_fingerprint"],
        "source": args["source"], "metadata": args["metadata"], "template-context": args["template_context"],
        "prompt-body": "wrong record prompt",
    }
    direct = build_provider_packet(**args)
    wrapped = _build_packet_ctx(tmp_path, record, args["profile"],
                                {"model-id": "model", "resolved": "ignored-fallback"},
                                dispatch_prompt=args["dispatch_prompt"])
    assert encode(direct) == encode(wrapped) == encode(expected)


@pytest.mark.parametrize("model,expected", [
    ({"model-id": "chosen", "resolved": "fallback"}, "chosen"),
    ({"resolved": "fallback"}, "fallback"), ({"model-id": "", "resolved": "fallback"}, "fallback"),
    ({}, None),
])
def test_wrapper_preserves_model_fallback_and_record_defaults(tmp_path, model, expected):
    packet = _build_packet_ctx(tmp_path, {"request-id": "request"},
                               {"profile_id": "profile", "provider_id": "provider"}, model,
                               dispatch_prompt="private")
    assert packet["model-id"] == expected
    assert packet["prompt-profile-id"] == "default"
    assert packet["metadata"] == packet["template-context"] == packet["params"] == packet["stream-controls"] == {}
    assert packet["model-alias"] is None


def test_wrapper_preserves_explicit_none_values(tmp_path):
    packet = _build_packet_ctx(tmp_path, {"request-id": "request", "metadata": None,
                                        "template-context": None, "prompt-profile-id": None},
                               {"profile_id": "profile", "provider_id": "provider"}, {},
                               dispatch_prompt="private")
    assert packet["metadata"] is packet["template-context"] is packet["prompt-profile-id"] is None


def test_metadata_and_context_cannot_redirect_execution_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = inputs(Path("trusted/../trusted"))
    args["metadata"] = {"working-root": "/foreign", "project-root": "/foreign",
                        "request-id": "foreign", "provider-id": "foreign"}
    args["template_context"] = {"working-root": "/foreign", "project": {"root": "/foreign"}}
    args["profile"]["working-root"] = "/foreign"
    packet = build_provider_packet(**args)
    assert packet["working-root"] == str((tmp_path / "trusted").resolve())
    assert packet["request-id"] == "request-123" and packet["provider-id"] == "provider"
    assert packet["metadata"] == args["metadata"]


def test_mapping_profile_and_stream_controls_copy(tmp_path):
    args = inputs(tmp_path)
    profile = args["profile"]
    args["profile"] = MappingProxyType(profile)
    packet = build_provider_packet(**args)
    assert packet["params"] is profile["params"]
    assert packet["metadata"] is args["metadata"]
    assert packet["template-context"] is args["template_context"]
    assert packet["stream-controls"] is not profile["params"]["stream-controls"]
    packet["stream-controls"]["include-progress"] = False
    assert profile["params"]["stream-controls"]["include-progress"] is True


def test_pure_packet_does_not_read_prompt_files_or_log_private_material(tmp_path, monkeypatch, caplog):
    args = inputs(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("packet builder attempted file content I/O")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    with caplog.at_level(logging.DEBUG):
        packet = build_provider_packet(**args)
    assert packet["prompt-body"] == args["dispatch_prompt"]
    assert caplog.records == []
