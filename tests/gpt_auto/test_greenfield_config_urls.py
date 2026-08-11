from __future__ import annotations

import sys

import pytest

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
                    "all-of": ["assistant-fresh", "text-present", "completion-control"],
                    "none-of": ["stop-control", "error-page"],
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
