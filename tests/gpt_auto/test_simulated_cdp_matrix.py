"""Deterministic CDP bridge/adaptor scenario matrix.

No browser, websocket, network, or ChatGPT process is used here.  The fake
client models CDP commands and target responses so lifecycle behaviour can be
tested repeatably, including malformed/negative responses.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
    _SNAPSHOT_FN,
    GptAutoCdpBrowserController,
)

from .test_greenfield_config_urls import valid_config


def test_snapshot_does_not_promote_static_streaming_animation_to_busy() -> None:
    """The live ChatGPT DOM keeps this class after a response completes."""
    assert 'selector !== ".streaming-animation"' in _SNAPSHOT_FN


def test_snapshot_activity_labels_are_case_insensitive_and_cover_tool_rows() -> None:
    """The bridge recognizes the labels operators see in ChatGPT's UI."""
    assert 'toLowerCase()' in _SNAPSHOT_FN
    for label in ("talked to app", "called tool", "searching the web", "read resource", "thinking"):
        assert label in _SNAPSHOT_FN


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
    assert ") : latestAgentTurn;" in _SNAPSHOT_FN
    assert "[class~=\"group/tool-message\"]" in _SNAPSHOT_FN


def test_snapshot_preserves_structural_hr_for_user_prompt_correlation() -> None:
    """A rendered thematic break must be recoverable only for correlation."""
    assert "const userCorrelation = (element)" in _SNAPSHOT_FN
    assert "querySelectorAll('hr')" in _SNAPSHOT_FN
    assert 'document.createTextNode("\\n---\\n")' in _SNAPSHOT_FN
    assert "correlationText" in _SNAPSHOT_FN
    assert "structuralHrCount" in _SNAPSHOT_FN


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

        async def evaluate(self, _page_handle, function, _argument=None, **_kwargs):
            self.functions.append(function)
            return "scrollIntoView" in function

    bridge = _MaterializeBridge()
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")

    assert await browser.materialize_latest_assistant_turn(page)
    assert len(bridge.functions) == 1
    assert "scrollIntoView" in bridge.functions[0]
    assert "click" not in bridge.functions[0]
    assert "Target.createTarget" not in bridge.functions[0]


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
async def test_configured_project_opens_its_workspace_route(monkeypatch) -> None:
    """A bare project URL must not create a global ChatGPT conversation."""
    browser = GptAutoCdpBrowserController(SimpleNamespace())
    page = CdpPageRef("page-1", "target-1", 1, "about:blank", "")
    navigated: list[str] = []

    async def new_window() -> CdpPageRef:
        return page

    async def navigate(_page: CdpPageRef, url: str) -> CdpPageRef:
        navigated.append(url)
        return page

    async def composer_ready(_page: CdpPageRef, *, timeout: float) -> None:
        assert timeout == 4

    async def snapshot(_page: CdpPageRef) -> dict[str, str]:
        return {"url": "https://chatgpt.com/g/g-p-test-project/project"}

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "snapshot", snapshot)
    monkeypatch.setattr(browser, "wait_for_composer", composer_ready)

    opened = await browser.open_project_page(
        project_name="ignored-when-url-is-configured",
        project_url="https://chat.openai.com/g/g-p-test-project",
        anchor_page=None,
        navigation_timeout=3,
        ready_timeout=4,
    )

    assert navigated == ["https://chatgpt.com/g/g-p-test-project/project"]
    assert opened["projectUrl"] == navigated[0]


@pytest.mark.asyncio
async def test_project_redirect_to_global_chat_is_closed_and_rejected(monkeypatch) -> None:
    browser = GptAutoCdpBrowserController(SimpleNamespace())
    page = CdpPageRef("page-1", "target-1", 1, "about:blank", "")
    closed: list[str] = []

    async def new_window() -> CdpPageRef:
        return page

    async def navigate(_page: CdpPageRef, _url: str) -> CdpPageRef:
        return page

    async def snapshot(_page: CdpPageRef) -> dict[str, str]:
        return {"url": "https://chatgpt.com/"}

    async def close(closed_page: CdpPageRef) -> None:
        closed.append(closed_page.handle)

    monkeypatch.setattr(browser, "new_window", new_window)
    monkeypatch.setattr(browser, "navigate", navigate)
    monkeypatch.setattr(browser, "snapshot", snapshot)
    monkeypatch.setattr(browser, "close", close)

    with pytest.raises(RuntimeError, match="Project is unavailable"):
        await browser.open_project_page(
            project_name="unused",
            project_url="https://chatgpt.com/g/g-p-test-project",
            anchor_page=None,
            navigation_timeout=3,
            ready_timeout=4,
        )

    assert closed == ["page-1"]


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
        self.calls: list[tuple[str, dict]] = []

    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "execCommand" in function:
            return str(argument or "")
        if "send-button" in function:
            return self.send_enabled
        if "stop-button" in function or "stop-generating" in function:
            return self.stop_visible
        return {"ok": True}

    async def call(self, method, params=None, **kwargs):
        self.calls.append((method, params or {}))
        if method == "dispatch_enter":
            return {"ok": True}
        return {"ok": True}


class _NavigationOnClickBridge(_GptOperationBridge):
    async def evaluate(self, page_handle, function, argument=None, **kwargs):
        if "send-button" in function:
            assert "async" not in function
        return await super().evaluate(page_handle, function, argument, **kwargs)


@pytest.mark.asyncio
async def test_gpt_provider_send_click_is_synchronous_after_python_settle_delay():
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
async def test_gpt_provider_waits_for_composer_state_before_click(monkeypatch):
    """The input event gets a bounded React settle window before Send."""
    import audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp as cdp

    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(cdp.asyncio, "sleep", record_sleep)
    browser = GptAutoCdpBrowserController(_GptOperationBridge())  # type: ignore[arg-type]
    await browser.submit(CdpPageRef("page-1", "target-1"), "settle first")
    assert delays[0] == GptAutoCdpBrowserController._COMPOSER_SETTLE_DELAY_SECONDS
    assert delays[0] >= 0.1


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
async def test_gpt_provider_submit_falls_back_to_enter_when_send_is_disabled():
    bridge = _GptOperationBridge(send_enabled=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    result = await browser.submit(page, "fallback")
    assert result["actionComplete"] is False
    assert result["sendButtonClicked"] is False
    assert result["enterDispatched"] is True
    assert any(method == "dispatch_enter" for method, _ in bridge.calls)


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
    # One dispatch_enter fallback from the failed first attempt, no more.
    assert sum(1 for method, _ in bridge.calls if method == "dispatch_enter") == 1


@pytest.mark.asyncio
async def test_gpt_provider_submit_gives_up_after_bounded_retries():
    """A send button that never becomes available exhausts the retry bound
    and still reports actionComplete=False -- never silently succeeds."""
    bridge = _TransientSendFailureBridge(fail_attempts=999)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    result = await browser.submit(page, "never recovers")
    assert result["actionComplete"] is False
    assert (
        sum(1 for method, _ in bridge.calls if method == "dispatch_enter")
        == GptAutoCdpBrowserController._SUBMIT_MAX_ATTEMPTS
    )


@pytest.mark.asyncio
async def test_gpt_provider_rejects_blank_prompt_and_reports_no_stop_control():
    bridge = _GptOperationBridge(stop_visible=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    with pytest.raises(ValueError, match="non-empty"):
        await browser.submit(page, "   ")
    assert (await browser.stop_generation(page))["stopped"] is False
