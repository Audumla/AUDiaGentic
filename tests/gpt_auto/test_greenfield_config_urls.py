from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers.adapters.gpt_auto.config import (
    ExistingBrowserPolicy,
    GptAutoConfig,
)
from audiagentic.components.providers.adapters.gpt_auto.urls import (
    canonical_chat_url,
    canonical_project_url,
    parse_project_id,
    parse_provider_session_id,
    url_matches_provider_session,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def valid_config() -> dict:
    return {
        "contract-version": "v1",
        "project-url": "https://chatgpt.com/g/g-p-project-audiagentic",
        "browser": {
            "executable": sys.executable,
            "remote-debugging-port": 9222,
            "existing-browser-policy": "fail",
            "shutdown-timeout-seconds": 10,
            "force-kill": False,
            "dedicated-window": True,
        },
        "cdp": {
            "connect-timeout-seconds": 15,
            "protocol-timeout-seconds": 30,
            "recovery-timeout-seconds": 30,
            "devtools-active-port-file": None,
        },
        "chat": {"ready-timeout-seconds": 30, "navigation-timeout-seconds": 30},
        "turn": {
            "submission-timeout-seconds": 15,
            "response-start-timeout-seconds": 120,
            "response-stall-timeout-seconds": 900,
            "response-timeout-seconds": 600,
            "poll-interval-seconds": 1,
            "response-stability-seconds": 6,
            "submission-proof-progress-lease-seconds": 300,
            "submission-proof-absolute-ceiling-seconds": 900,
        },
        "workflow": {
            "dom-signals": {
                "stop-control": {
                    "scope": "document",
                    "selectors": ['[data-testid="stop-button"]'],
                    "visible": True,
                },
                "completion-control": {
                    "scope": "latest-assistant-turn",
                    "selectors": ['[data-testid="copy-turn-action-button"]'],
                    "visible": False,
                },
                "message-finalized": {
                    "scope": "latest-assistant-turn",
                    "selectors": ["[data-is-last-node]"],
                    "visible": False,
                },
                "error-page": {
                    "scope": "document",
                    "selectors": [".error-page"],
                    "visible": True,
                },
            },
            "evidence-policies": {
                "response-started": {"any-of": ["assistant-fresh", "stop-control"]},
                "response-active": {"any-of": ["text-changed", "stop-control"]},
                "response-complete": {
                    "all-of": ["assistant-fresh", "text-present"],
                    "any-of": ["completion-control", "message-finalized"],
                    "none-of": ["error-page"],
                },
                "response-failed": {"any-of": ["error-page"]},
            },
        },
    }


def test_strict_config_is_typed_and_frozen():
    config = GptAutoConfig.from_dict(valid_config())
    assert config.browser.existing_browser_policy is ExistingBrowserPolicy.FAIL
    assert config.cdp_url == "http://127.0.0.1:9222"
    with pytest.raises(Exception):
        config.project_url = "changed"  # type: ignore[misc]


def test_response_complete_policy_never_regresses_to_the_stuck_stop_control_veto():
    """GP07 regression guard: this is the one committed, source-of-truth
    workflow policy every deterministic AND live-gated (AUDIAGENTIC_GPT_AUTO_LIVE=1)
    test builds its config from -- the gitignored local
    .audiagentic/config/providers/gpt-auto*.yaml files are a SEPARATE,
    uncommitted copy this fixture cannot protect. Lock in the specific shape
    that fixes the stuck stop-control bug so a future edit can't silently
    reintroduce it here."""
    policy = GptAutoConfig.from_dict(valid_config()).workflow.policy("response-complete")
    assert "stop-control" not in policy.none_of, (
        "stop-control is proven live-unreliable (sticks after real completion) "
        "and must stay advisory-only, never a completion veto"
    )
    assert "message-finalized" in policy.any_of
    assert "completion-control" in policy.any_of
    assert policy.any_of, "at least one corroborating any-of signal must be required"


def test_project_url_is_optional_for_project_name_discovery():
    value = valid_config()
    del value["project-url"]
    assert GptAutoConfig.from_dict(value).project_url is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["browser"].update({"browser_port": 1}),
        lambda value: value["browser"].update({"existing-browser-policy": "kill"}),
        lambda value: value["turn"].update({"response-timeout-seconds": -1}),
    ],
)
def test_invalid_or_legacy_config_fails(mutation):
    value = valid_config()
    mutation(value)
    with pytest.raises(AudiaGenticError):
        GptAutoConfig.from_dict(value)


def test_chatgpt_url_identity_helpers_are_pure_and_exact():
    url = "https://chat.openai.com/g/g-p-project-audiagentic/c/conversation-1?x=1"
    assert parse_project_id(url) == "g-p-project-audiagentic"
    assert parse_provider_session_id(url) == "conversation-1"
    assert canonical_project_url(url) == "https://chatgpt.com/g/g-p-project-audiagentic"
    assert canonical_chat_url(url) == (
        "https://chatgpt.com/g/g-p-project-audiagentic/c/conversation-1"
    )
    assert url_matches_provider_session(url, "conversation-1")
    assert not url_matches_provider_session(url, "conversation-2")


def test_live_workflow_does_not_treat_static_streaming_animation_as_busy() -> None:
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_dict(document)
    signals = {item["name"]: item for item in config.workflow.bridge_signals()}

    assert ".streaming-animation" not in signals["streaming-indicator"]["selectors"]
