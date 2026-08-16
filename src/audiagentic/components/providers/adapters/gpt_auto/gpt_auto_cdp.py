"""ChatGPT-specific browser operations over the generic CDP controller."""

from __future__ import annotations

import asyncio
from typing import Any

from .cdp.cdp_browser import CdpBrowserController, CdpPageRef, CdpWindowBounds
from .urls import canonical_project_url, parse_project_id

_PROJECTS_URL = "https://chatgpt.com/projects"

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
    // ChatGPT currently leaves `.streaming-animation` on completed assistant
    // messages.  It describes the renderer, not an active generation, so it
    // must never be allowed to make the provider appear busy during resume.
    const selectors = spec.name === "streaming-indicator"
      ? spec.selectors.filter(selector => selector !== ".streaming-animation")
      : spec.selectors;
    domSignals[spec.name] = !!root && selectors.some(selector =>
      Array.from(root.querySelectorAll(selector)).some(el => {
        if (spec.visible && !shown(el)) return false;
        const fragments = spec.textContainsAny || [];
        if (!fragments.length) return true;
        const content = (el.innerText || el.textContent || "").toLowerCase();
        return fragments.some(fragment => content.includes(String(fragment).toLowerCase()));
      })
    );
  }
  const boundedText = (element) => ((element?.innerText || element?.textContent || "").trim()).slice(0, 20000) || null;
  // User messages are collapsible in the ChatGPT UI.  Reading the outer
  // message node includes the presentation controls ("Show more" /
  // "Show less"), which makes a durable prompt digest fail to match after a
  // resume even though the submitted text is unchanged.  Hash only the
  // message-content node when it exists.
  const userText = (element) => boundedText(
    element?.querySelector('[data-testid="collapsible-user-message-content"]') || element
  );
  const text = (list, reader = boundedText) => list.length ? reader(list[list.length - 1]) : null;
  const selectors = '[data-testid="stop-button"], [data-testid="stop-generating"], .result-streaming, .result-thinking, [aria-busy="true"]';
  const generating = Array.from(document.querySelectorAll(selectors)).some(shown);
  const composer = document.querySelector(".ProseMirror");
  return {
    url: location.href, composerPresent: !!composer,
    composerEditable: !!composer && composer.isContentEditable && !composer.hasAttribute("disabled"),
    userCount: users.length, assistantCount: assistants.length,
    userMessageIds: users.map(e => e.getAttribute("data-message-id")).filter(Boolean),
    userMessageTexts: users.map(userText).filter(Boolean).slice(-64),
    // GP08: the ordered assistant-message sequence, mirroring the
    // user-message arrays above. "Latest assistant" alone cannot answer
    // "what was the response to request A" once a later, unrelated turn
    // (from any actor) has entered the same conversation -- this ordered
    // list is the raw data a request-addressable correlation layer needs.
    assistantMessageIds: assistants.map(e => e.getAttribute("data-message-id")).filter(Boolean),
    assistantMessageTexts: assistants.map(e => boundedText(e)).filter(Boolean).slice(-64),
    latestUserId: users.length ? users[users.length - 1].getAttribute("data-message-id") || null : null,
    latestAssistantId: latestAssistant?.getAttribute("data-message-id") || null,
    latestUserText: text(users, userText), latestAssistantText: text(assistants), generating, domSignals,
    errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
  };
}
"""


class GptAutoCdpBrowserController(CdpBrowserController):
    """ChatGPT-specific selectors, composites, and conversation operations."""

    async def wait_for_composer(self, page: CdpPageRef, *, timeout: float) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            snapshot = await self.snapshot(page)
            if snapshot.get("composerPresent") and snapshot.get("composerEditable"):
                return snapshot
            await asyncio.sleep(0.25)
        raise TimeoutError("ChatGPT composer did not become ready")

    async def snapshot(
        self, page: CdpPageRef, *, signals: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return await self.evaluate(page, _SNAPSHOT_FN, signals or [])

    async def stop_generation(self, page: CdpPageRef) -> dict[str, bool]:
        stopped = await self.evaluate(
            page,
            r"""() => {
              const selectors = [
                '[data-testid="stop-button"]',
                '[data-testid="stop-generating"]',
                'button[aria-label*="Stop generating" i]',
                'button[aria-label*="Stop response" i]',
                'button[title*="Stop generating" i]',
                'button[title*="Stop response" i]'
              ];
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                  s.visibility !== 'hidden' && s.opacity !== '0';
              };
              const button = selectors.flatMap(s => Array.from(document.querySelectorAll(s)))
                .find(el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true');
              if (!button) return false;
              button.click();
              return true;
            }""",
        )
        return {"stopped": bool(stopped)}

    async def submit(
        self, page: CdpPageRef, text: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        async def _submit() -> dict[str, Any]:
            typed = await self.evaluate(
                page,
                """(text) => {
              const editor = document.querySelector('.ProseMirror');
              if (!editor) throw new Error('composer not found');
              editor.focus();
              const selection = window.getSelection(); selection.removeAllRanges();
              const range = document.createRange(); range.selectNodeContents(editor); selection.addRange(range);
              if (!document.execCommand('insertText', false, text)) throw new Error('browser rejected atomic composer insertion');
              editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
              return (editor.innerText || editor.textContent || '').trim();
            }""",
                text,
            )
            # Keep the settling delay outside the page execution context.  A
            # ChatGPT send click can synchronously replace/navigate the React
            # tree; awaiting a browser-side timer across that replacement can
            # make CDP report "Promise was collected" even though the click
            # side effect was accepted.
            await asyncio.sleep(0.025)
            sent = await self.evaluate(
                page,
                """() => {
              const button = document.querySelector('[data-testid="send-button"], button[aria-label*="Send" i]');
              if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return false;
              button.click(); return true;
            }""",
            )
            if not sent:
                await self.bridge.call("dispatch_enter", {"pageHandle": self._handle(page)})
            # Enter dispatch is only a fallback attempt.  CDP has no proof
            # that ChatGPT accepted it, so do not report a completed submit
            # when the Send control was unavailable.
            return {
                "actionComplete": bool(sent),
                "typedText": typed,
                "sendButtonClicked": bool(sent),
                "enterDispatched": not bool(sent),
            }

        if timeout is None:
            return await _submit()
        async with asyncio.timeout(timeout):
            return await _submit()

    async def find_project_url(self, page: CdpPageRef, project_name: str) -> dict[str, str]:
        result = await self.evaluate(
            page,
            r"""async (name) => {
              const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
              const wanted = normalize(name).toLowerCase();
              for (let i = 0; i < 120; i++) {
                const row = Array.from(document.querySelectorAll('[role=row]')).find(row => {
                  const values = [...Array.from(row.querySelectorAll('[role=cell], [role=gridcell]')).map(c => c.innerText || c.textContent), ...(row.innerText || '').split(/\r?\n/)].map(normalize);
                  return values.some(value => value.toLowerCase() === wanted);
                });
                if (row) { row.click(); for (let j = 0; j < 120; j++) { if (/\/g\/g-p-[^/]+/.test(location.pathname)) return {url: location.href, name}; await new Promise(r => setTimeout(r, 100)); } }
                await new Promise(r => setTimeout(r, 100));
              }
              throw new Error(`ChatGPT project not found: ${name}`);
            }""",
            project_name,
        )
        return {"url": str(result["url"]), "name": str(result.get("name") or project_name)}

    async def open_project_page(
        self,
        *,
        project_name: str,
        project_url: str | None,
        anchor_page: CdpPageRef | None,
        navigation_timeout: float,
        ready_timeout: float,
    ) -> dict[str, Any]:
        page = await self.new_tab(in_window=anchor_page) if anchor_page else await self.new_window()
        target = project_url
        try:
            if not target or not parse_project_id(target):
                async with asyncio.timeout(navigation_timeout):
                    await self.navigate(page, _PROJECTS_URL)
                match = await self.find_project_url(page, project_name)
                target = canonical_project_url(match["url"]) + "/project"
            if not target:
                raise RuntimeError("gpt-auto could not resolve a ChatGPT project URL")
            async with asyncio.timeout(navigation_timeout):
                page = await self.navigate(page, target)
            await self.wait_for_composer(page, timeout=ready_timeout)
            return {"page": page, "projectUrl": target}
        except Exception as exc:
            await self.close(page)
            raise RuntimeError(
                f"gpt-auto project page open failed: {type(exc).__name__}: {exc}"
            ) from exc


__all__ = ["GptAutoCdpBrowserController", "CdpPageRef", "CdpWindowBounds"]
