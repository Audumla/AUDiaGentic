"""Deterministic CDP bridge/adaptor scenario matrix.

No browser, websocket, network, or ChatGPT process is used here.  The fake
client models CDP commands and target responses so lifecycle behaviour can be
tested repeatably, including malformed/negative responses.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import (
    BridgeEvent,
    PythonCdpBridge,
)
from audiagentic.components.providers.adapters.gpt_auto.cdp.cdp_browser import (
    CdpBrowserController,
    CdpPageRef,
    CdpWindowBounds,
)
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    _COMPOSER_READY_FN,
    _PROJECT_NEW_CHAT_POINT_FN,
    _SNAPSHOT_FN,
    GptAutoCdpBrowserController,
)
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatSnapshot

from .test_greenfield_config_urls import valid_config


class _NoopBridge:
    async def call(self, *_args, **_kwargs):
        return {}


@pytest.mark.asyncio
async def test_wait_for_composer_uses_lightweight_readiness_probe(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/projects", "")
    functions: list[str] = []

    async def evaluate(_page, function, _argument=None):
        functions.append(function)
        return {"composerPresent": True, "composerEditable": True, "visible": True}

    async def snapshot(_page, **_kwargs):
        raise AssertionError("full DOM snapshot must not gate composer readiness")

    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(browser, "snapshot", snapshot)

    ready = await browser.wait_for_composer(page, timeout=1)

    assert ready["composerEditable"] is True
    assert functions == [_COMPOSER_READY_FN]


def test_snapshot_does_not_promote_static_streaming_animation_to_busy() -> None:
    """The live ChatGPT DOM keeps this class after a response completes."""
    assert 'selector !== ".streaming-animation"' in _SNAPSHOT_FN


def test_snapshot_activity_labels_are_case_insensitive_and_cover_tool_rows() -> None:
    """The bridge recognizes the labels operators see in ChatGPT's UI."""
    assert 'toLowerCase()' in _SNAPSHOT_FN
    for visible, canonical in (
        ("talked to app", "talked-to-app"),
        ("read resource", "read-resource"),
        ("called tool", "called-tool"),
        ("searching the web", "searching-web"),
        ("thinking", "thinking"),
    ):
        assert f'["{visible}", "{canonical}"]' in _SNAPSHOT_FN


def test_snapshot_activity_anchors_to_latest_agent_turn_before_assistant_node() -> None:
    """Streaming tool rows must be visible before ChatGPT adds an assistant node.

    A live GPT-T2 turn rendered ``group/tool-message`` rows inside the current
    ``.agent-turn`` while ``[data-message-author-role=assistant]`` was still
    absent.  The regression made ``assistantTurn`` null in that phase, so the
    activity scan returned no tool counts and the gateway lease expired while
    the browser was visibly working.  Keep the semantic-turn fallback wired
    into the production snapshot script.
    """
    assert "const agentTurns = Array.from(document.querySelectorAll('.agent-turn'))" in _SNAPSHOT_FN
    assert "const latestAgentTurn = agentTurns.length ? agentTurns[agentTurns.length - 1] : null" in _SNAPSHOT_FN
    assert "const progressTurns = agentTurns.length" in _SNAPSHOT_FN
    assert "const latestFallbackActivityBlock" in _SNAPSHOT_FN
    assert "fallbackHasUnansweredPrompt" in _SNAPSHOT_FN
    assert "[class~=\"group/tool-message\"]" in _SNAPSHOT_FN


def test_snapshot_has_structural_progress_fallback_and_semantic_digest() -> None:
    for selector in (
        '[data-testid*="citation" i]',
        '[data-testid="writing-block-container"]',
        "table",
        "[aria-valuenow]",
        "[aria-valuetext]",
        "[data-phase]",
        "[data-progress]",
    ):
        assert selector in _SNAPSHOT_FN
    for kind in (
        "dom-status",
        "dom-progress",
        "dom-tool-result",
        "dom-connector",
        "dom-citation",
        "dom-table",
        "dom-materialization",
    ):
        assert kind in _SNAPSHOT_FN
    assert "const semanticStateDigest = (node, excludedRoots = null, lexicalCarriers = null, canonicalLexicalRoots = []) =>" in _SNAPSHOT_FN
    assert "const semanticNodeDigest = (node, excludedRoots = null, lexicalCarriers = null, canonicalLexicalRoots = []) =>" in _SNAPSHOT_FN
    assert "const boundedScalarMaterial = value =>" in _SNAPSHOT_FN
    assert "const boundedTextForKind = node =>" in _SNAPSHOT_FN
    assert "const visibleTextDigest = (node, excludedRoots = null) =>" in _SNAPSHOT_FN
    assert "dom-activity-v2" in _SNAPSHOT_FN
    assert "new MutationObserver" in _SNAPSHOT_FN
    assert "domActivityOwnerPromptMessageId" in _SNAPSHOT_FN


def test_completion_snapshot_accepts_current_regenerate_response_control() -> None:
    defaults = (
        Path(__file__).parents[2]
        / "src/audiagentic/components/providers/adapters/gpt_auto/gpt-auto-defaults.yaml"
    )
    assert 'button[aria-label="Regenerate response"]' in defaults.read_text(encoding="utf-8")


def test_snapshot_resolves_sidebar_title_by_active_conversation_url() -> None:
    assert "const conversationId" in _SNAPSHOT_FN
    assert "const conversationTitle" in _SNAPSHOT_FN
    assert 'querySelectorAll("a[href]")' in _SNAPSHOT_FN
    assert "const genericLabel" in _SNAPSHOT_FN
    assert "skip to content" in _SNAPSHOT_FN
    assert "anchor.innerText || anchor.textContent" in _SNAPSHOT_FN
    assert "conversationTitle," in _SNAPSHOT_FN


def test_snapshot_rejects_navigation_label_as_conversation_title() -> None:
    snap = ChatSnapshot.from_bridge({
        "url": "https://chatgpt.com/g/g-p-x/c/c-x",
        "conversationTitle": "Skip to content",
    })
    assert snap.conversation_title is None


def test_snapshot_preserves_structural_hr_for_user_prompt_correlation() -> None:
    """A rendered thematic break must be recoverable only for correlation."""
    assert "const userCorrelation = (element)" in _SNAPSHOT_FN
    assert "querySelectorAll('hr')" in _SNAPSHOT_FN
    assert 'document.createTextNode("\\n---\\n")' in _SNAPSHOT_FN
    assert "correlationText" in _SNAPSHOT_FN
    assert "structuralHrCount" in _SNAPSHOT_FN


def test_snapshot_user_correlation_removes_presentation_controls_without_text_filtering() -> None:
    """Correlation must remove UI controls structurally, not words by text.

    This prevents a collapsed long prompt's ``Show more`` button from
    poisoning the fingerprint while preserving a real prompt containing the
    same words.
    """
    assert 'clone.querySelectorAll(\'button, [role="button"' in _SNAPSHOT_FN
    assert '[aria-label*="show more" i]' in _SNAPSHOT_FN
    assert 'if (!hrs.length) return {text: null, hrCount: 0};' not in _SNAPSHOT_FN
    assert 'return {text, hrCount: hrs.length};' in _SNAPSHOT_FN


@pytest.mark.asyncio
async def test_materialize_latest_assistant_turn_scrolls_without_provider_side_effects() -> None:
    """Virtualized long chats must be brought into view read-only.

    The operation is intentionally separate from ``snapshot``: it may cause
    ChatGPT to mount the end-of-turn action bar, but it must never submit,
    click, refresh, or create a target.
    """
    class _MaterializeBridge:
        def __init__(self) -> None:
            self.functions: list[str] = []
            self.calls: list[tuple[str, dict]] = []

        async def call(self, method, params=None, **_kwargs):
            self.calls.append((method, dict(params or {})))
            return {"ok": True}

        async def evaluate(self, _page_handle, function, _argument=None, **_kwargs):
            self.functions.append(function)
            return "scrollIntoView" in function

    bridge = _MaterializeBridge()
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")

    assert await browser.materialize_latest_assistant_turn(page)
    assert len(bridge.functions) == 2
    assert "scrollIntoView" in bridge.functions[0]
    assert "click" not in bridge.functions[0]
    assert "Target.createTarget" not in bridge.functions[0]
    assert [method for method, _params in bridge.calls] == [
        "set_focus_emulation",
    ]
    assert [params["enabled"] for _method, params in bridge.calls] == [True]

    await browser.release_focus_emulation(page)
    assert [params["enabled"] for _method, params in bridge.calls] == [True, False]


@pytest.mark.asyncio
async def test_delivery_timeout_retry_targets_only_provider_retry_control() -> None:
    class _RetryBridge:
        async def evaluate(self, _page_handle, function, _argument=None, **_kwargs):
            assert 'regenerate-thread-error-button' in function
            assert "text !== 'retry'" in function
            assert '.click()' in function
            return True

    browser = GptAutoCdpBrowserController(_RetryBridge())  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    assert await browser.retry_delivery_timeout(page)


class _ScenarioClient:
    def __init__(self) -> None:
        self.events: asyncio.Queue = asyncio.Queue()
        self.calls: list[tuple[str, dict, str | None]] = []
        self.targets: dict[str, dict] = {}
        self.next_target = 1
        self.fail_method: str | None = None
        self.window_open_target: str | None = None

    async def command(self, method, params=None, *, session_id=None, timeout=None, required_generation=None):
        params = params or {}
        self.calls.append((method, params, session_id))
        if method == self.fail_method:
            raise RuntimeError(f"simulated {method} failure")
        if method == "Target.getTargets":
            return {"targetInfos": list(self.targets.values())}
        if method in {"Target.setDiscoverTargets", "Page.enable", "Page.setLifecycleEventsEnabled"}:
            return {}
        if method == "Target.createTarget":
            target_id = f"target-{self.next_target}"
            self.next_target += 1
            self.targets[target_id] = {
                "targetId": target_id,
                "type": "page",
                "url": "about:blank",
                "title": "",
            }
            return {"targetId": target_id}
        if method == "Browser.getWindowForTarget":
            return {"windowId": 10 if params["targetId"] == self.window_open_target else 20}
        if method == "Target.attachToTarget":
            return {"sessionId": f"session-{params['targetId']}"}
        if method == "Page.navigate":
            return (
                {"errorText": "simulated navigation error"}
                if self.fail_method == "Page.navigate:error"
                else {}
            )
        if method == "Runtime.evaluate":
            if "window.open" in str(params.get("expression") or ""):
                anchor_target = (session_id or "").removeprefix("session-")
                target_id = f"target-{self.next_target}"
                self.next_target += 1
                self.targets[target_id] = {
                    "targetId": target_id,
                    "type": "page",
                    "url": "about:blank",
                    "title": "",
                    "openerId": anchor_target,
                }
            return {"result": {"value": {"ok": True}}}
        if method == "Browser.getVersion":
            return {"Browser": "Fake/1", "Protocol-Version": "1.3"}
        if method == "Browser.getWindowBounds":
            return {
                "bounds": {
                    "left": 0,
                    "top": 0,
                    "width": 800,
                    "height": 600,
                    "windowState": "normal",
                }
            }
        if method == "Target.getTargetInfo":
            return {
                "targetInfo": self.targets.get(
                    params["targetId"], {"targetId": params["targetId"], "type": "page"}
                )
            }
        if method in {"Browser.setWindowBounds", "Target.activateTarget", "Target.closeTarget"}:
            if method == "Target.closeTarget":
                self.targets.pop(params["targetId"], None)
            return {}
        return {}


def _bridge() -> tuple[PythonCdpBridge, _ScenarioClient]:
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _ScenarioClient()
    bridge._client = fake
    return bridge, fake


@pytest.mark.asyncio
async def test_bridge_positive_lifecycle_sequence_is_typed_and_reusable():
    bridge, fake = _bridge()
    browser = CdpBrowserController(bridge)
    page = await browser.new_window()
    same_window = await browser.new_tab(in_window=page)
    assert page.window_id == 20
    assert same_window.window_id == 20
    assert (await browser.browser_info())["Protocol-Version"] == "1.3"
    moved = await browser.navigate(page, "https://example.test/review")
    assert moved.url.endswith("/review")
    assert await browser.evaluate(page, "(value) => value", {"ok": True}) == {"ok": True}
    assert await bridge.call("window_id", {"pageHandle": page.handle}) == {"windowId": 20}
    target_info = await bridge.call("target_info", {"pageHandle": page.handle})
    assert target_info["targetInfo"]["targetId"] == page.target_id
    assert target_info["targetInfo"]["type"] == "page"
    await browser.set_bounds(page, CdpWindowBounds(window_state="maximized"))
    await browser.activate(page)
    await browser.close(same_window)
    assert "Target.closeTarget" in [method for method, _, _ in fake.calls]


@pytest.mark.asyncio
async def test_projects_new_chat_uses_trusted_cdp_pointer_click(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"clicked": True}

    browser = GptAutoCdpBrowserController(Bridge())
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/projects", "")

    async def evaluate(_page, _function, _name=None):
        return {"x": 123.5, "y": 456.5, "projectId": "g-p-audiagentic"}

    monkeypatch.setattr(browser, "evaluate", evaluate)

    assert await browser._select_project_from_projects_page(page, "AUDiaGentic", timeout=1) == {"clicked": True, "projectId": "g-p-audiagentic"}
    assert calls == [
        ("keep_page_active", {"pageHandle": "page-1"}),
        ("click", {"pageHandle": "page-1", "x": 123.5, "y": 456.5}),
    ]


@pytest.mark.asyncio
async def test_sidebar_project_uses_trusted_pointer_for_exact_project(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    inputs: list[object] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"clicked": True}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/", "")

    async def evaluate(_page, _function, value=None):
        inputs.append(value)
        return {"action": "selected", "projectId": "g-p-69cc8c4cc7648191a009f358113d8dd2", "x": 101.5, "y": 202.5}

    monkeypatch.setattr(browser, "evaluate", evaluate)

    assert await browser._select_project_from_sidebar(
        page,
        "AUDiaGentic",
        expected_project_id="g-p-69cc8c4cc7648191a009f358113d8dd2",
        timeout=2,
    ) == {"clicked": True, "projectId": "g-p-69cc8c4cc7648191a009f358113d8dd2"}
    assert inputs == [{
        "name": "AUDiaGentic",
        "expectedProjectId": "g-p-69cc8c4cc7648191a009f358113d8dd2",
    }]
    assert calls == [
        ("keep_page_active", {"pageHandle": "page-1"}),
        ("click", {"pageHandle": "page-1", "x": 101.5, "y": 202.5}),
    ]


@pytest.mark.asyncio
async def test_sidebar_occluded_new_chat_hovers_once_then_trusted_clicks(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    actions = iter([
        {"action": "hover", "x": 120.0, "y": 44.0},
        {"action": "selected", "projectId": "g-p-69cc", "x": 277.6, "y": 44.0},
    ])

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"ok": True}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/", "")

    async def evaluate(_page, function, value=None):
        assert "button.contains(document.elementFromPoint" in function
        assert value["expectedProjectId"] == "g-p-69cc"
        return next(actions)

    monkeypatch.setattr(browser, "evaluate", evaluate)

    assert await browser._select_project_from_sidebar(
        page, "AUDiaGentic", expected_project_id="g-p-69cc", timeout=2
    ) == {"clicked": True, "projectId": "g-p-69cc"}
    assert calls == [
        ("keep_page_active", {"pageHandle": "page-1"}),
        ("hover", {"pageHandle": "page-1", "x": 120.0, "y": 44.0}),
        ("keep_page_active", {"pageHandle": "page-1"}),
        ("click", {"pageHandle": "page-1", "x": 277.6, "y": 44.0}),
    ]


@pytest.mark.asyncio
async def test_sidebar_project_rejects_wrong_exact_project_id(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/", "")

    async def evaluate(_page, function, value=None):
        assert "data-app-action-sidebar-project-id" in function
        assert value["expectedProjectId"] == "g-p-expected"
        return {"action": "project-id-mismatch", "actualProjectId": "g-p-wrong"}

    monkeypatch.setattr(browser, "evaluate", evaluate)

    assert await browser._select_project_from_sidebar(
        page, "AUDiaGentic", expected_project_id="g-p-expected", timeout=2
    ) is None
    assert calls == []


def test_projects_new_chat_point_scrolls_before_viewport_validation() -> None:
    scroll = _PROJECT_NEW_CHAT_POINT_FN.index("button.scrollIntoView")
    rect = _PROJECT_NEW_CHAT_POINT_FN.index("button.getBoundingClientRect", scroll)
    viewport = _PROJECT_NEW_CHAT_POINT_FN.index("window.innerWidth", rect)

    assert scroll < rect < viewport
    assert "x < 0 || y < 0" in _PROJECT_NEW_CHAT_POINT_FN
    assert "matching.length !== 1" in _PROJECT_NEW_CHAT_POINT_FN
    assert "canonicalProjectId" in _PROJECT_NEW_CHAT_POINT_FN


@pytest.mark.asyncio
async def test_sidebar_project_expands_once_before_selecting_new_chat(monkeypatch) -> None:
    import audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp as cdp

    calls: list[tuple[str, object]] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"clicked": True}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/", "")
    actions = iter([
        {"action": "expand", "x": 20, "y": 30},
        {"action": "waiting"},
        {"action": "selected", "projectId": "g-p-bigcherry", "x": 40, "y": 50},
    ])
    delays: list[float] = []

    async def evaluate(_page, _function, _value=None):
        return next(actions)

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(cdp.asyncio, "sleep", record_sleep)

    assert await browser._select_project_from_sidebar(
        page, "BigCherry", expected_project_id="g-p-bigcherry", timeout=2
    ) == {"clicked": True, "projectId": "g-p-bigcherry"}
    assert delays.count(browser._PAGE_READY_PAUSE_SECONDS) == 1
    assert [method for method, _params in calls].count("click") == 2


@pytest.mark.asyncio
async def test_sidebar_project_never_repeats_expand_pointer(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"clicked": True}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/", "")
    actions = iter([
        {"action": "expand", "x": 20, "y": 30},
        {"action": "expand", "x": 20, "y": 30},
    ])

    async def evaluate(_page, _function, _value=None):
        return next(actions)

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(asyncio, "sleep", no_wait)

    assert await browser._select_project_from_sidebar(
        page, "BigCherry", expected_project_id="g-p-bigcherry", timeout=2
    ) is None
    assert [method for method, _params in calls].count("click") == 1


@pytest.mark.asyncio
async def test_timed_out_anchor_cleanup_closes_only_late_blank_targets(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    anchor = CdpPageRef("anchor", "anchor-target", 7, "http://127.0.0.1:8765/dashboard", "")
    late_blank = CdpPageRef("late", "late-target", 7, "about:blank", "", "anchor-target")
    navigated = CdpPageRef("navigated", "navigated-target", 7, "https://example.test/", "", "anchor-target")
    unrelated = CdpPageRef("unrelated", "unrelated-target", 7, "about:blank", "", "other-target")
    closed: list[CdpPageRef] = []

    async def pages():
        return (late_blank, navigated, unrelated)

    async def close(page):
        closed.append(page)

    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "close", close)

    await browser._close_late_anchor_targets(anchor, {"anchor-target"})

    assert closed == [late_blank]


@pytest.mark.asyncio
async def test_timed_out_anchor_cleanup_fails_closed_when_baseline_is_unknown() -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    anchor = CdpPageRef("anchor", "anchor-target", 7, "http://127.0.0.1:8765/dashboard", "")
    closed: list[CdpPageRef] = []

    async def close(page):
        closed.append(page)

    browser.close = close  # type: ignore[method-assign]
    await browser._close_late_anchor_targets(anchor, None)

    assert closed == []


@pytest.mark.asyncio
async def test_timed_out_anchor_cleanup_catches_target_that_appears_after_first_scan(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    anchor = CdpPageRef("anchor", "anchor-target", 7, "http://127.0.0.1:8765/dashboard", "")
    late_blank = CdpPageRef("late", "late-target", 7, "about:blank", "", "anchor-target")
    closed: list[CdpPageRef] = []
    scans = iter([(), (late_blank,), (late_blank,)])

    async def pages():
        return next(scans)

    async def close(page):
        closed.append(page)

    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "close", close)
    await browser._close_late_anchor_targets(anchor, {"anchor-target"})

    assert closed == [late_blank]


@pytest.mark.asyncio
async def test_new_session_selects_exact_project_from_sidebar(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    anchor = CdpPageRef("anchor", "anchor-target", 7, "http://127.0.0.1:8765/dashboard", "")
    page = CdpPageRef("page-1", "target-1", 7, "about:blank", "")
    project_id = "g-p-6a7bbf85d06c8191835b0d64958b4d7a"
    selected_url = f"https://chatgpt.com/g/{project_id}-bigcherry/project"
    calls: list[tuple[str, object]] = []

    async def new_tab(*, in_window=None, url=None):
        calls.append(("new-tab", (in_window, url)))
        return page

    async def navigate(_page, url):
        calls.append(("navigate", url))
        return page

    async def evaluate(_page, _function, name=None):
        calls.append(("find-project", name))
        return True

    async def select_sidebar(_page, name, *, expected_project_id, timeout):
        calls.append(("select-sidebar", (name, expected_project_id, timeout)))
        return True

    page_after_click = CdpPageRef(page.handle, page.target_id, page.window_id, selected_url, "")

    async def pages():
        return (page,)

    async def page_by_handle(_handle):
        return page_after_click

    async def snapshot(_page):
        return {"url": selected_url, "composerPresent": True, "composerEditable": True}

    async def wait_for_composer(_page, *, timeout):
        calls.append(("composer", timeout))
        return await snapshot(_page)

    monkeypatch.setattr(browser, "new_tab", new_tab)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "snapshot", snapshot)
    monkeypatch.setattr(browser, "wait_for_composer", wait_for_composer)

    opened = await browser.open_project_page(
        project_name="BigCherry",
        project_url=f"https://chatgpt.com/g/{project_id}-bigcherry/project",
        anchor_page=anchor,
        navigation_timeout=3,
        ready_timeout=4,
    )

    assert calls == [
        ("new-tab", (anchor, None)),
        ("navigate", "https://chatgpt.com/"),
        ("select-sidebar", ("BigCherry", project_id, 3.0)),
        ("composer", 4),
    ]
    assert opened["projectUrl"] == selected_url


@pytest.mark.asyncio
async def test_new_session_uses_direct_projects_fallback_when_sidebar_has_no_project(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    page = CdpPageRef("page-1", "target-1", 7, "about:blank", "")
    project_id = "g-p-6a7bbf85d06c8191835b0d64958b4d7a"
    selected_url = f"https://chatgpt.com/g/{project_id}-bigcherry/project"
    calls: list[tuple[str, object]] = []

    async def new_window():
        return page

    async def navigate(_page, url):
        calls.append(("navigate", url))
        return page

    async def pages():
        return (page,)

    async def select_sidebar(_page, name, *, expected_project_id, timeout):
        calls.append(("select-sidebar", (name, expected_project_id, timeout)))
        return False

    async def wait_for_projects_route(_page, *, timeout):
        calls.append(("projects-route", timeout))
        return True

    async def select_project(_page, name, *, expected_project_id=None, timeout):
        calls.append(("select-project", (name, timeout)))
        return True

    async def page_by_handle(_handle):
        return CdpPageRef(page.handle, page.target_id, page.window_id, selected_url, "")

    async def wait_for_composer(_page, *, timeout):
        calls.append(("composer", timeout))
        return {"composerPresent": True, "composerEditable": True}

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "_wait_for_projects_route", wait_for_projects_route)
    monkeypatch.setattr(browser, "_select_project_from_projects_page", select_project)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "wait_for_composer", wait_for_composer)

    opened = await browser.open_project_page(
        project_name="BigCherry",
        project_url=f"https://chatgpt.com/g/{project_id}-bigcherry/project",
        anchor_page=None,
        navigation_timeout=3,
        ready_timeout=4,
    )

    assert calls == [
        ("navigate", "https://chatgpt.com/"),
        ("select-sidebar", ("BigCherry", project_id, 3.0)),
        ("navigate", "https://chatgpt.com/projects"),
        ("projects-route", 3),
        ("select-project", ("BigCherry", 3)),
        ("composer", 4),
    ]
    assert opened["projectUrl"] == selected_url


@pytest.mark.asyncio
async def test_new_session_rejects_projects_ui_identity_mismatch(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    page = CdpPageRef("page-1", "target-1", 7, "about:blank", "")
    configured_id = "g-p-configured"
    discovered_url = "https://chatgpt.com/g/g-p-different-project/project"
    closed: list[CdpPageRef] = []

    async def new_window():
        return page

    async def navigate(_page, _url):
        return page

    async def evaluate(_page, _function, _name=None):
        return True

    async def hover_text(_page, _label):
        return True

    async def click_text(_page, _label):
        return True

    async def wait_for_projects_route(_page, *, timeout):
        return True

    async def select_project(_page, _name, *, expected_project_id=None, timeout):
        return True

    async def select_sidebar(_page, _name, *, expected_project_id, timeout):
        return True

    discovered = CdpPageRef(page.handle, page.target_id, page.window_id, discovered_url, "")

    async def pages():
        return (page,)

    async def page_by_handle(_handle):
        return discovered

    async def close(closed_page):
        closed.append(closed_page)

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(browser, "hover_text", hover_text)
    monkeypatch.setattr(browser, "click_text", click_text)
    monkeypatch.setattr(browser, "_wait_for_projects_route", wait_for_projects_route)
    monkeypatch.setattr(browser, "_select_project_from_projects_page", select_project)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "close", close)
    with pytest.raises(RuntimeError, match="does not match configured project identity"):
        await browser.open_project_page(
            project_name="BigCherry",
            project_url=f"https://chatgpt.com/g/{configured_id}-bigcherry/project",
            anchor_page=None,
            navigation_timeout=0.01,
            ready_timeout=4,
        )

    assert closed == [page]


@pytest.mark.asyncio
async def test_new_session_rejects_wrong_projects_fallback_target_without_configured_url(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    projects_page = CdpPageRef("projects", "projects-target", 7, "about:blank", "")
    wrong_page = CdpPageRef(
        "chat", "chat-target", 7,
        "https://chatgpt.com/g/g-p-gpt-t1/project", "gpt-t1",
        opener_id=None,
    )
    closed: list[CdpPageRef] = []
    page_scans = 0

    async def new_window():
        return projects_page

    async def navigate(_page, _url):
        return projects_page

    async def select_sidebar(_page, _name, *, expected_project_id, timeout):
        return False

    async def open_projects(_page, *, timeout):
        return True

    async def select_project(_page, _name, *, expected_project_id=None, timeout):
        return {"clicked": True, "projectId": "g-p-bigcherry"}

    async def pages():
        nonlocal page_scans
        page_scans += 1
        return (projects_page,) if page_scans == 1 else (projects_page, wrong_page)

    async def page_by_handle(_handle):
        return CdpPageRef(
            projects_page.handle, projects_page.target_id, projects_page.window_id,
            "https://chatgpt.com/projects", "Projects",
        )

    async def close(page):
        closed.append(page)

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "_open_projects_tab", open_projects)
    monkeypatch.setattr(browser, "_select_project_from_projects_page", select_project)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "close", close)
    with pytest.raises(RuntimeError, match="does not match configured project identity"):
        await browser.open_project_page(
            project_name="BigCherry",
            project_url=None,
            anchor_page=None,
            navigation_timeout=0.01,
            ready_timeout=4,
        )

    assert closed == [wrong_page, projects_page]

@pytest.mark.asyncio
async def test_new_session_adopts_ui_opened_target_and_closes_projects_tab(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    projects_page = CdpPageRef("projects", "projects-target", 7, "about:blank", "")
    project_id = "g-p-6a7bbf85d06c8191835b0d64958b4d7a"
    opened_page = CdpPageRef(
        "chat", "chat-target", 7,
        f"https://chatgpt.com/g/{project_id}-bigcherry/project", "BigCherry",
        opener_id=None,
    )
    foreign_page = CdpPageRef("personal", "personal-target", 7, opened_page.url, "Personal")
    closed: list[CdpPageRef] = []
    page_scans = 0

    async def new_window():
        return projects_page

    async def navigate(_page, _url):
        return projects_page

    async def evaluate(_page, _function, _name=None):
        return True

    async def hover_text(_page, _label):
        return True

    async def click_text(_page, _label):
        return True

    async def wait_for_projects_route(_page, *, timeout):
        return True

    async def select_project(_page, _name, *, expected_project_id=None, timeout):
        return True

    async def select_sidebar(_page, _name, *, expected_project_id, timeout):
        return True

    async def pages():
        nonlocal page_scans
        page_scans += 1
        return (
            (projects_page, foreign_page)
            if page_scans == 1
            else (projects_page, foreign_page, opened_page)
        )

    async def page_by_handle(_handle):
        return CdpPageRef(
            projects_page.handle, projects_page.target_id, projects_page.window_id,
            "https://chatgpt.com/", "ChatGPT",
        )

    async def wait_for_composer(page, *, timeout):
        assert page == opened_page
        assert timeout == 4
        return {"composerPresent": True, "composerEditable": True}

    async def close(page):
        closed.append(page)

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "evaluate", evaluate)
    monkeypatch.setattr(browser, "hover_text", hover_text)
    monkeypatch.setattr(browser, "click_text", click_text)
    monkeypatch.setattr(browser, "_wait_for_projects_route", wait_for_projects_route)
    monkeypatch.setattr(browser, "_select_project_from_projects_page", select_project)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "wait_for_composer", wait_for_composer)
    monkeypatch.setattr(browser, "close", close)

    result = await browser.open_project_page(
        project_name="BigCherry",
        project_url=f"https://chatgpt.com/g/{project_id}-bigcherry/project",
        anchor_page=None,
        navigation_timeout=3,
        ready_timeout=4,
    )

    assert result["page"] == opened_page
    assert closed == [projects_page]


@pytest.mark.asyncio
async def test_new_session_rejects_fresh_wrong_project_target_without_opener(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(_NoopBridge())
    projects_page = CdpPageRef("projects", "projects-target", 7, "about:blank", "")
    configured_id = "g-p-configured"
    wrong_page = CdpPageRef(
        "chat", "chat-target", 7,
        "https://chatgpt.com/g/g-p-wrong-project/project", "Wrong Project",
        opener_id=None,
    )
    closed: list[CdpPageRef] = []
    page_scans = 0

    async def new_window():
        return projects_page

    async def navigate(_page, _url):
        return projects_page

    async def select_sidebar(_page, _name, *, expected_project_id, timeout):
        return True

    async def pages():
        nonlocal page_scans
        page_scans += 1
        return (projects_page,) if page_scans == 1 else (projects_page, wrong_page)

    async def page_by_handle(_handle):
        return CdpPageRef(
            projects_page.handle, projects_page.target_id, projects_page.window_id,
            "https://chatgpt.com/", "ChatGPT",
        )

    async def close(page):
        closed.append(page)

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "_select_project_from_sidebar", select_sidebar)
    monkeypatch.setattr(browser, "pages", pages)
    monkeypatch.setattr(browser, "page_by_handle", page_by_handle)
    monkeypatch.setattr(browser, "close", close)
    with pytest.raises(RuntimeError, match="does not match configured project identity"):
        await browser.open_project_page(
            project_name="BigCherry",
            project_url=f"https://chatgpt.com/g/{configured_id}-bigcherry/project",
            anchor_page=None,
            navigation_timeout=0.01,
            ready_timeout=4,
        )

    assert closed == [wrong_page, projects_page]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("unknown_handle", "unknown or closed page handle"),
        ("bad_url", "url must include a scheme"),
        ("bad_page_type", "expected CdpPageRef"),
    ],
)
async def test_typed_api_rejects_invalid_inputs(operation: str, expected: str):
    bridge, _ = _bridge()
    browser = CdpBrowserController(bridge)
    if operation == "unknown_handle":
        with pytest.raises(RuntimeError, match=expected):
            await browser.page_by_handle("page-missing")
    elif operation == "bad_url":
        page = await browser.new_window()
        with pytest.raises(ValueError, match=expected):
            await browser.navigate(page, "/relative")
    else:
        with pytest.raises(TypeError, match=expected):
            await browser.close("page-1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bridge_negative_protocol_and_navigation_failures_are_not_silent():
    bridge, fake = _bridge()
    page = await bridge.call("create_page")
    fake.fail_method = "Target.attachToTarget"
    with pytest.raises(RuntimeError, match="simulated Target.attachToTarget failure"):
        await bridge.evaluate(page["pageHandle"], "() => true")

    fake.fail_method = None
    fake.fail_method = "Page.navigate:error"
    with pytest.raises(RuntimeError, match="simulated navigation error"):
        await bridge.call("navigate", {"pageHandle": page["pageHandle"], "url": "https://bad.test"})


@pytest.mark.asyncio
async def test_bridge_unknown_method_and_closed_page_are_terminal_errors():
    bridge, _ = _bridge()
    page = await bridge.call("create_page")
    with pytest.raises(RuntimeError, match="unknown bridge method"):
        await bridge.call("not_a_cdp_operation", {"pageHandle": page["pageHandle"]})
    await bridge.call("close_page", {"pageHandle": page["pageHandle"]})
    with pytest.raises(RuntimeError, match="unknown or closed page handle"):
        await bridge.call("window_id", {"pageHandle": page["pageHandle"]})


@pytest.mark.asyncio
async def test_bridge_event_classification_only_marks_terminal_targets_as_page_loss():
    bridge, fake = _bridge()
    page = await bridge.call("create_page")
    target = page["targetId"]
    await fake.events.put(
        type(
            "Event",
            (),
            {
                "method": "Target.targetInfoChanged",
                "params": {"targetId": target},
                "session_id": None,
            },
        )()
    )
    await fake.events.put(
        type(
            "Event",
            (),
            {"method": "Page.lifecycleEvent", "params": {"targetId": target}, "session_id": None},
        )()
    )
    await fake.events.put(
        type(
            "Event",
            (),
            {
                "method": "Target.targetDestroyed",
                "params": {"targetId": target},
                "session_id": None,
            },
        )()
    )
    task = asyncio.create_task(bridge._route_events(fake))
    changed = await asyncio.wait_for(bridge.events.get(), timeout=1)
    lifecycle = await asyncio.wait_for(bridge.events.get(), timeout=1)
    destroyed = await asyncio.wait_for(bridge.events.get(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert changed == BridgeEvent("target_changed", page["pageHandle"], {"targetId": target})
    assert lifecycle.name == "page_lifecycle"
    assert destroyed.name == "page_closed"


@pytest.mark.asyncio
async def test_tab_creation_is_serialized_under_concurrency():
    bridge, fake = _bridge()
    await asyncio.gather(*(bridge.call("create_page") for _ in range(12)))
    creates = [call for call in fake.calls if call[0] == "Target.createTarget"]
    assert len(creates) == 12
    assert [call[1]["newWindow"] for call in creates].count(True) == 0


class _GptOperationBridge:
    def __init__(self, *, send_enabled: bool = True, stop_visible: bool = True) -> None:
        self.send_enabled = send_enabled
        self.stop_visible = stop_visible
        self.inserted_text = ""
        self.calls: list[tuple[str, dict]] = []

    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "editor?.innerText" in function:
            return self.inserted_text
        if "send-button" in function:
            return self.send_enabled
        if "stop-button" in function or "stop-generating" in function:
            return self.stop_visible
        return {"ok": True}

    async def call(self, method, params=None, **kwargs):
        self.calls.append((method, params or {}))
        if method == "insert_text":
            self.inserted_text = str((params or {}).get("text") or "")
        if method == "dispatch_enter":
            return {"ok": True}
        return {"ok": True}


class _NavigationOnClickBridge(_GptOperationBridge):
    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "send-button" in function:
            assert "async" not in function
        return await super().evaluate(page_handle, function, argument, **kwargs)


class _HungClickAcknowledgementBridge(_GptOperationBridge):
    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "send-button" in function:
            await asyncio.Event().wait()
        return await super().evaluate(page_handle, function, argument, **kwargs)


@pytest.mark.asyncio
async def test_gpt_provider_send_click_is_synchronous():
    bridge = _NavigationOnClickBridge()
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    result = await browser.submit(CdpPageRef("page-1", "target-1"), "stable send")
    assert result == {
        "actionComplete": True,
        "typedText": "stable send",
        "sendButtonClicked": True,
        "enterDispatched": False,
    }


@pytest.mark.asyncio
async def test_gpt_provider_hung_click_acknowledgement_exits_ambiguous_quickly(monkeypatch):
    from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
        ComposerSubmissionTimeout,
    )

    monkeypatch.setattr(
        GptAutoCdpBrowserController,
        "_SEND_CLICK_ACK_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(GptAutoCdpBrowserController, "_PAGE_READY_PAUSE_SECONDS", 0.0)
    monkeypatch.setattr(GptAutoCdpBrowserController, "_TYPED_PAUSE_SECONDS", 0.0)
    browser = GptAutoCdpBrowserController(
        _HungClickAcknowledgementBridge(),  # type: ignore[arg-type]
        action_pause_seconds=0.0,
    )

    with pytest.raises(ComposerSubmissionTimeout) as raised:
        await asyncio.wait_for(
            browser.submit(
                CdpPageRef("page-1", "target-1"),
                "ambiguous send",
                timeout=120.0,
            ),
            timeout=0.5,
        )

    assert raised.value.send_attempted is True
    assert raised.value.stage == "send-button"


@pytest.mark.asyncio
async def test_gpt_provider_waits_for_composer_state_before_click(monkeypatch):
    """Readiness polling continues beyond the old three-attempt limit."""
    import audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp as cdp

    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(cdp.asyncio, "sleep", record_sleep)
    browser = GptAutoCdpBrowserController(_TransientSendFailureBridge(fail_attempts=5))  # type: ignore[arg-type]
    await browser.submit(CdpPageRef("page-1", "target-1"), "settle first")
    assert delays.count(GptAutoCdpBrowserController._SUBMIT_POLL_SECONDS) == 5
    assert delays.count(GptAutoCdpBrowserController._PAGE_READY_PAUSE_SECONDS) >= 2
    # insertion, send-button readiness, and the post-click render turn each
    # get a short browser-action pause.
    assert delays.count(GptAutoCdpBrowserController._ACTION_PAUSE_SECONDS) >= 3


@pytest.mark.asyncio
async def test_gpt_provider_submit_and_stop_use_fake_dom_responses():
    bridge = _GptOperationBridge()
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    submitted = await browser.submit(page, "review gateway")
    assert submitted == {
        "actionComplete": True,
        "typedText": "review gateway",
        "sendButtonClicked": True,
        "enterDispatched": False,
    }
    assert (await browser.stop_generation(page))["stopped"] is True


@pytest.mark.asyncio
async def test_gpt_provider_never_bypasses_disabled_send_with_enter():
    bridge = _GptOperationBridge(send_enabled=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
        ComposerSubmissionTimeout,
    )
    with pytest.raises(ComposerSubmissionTimeout) as raised:
        await browser.submit(page, "fallback", timeout=0.02)
    assert raised.value.send_attempted is False
    assert raised.value.stage == "composer-readiness"
    assert not any(method == "dispatch_enter" for method, _ in bridge.calls)


class _TransientSendFailureBridge(_GptOperationBridge):
    """The send button is disabled for the first `fail_attempts` evaluate
    calls that check it, then becomes available -- simulates the real
    composer-not-yet-settled window found live (GP11)."""

    def __init__(self, *, fail_attempts: int) -> None:
        super().__init__(send_enabled=False)
        self._fail_attempts = fail_attempts
        self._send_checks = 0

    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "send-button" in function:
            self._send_checks += 1
            self.send_enabled = self._send_checks > self._fail_attempts
        return await super().evaluate(page_handle, function, argument, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at,ambiguous", [(1, False), (2, True)])
async def test_composer_timeout_preserves_send_boundary(monkeypatch, fail_at, ambiguous):
    from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
        ComposerSubmissionTimeout,
    )

    browser = GptAutoCdpBrowserController(_GptOperationBridge())
    calls = 0

    async def evaluate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise TimeoutError("simulated CDP timeout")
        return "prompt"

    monkeypatch.setattr(browser, "evaluate", evaluate)
    with pytest.raises(ComposerSubmissionTimeout) as raised:
        await browser.submit(CdpPageRef("page-1", "target-1"), "prompt")
    assert raised.value.send_attempted is ambiguous
    assert raised.value.stage == ("send-button" if ambiguous else "composer-insertion")


@pytest.mark.asyncio
async def test_gpt_provider_submit_retries_and_recovers_from_transient_send_failure():
    """GP11: a transiently-disabled/absent send button (e.g. right after a
    prior turn resolves, before the composer settles) must not fail the
    whole submission on the first attempt -- submit() retries a bounded
    number of times and succeeds once the button becomes available again."""
    bridge = _TransientSendFailureBridge(fail_attempts=1)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    result = await browser.submit(page, "retry recovers")
    assert result["actionComplete"] is True
    assert result["sendButtonClicked"] is True
    # Retry only before sending; Enter is reserved for the final attempt.
    assert sum(1 for method, _ in bridge.calls if method == "dispatch_enter") == 0


@pytest.mark.asyncio
async def test_gpt_provider_submit_gives_up_after_bounded_retries():
    """A permanently disabled Send times out without a submission attempt."""
    bridge = _TransientSendFailureBridge(fail_attempts=999)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
        ComposerSubmissionTimeout,
    )
    with pytest.raises(ComposerSubmissionTimeout):
        await browser.submit(page, "never recovers", timeout=0.02)
    assert (
        sum(1 for method, _ in bridge.calls if method == "dispatch_enter")
        == 0
    )


@pytest.mark.asyncio
async def test_gpt_provider_rejects_blank_prompt_and_reports_no_stop_control():
    bridge = _GptOperationBridge(stop_visible=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    with pytest.raises(ValueError, match="non-empty"):
        await browser.submit(page, "   ")
    assert (await browser.stop_generation(page))["stopped"] is False
@pytest.mark.asyncio
async def test_projects_new_chat_rejects_identityless_dom_pointer(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Bridge:
        async def call(self, method, params=None, **_kwargs):
            calls.append((method, params))
            return {"clicked": True}

    browser = GptAutoCdpBrowserController(Bridge(), action_pause_seconds=0.0)
    page = CdpPageRef("page-1", "target-1", 7, "https://chatgpt.com/projects", "")

    async def evaluate(_page, _function, _value=None):
        return {"x": 123.5, "y": 456.5}

    monkeypatch.setattr(browser, "evaluate", evaluate)

    assert await browser._select_project_from_projects_page(
        page, "BigCherry", timeout=0.05
    ) is None
    assert calls == []
