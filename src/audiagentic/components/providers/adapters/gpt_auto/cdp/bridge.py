"""GPT-auto browser operations implemented directly over Python CDP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ..config import GptAutoConfig
from ..urls import canonical_project_url, parse_project_id
from .client import CdpClient


@dataclass(frozen=True)
class BridgeEvent:
    name: str
    page_handle: str | None = None
    payload: dict[str, Any] | None = None


_SNAPSHOT_FN = r"""
(signalSpecs) => {
  const shown = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" &&
      s.visibility !== "hidden" && s.opacity !== "0";
  };
  const users = Array.from(document.querySelectorAll('[data-message-author-role="user"]'));
  const assistants = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
    .filter(e => !(e.getAttribute("data-message-id") || "").startsWith("request-placeholder-request-"));
  const latestAssistant = assistants.length ? assistants[assistants.length - 1] : null;
  const assistantTurn = latestAssistant && (latestAssistant.closest("article") || latestAssistant.parentElement?.parentElement);
  const domSignals = {};
  for (const spec of signalSpecs) {
    const root = spec.scope === "latest-assistant-turn" ? assistantTurn : document;
    domSignals[spec.name] = !!root && spec.selectors.some(selector =>
      Array.from(root.querySelectorAll(selector)).some(el => {
        if (spec.visible && !shown(el)) return false;
        const fragments = spec.textContainsAny || [];
        if (!fragments.length) return true;
        const content = (el.innerText || el.textContent || "").toLowerCase();
        return fragments.some(fragment => content.includes(String(fragment).toLowerCase()));
      })
    );
  }
  const text = (list) => list.length ? ((list[list.length - 1].innerText || "").trim() || null) : null;
  const selectors = '[data-testid="stop-button"], [data-testid="stop-generating"], .result-streaming, .result-thinking, [aria-busy="true"]';
  const generating = Array.from(document.querySelectorAll(selectors)).some(shown);
  const composer = document.querySelector(".ProseMirror");
  return {
    url: location.href, composerPresent: !!composer,
    composerEditable: !!composer && composer.isContentEditable && !composer.hasAttribute("disabled"),
    userCount: users.length, assistantCount: assistants.length,
    latestAssistantId: latestAssistant?.getAttribute("data-message-id") || null,
    latestUserText: text(users), latestAssistantText: text(assistants), generating, domSignals,
    errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
  };
}
"""


class PythonCdpBridge:
    """Browser-operation façade over the in-process Python CDP client."""

    def __init__(self, config: GptAutoConfig) -> None:
        self.config = config
        self._client: CdpClient | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pages: dict[str, str] = {}
        self._sessions: dict[str, str] = {}
        self._next_page = 1
        # One admission point for browser window/tab creation.  The lock is
        # deliberately held only until a stable page handle is returned;
        # navigation and turn execution may proceed concurrently afterward.
        self._tab_open_lock = asyncio.Lock()
        self.events: asyncio.Queue[BridgeEvent] = asyncio.Queue()

    @property
    def cdp_browser(self):
        """Return the typed GPT-auto CDP browser controller."""
        from ..gpt_auto_cdp import GptAutoCdpBrowserController

        return GptAutoCdpBrowserController(self)

    @property
    def client(self) -> CdpClient:
        if self._client is None:
            raise RuntimeError("Python CDP bridge is not running")
        return self._client

    async def start(self) -> None:
        if self._client is not None:
            return
        client = CdpClient(
            self.config.cdp_url, default_timeout=self.config.cdp.protocol_timeout_seconds
        )
        await client.start()
        self._client = client
        self._reader_task = asyncio.create_task(self._route_events(client))
        await client.command("Target.setDiscoverTargets", {"discover": True})
        await self._refresh_pages()

    async def _route_events(self, client: CdpClient) -> None:
        while self._client is client:
            event = await client.events.get()
            target_id = str(event.params.get("targetId") or "")
            if not target_id and event.session_id:
                target_id = next(
                    (
                        target
                        for target, session in self._sessions.items()
                        if session == event.session_id
                    ),
                    "",
                )
            handle = next((h for h, target in self._pages.items() if target == target_id), None)
            if event.method == "cdp.disconnected":
                await self.events.put(BridgeEvent("browser_disconnected"))
            elif event.method in {"Target.targetDestroyed", "Target.targetCrashed"}:
                if handle:
                    await self.events.put(
                        BridgeEvent(
                            "page_closed" if event.method.endswith("Destroyed") else "page_crashed",
                            handle,
                            event.params,
                        )
                    )
            elif event.method == "Target.targetCreated":
                await self.events.put(BridgeEvent("target_created", handle, event.params))
            elif event.method == "Target.targetInfoChanged":
                await self.events.put(BridgeEvent("target_changed", handle, event.params))
            elif event.method in {
                "Page.lifecycleEvent",
                "Page.loadEventFired",
                "Page.domContentEventFired",
            }:
                await self.events.put(BridgeEvent("page_lifecycle", handle, event.params))
            elif event.method == "Target.detachedFromTarget" and handle:
                self._sessions.pop(target_id, None)

    async def _refresh_pages(self) -> list[dict[str, Any]]:
        targets = await self.client.command("Target.getTargets")
        result: list[dict[str, Any]] = []
        for info in targets.get("targetInfos", []):
            if info.get("type") != "page":
                continue
            target_id = str(info["targetId"])
            handle = next((h for h, value in self._pages.items() if value == target_id), None)
            if handle is None:
                handle = f"page-{self._next_page}"
                self._next_page += 1
                self._pages[handle] = target_id
            result.append(
                {
                    "pageHandle": handle,
                    "url": str(info.get("url") or ""),
                    "title": str(info.get("title") or ""),
                    "targetId": target_id,
                    "windowId": await self._window_id(target_id),
                }
            )
        return result

    async def _window_id(self, target_id: str) -> int | None:
        result = await self.client.command("Browser.getWindowForTarget", {"targetId": target_id})
        value = result.get("windowId") if isinstance(result, dict) else None
        return int(value) if value is not None else None

    async def _target(self, handle: str) -> str:
        try:
            return self._pages[handle]
        except KeyError as exc:
            raise RuntimeError(f"unknown or closed page handle: {handle}") from exc

    async def _session(self, handle: str) -> str:
        target_id = await self._target(handle)
        session = self._sessions.get(target_id)
        if session:
            return session
        result = await self.client.command(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        session = str(result["sessionId"])
        self._sessions[target_id] = session
        await self.client.command("Page.enable", session_id=session)
        await self.client.command(
            "Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session
        )
        return session

    async def _evaluate(
        self,
        handle: str,
        function: str,
        argument: Any = None,
        *,
        user_gesture: bool = False,
    ) -> Any:
        session = await self._session(handle)
        expression = f"({function})({json.dumps(argument, separators=(',', ':'))})"
        result = await self.client.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": user_gesture,
            },
            session_id=session,
        )
        exception = result.get("exceptionDetails") if isinstance(result, dict) else None
        if exception:
            raise RuntimeError(str(exception))
        return (result.get("result") or {}).get("value")

    async def evaluate(self, page_handle: str, function: str, argument: Any = None) -> Any:
        """Evaluate a function in a bound page for generic API composites."""
        if not isinstance(function, str) or not function.strip():
            raise ValueError("function must be a non-empty string")
        return await self._evaluate(page_handle, function, argument)

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        params = params or {}
        if method == "browser_info":
            return await self.client.command("Browser.getVersion", timeout=timeout)
        if method == "list_pages":
            return await self._refresh_pages()
        if method in {"create_page", "create_window_page"}:
            async with self._tab_open_lock:
                result = await self.client.command(
                    "Target.createTarget",
                    {
                        "url": "about:blank",
                        "background": True,
                        "newWindow": method == "create_window_page",
                    },
                    timeout=timeout,
                )
                target_id = str(result["targetId"])
                handle = f"page-{self._next_page}"
                self._next_page += 1
                self._pages[handle] = target_id
                return {
                    "pageHandle": handle,
                    "targetId": target_id,
                    "windowId": await self._window_id(target_id),
                }
        if method == "create_page_in_window":
            """Open a tab from an anchor page so Chromium keeps its window."""
            async with self._tab_open_lock:
                anchor = str(params["anchorPageHandle"])
                anchor_target = await self._target(anchor)
                before = {
                    str(info["targetId"])
                    for info in (await self.client.command("Target.getTargets")).get("targetInfos", [])
                }
                await self._evaluate(
                    anchor,
                    "() => { window.open('about:blank', '_blank'); return true; }",
                    user_gesture=True,
                )
                deadline = asyncio.get_running_loop().time() + (timeout or 5.0)
                target_id: str | None = None
                while asyncio.get_running_loop().time() < deadline:
                    targets = (await self.client.command("Target.getTargets")).get("targetInfos", [])
                    for info in targets:
                        candidate = str(info.get("targetId") or "")
                        if (
                            candidate not in before
                            and info.get("type") == "page"
                            and str(info.get("openerId") or "") == anchor_target
                        ):
                            target_id = candidate
                            break
                    if target_id:
                        break
                    await asyncio.sleep(0.05)
                if target_id is None:
                    raise RuntimeError("window.open did not create a page target")
                handle = f"page-{self._next_page}"
                self._next_page += 1
                self._pages[handle] = target_id
            return {
                "pageHandle": handle,
                "targetId": target_id,
                "windowId": await self._window_id(target_id),
            }
        if method == "close_page":
            target_id = await self._target(str(params["pageHandle"]))
            await self.client.command(
                "Target.closeTarget", {"targetId": target_id}, timeout=timeout
            )
            self._pages.pop(str(params["pageHandle"]), None)
            self._sessions.pop(target_id, None)
            return {"closed": True}
        handle = str(params["pageHandle"])
        if method == "window_id":
            return {"windowId": await self._window_id(await self._target(handle))}
        if method == "window_bounds":
            window_id = params.get("windowId")
            if window_id is None:
                window_id = await self._window_id(await self._target(handle))
            return await self.client.command(
                "Browser.getWindowBounds", {"windowId": window_id}, timeout=timeout
            )
        if method == "set_window_bounds":
            window_id = params.get("windowId")
            if window_id is None:
                window_id = await self._window_id(await self._target(handle))
            return await self.client.command(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": dict(params["bounds"])},
                timeout=timeout,
            )
        if method == "target_info":
            target_id = await self._target(handle)
            return await self.client.command(
                "Target.getTargetInfo", {"targetId": target_id}, timeout=timeout
            )
        if method == "activate_target":
            target_id = await self._target(handle)
            return await self.client.command(
                "Target.activateTarget", {"targetId": target_id}, timeout=timeout
            )
        session = await self._session(handle)
        if method == "navigate":
            result = await self.client.command(
                "Page.navigate", {"url": params["url"]}, session_id=session, timeout=timeout
            )
            if result and result.get("errorText"):
                raise RuntimeError(str(result["errorText"]))
            return {"url": str(params["url"])}
        if method == "snapshot":
            return await self._evaluate(handle, _SNAPSHOT_FN, params.get("signals", []))
        if method == "keep_page_active":
            await self.client.command("Page.bringToFront", session_id=session)
            await self._evaluate(
                handle,
                "() => { window.focus(); document.dispatchEvent(new Event('visibilitychange')); return true; }",
            )
            return {"ok": True}
        if method == "submit_prompt":
            text = str(params["text"])
            typed = await self._evaluate(
                handle,
                """(text) => {
              const editor = document.querySelector('.ProseMirror');
              if (!editor) throw new Error('composer not found');
              editor.focus();
              const selection = window.getSelection(); selection.removeAllRanges();
              const range = document.createRange(); range.selectNodeContents(editor); selection.addRange(range);
              if (!document.execCommand('insertText', false, text)) throw new Error('browser rejected atomic composer insertion');
              // Keep React's controlled composer state in sync with the DOM
              // mutation; without this, ChatGPT can leave its send control
              // disabled even though innerText contains the prompt.
              editor.dispatchEvent(new InputEvent('input', {
                bubbles: true, inputType: 'insertText', data: text
              }));
              return (editor.innerText || editor.textContent || '').trim();
            }""",
                text,
            )
            # ChatGPT's composer is React-controlled; a raw CDP Enter event
            # can leave the text visible without dispatching the send action.
            # Prefer the rendered send control, retaining Enter only as a
            # compatibility fallback for older composer variants.
            sent = await self._evaluate(
                handle,
                """async () => {
                  await new Promise(resolve => setTimeout(resolve, 25));
                  const button = document.querySelector(
                    '[data-testid="send-button"], button[aria-label*="Send" i]'
                  );
                  if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return false;
                  button.click();
                  return true;
                }""",
            )
            if not sent:
                await self.client.command(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown", "key": "Enter", "code": "Enter",
                        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                    },
                    session_id=session,
                )
                await self.client.command(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp", "key": "Enter", "code": "Enter",
                        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                    },
                    session_id=session,
                )
            return {"actionComplete": True, "typedText": typed}
        if method == "stop_generation":
            return {
                "stopped": bool(
                    await self._evaluate(
                        handle,
                        "() => { const b=document.querySelector('[data-testid=stop-button], [data-testid=stop-generating]'); if (b) { b.click(); return true; } return false; }",
                    )
                )
            }
        if method == "find_project_url":
            return await self._evaluate(
                handle,
                """async (name) => {
              const normalize = value => String(value || '').replace(/\\s+/g, ' ').trim();
              const wanted = normalize(name).toLowerCase();
              for (let i = 0; i < 120; i++) {
                const row = Array.from(document.querySelectorAll('[role=row]')).find(row => {
                  const values = [...Array.from(row.querySelectorAll('[role=cell], [role=gridcell]')).map(c => c.innerText || c.textContent), ...(row.innerText || '').split(/\\r?\\n/)].map(normalize);
                  return values.some(value => value.toLowerCase() === wanted);
                });
                if (row) { row.click(); for (let j = 0; j < 120; j++) { if (/\\/g\\/g-p-[^/]+/.test(location.pathname)) return {url: location.href, name}; await new Promise(r => setTimeout(r, 100)); } }
                await new Promise(r => setTimeout(r, 100));
              }
              throw new Error(`ChatGPT project not found: ${name}`);
            }""",
                params["projectName"],
            )
        raise RuntimeError(f"unknown bridge method: {method}")

    async def wait_for_composer(
        self, page_handle: str, *, timeout: float, poll_interval: float = 0.25
    ) -> dict[str, Any]:
        """Wait until a page exposes an editable ChatGPT composer."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            snapshot = await self.call("snapshot", {"pageHandle": page_handle, "signals": []})
            if snapshot.get("composerPresent") and snapshot.get("composerEditable"):
                return snapshot
            await asyncio.sleep(poll_interval)
        raise TimeoutError("ChatGPT composer did not become ready")

    async def open_project_page(
        self,
        *,
        project_name: str,
        project_url: str | None,
        anchor_page_handle: str | None = None,
        navigation_timeout: float,
        ready_timeout: float,
    ) -> dict[str, Any]:
        """Create/bind a page, resolve a project if necessary, and wait ready."""
        method = "create_page_in_window" if anchor_page_handle else "create_window_page"
        params = {"anchorPageHandle": anchor_page_handle} if anchor_page_handle else None
        page = await self.call(method, params)
        handle = str(page["pageHandle"])
        target = project_url
        try:
            if not target or not parse_project_id(target):
                await self.call(
                    "navigate",
                    {"pageHandle": handle, "url": "https://chatgpt.com/projects"},
                    timeout=navigation_timeout + 2,
                )
                match = await self.call(
                    "find_project_url",
                    {"pageHandle": handle, "projectName": project_name},
                    timeout=ready_timeout + 2,
                )
                target = canonical_project_url(str(match["url"])) + "/project"
            if not target:
                raise RuntimeError("gpt-auto could not resolve a ChatGPT project URL")
            await self.call(
                "navigate",
                {"pageHandle": handle, "url": target},
                timeout=navigation_timeout + 2,
            )
            await self.wait_for_composer(handle, timeout=ready_timeout)
            return {**page, "pageHandle": handle, "projectUrl": target}
        except Exception:
            await self.call("close_page", {"pageHandle": handle})
            raise

    async def submit_prompt_verified(
        self, page_handle: str, text: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Submit text and enforce the bridge's exact typed-text contract."""
        result = await self.call(
            "submit_prompt",
            {"pageHandle": page_handle, "text": text},
            timeout=timeout,
        )

        def normalize(value: Any) -> str:
            return " ".join(str(value or "").split())

        if normalize(result.get("typedText")) != normalize(text):
            raise RuntimeError("composer text verification failed; prompt was not submitted")
        return result

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.stop()
        task, self._reader_task = self._reader_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._pages.clear()
        self._sessions.clear()
