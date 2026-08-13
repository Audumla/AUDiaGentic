"""Deterministic CDP bridge/adaptor scenario matrix.

No browser, websocket, network, or ChatGPT process is used here.  The fake
client models CDP commands and target responses so lifecycle behaviour can be
tested repeatably, including malformed/negative responses.
"""

from __future__ import annotations

import asyncio

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
    GptAutoCdpBrowserController,
)

from .test_greenfield_config_urls import valid_config


class _ScenarioClient:
    def __init__(self) -> None:
        self.events: asyncio.Queue = asyncio.Queue()
        self.calls: list[tuple[str, dict, str | None]] = []
        self.targets: dict[str, dict] = {}
        self.next_target = 1
        self.fail_method: str | None = None
        self.window_open_target: str | None = None

    async def command(self, method, params=None, *, session_id=None, timeout=None):
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
            return {"errorText": "simulated navigation error"} if self.fail_method == "Page.navigate:error" else {}
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
            return {"bounds": {"left": 0, "top": 0, "width": 800, "height": 600, "windowState": "normal"}}
        if method == "Target.getTargetInfo":
            return {"targetInfo": self.targets.get(params["targetId"], {"targetId": params["targetId"], "type": "page"})}
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
    await fake.events.put(type("Event", (), {"method": "Target.targetInfoChanged", "params": {"targetId": target}, "session_id": None})())
    await fake.events.put(type("Event", (), {"method": "Page.lifecycleEvent", "params": {"targetId": target}, "session_id": None})())
    await fake.events.put(type("Event", (), {"method": "Target.targetDestroyed", "params": {"targetId": target}, "session_id": None})())
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


@pytest.mark.asyncio
async def test_gpt_provider_submit_and_stop_use_fake_dom_responses():
    bridge = _GptOperationBridge()
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    submitted = await browser.submit(page, "review gateway")
    assert submitted == {"actionComplete": True, "typedText": "review gateway"}
    assert (await browser.stop_generation(page))["stopped"] is True


@pytest.mark.asyncio
async def test_gpt_provider_submit_falls_back_to_enter_when_send_is_disabled():
    bridge = _GptOperationBridge(send_enabled=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    result = await browser.submit(page, "fallback")
    assert result["actionComplete"] is True
    assert any(method == "dispatch_enter" for method, _ in bridge.calls)


@pytest.mark.asyncio
async def test_gpt_provider_rejects_blank_prompt_and_reports_no_stop_control():
    bridge = _GptOperationBridge(stop_visible=False)
    browser = GptAutoCdpBrowserController(bridge)  # type: ignore[arg-type]
    page = CdpPageRef("page-1", "target-1")
    with pytest.raises(ValueError, match="non-empty"):
        await browser.submit(page, "   ")
    assert (await browser.stop_generation(page))["stopped"] is False
