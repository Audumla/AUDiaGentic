from __future__ import annotations

import asyncio
import os

import pytest

from audiagentic.components.providers.adapters.gpt_auto.cdp.bridge import PythonCdpBridge
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


class _FakeClient:
    def __init__(self) -> None:
        self.events = asyncio.Queue()
        self.calls: list[tuple[str, dict, str | None]] = []
        self.next_target = 1

    async def command(self, method, params=None, *, session_id=None, timeout=None):
        params = params or {}
        self.calls.append((method, params, session_id))
        if method == "Target.getTargets":
            return {"targetInfos": []}
        if method in {"Target.setDiscoverTargets", "Target.closeTarget"}:
            return {}
        if method == "Target.createTarget":
            target = f"target-{self.next_target}"
            self.next_target += 1
            return {"targetId": target}
        if method == "Browser.getWindowForTarget":
            return {"windowId": 42}
        if method == "Browser.getVersion":
            return {"Browser": "Chrome/Test", "Protocol-Version": "1.3"}
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
        if method == "Browser.setWindowBounds":
            return {}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": params["targetId"], "type": "page"}}
        if method == "Target.activateTarget":
            return {}
        if method == "Target.attachToTarget":
            return {"sessionId": f"session-{params['targetId']}"}
        if method == "Runtime.evaluate":
            return {"result": {"value": {"ok": True}}}
        return {}


@pytest.mark.asyncio
async def test_python_bridge_serializes_page_creation_and_returns_window_identity():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    bridge._client = fake
    await bridge._refresh_pages()

    first, second = await asyncio.gather(
        bridge.call("create_window_page"), bridge.call("create_page")
    )

    assert first["pageHandle"] != second["pageHandle"]
    assert first["windowId"] == 42
    assert second["windowId"] == 42
    creates = [call for call in fake.calls if call[0] == "Target.createTarget"]
    assert creates[0][1]["newWindow"] is True
    assert creates[1][1]["newWindow"] is False


@pytest.mark.asyncio
async def test_python_bridge_uses_page_session_for_navigation_and_evaluation():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    bridge._client = fake
    page = await bridge.call("create_page")

    await bridge.call("navigate", {"pageHandle": page["pageHandle"], "url": "about:blank"})
    await bridge.evaluate(page["pageHandle"], "() => ({ok: true})")

    assert any(call[0] == "Target.attachToTarget" for call in fake.calls)
    assert any(call[0] == "Page.navigate" for call in fake.calls)
    assert any(call[0] == "Runtime.evaluate" for call in fake.calls)


@pytest.mark.asyncio
async def test_python_bridge_exposes_browser_window_and_target_api_operations():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    bridge._client = fake
    page = await bridge.call("create_page")

    assert (await bridge.call("browser_info"))["Protocol-Version"] == "1.3"
    bounds = await bridge.call("window_bounds", {"pageHandle": page["pageHandle"]})
    assert bounds["bounds"]["width"] == 800
    await bridge.call(
        "set_window_bounds",
        {"pageHandle": page["pageHandle"], "bounds": {"windowState": "maximized"}},
    )
    target_info = await bridge.call("target_info", {"pageHandle": page["pageHandle"]})
    assert target_info["targetInfo"]["type"] == "page"
    await bridge.call("activate_target", {"pageHandle": page["pageHandle"]})
    methods = [call[0] for call in fake.calls]
    assert "Browser.getVersion" in methods
    assert "Browser.setWindowBounds" in methods
    assert "Target.activateTarget" in methods


@pytest.mark.asyncio
async def test_typed_browser_api_validates_and_wraps_page_operations():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    bridge._client = fake
    api = GptAutoCdpBrowserController(bridge)
    page = await api.new_window()
    assert isinstance(page, CdpPageRef)
    assert page.window_id == 42
    moved = await api.navigate(page, "https://example.test")
    assert moved.url == "https://example.test"
    await api.set_bounds(page, CdpWindowBounds(window_state="maximized"))
    with pytest.raises(ValueError, match="url"):
        await api.navigate(page, "/relative")
    with pytest.raises(TypeError, match="CdpPageRef"):
        await api.close("page-1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_generic_browser_api_supports_common_page_composites():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    bridge._client = fake
    api = CdpBrowserController(bridge)
    page = await api.new_window()
    assert page.window_id == 42
    assert await api.evaluate(page, "(value) => value", {"ok": True}) == {"ok": True}
    await api.activate(page)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_GPT_AUTO_LIVE") != "1",
    reason="set AUDIAGENTIC_GPT_AUTO_LIVE=1 to use the existing CDP browser",
)
async def test_python_bridge_live_page_and_window_lifecycle():
    """Smoke test for generic lifecycle plus the GPT adapter boundary."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    api = GptAutoCdpBrowserController(bridge)
    pages: list[str] = []
    await bridge.start()
    try:
        page, second_page = await asyncio.gather(
            bridge.call("create_window_page"), bridge.call("create_page")
        )
        pages.extend([page["pageHandle"], second_page["pageHandle"]])
        assert page["windowId"] is not None
        assert second_page["pageHandle"] != page["pageHandle"]
        browser_info = await bridge.call("browser_info")
        assert browser_info.get("protocolVersion") or browser_info.get("Protocol-Version")
        target_info = await bridge.call("target_info", {"pageHandle": page["pageHandle"]})
        assert target_info["targetInfo"]["type"] == "page"
        bounds = await bridge.call("window_bounds", {"pageHandle": page["pageHandle"]})
        assert bounds["bounds"]["windowState"] in {"normal", "maximized", "minimized"}
        await bridge.call(
            "set_window_bounds", {"pageHandle": page["pageHandle"], "bounds": bounds["bounds"]}
        )
        await bridge.call("activate_target", {"pageHandle": page["pageHandle"]})
        in_window = await bridge.call(
            "create_page_in_window", {"anchorPageHandle": page["pageHandle"]}
        )
        pages.append(in_window["pageHandle"])
        assert in_window["windowId"] == page["windowId"]
        listed = await bridge.call("list_pages")
        assert any(item["pageHandle"] == page["pageHandle"] for item in listed)
        html = (
            "data:text/html,<html><body>"
            "<div class='ProseMirror' contenteditable='true'></div>"
            "</body></html>"
        )
        await bridge.call("navigate", {"pageHandle": page["pageHandle"], "url": html})
        page_ref = await api.page_by_handle(page["pageHandle"])
        snapshot = await api.wait_for_composer(page_ref, timeout=5)
        assert snapshot["composerPresent"] is True
        assert snapshot["composerEditable"] is True
        await bridge.call("keep_page_active", {"pageHandle": page["pageHandle"]})
        submitted = await api.submit(page_ref, "CDP bridge live smoke")
        assert submitted == {
            "actionComplete": True,
            "typedText": "CDP bridge live smoke",
        }
        stopped = await api.stop_generation(page_ref)
        assert stopped["stopped"] is False
        target_id = await bridge._target(page["pageHandle"])
        await bridge.client.command("Target.closeTarget", {"targetId": target_id})
        deadline = asyncio.get_running_loop().time() + 5
        lifecycle = None
        while asyncio.get_running_loop().time() < deadline:
            event = await asyncio.wait_for(bridge.events.get(), timeout=5)
            if event.name == "page_closed" and event.page_handle == page["pageHandle"]:
                lifecycle = event
                break
        assert lifecycle is not None
        pages.remove(page["pageHandle"])
    finally:
        for page_handle in reversed(pages):
            try:
                await bridge.call("close_page", {"pageHandle": page_handle})
            except Exception:
                pass
        await bridge.stop()
