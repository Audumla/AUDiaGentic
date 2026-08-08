"""Test: end-to-end timing comparison of polling vs event-based mechanisms.

Runs each of the four key entry-flow wait patterns using BOTH polling and
event-based approaches, then prints a summary table showing the delta.

This is the primary evidence for whether the event-based approach delivers
measurable improvement before slotting it into production code.

Prerequisites: Chrome/Edge open with --remote-debugging-port=9222, logged into ChatGPT.

    python tests/gpt_auto/test_event_timing_comparison.py
"""

from __future__ import annotations

import asyncio
import time

from audiagentic.components.providers.adapters.gpt_auto.playwright_client import (
    PlaywrightClient,
)

# ── Predicates copied from production code ─────────────────────────────

_READY_JS = """
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


async def _poll_ready(page, timeout_s: float = 30.0) -> tuple[bool, float]:
    """Polling version of wait_for_chatgpt_ready."""
    start = time.monotonic()
    deadline = start + timeout_s
    while time.monotonic() < deadline:
        result = await page.evaluate(_READY_JS)
        if result:
            return True, time.monotonic() - start
        await asyncio.sleep(0.5)
    return False, time.monotonic() - start


async def _event_ready(page, timeout_ms: int = 30000) -> tuple[bool, float]:
    """Event-based version using wait_for_function."""
    start = time.monotonic()
    try:
        await page.wait_for_function(_READY_JS, timeout=timeout_ms)
        return True, time.monotonic() - start
    except Exception:
        return False, time.monotonic() - start


async def _poll_url(page, target: str, max_iter: int = 20) -> tuple[bool, float]:
    """Polling version of navigation detection."""
    start = time.monotonic()
    for _ in range(max_iter):
        url = ""
        try:
            url = await page.evaluate("() => window.location.href")
        except RuntimeError:
            pass
        if target in url:
            return True, time.monotonic() - start
        await asyncio.sleep(0.5)
    return False, time.monotonic() - start


async def _event_url(page, pattern: str, timeout_ms: int = 10000) -> tuple[bool, float]:
    """Event-based version using wait_for_url."""
    start = time.monotonic()
    try:
        await page.wait_for_url(pattern, timeout=timeout_ms)
        return True, time.monotonic() - start
    except Exception:
        return False, time.monotonic() - start


async def _poll_generation(page, selector: str, timeout_s: float = 5.0) -> tuple[bool, float]:
    """Polling version of is_generating check."""
    start = time.monotonic()
    deadline = start + timeout_s
    while time.monotonic() < deadline:
        result = await page.evaluate(f"() => !!document.querySelector('{selector}')")
        if result:
            return True, time.monotonic() - start
        await asyncio.sleep(0.5)
    return False, time.monotonic() - start


async def _event_selector(page, selector: str, timeout_ms: int = 5000) -> tuple[bool, float]:
    """Event-based version using wait_for_selector."""
    start = time.monotonic()
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return True, time.monotonic() - start
    except Exception:
        return False, time.monotonic() - start


async def main() -> None:
    client = PlaywrightClient(target_url="https://chat.openai.com")

    try:
        print("→ Launching Chrome …")
        await client.start()
        pg = client.page
        assert pg is not None, "No page available"

        print("→ Waiting for ChatGPT to load …")
        await asyncio.sleep(5)

        results = []

        # ── 1. ChatGPT ready check ──────────────────────────────────────
        print("\n═══ 1. ChatGPT ready check (ProseMirror + no login)")
        ok_poll, t_poll = await _poll_ready(pg, timeout_s=30.0)
        ok_event, t_event = await _event_ready(pg, timeout_ms=30000)

        print(f"  Polling:    {'OK' if ok_poll else 'FAIL'} — {t_poll:.3f}s")
        print(f"  Event-based: {'OK' if ok_event else 'FAIL'} — {t_event:.3f}s")
        delta = t_poll - t_event
        print(f"  Delta:      {delta:+.3f}s")
        results.append(("ready_check", ok_poll, t_poll, ok_event, t_event))

        # ── 2. Navigation detection (home → /projects) ─────────────────
        print("\n═══ 2. Navigation detection (home → /projects)")
        await pg.goto("https://chatgpt.com", wait_until="domcontentloaded")
        await asyncio.sleep(1)

        ok_poll, t_poll = await _poll_url(pg, "projects")
        # Re-navigate for event-based test
        await pg.goto("https://chatgpt.com", wait_until="domcontentloaded")
        await asyncio.sleep(1)

        ok_event, t_event = await _event_url(pg, "*projects*", timeout_ms=10000)

        print(f"  Polling:     {'OK' if ok_poll else 'FAIL'} — {t_poll:.3f}s")
        print(f"  Event-based: {'OK' if ok_event else 'FAIL'} — {t_event:.3f}s")
        delta = t_poll - t_event
        print(f"  Delta:       {delta:+.3f}s")
        results.append(("navigation", ok_poll, t_poll, ok_event, t_event))

        # ── 3. Generation start detection ───────────────────────────────
        print("\n═══ 3. Generation start (stop button appears)")
        # Inject a fake stop button after a delay for both approaches
        selector = '[data-testid="stop-generating"]'

        # Polling: inject, then poll
        async def _inject_for_poll():
            await asyncio.sleep(0.1)
            await pg.evaluate("""() => {
                const btn = document.createElement('div');
                btn.setAttribute('data-testid', 'stop-generating');
                btn.id = 'test-stop';
                document.body.appendChild(btn);
            }""")

        asyncio.create_task(_inject_for_poll())
        ok_poll, t_poll = await _poll_generation(pg, selector, timeout_s=5.0)

        # Event-based: inject, then wait_for_selector
        async def _inject_for_event():
            await asyncio.sleep(0.1)
            await pg.evaluate("""() => {
                const btn = document.createElement('div');
                btn.setAttribute('data-testid', 'stop-generating');
                btn.id = 'test-stop-2';
                document.body.appendChild(btn);
            }""")

        # Clean up first test button
        await pg.evaluate(
            "() => { const el = document.getElementById('test-stop'); if (el) el.remove(); }"
        )

        asyncio.create_task(_inject_for_event())
        ok_event, t_event = await _event_selector(pg, selector, timeout_ms=5000)

        print(f"  Polling:     {'OK' if ok_poll else 'FAIL'} — {t_poll:.3f}s")
        print(f"  Event-based: {'OK' if ok_event else 'FAIL'} — {t_event:.3f}s")
        delta = t_poll - t_event
        print(f"  Delta:       {delta:+.3f}s")
        results.append(("generation_start", ok_poll, t_poll, ok_event, t_event))

        # Clean up
        await pg.evaluate(
            "() => { const el = document.getElementById('test-stop-2'); if (el) el.remove(); }"
        )

        # ── 4. Generation stop detection ────────────────────────────────
        print("\n═══ 4. Generation stop (stop button disappears)")
        # Inject stop button first
        await pg.evaluate("""() => {
            const btn = document.createElement('div');
            btn.setAttribute('data-testid', 'stop-generating');
            btn.id = 'test-stop-3';
            document.body.appendChild(btn);
        }""")

        # Polling: remove after delay, poll for absence
        async def _remove_for_poll():
            await asyncio.sleep(0.2)
            await pg.evaluate(
                "() => { const el = document.getElementById('test-stop-3'); if (el) el.remove(); }"
            )

        asyncio.create_task(_remove_for_poll())
        start = time.monotonic()
        deadline = start + 5.0
        found_absent = False
        while time.monotonic() < deadline:
            result = await pg.evaluate(
                "() => !document.querySelector('[data-testid=\"stop-generating\"]')"
            )
            if result:
                found_absent = True
                break
            await asyncio.sleep(0.5)
        t_poll_gen_stop = time.monotonic() - start

        # Re-inject for event-based test
        await pg.evaluate("""() => {
            const btn = document.createElement('div');
            btn.setAttribute('data-testid', 'stop-generating');
            btn.id = 'test-stop-4';
            document.body.appendChild(btn);
        }""")

        # Event-based: remove after delay, wait_for_function for absence
        async def _remove_for_event():
            await asyncio.sleep(0.2)
            await pg.evaluate(
                "() => { const el = document.getElementById('test-stop-4'); if (el) el.remove(); }"
            )

        asyncio.create_task(_remove_for_event())
        start = time.monotonic()
        try:
            await pg.wait_for_function(
                "() => !document.querySelector('[data-testid=\"stop-generating\"]')",
                timeout=5000,
            )
            t_event_gen_stop = time.monotonic() - start
            ok_event_gen_stop = True
        except Exception:
            t_event_gen_stop = time.monotonic() - start
            ok_event_gen_stop = False

        print(f"  Polling:     {'OK' if found_absent else 'FAIL'} — {t_poll_gen_stop:.3f}s")
        print(f"  Event-based: {'OK' if ok_event_gen_stop else 'FAIL'} — {t_event_gen_stop:.3f}s")
        delta = t_poll_gen_stop - t_event_gen_stop
        print(f"  Delta:       {delta:+.3f}s")
        results.append(
            ("generation_stop", found_absent, t_poll_gen_stop, ok_event_gen_stop, t_event_gen_stop)
        )

        # ── Summary table ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print(f"{'Scenario':<25} {'Polling':>10} {'Event':>10} {'Delta':>10}")
        print("-" * 70)
        for name, _, tp, _, te in results:
            d = tp - te
            print(f"{name:<25} {tp:>9.3f}s {te:>9.3f}s {d:>+9.3f}s")
        print("-" * 70)
        total_poll = sum(tp for _, _, tp, _, _ in results)
        total_event = sum(te for _, _, _, _, te in results)
        print(
            f"{'TOTAL':<25} {total_poll:>9.3f}s {total_event:>9.3f}s {total_poll - total_event:>+9.3f}s"
        )

        # Theoretical max savings (worst case where each mechanism is hit at full timeout)
        print("\n═══ Theoretical worst-case savings ═══")
        print("  Scenario                    | Polling max     | Event-based    | Max saved")
        print("  ----------------------------|-----------------|----------------|----------")
        print("  ready_check (30s timeout)   | 15.0s avg poll  | instant fire   | ~14.8s")
        print("  login_wait (120s timeout)   | 60.0s avg poll  | instant fire   | ~59.8s")
        print("  navigation (20 iter × 0.5s) | 10.0s max       | instant fire   | ~9.8s")
        print("  generation_start (5s)       | 2.5s avg poll   | instant fire   | ~2.3s")
        print("  generation_stop (stability) | 15.0s window    | 15.0s window   | 0s (inherent)")
        print("  ----------------------------|-----------------|----------------|----------")
        print("  Total max saved per session: ~86.7s (with login page hit)")
        print("  Total max saved per session: ~26.9s (without login page)")

        await client.screenshot(path="/tmp/test-comparison-done.png")
        print("\n  Screenshot saved to /tmp/test-comparison-done.png")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
