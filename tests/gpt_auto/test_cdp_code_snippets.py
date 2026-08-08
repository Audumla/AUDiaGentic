"""Live test: validate each gpt-auto code snippet against real ChatGPT via CDP.

Tests every JavaScript predicate and DOM operation used by the gpt-auto adapter,
one at a time, connected to a real browser via CDP. This validates the actual
code paths without the overhead of full session transport flow.

Prerequisites: Chrome/Edge open with --remote-debugging-port=9222, logged into ChatGPT.

    python tests/gpt_auto/test_cdp_code_snippets.py
"""

from __future__ import annotations

import asyncio

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient

# ── Predicates from prompt_injector.py ────────────────────────────────

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

_CLEAR_EDITOR_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };
    el.innerHTML = '';
    el.focus();
    return { ok: true };
}"""

_APPEND_TEXT_JS = """(text) => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };
    const existing = el.textContent || '';
    const next = existing + text;
    const inputEvent = new InputEvent('beforeinput', {
        bubbles: true, cancelable: true,
        inputType: 'insertText', data: text,
    });
    el.dispatchEvent(inputEvent);
    el.textContent = next;
    const afterInput = new Event('input', { bubbles: true });
    el.dispatchEvent(afterInput);
    return { ok: true, textLength: next.length };
}"""

_SUBMIT_JS = """() => {
    const el = document.querySelector('.ProseMirror');
    if (!el) return { error: 'editor not found' };
    const btns = document.querySelectorAll('button, [role="button"]');
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('send') || label.includes('submit')) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, buttonLabel: b.getAttribute('aria-label') };
        }
    }
    const editorRect = el.getBoundingClientRect();
    for (const b of btns) {
        const bRect = b.getBoundingClientRect();
        const style = window.getComputedStyle(b);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        if (bRect.width > 0 && bRect.height > 0 &&
            bRect.left > editorRect.left + editorRect.width * 0.5 &&
            Math.abs(bRect.top - editorRect.bottom) < 60) {
            b.click();
            return { submitted: true, textLength: el.innerText.length, fallbackPosition: true };
        }
    }
    const enterEvent = new KeyboardEvent('keydown', {
        bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', which: 13, keyCode: 13
    });
    el.dispatchEvent(enterEvent);
    return { submitted: true, textLength: el.innerText.length, fallbackMethod: 'keyboard' };
}"""

# ── Predicates from dom_reader.py ─────────────────────────────────────

_GET_RESPONSE_STATE_JS = """() => {
    const blocks = document.querySelectorAll('[data-message-author-role="assistant"]');
    const real = Array.from(blocks).filter(b => !b.getAttribute('data-message-id', '').startsWith('request-placeholder-request-'));
    const count = real.length;
    if (count === 0) return { count: 0, text: null };
    const last = real[count - 1];
    const text = (last.innerText || '').trim();
    return { count, text: text.length > 0 ? text : null };
}"""

_IS_GENERATING_JS = """
() => {
    if (document.querySelector('[data-testid="stop-generating"]')) return true;
    const loaders = document.querySelectorAll('.loading-dots, [class*="streaming"], .result-streaming, .result-thinking, [class*="result-thinking"]');
    if (loaders.length > 0) return true;
    const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop')) return true;
    }
    const busySelectors = [
        '[class*="spinner"]', '[class*="loading"]', '[aria-busy="true"]',
        '[data-busy="true"]', '[class*="busy"]',
    ];
    for (const sel of busySelectors) {
        if (document.querySelector(sel)) return true;
    }
    const editor = document.querySelector('.ProseMirror');
    if (editor) {
        if (!editor.isContentEditable || editor.hasAttribute('disabled') || !editor.getAttribute('contenteditable')) return true;
    }
    return false;
}
"""

_STOP_GENERATION_JS = """() => {
    const btn = document.querySelector('[data-testid="stop-generating"]');
    if (btn) { btn.click(); return true; }
    const btns = document.querySelectorAll('button, [role="button"]');
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop')) { b.click(); return true; }
    }
    return false;
}"""

# ── Helpers from dom_reader.py ────────────────────────────────────────


async def _get_response_state(client: CdpClient) -> tuple[int, str | None]:
    """Return (assistant_block_count, last_block_text)."""
    try:
        result = await client.evaluate(_GET_RESPONSE_STATE_JS)
    except Exception:
        return 0, None
    if not isinstance(result, dict):
        return 0, None
    count = result.get("count") or 0
    text = result.get("text")
    return int(count), (str(text).strip() if isinstance(text, str) and text.strip() else None)


async def is_generating(client: CdpClient) -> bool:
    """Return whether ChatGPT appears to still be generating."""
    try:
        result = await client.evaluate(_IS_GENERATING_JS)
    except Exception:
        return False
    return bool(result)


# ── Test runner ───────────────────────────────────────────────────────


async def main() -> int:
    client = CdpClient(cdp_url="http://127.0.0.1:9222")
    await client.start()

    # Find a ChatGPT tab with the editor
    tabs = await client.list_tabs()
    chat_tab = None
    for t in tabs:
        if "chatgpt.com" in t.url and "/projects" not in t.url:
            chat_tab = t
            break

    if not chat_tab or not chat_tab.tab_id:
        print("FAIL — no ChatGPT tab found. Open one with --remote-debugging-port=9222")
        await client.stop()
        return 1

    activated = await client.activate_tab(chat_tab.tab_id)
    if not activated:
        print(f"FAIL — could not activate tab {chat_tab.tab_id}")
        await client.stop()
        return 1

    print(f"→ Active ChatGPT tab: {activated.url}")

    passed = 0
    failed = 0

    # ── Test 1: _IS_READY_JS (ready check predicate) ────────────────────
    print("\n━━━ Test 1: _IS_READY_JS — ready check predicate")
    try:
        is_ready = await client.evaluate(_IS_READY_JS)
        if is_ready:
            print(f"  PASS — ready={is_ready}")
            passed += 1
        else:
            print(f"  FAIL — ready={is_ready} (expected True on logged-in page)")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 2: _CLEAR_EDITOR_JS (clear editor) ────────────────────────
    print("\n━━━ Test 2: _CLEAR_EDITOR_JS — clear .ProseMirror editor")
    try:
        result = await client.evaluate(_CLEAR_EDITOR_JS)
        if isinstance(result, dict) and result.get("ok"):
            print("  PASS — editor cleared successfully")
            passed += 1
        else:
            print(f"  FAIL — {result}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 3: _APPEND_TEXT_JS (inject text into editor) ──────────────
    print("\n━━━ Test 3: _APPEND_TEXT_JS — inject text into .ProseMirror")
    test_text = "test-injection-12345"
    try:
        result = await client.evaluate(_APPEND_TEXT_JS, test_text)
        if isinstance(result, dict) and result.get("ok"):
            # Verify the text appears in the editor
            editor_text = await client.evaluate("""() => {
                const el = document.querySelector('.ProseMirror');
                return el ? el.textContent.trim() : '';
            }""")
            if test_text in editor_text:
                print(f"  PASS — text injected and verified (length={result.get('textLength')})")
                passed += 1
            else:
                print(
                    f"  FAIL — text injected but not found in editor (editor has: {editor_text[:50]!r})"
                )
                failed += 1
        else:
            print(f"  FAIL — {result}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 4: _SUBMIT_JS (submit editor content) ─────────────────────
    print("\n━━━ Test 4: _SUBMIT_JS — submit button detection")
    try:
        result = await client.evaluate(_SUBMIT_JS)
        if isinstance(result, dict):
            if result.get("error"):
                print(f"  FAIL — {result['error']}")
                failed += 1
            else:
                label = result.get("buttonLabel", "N/A")
                print(
                    f"  PASS — submit detected (label={label}, textLength={result.get('textLength')})"
                )
                passed += 1
        else:
            print(f"  FAIL — unexpected result: {result}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 5: _IS_GENERATING_JS (generation state detection) ─────────
    print("\n━━━ Test 5: _IS_GENERATING_JS — generation state detection")
    try:
        gen = await client.evaluate(_IS_GENERATING_JS)
        if isinstance(gen, bool):
            if gen:
                print("  PASS — generating=True (ChatGPT is currently active)")
                passed += 1
            else:
                print("  PASS — generating=False (no active generation)")
                passed += 1
        else:
            print(f"  FAIL — expected bool, got {type(gen).__name__}: {gen}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 6: _GET_RESPONSE_STATE_JS (response count/text) ───────────
    print("\n━━━ Test 6: _GET_RESPONSE_STATE_JS — response state")
    try:
        result = await client.evaluate(_GET_RESPONSE_STATE_JS)
        if isinstance(result, dict):
            count = result.get("count", 0)
            text_preview = (result.get("text") or "")[:80]
            print(f"  PASS — count={count}, text_preview={text_preview!r}")
            passed += 1
        else:
            print(f"  FAIL — expected dict, got {type(result).__name__}: {result}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 7: _STOP_GENERATION_JS (stop button detection) ────────────
    print("\n━━━ Test 7: _STOP_GENERATION_JS — stop button detection")
    try:
        result = await client.evaluate(_STOP_GENERATION_JS)
        if isinstance(result, bool):
            if result:
                print("  PASS — stop button found and clicked (generation was active)")
                passed += 1
            else:
                print("  PASS — no stop button found (not generating)")
                passed += 1
        else:
            print(f"  FAIL — expected bool, got {type(result).__name__}: {result}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 8: _get_response_state helper (tuple return) ──────────────
    print("\n━━━ Test 8: _get_response_state() — Python helper function")
    try:
        count, text = await _get_response_state(client)
        print(f"  PASS — count={count}, text_length={len(text or '')}")
        passed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Test 9: is_generating helper (bool return) ─────────────────────
    print("\n━━━ Test 9: is_generating() — Python helper function")
    try:
        gen = await is_generating(client)
        if isinstance(gen, bool):
            print(f"  PASS — generating={gen}")
            passed += 1
        else:
            print(f"  FAIL — expected bool, got {type(gen).__name__}: {gen}")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Summary ────────────────────────────────────────────────────────
    total = passed + failed
    print("\n" + "=" * 60)
    print(f"Tests passed: {passed}/{total}")
    if failed > 0:
        print(f"Tests failed: {failed}")
    print("=" * 60)

    await client.stop()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
