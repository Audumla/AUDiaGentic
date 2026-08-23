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
from audiagentic.components.providers.adapters.gpt_auto.cdp.client import (
    CdpError,
    CdpProtocolError,
    CdpStaleGenerationError,
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

    async def command(self, method, params=None, *, session_id=None, timeout=None, required_generation=None):
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


class _GenerationRaceClient:
    """Enforces required_generation the same way the real CdpClient does,
    and simulates a reconnect completing in the gap between a session
    finishing its attach sequence and the caller's actual work command
    being sent -- the exact TOCTOU window GP18 code review flagged."""

    def __init__(self) -> None:
        self.connection_generation = 1
        self._attach_count = 0
        self.commands: list[tuple[str, str | None, int | None]] = []

    async def command(self, method, params=None, *, session_id=None, timeout=None, required_generation=None):
        self.commands.append((method, session_id, required_generation))
        if required_generation is not None and required_generation != self.connection_generation:
            raise CdpStaleGenerationError(
                f"stale: required={required_generation} current={self.connection_generation}"
            )
        if method == "Target.attachToTarget":
            self._attach_count += 1
            return {"sessionId": f"session-gen{self.connection_generation}-{self._attach_count}"}
        if method == "Page.setLifecycleEventsEnabled":
            # A concurrent reconnect completes exactly after the FIRST
            # session finishes attaching -- only once, so the retried
            # attach converges instead of looping forever.
            if self.connection_generation == 1:
                self.connection_generation = 2
            return {}
        if method in {"Page.enable", "Target.setDiscoverTargets"}:
            return {}
        if method == "Target.getTargets":
            return {"targetInfos": []}
        if method == "Runtime.evaluate":
            return {"result": {"value": "ok"}}
        return {}


@pytest.mark.asyncio
async def test_session_command_retries_once_when_reconnect_happens_between_session_fetch_and_send():
    """GP18 code-review follow-up (the specific test the reviewer asked
    for): deliberately force a reconnect precisely between _session()
    finishing and its session-scoped command being sent, and prove no
    stale sessionId is ever actually transmitted -- the bridge must
    detect the generation mismatch and retry with a freshly-attached
    session instead of sending a doomed request."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    client = _GenerationRaceClient()
    bridge._client = client
    bridge._known_connection_generation = client.connection_generation
    bridge._pages["page-1"] = "target-1"

    result = await bridge._session_command("page-1", "Runtime.evaluate", {"expression": "1"})

    assert result == {"result": {"value": "ok"}}
    attach_calls = [c for c in client.commands if c[0] == "Target.attachToTarget"]
    assert len(attach_calls) == 2, "expected exactly one retry after the mid-attach generation bump"
    # The fake logs a call before enforcing required_generation (mirroring
    # the real client's own trace-then-check order), so the doomed
    # generation-1 attempt is recorded too -- it must have been REJECTED
    # (never actually reached a successful result), and the retry must
    # have used the fresh, post-bump session.
    runtime_calls = [c for c in client.commands if c[0] == "Runtime.evaluate"]
    assert len(runtime_calls) == 2
    rejected, retried = runtime_calls
    assert rejected == ("Runtime.evaluate", "session-gen1-1", 1)
    assert retried == ("Runtime.evaluate", "session-gen2-2", 2)
    assert bridge._sessions["target-1"] == "session-gen2-2"


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
async def test_refresh_pages_tolerates_one_target_with_no_resolvable_window():
    """A devtools:// inspector page (or any windowless target) alongside real
    tabbed pages must not abort enumeration of every other live page --
    reproduced live 2026-08-16 when an operator-opened devtools inspector
    broke session dispatch machine-wide across every gpt-auto project
    sharing the browser."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()

    async def command(method, params=None, *, session_id=None, timeout=None):
        params = params or {}
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {"targetId": "target-devtools", "type": "page", "url": "devtools://devtools/x"},
                    {"targetId": "target-real", "type": "page", "url": "https://chatgpt.com/"},
                ]
            }
        if method == "Browser.getWindowForTarget":
            if params.get("targetId") == "target-devtools":
                raise CdpError("Browser window not found")
            return {"windowId": 42}
        return await _FakeClient.command(fake, method, params, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake

    pages = await bridge._refresh_pages()

    assert len(pages) == 2
    by_target = {p["targetId"]: p for p in pages}
    assert by_target["target-devtools"]["windowId"] is None
    assert by_target["target-real"]["windowId"] == 42


@pytest.mark.asyncio
async def test_refresh_pages_skips_window_lookup_for_unrelated_browser_tabs():
    """GP42: the shared browser can have dozens of ordinary tabs open that
    have nothing to do with gpt-auto. _refresh_pages() must not spend a
    Browser.getWindowForTarget round-trip resolving a window for every one
    of them -- only tabs that could plausibly be ours (ChatGPT, the gateway
    dashboard, data: pages, and about:blank) are worth resolving."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    window_lookup_targets: list[str] = []

    async def command(method, params=None, *, session_id=None, timeout=None):
        params = params or {}
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {"targetId": "target-chatgpt", "type": "page", "url": "https://chatgpt.com/c/abc"},
                    {"targetId": "target-dashboard", "type": "page", "url": "http://127.0.0.1:8765/dashboard?audiagentic-window-anchor=1"},
                    {"targetId": "target-reddit", "type": "page", "url": "https://reddit.com/r/x"},
                    {"targetId": "target-amazon", "type": "page", "url": "https://amazon.com/dp/1"},
                    {"targetId": "target-blank", "type": "page", "url": "about:blank"},
                ]
            }
        if method == "Browser.getWindowForTarget":
            window_lookup_targets.append(str(params.get("targetId")))
            return {"windowId": 42}
        return await _FakeClient.command(fake, method, params, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake

    pages = await bridge._refresh_pages()

    assert len(pages) == 5
    assert set(window_lookup_targets) == {"target-chatgpt", "target-dashboard", "target-blank"}
    by_target = {p["targetId"]: p for p in pages}
    assert by_target["target-reddit"]["windowId"] is None
    assert by_target["target-amazon"]["windowId"] is None
    assert by_target["target-chatgpt"]["windowId"] == 42
    assert by_target["target-dashboard"]["windowId"] == 42
    assert by_target["target-blank"]["windowId"] == 42


@pytest.mark.asyncio
async def test_get_page_resolves_single_target_without_enumerating_all_tabs():
    """GP42: chat.py calls page_by_handle() on every poll tick of every
    open conversation. That must not enumerate every target on the shared
    browser (Target.getTargets) each time -- only look up the one handle
    already known locally, via Target.getTargetInfo."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    get_targets_calls = 0

    async def command(method, params=None, *, session_id=None, timeout=None):
        nonlocal get_targets_calls
        params = params or {}
        if method == "Target.getTargets":
            get_targets_calls += 1
            return {"targetInfos": []}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": params["targetId"], "url": "https://chatgpt.com/c/abc"}}
        return await _FakeClient.command(fake, method, params, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake
    bridge._pages["page-1"] = "target-1"

    page = await bridge.call("get_page", {"pageHandle": "page-1"})

    assert page == {
        "pageHandle": "page-1",
        "url": "https://chatgpt.com/c/abc",
        "title": "",
        "targetId": "target-1",
        "windowId": 42,
    }
    assert get_targets_calls == 0


@pytest.mark.asyncio
async def test_get_page_raises_and_forgets_handle_for_genuinely_closed_target():
    """A CdpProtocolError from Target.getTargetInfo is the CDP server
    itself saying the target no longer exists -- the one case where
    forgetting the handle is correct."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()

    async def command(method, params=None, *, session_id=None, timeout=None):
        if method == "Target.getTargetInfo":
            raise CdpProtocolError("No target with given id found")
        return await _FakeClient.command(fake, method, params or {}, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake
    bridge._pages["page-1"] = "target-1"
    bridge._sessions["target-1"] = "session-1"

    with pytest.raises(RuntimeError, match="unknown or closed page handle"):
        await bridge.call("get_page", {"pageHandle": "page-1"})

    assert "page-1" not in bridge._pages
    assert "target-1" not in bridge._sessions


@pytest.mark.asyncio
async def test_get_page_preserves_handle_on_transport_failure():
    """GP42 code review blocker (B1): GP18 established _pages deliberately
    survives a CDP WebSocket reconnect -- attached sessionIds do not, but
    target/page identity does. A transport-level CdpError (connection
    closed, client stopped, stale connection) from Target.getTargetInfo is
    NOT proof the target itself is gone; erasing the handle on any such
    CdpError would turn a recoverable connection event into apparent page
    destruction. Only a CdpProtocolError (the CDP server's own "no such
    target" response) may do that."""
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()

    async def command(method, params=None, *, session_id=None, timeout=None):
        if method == "Target.getTargetInfo":
            raise CdpError("CDP connection closed: socket closed")
        return await _FakeClient.command(fake, method, params or {}, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake
    bridge._pages["page-1"] = "target-1"
    bridge._sessions["target-1"] = "session-1"

    with pytest.raises(CdpError):
        await bridge.call("get_page", {"pageHandle": "page-1"})

    assert bridge._pages["page-1"] == "target-1"
    assert bridge._sessions["target-1"] == "session-1"


@pytest.mark.asyncio
async def test_page_by_handle_uses_get_page_not_full_page_enumeration():
    bridge = PythonCdpBridge(GptAutoConfig.from_dict(valid_config()))
    fake = _FakeClient()
    get_targets_calls = 0

    async def command(method, params=None, *, session_id=None, timeout=None):
        nonlocal get_targets_calls
        params = params or {}
        if method == "Target.getTargets":
            get_targets_calls += 1
            return {"targetInfos": []}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": params["targetId"], "url": "https://chatgpt.com/c/abc"}}
        return await _FakeClient.command(fake, method, params, session_id=session_id, timeout=timeout)

    fake.command = command
    bridge._client = fake
    bridge._pages["page-1"] = "target-1"
    api = CdpBrowserController(bridge)

    page = await api.page_by_handle("page-1")

    assert isinstance(page, CdpPageRef)
    assert page.handle == "page-1"
    assert page.url == "https://chatgpt.com/c/abc"
    assert get_targets_calls == 0


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
            "<div id='prompt-textarea' class='ProseMirror' contenteditable='true'></div>"
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
