"""CDP client — connects to an existing browser via puppeteer-core.

Uses a Node.js helper (gpt_auto_cdp.cjs) that runs puppeteer-core and
connects to Chrome/Brave's DevTools Protocol port.  This keeps
``navigator.webdriver == false`` so ChatGPT doesn't flag bot detection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CDP_SCRIPT = Path(__file__).with_name("gpt_auto_cdp.cjs")

# Bounds the whole connect RPC: puppeteer.connect() has no websocket handshake
# timeout, so an unreachable or stale endpoint would otherwise hang forever.
_CONNECT_TIMEOUT_SECONDS = 15.0

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# ChatGPT workspace (project) URL pattern.
# https://chatgpt.com/g/g-p-{id}-{slug}/c/{conversation-id}
_WORKSPACE_URL_PATTERN = r"/g/g-p-"


@dataclass(frozen=True)
class TabInfo:
    """Metadata about a browser tab."""

    url: str
    title: str
    tab_id: str = ""


@dataclass(frozen=True)
class WorkspaceInfo:
    """Information about a ChatGPT workspace (project)."""

    name: str
    url: str

    @property
    def project_slug(self) -> str:
        """Extract the slug portion from the URL (e.g. 'audiagentic')."""
        # /g/g-p-{id}-{slug}
        parts = self.url.rstrip("/").split("/")
        for p in parts:
            if p.startswith("g-p-"):
                return p.split("-", 2)[-1]  # g-p-id-slug -> slug
        return ""


class CdpClient:
    """Manages a CDP connection via puppeteer-core subprocess.

    Connects to an already-running Chrome/Brave with ``--remote-debugging-port``.
    """

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        self._cdp_url = cdp_url
        self._proc: asyncio.subprocess.Process | None = None
        self._seq: int = 0

    # -- lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        """Start the Node.js helper and connect to browser."""
        node = _find_node()
        env = os.environ.copy()
        from .install import node_module_path

        managed_node_path = str(node_module_path())
        npath = os.getenv("NODE_PATH")
        env["NODE_PATH"] = managed_node_path + (os.pathsep + npath if npath else "")

        proc = await asyncio.create_subprocess_exec(
            node,
            str(_CDP_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._proc = proc

        # Wait for ready signal on stderr
        async with asyncio.timeout(10):
            while True:
                line = await proc.stderr.readline()
                if not line:
                    raise RuntimeError("CDP helper exited")
                text = line.decode().strip()
                logger.debug("CDP helper: %s", text)
                if "ready" in text:
                    break

        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await self._send("connect", self._connect_params())
        except TimeoutError:
            # puppeteer.connect() sets no websocket handshake timeout, so a
            # stale DevToolsActivePort endpoint hangs rather than failing.
            # Killing the helper is the only clean cancellation: a connect()
            # left running in it could still open a socket nobody owns.
            await self._kill_helper()
            raise RuntimeError(
                f"connect: timed out after {_CONNECT_TIMEOUT_SECONDS:.0f}s ({self._cdp_url})"
            ) from None
        logger.info("Connected to browser via CDP (%s)", self._cdp_url)

    def _connect_params(self) -> dict[str, Any]:
        """Tell the helper how to reach the browser, with a websocket fallback.

        ``browserURL`` is always offered first. The helper falls back to
        ``browserWSEndpoint`` only if that connect actually fails -- attempting
        the connection is the probe, so there is no window for the endpoint to
        change between checking and using it.
        """
        params: dict[str, Any] = {"browserURL": self._cdp_url}
        ws_endpoint = _ws_endpoint_from_active_port_file(self._cdp_url)
        if ws_endpoint is not None:
            params["browserWSEndpoint"] = ws_endpoint
        return params

    async def _kill_helper(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass

    async def stop(self) -> None:
        """Disconnect from browser and stop the helper."""
        try:
            await self._send("disconnect")
        except Exception:
            pass
        if self._proc and self._proc.stdin:
            self._proc.stdin.close()
            await self._proc.wait()

    # -- tab operations ------------------------------------------------------------

    async def new_tab(self, url: str = "https://chatgpt.com") -> TabInfo:
        """Open a new tab and navigate to *url*."""
        result = await self._send("new_tab", {"url": url})
        return TabInfo(url=result["url"], title="", tab_id=result.get("tabId", ""))

    async def find_tab(
        self,
        url_pattern: str | None = None,
        title_pattern: str | None = None,
    ) -> TabInfo | None:
        """Find the first ChatGPT tab matching patterns."""
        result = await self._send(
            "find_tab",
            {
                "urlPattern": url_pattern or "chatgpt",
                "titlePattern": title_pattern or "AUDiaGentic",
            },
        )
        if not result.get("found"):
            return None
        return TabInfo(url=result["url"], title=result["title"], tab_id=result.get("tabId", ""))

    async def list_tabs(self) -> list[TabInfo]:
        """Return metadata for all open browser tabs."""
        result = await self._send("list_tabs")
        return [
            TabInfo(url=t.get("url", ""), title=t.get("title", ""), tab_id=t.get("tabId", ""))
            for t in result.get("tabs", [])
        ]

    async def activate_tab(self, tab_id: str) -> TabInfo | None:
        """Activate the tab with *tab_id*; returns None if it no longer exists."""
        result = await self._send("activate_tab", {"tabId": tab_id})
        if not result.get("found"):
            return None
        return TabInfo(url=result["url"], title="", tab_id=result.get("tabId", ""))

    async def bring_to_front(self) -> None:
        """Focus the active tab in the browser window (brings it to the foreground).

        Backgrounded ChatGPT tabs pause SSE streaming — responses start, emit
        one chunk, then freeze until the tab is visible again.  Calling this
        before submitting a prompt keeps the tab foregrounded so the stream
        actually completes.

        Prefer :meth:`keep_page_active`, which survives the window being
        occluded *during* the response and does not steal the user's focus.
        """
        await self._send("bring_to_front", {})

    async def keep_page_active(self) -> dict[str, Any]:
        """Make the page report as focused/visible regardless of occlusion.

        ``bring_to_front`` only helps at the instant it is called: if the
        browser window is covered while the response is still streaming,
        ChatGPT's SSE stream aborts after the first chunk and the assistant
        block freezes part-written (observed 2026-08-09: stuck at 10
        characters for 15+ minutes, ``streaming-animation`` still applied,
        stop button already gone).

        This applies CDP focus emulation plus an active web-lifecycle state,
        so the renderer keeps streaming while the window sits behind the
        user's editor — without repeatedly grabbing focus.

        Returns the helper's report of which emulations applied; callers
        should treat a partial result as best-effort rather than fatal.
        """
        return await self._send("keep_page_active", {})

    # -- page operations -----------------------------------------------------------

    async def click(self, selector: str) -> None:
        """Click the first element matching *selector* via CDP (proper pointer event)."""
        await self._send("click", {"selector": selector})

    async def click_js(self, js_query: str) -> bool:
        """Click an element found by JS query using puppeteer's native click.

        *js_query* should return an element, e.g. ``document.querySelector('[aria-label="New project"]')``.
        Returns True if the element was found and clicked.
        """
        result = await self._send("click_js", {"js": js_query})
        return bool(result.get("ok", False))

    async def click_project_row(self, project_name: str) -> bool:
        """Click a project row on the /projects page by name.

        Uses puppeteer's native click on the div[role="row"] element.
        Returns True if the project was found and clicked.
        """
        js = f"""() => {{
            const main = document.querySelector('main');
            if (!main) return null;
            const rows = main.querySelectorAll('[role="row"]');
            for (const row of rows) {{
                const text = row.textContent.trim();
                if (text.toLowerCase().includes('{project_name.lower()}')) {{
                    return row;
                }}
            }}
            return null;
        }}"""
        result = await self._send("click_js", {"js": js})
        return bool(result.get("ok", False))

    async def mouse_click(self, x: int, y: int) -> None:
        """Click at pixel coordinates (x, y) using puppeteer's mouse emulation.

        This dispatches proper pointer events that React/ProseMirror can detect,
        unlike JS-dispatched PointerEvents which may be filtered by ChatGPT's
        bot detection.
        """
        await self._send("mouse_click", {"x": x, "y": y})

    async def type_text(self, text: str, delay: float = 0.03) -> None:
        """Type *text* character-by-character (human-like)."""
        await self._send(
            "type_text",
            {
                "text": text,
                "delay": int(delay * 1000),
            },
        )

    async def press_key(self, key: str = "Enter") -> None:
        """Press a single key."""
        await self._send("press_key", {"key": key})

    # -- DOM evaluation ------------------------------------------------------------

    async def evaluate(self, script: str, *args) -> Any:
        """Execute JavaScript on the active page.

        When *args* are provided, they are serialized as ``window._cdpArgs``
        and the script should reference them as ``_cdpArgs[0]``, etc.
        The JS wrapper handles this transparently for single-string args.
        """
        if args:
            # Wrap: set _cdpArgs on window, then call the function
            import json

            serialized = json.dumps(args)
            wrapped = (
                f"(() => {{ window._cdpArgs={serialized}; return ({script})(..._cdpArgs); }})()"
            )
            result = await self._send("evaluate", {"script": wrapped})
        else:
            result = await self._send("evaluate", {"script": script})
        return result.get("value")

    async def evaluate_resilient(
        self,
        script: str,
        *,
        attempts: int = 5,
        delay: float = 0.5,
    ) -> Any:
        """``evaluate`` that tolerates a navigation destroying the context.

        ChatGPT navigates during normal operation -- workspace root to
        ``/c/{conversation-id}`` on the first turn, and again whenever a
        workspace is resolved. Any evaluate racing that navigation fails with
        "Execution context was destroyed", which is expected mid-flight rather
        than a real error. Callers that poll across a navigation boundary
        should use this instead of :meth:`evaluate`; anything else propagates
        unchanged.
        """
        last_exc: RuntimeError | None = None
        for attempt in range(attempts):
            try:
                return await self.evaluate(script)
            except RuntimeError as exc:
                message = str(exc).lower()
                if "detached" not in message and "execution context was destroyed" not in message:
                    raise
                last_exc = exc
                logger.debug(
                    "evaluate hit a destroyed context (navigating), retry %d/%d",
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("evaluate_resilient: retries exhausted with no captured error")

    # -- waiting -------------------------------------------------------------------

    async def wait_for_function(
        self,
        predicate_js: str,
        *,
        timeout_ms: int = 30000,
    ) -> None:
        """Wait for *predicate_js* to return a truthy value.

        Uses puppeteer's waitForFunction — event-based via CDP, no polling.
        Raises RuntimeError on timeout.

        Args:
            predicate_js: A JavaScript expression returning a boolean,
                e.g. ``'() => !!document.querySelector(".ProseMirror")'``
            timeout_ms: Maximum milliseconds to wait (default 30000).
        """
        started = asyncio.get_running_loop().time()
        logger.info(
            "CDP wait_for_function begin timeout-ms=%d predicate-chars=%d",
            timeout_ms,
            len(predicate_js),
            extra={"gpt-auto-phase": "cdp.wait-for-function.begin"},
        )
        try:
            await self._send(
                "wait_for_function",
                {"predicate": predicate_js, "timeoutMs": timeout_ms},
            )
        except Exception:
            logger.exception(
                "CDP wait_for_function failed elapsed-ms=%.1f timeout-ms=%d",
                (asyncio.get_running_loop().time() - started) * 1000,
                timeout_ms,
                extra={"gpt-auto-phase": "cdp.wait-for-function.failed"},
            )
            raise
        logger.info(
            "CDP wait_for_function complete elapsed-ms=%.1f timeout-ms=%d",
            (asyncio.get_running_loop().time() - started) * 1000,
            timeout_ms,
            extra={"gpt-auto-phase": "cdp.wait-for-function.complete"},
        )

    # -- utility -------------------------------------------------------------------

    async def get_url(self) -> str:
        """Return the current page URL."""
        result = await self._send("get_url")
        return result.get("url", "")

    async def screenshot(self, path: str) -> None:
        """Take a screenshot and save to *path*."""
        await self._send("screenshot", {"path": path})

    # -- internal ------------------------------------------------------------------

    async def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("CDP helper not running")

        msg = {"id": self._seq, "method": method, "params": params or {}}
        self._seq += 1
        started = asyncio.get_running_loop().time()
        logger.debug(
            "CDP command begin id=%d method=%s params=%s",
            msg["id"],
            method,
            _summarize_cdp_params(params or {}),
            extra={"gpt-auto-phase": "cdp.command.begin", "cdp-method": method},
        )
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

        async with asyncio.timeout(30):
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    raise RuntimeError("CDP helper exited unexpectedly")
                try:
                    resp = json.loads(line.decode().strip())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if resp.get("id") == msg["id"]:
                    if "error" in resp:
                        logger.error(
                            "CDP command failed id=%d method=%s elapsed-ms=%.1f error=%s",
                            msg["id"], method,
                            (asyncio.get_running_loop().time() - started) * 1000,
                            resp["error"],
                            extra={"gpt-auto-phase": "cdp.command.failed", "cdp-method": method},
                        )
                        raise RuntimeError(f"{method}: {resp['error']}")
                    result = resp.get("result", {})
                    logger.debug(
                        "CDP command complete id=%d method=%s elapsed-ms=%.1f result=%s",
                        msg["id"], method,
                        (asyncio.get_running_loop().time() - started) * 1000,
                        _summarize_cdp_result(result),
                        extra={"gpt-auto-phase": "cdp.command.complete", "cdp-method": method},
                    )
                    return result


def _summarize_cdp_params(params: dict[str, Any]) -> dict[str, Any]:
    """Log CDP shape and sizes without logging prompt or JavaScript bodies."""
    summary = {}
    for key, value in params.items():
        if key in {"script", "predicate", "js", "text"}:
            summary[key] = f"<{len(value)} chars>" if isinstance(value, str) else "<redacted>"
        else:
            summary[key] = value
    return summary


def _summarize_cdp_result(result: Any) -> str:
    if isinstance(result, dict):
        return str(sorted(result.keys()))
    return type(result).__name__


def _browser_user_data_dir() -> Path | None:
    """The single user-data directory whose ``DevToolsActivePort`` may be read.

    Explicit configuration wins; otherwise the default profile of the browser
    gpt-auto supports. Deliberately not a search across Chromium-family
    installs: a second candidate can only ever contribute a websocket UUID
    belonging to a different browser instance.
    """
    override = os.getenv("AUDIAGENTIC_GPT_AUTO_USER_DATA_DIR")
    if override:
        return Path(override)
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "User Data"


def _ws_endpoint_from_active_port_file(cdp_url: str) -> str | None:
    """Build a ``browserWSEndpoint`` from the browser's ``DevToolsActivePort`` file.

    The file holds the debugging port on line 1 and the browser websocket path
    on line 2. Only read for a loopback *cdp_url*: a local file says nothing
    about a browser on another host, and its UUID is exactly the part that
    cannot be inferred from the port.

    A file matching on port can still be stale, so the caller must bound the
    connect attempt rather than trusting the endpoint.
    """
    from urllib.parse import urlparse

    parsed = urlparse(cdp_url)
    host = parsed.hostname or "127.0.0.1"
    if host not in _LOOPBACK_HOSTS:
        return None
    user_data_dir = _browser_user_data_dir()
    if user_data_dir is None:
        return None
    try:
        lines = (user_data_dir / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if len(lines) < 2:
        return None
    port, ws_path = lines[0].strip(), lines[1].strip()
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return None
    if not ws_path.startswith("/devtools/browser/"):
        return None
    if parsed.port is not None and int(port) != parsed.port:
        return None
    return f"ws://{_format_host(host)}:{port}{ws_path}"


def _format_host(host: str) -> str:
    """Bracket an IPv6 literal so the authority parses as host + port."""
    return f"[{host}]" if ":" in host else host


def _find_node() -> str:
    """Locate the node executable (synchronous)."""
    import shutil

    for name in ("nodejs", "node"):
        path = shutil.which(name)
        if path:
            return path
    return "node"
