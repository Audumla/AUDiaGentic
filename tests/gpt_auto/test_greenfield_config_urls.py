from __future__ import annotations


def test_project_title_suffix_is_not_project_identity():
    from audiagentic.components.providers.adapters.gpt_auto.urls import parse_project_id, canonical_chat_url
    project = "g-p-6a7bbf85d06c8191835b0d64958b4d7a"
    base = f"https://chatgpt.com/g/{project}"
    assert parse_project_id(base + "-bigcherry/c/chat") == parse_project_id(base + "/project")
    assert parse_project_id(base + "-renamed/c/chat") == project
    assert canonical_chat_url(base + "-bigcherry/c/chat") == base + "/c/chat"
    assert parse_project_id(base + "/project") != parse_project_id("https://chatgpt.com/g/g-p-00000000000000000000000000000000/project")

import sys
from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers.adapters.gpt_auto.config import (
    ExistingBrowserPolicy,
    GptAutoConfig,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot
from audiagentic.components.providers.adapters.gpt_auto.turn import _facts
from audiagentic.components.providers.adapters.gpt_auto.urls import (
    canonical_chat_url,
    canonical_project_url,
    is_gpt_auto_relevant_url,
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
            "response-generating-override-stability-seconds": 30,
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
                "more-actions-menu": {
                    "scope": "latest-assistant-turn",
                    "selectors": ['button[aria-label="More actions"]'],
                    "visible": True,
                },
                "canvas-edit-control": {
                    "scope": "latest-assistant-turn",
                    "selectors": ['[data-testid="writing-block-header-magic-edit-button"]'],
                    "visible": True,
                },
                "canvas-open-editor-control": {
                    "scope": "latest-assistant-turn",
                    "selectors": ['button[aria-label="Open editor"]'],
                    "visible": True,
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
                    "any-of-groups": [
                        ["completion-control", "more-actions-menu"],
                        ["canvas-edit-control", "canvas-open-editor-control", "not-generating"],
                    ],
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
    assert {"completion-control", "more-actions-menu"} in {frozenset(g) for g in policy.any_of_groups}


def test_response_complete_policy_never_regresses_to_either_witness_alone(): # GP17, GP32
    """GP17 regression guard: completion-control and its corroborating
    partner were proven live-unreliable INDEPENDENTLY (each can fire on a
    genuinely incomplete turn and then stay persistently true through the
    whole stability window, so text stability alone does not catch a
    shared false-positive). Both must be required TOGETHER within one
    corroborating group, never accepted as sufficient alone (a flat
    any-of) -- a future edit that silently reverts to a flat any-of would
    reintroduce the false-positive-early-completion bug that produced
    real truncated live results on 2026-08-16.

    GP32 (2026-08-17): response-complete uses any-of-groups (a disjunction
    of AND-groups) so a future signal loss can degrade to surviving groups
    instead of total failure. Every individual group must still require its
    full corroborating set together. Renderer-position markers such as
    data-is-last-node/data-is-only-node are intentionally excluded because
    they can appear before a response is complete."""
    policy = GptAutoConfig.from_dict(valid_config()).workflow.policy("response-complete")
    assert not policy.any_of, (
        "response-complete must not accept any single corroborating witness "
        "alone via a flat any-of -- each any-of-groups entry must require "
        "its full pair together"
    )
    assert any(
        {"completion-control", "more-actions-menu"} <= set(group)
        for group in policy.any_of_groups
    )
    for group in policy.any_of_groups:
        assert len(group) >= 2, (
            "each any-of-groups entry must itself require more than one "
            "corroborating signal -- a single-fact group would let that "
            "one witness satisfy response-complete alone, reintroducing "
            "the GP17 false-positive-early-completion bug"
        )


def test_response_complete_recognizes_the_canvas_response_variant():
    """GP33 follow-up: ChatGPT's canvas/writing-block response type
    (confirmed live 2026-08-17) renders a completely different end-of-turn
    action bar than the standard chat-turn bubble -- completion-control and
    more-actions-menu were confirmed document-scoped-absent for a
    genuinely complete canvas turn, which would make response-complete
    permanently unsatisfiable for that whole response variant (the exact
    GP32 failure shape again). A second any-of-groups entry
    (canvas-edit-control + canvas-open-editor-control) must be present so
    the standard chat-bubble variant losing its signals doesn't take the
    canvas variant down with it, and vice versa."""
    policy = GptAutoConfig.from_dict(valid_config()).workflow.policy("response-complete")
    assert any(
        {"canvas-edit-control", "canvas-open-editor-control"} <= set(group)
        for group in policy.any_of_groups
    )


def test_project_url_is_optional_for_project_name_discovery():
    value = valid_config()
    del value["project-url"]
    assert GptAutoConfig.from_dict(value).project_url is None


def test_repository_base_gpt_auto_profile_does_not_pin_a_chatgpt_project():
    """The shared base profile must use the admitted project name.

    A fixed URL takes precedence over ``project_name`` in
    ``PersistentChat.open_project_page`` and silently routes every caller to
    that one ChatGPT project.  Dedicated aliases such as gpt-auto-t1/t2 can
    remain explicitly pinned; only the reusable base profile is dynamic.
    """
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )

    assert GptAutoConfig.from_project_dict(document).project_url is None


def test_configured_project_url_must_identify_a_chatgpt_project():
    value = valid_config()
    value["project-url"] = "https://chatgpt.com/c/general-conversation"

    with pytest.raises(AudiaGenticError, match="ChatGPT Project"):
        GptAutoConfig.from_dict(value)


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
    assert not url_matches_provider_session(
        "https://chatgpt.com/c/conversation-1", "conversation-1"
    )


def test_is_gpt_auto_relevant_url_scopes_to_plausible_owned_tabs():
    assert is_gpt_auto_relevant_url("https://chatgpt.com/c/abc")
    assert is_gpt_auto_relevant_url("https://chat.openai.com/g/g-p-x")
    assert is_gpt_auto_relevant_url("data:text/html;charset=utf-8,<html></html>")
    assert is_gpt_auto_relevant_url("http://127.0.0.1:8765/dashboard?audiagentic-window-anchor=1")
    assert is_gpt_auto_relevant_url("about:blank")
    assert is_gpt_auto_relevant_url("")
    assert not is_gpt_auto_relevant_url("https://reddit.com/r/x")
    assert not is_gpt_auto_relevant_url("https://amazon.com/dp/1")
    assert not is_gpt_auto_relevant_url("devtools://devtools/x")


def test_live_workflow_does_not_treat_static_streaming_animation_as_busy() -> None:
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(document)
    signals = {item["name"]: item for item in config.workflow.bridge_signals()}

    assert ".streaming-animation" not in signals["streaming-indicator"]["selectors"]


def _synthetic_snapshot(
    dom_signals: list[str], *, assistant_id: str | None = "a1", generating: bool = False
) -> ChatSnapshot:
    return ChatSnapshot(
        url="https://chatgpt.com/x",
        composer_present=True,
        composer_editable=True,
        user_count=1,
        assistant_count=1 if assistant_id else 0,
        latest_assistant_id=assistant_id,
        latest_user_text="hi",
        latest_assistant_text="hello world" if assistant_id else None,
        dom_signals=frozenset(dom_signals),
        error_present=False,
        generating=generating,
    )


def test_real_merged_config_response_complete_requires_both_witnesses_together() -> None:
    """GP32 integration guard: exercises turn.py's real _facts() pipeline
    against the ACTUAL trimmed, merged .audiagentic/config/providers/
    gpt-auto.yaml (not the synthetic valid_config() fixture every other
    test in this file uses) -- the one file every other test's fixture
    comment explicitly says it cannot protect. Neither witness alone may
    satisfy response-complete; only the pair together may."""
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(document)
    policy = config.workflow.policy("response-complete")
    baseline = _synthetic_snapshot([], assistant_id=None)

    both = _facts(baseline, baseline, _synthetic_snapshot(["completion-control", "more-actions-menu"]))
    assert policy.evaluate(both).satisfied

    only_completion = _facts(baseline, baseline, _synthetic_snapshot(["completion-control"]))
    assert not policy.evaluate(only_completion).satisfied

    only_more_actions = _facts(baseline, baseline, _synthetic_snapshot(["more-actions-menu"]))
    assert not policy.evaluate(only_more_actions).satisfied


def test_real_merged_config_response_complete_recognizes_canvas_variant_alone() -> None:
    """GP33 integration guard: a canvas/writing-block turn carries NEITHER
    completion-control nor more-actions-menu (confirmed live 2026-08-17,
    document-scoped-absent) -- only canvas-edit-control and
    canvas-open-editor-control. response-complete must still resolve via
    its second any-of-groups entry, against the real merged config, not
    just the synthetic fixture."""
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(document)
    policy = config.workflow.policy("response-complete")
    baseline = _synthetic_snapshot([], assistant_id=None)

    canvas_only = _facts(
        baseline, baseline, _synthetic_snapshot(["canvas-edit-control", "canvas-open-editor-control"])
    )
    assert policy.evaluate(canvas_only).satisfied

    canvas_single_witness = _facts(baseline, baseline, _synthetic_snapshot(["canvas-edit-control"]))
    assert not policy.evaluate(canvas_single_witness).satisfied


def test_real_merged_config_canvas_group_rejects_mid_generation_false_positive() -> None:
    """GP34/code-review guard: live monitoring confirmed canvas-edit-control
    and canvas-open-editor-control both appear within ~150 characters of a
    response that ultimately reached ~1900 characters -- i.e. at
    canvas-panel-creation time, not completion. Code review's own
    hypothetical failure sequence: both canvas controls present while
    ChatGPT is still genuinely mid-generation (a real pause, not yet the
    final answer) must NOT satisfy response-complete. This is the concrete
    scenario not-generating's addition to the canvas group exists to
    catch -- without it, this test would have failed before tonight's fix
    and did fail during code review's analysis of the pre-fix diff."""
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(document)
    policy = config.workflow.policy("response-complete")
    baseline = _synthetic_snapshot([], assistant_id=None)

    mid_generation_canvas = _facts(
        baseline,
        baseline,
        _synthetic_snapshot(
            ["canvas-edit-control", "canvas-open-editor-control"], generating=True
        ),
    )
    assert not policy.evaluate(mid_generation_canvas).satisfied

    # Once generation genuinely stops, the same two signals DO satisfy it.
    genuinely_done_canvas = _facts(
        baseline,
        baseline,
        _synthetic_snapshot(
            ["canvas-edit-control", "canvas-open-editor-control"], generating=False
        ),
    )
    assert policy.evaluate(genuinely_done_canvas).satisfied


def test_real_merged_config_ignores_renderer_position_markers() -> None:
    """Renderer-position markers are not end-of-turn evidence.

    ``data-is-last-node`` and ``data-is-only-node`` describe the current
    render tree and can be present while a response is still growing.  They
    must not satisfy the real merged completion policy, even when the raw
    snapshot says the page is not currently generating.
    """
    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load(
        (root / ".audiagentic/config/providers/gpt-auto.yaml").read_text(encoding="utf-8")
    )
    config = GptAutoConfig.from_project_dict(document)
    policy = config.workflow.policy("response-complete")
    baseline = _synthetic_snapshot([], assistant_id=None)

    for marker in ("message-finalized", "data-is-last-node", "data-is-only-node"):
        marker_only = _facts(
            baseline, baseline, _synthetic_snapshot([marker], generating=False)
        )
        assert not policy.evaluate(marker_only).satisfied, marker

    bridge_signals = {item["name"]: item for item in config.workflow.bridge_signals()}
    assert "message-finalized" not in bridge_signals
    assert not any(
        "data-is-last-node" in selector or "data-is-only-node" in selector
        for item in bridge_signals.values()
        for selector in item["selectors"]
    )
