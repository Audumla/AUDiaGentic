"""Prompt injection into ChatGPT's ProseMirror editor.

ChatGPT uses a ProseMirror-based rich text editor (div.ProseMirror) for input,
not a textarea.  Click the editor, type the prompt, press Enter to submit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from audiagentic.components.providers.adapters.gpt_auto.humanize import (
    think_delay,
    typing_delays,
)

logger = logging.getLogger(__name__)


async def _evaluate_resilient(client: Any, script: str) -> Any:
    """Use navigation-safe evaluation when the client provides it.

    Small protocol fakes and the legacy Playwright client only expose
    ``evaluate``; falling back keeps those callers compatible without
    reintroducing login waits.
    """
    resilient = getattr(client, "evaluate_resilient", None)
    if resilient is not None:
        return await resilient(script)
    return await client.evaluate(script)

_PROSEMIRROR_SELECTOR = ".ProseMirror"

# JavaScript: check if ChatGPT chat interface is ready (logged in + input visible)
_IS_READY_JS = """
() => {
    const editor = document.querySelector('.ProseMirror');
    if (!editor) return false;

    const text = document.body.textContent || '';
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return false;
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"]')) return false;
    if (document.querySelector('.error-page, [data-testid*="error"]')) return false;
    return true;
}
"""

_IS_LOGIN_PAGE_JS = """
() => {
    const text = document.body.textContent || '';
    if (text.includes('Sign in') || text.includes('Log in') || text.includes('Welcome back')) return 'login';
    if (document.querySelector('[data-testid="login-button"], [data-testid="signup-button"]')) return 'login';
    const emailInput = document.querySelector('input[type="email"]');
    const passInput = document.querySelector('input[type="password"]');
    if (emailInput && passInput && !document.querySelector('.ProseMirror')) return 'login';
    return 'unknown';
}
"""

_IS_LOGGED_IN_JS = """
() => {
    const chatInput = document.querySelector('.ProseMirror');
    const hasHistory = document.querySelector('[data-testid="conversation"], .conversation-list, nav[aria-label="Chat history"]') !== null;
    return !!chatInput || hasHistory;
}
"""

_GET_EDITOR_TEXT_JS = """
() => {
    const editor = document.querySelector('.ProseMirror');
    if (!editor) return '';
    return editor.innerText.trim();
}
"""


async def wait_for_chatgpt_ready(
    client: Any,
    timeout: float = 30.0,
    login_timeout: float = 20.0,
) -> bool:
    """Wait for ChatGPT to be loaded and ready for input.

    Returns ``True`` if the page is ready within *timeout* seconds.

    **The browser is assumed to be signed in already.** gpt-auto attaches to a
    long-lived user browser and never waits for or drives interactive sign-in.
    ``login_timeout`` remains an ignored compatibility argument for callers
    that still pass it; authentication is a precondition and a detected login
    page fails immediately.

    Page reads use ``evaluate_resilient`` because this runs immediately after
    the workspace navigation, where racing a destroyed execution context is
    expected rather than exceptional.
    """
    logger.info(
        "gpt-auto readiness check begin ready-timeout=%.1fs login-wait=disabled",
        timeout,
        extra={"gpt-auto-phase": "readiness.begin"},
    )

    page_state = await _evaluate_resilient(client, _IS_LOGIN_PAGE_JS)
    if page_state == "login":
        logger.error(
            "gpt-auto readiness failed: login page detected; refusing to wait or sign in",
            extra={"gpt-auto-phase": "readiness.login-failed"},
        )
        return False

    is_ready = await _evaluate_resilient(client, _IS_READY_JS)
    if is_ready:
        logger.info("gpt-auto readiness complete: composer present", extra={"gpt-auto-phase": "readiness.complete"})
        return True

    logger.info("Waiting for chat interface (timeout: %.0fs)", timeout)
    try:
        await client.wait_for_function(_IS_READY_JS, timeout_ms=int(timeout * 1000))
        logger.info("gpt-auto readiness complete: composer appeared", extra={"gpt-auto-phase": "readiness.complete"})
        return True
    except Exception:
        logger.warning(
            "gpt-auto readiness failed after %.1fs: composer did not appear",
            timeout,
            extra={"gpt-auto-phase": "readiness.timeout"},
        )
        return False


# Clear any existing text in the ProseMirror editor and focus it.
_CLEAR_EDITOR_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };
    el.innerHTML = '';
    el.focus();
    return { ok: true };
}"""

# JavaScript: inject a text chunk into the ProseMirror editor with proper
# event dispatching.  Works around puppeteer CDP limitations where keyboard
# events don't reach React/ProseMirror handlers when connected via CDP to an
# already-running browser.  Typing is simulated by appending word chunks with
# human pauses between them (see inject_prompt).
_APPEND_TEXT_JS = """(text) => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };

    const existing = el.textContent || '';
    const next = existing + text;

    // Dispatch beforeinput event (React/ProseMirror listens for this)
    const inputEvent = new InputEvent('beforeinput', {
        bubbles: true, cancelable: true,
        inputType: 'insertText', data: text,
    });
    el.dispatchEvent(inputEvent);

    // Set the text content directly
    el.textContent = next;

    // Dispatch input event to notify React of the change
    const afterInput = new Event('input', { bubbles: true });
    el.dispatchEvent(afterInput);

    return { ok: true, textLength: next.length };
}"""

# Submit the current editor content by clicking the send button — try multiple
# selectors, fall back to a keyboard Enter.
_SUBMIT_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };

    // Click the send button to submit — try multiple selectors
    const btns = document.querySelectorAll('button, [role="button"]');
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('send') || label.includes('submit')) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, buttonLabel: b.getAttribute('aria-label') };
        }
    }

    // Fallback 1: look for the send button near the editor by position (bottom-right of input area)
    const editorRect = el.getBoundingClientRect();
    for (const b of btns) {
        const bRect = b.getBoundingClientRect();
        const style = window.getComputedStyle(b);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        // Send button is typically to the right of the editor at roughly the same height
        if (bRect.width > 0 && bRect.height > 0 &&
            bRect.left > editorRect.left + editorRect.width * 0.5 &&
            Math.abs(bRect.top - editorRect.bottom) < 60) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, fallbackPosition: true };
        }
    }

    // Fallback 2: try keyboard Enter (works in most ChatGPT contexts)
    const enterEvent = new KeyboardEvent('keydown', {
        bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', which: 13, keyCode: 13
    });
    el.dispatchEvent(enterEvent);
    return { submitted: true, textLength: el.innerText.length, fallbackMethod: 'keyboard' };
}"""


async def inject_prompt(
    client: Any,
    prompt: str,
    typing_delay: float = 0.03,
    humanize: bool = True,
    think_min: float = 1.5,
    think_max: float = 6.0,
    paste_threshold: int = 300,
    editor_wait_seconds: float = 20.0,
) -> None:
    """Inject *prompt* into ChatGPT's ProseMirror editor and submit.

    Uses JS evaluate to inject text and dispatch events directly in the page
    context.  When ``humanize`` is True (default):

    - Prompts at or above ``paste_threshold`` characters are pasted in one
      shot (like Ctrl+V from a file) — fast, and humans do paste long text.
    - Shorter prompts are typed word-by-word with jittered per-character
      delays, looking like a real typist.

    Either way a randomized "thinking" pause is taken before pressing send,
    which looks far less scripted to ChatGPT's bot detection.
    """
    started = asyncio.get_running_loop().time()
    logger.info(
        "gpt-auto inject begin prompt-chars=%d editor-wait-seconds=%.1f",
        len(prompt),
        editor_wait_seconds,
        extra={"gpt-auto-phase": "inject.begin"},
    )

    # The composer is verified present when the session opens, but a turn can
    # be injected much later, and ChatGPT re-renders (or navigates) in between
    # -- notably workspace-root -> /c/{conversation-id} after the first turn.
    # Failing immediately on a transient absence turned an ordinary re-render
    # into "inject_prompt failed: editor not found" and lost the whole turn, so
    # wait briefly for the editor before treating it as a real fault.
    clear = None
    last_clear_error = "editor not found"
    for attempt in range(1, 6):
        wait_started = asyncio.get_running_loop().time()
        try:
            await client.wait_for_function(
                '() => !!document.querySelector(".ProseMirror")',
                timeout_ms=int(editor_wait_seconds * 1000),
            )
            logger.info(
                "gpt-auto inject editor wait complete attempt=%d elapsed-ms=%.1f",
                attempt,
                (asyncio.get_running_loop().time() - wait_started) * 1000,
                extra={"gpt-auto-phase": "inject.editor-wait.complete"},
            )
        except Exception:
            logger.exception(
                "gpt-auto inject editor wait failed attempt=%d elapsed-ms=%.1f",
                attempt,
                (asyncio.get_running_loop().time() - wait_started) * 1000,
                extra={"gpt-auto-phase": "inject.editor-wait.failed"},
            )

        clear_started = asyncio.get_running_loop().time()
        clear = await _evaluate_resilient(client, _CLEAR_EDITOR_JS)
        if not (isinstance(clear, dict) and "error" in clear):
            logger.info(
                "gpt-auto inject editor cleared attempt=%d elapsed-ms=%.1f",
                attempt,
                (asyncio.get_running_loop().time() - clear_started) * 1000,
                extra={"gpt-auto-phase": "inject.clear.complete"},
            )
            break

        last_clear_error = str(clear["error"])
        logger.warning(
            "gpt-auto inject clear failed attempt=%d elapsed-ms=%.1f error=%s",
            attempt,
            (asyncio.get_running_loop().time() - clear_started) * 1000,
            last_clear_error,
            extra={"gpt-auto-phase": "inject.clear.retry"},
        )
        if attempt < 5:
            await asyncio.sleep(0.25 * attempt)

    if isinstance(clear, dict) and "error" in clear:
        logger.error(
            "gpt-auto inject clear failed after retries error=%s total-elapsed-ms=%.1f",
            last_clear_error,
            (asyncio.get_running_loop().time() - started) * 1000,
            extra={"gpt-auto-phase": "inject.clear.failed"},
        )
        raise RuntimeError(f"inject_prompt failed: {last_clear_error}")

    words = prompt.split()
    if humanize and words:
        if len(prompt) >= paste_threshold:
            # Large prompt -> simulate a paste (single-shot, fast)
            result = await client.evaluate(_APPEND_TEXT_JS, prompt)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(f"inject_prompt failed: {result['error']}")
            logger.info("Prompt pasted in one shot (%d chars)", len(prompt))
        else:
            delays = typing_delays(len(prompt))
            # Map the per-char delay schedule onto the position of each word end
            char_index = 0
            for word in words:
                if char_index > 0:
                    # A natural gap between words (~average of the next char delay)
                    await asyncio.sleep(delays[min(char_index, len(delays) - 1)] * 1.5)
                result = await client.evaluate(_APPEND_TEXT_JS, word + " ")
                if isinstance(result, dict) and "error" in result:
                    raise RuntimeError(f"inject_prompt failed: {result['error']}")
                char_index += len(word) + 1
            # Final prompt minus trailing space is handled naturally by ChatGPT
            logger.info("Prompt typed with humanized cadence (%d chars)", char_index)

        # Human "thinking" pause before pressing send
        pause = think_delay(think_min, think_max)
        logger.info("Thinking before submit (%.1fs)", pause)
        await asyncio.sleep(pause)

        submit_started = asyncio.get_running_loop().time()
        result = await client.evaluate(_SUBMIT_JS)
        if isinstance(result, dict):
            if "error" in result:
                raise RuntimeError(f"inject_prompt failed: {result['error']}")
            logger.info("Prompt submitted (%d chars)", result.get("textLength", 0))
            logger.info(
                "gpt-auto inject submit complete elapsed-ms=%.1f total-elapsed-ms=%.1f",
                (asyncio.get_running_loop().time() - submit_started) * 1000,
                (asyncio.get_running_loop().time() - started) * 1000,
                extra={"gpt-auto-phase": "inject.submit.complete"},
            )
        return

    # Non-humanized fallback: inject whole prompt, then submit
    result = await client.evaluate(_APPEND_TEXT_JS, prompt)
    if isinstance(result, dict):
        if "error" in result:
            raise RuntimeError(f"inject_prompt failed: {result['error']}")
        result = await client.evaluate(_SUBMIT_JS)
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"inject_prompt failed: {result['error']}")
        logger.info("Prompt injected and submitted (%d chars)", result.get("textLength", 0))


async def inject_prompt_with_retry(
    client: Any,
    prompt: str,
    typing_delay: float = 0.03,
    max_retries: int = 2,
) -> None:
    """Inject a prompt, retrying focus if the first attempt fails."""
    for attempt in range(1, max_retries + 1):
        try:
            await inject_prompt(client, prompt, typing_delay)
            return
        except RuntimeError as exc:
            if attempt < max_retries:
                logger.warning("inject_prompt attempt %d failed: %s — retrying", attempt, exc)
                await asyncio.sleep(1.0)
            else:
                raise
