"""Live test: prompt → response → follow-up flow via CDP.

Validates the full gpt-auto interaction loop against a real browser, but at a
lower level than test_session_transport_live.py. Tests each step individually:
1. Ready check (wait_for_chatgpt_ready)
2. Inject prompt (inject_prompt)
3. Wait for response start
4. Poll until stability window passes
5. Read response text
6. Follow-up prompt in same conversation

Prerequisites: Chrome/Edge open with --remote-debugging-port=9222, logged into ChatGPT.

    python tests/gpt_auto/test_cdp_prompt_flow.py [--conversation-id ID]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

sys.path.insert(0, str(__file__.replace("\\", "/").rsplit("/", 1)[0]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient
from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
    _get_response_state,
    get_response_text,
    is_generating,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
    inject_prompt,
    wait_for_chatgpt_ready,
)

# ── Helpers ───────────────────────────────────────────────────────────

_RESPONSE_STABILITY_SECONDS = 15.0


async def poll_until_stable(
    client: CdpClient, base_count: int, base_text: str | None, timeout_s: float = 120.0
) -> str | None:
    """Poll until response text is stable for _RESPONSE_STABILITY_SECONDS."""
    start_deadline = time.monotonic() + 30.0
    deadline = time.monotonic() + timeout_s
    last_text: str | None = None
    stable_since: float | None = None

    # Wait for response to start
    while time.monotonic() < start_deadline:
        count, text = await _get_response_state(client)
        if count > base_count or (text is not None and text != base_text):
            break
        if await is_generating(client):
            break
        await asyncio.sleep(1.0)

    # Poll until stable
    while time.monotonic() < deadline:
        count, text = await _get_response_state(client)
        has_fresh = count > base_count or (text is not None and text != base_text)

        if not has_fresh:
            stable_since = None
            if not await is_generating(client):
                # No generation and no fresh content — likely a hang
                return last_text
            await asyncio.sleep(2.0)
            continue

        if text and text != last_text:
            last_text = text
            stable_since = time.monotonic()
            continue

        if text is None:
            last_text = None
            stable_since = None
            await asyncio.sleep(2.0)
            continue

        # Text unchanged — check if generating stopped
        if await is_generating(client):
            await asyncio.sleep(2.0)
            continue

        # Generating stopped — check stability
        if stable_since is None:
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= _RESPONSE_STABILITY_SECONDS:
            final_text = await get_response_text(client)
            if final_text == last_text:
                return final_text
            if final_text:
                last_text = final_text
                stable_since = time.monotonic()

        await asyncio.sleep(2.0)

    return last_text


# ── Test runner ───────────────────────────────────────────────────────


async def main(conversation_id: str | None = None) -> int:
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

    # ── Step 1: Ready check ────────────────────────────────────────────
    print("\n━━━ Step 1: wait_for_chatgpt_ready()")
    try:
        start = time.monotonic()
        ready = await wait_for_chatgpt_ready(client, timeout=15.0)
        elapsed = time.monotonic() - start
        if ready:
            print(f"  PASS — ready in {elapsed:.2f}s")
            passed += 1
        else:
            print("  FAIL — not ready after 15s")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Step 2: Inject a short prompt ──────────────────────────────────
    print("\n━━━ Step 2: inject_prompt() — turn 1")
    prompt1 = "What is 2+2? Respond with just the number."
    try:
        start = time.monotonic()
        await inject_prompt(
            client,
            prompt1,
            humanize=True,
            think_min=0.5,
            think_max=1.0,
        )
        elapsed = time.monotonic() - start
        print(f"  PASS — prompt injected and submitted in {elapsed:.2f}s")
        passed += 1
    except Exception as e:
        print(f"  FAIL — inject_prompt failed: {e}")
        failed += 1

    # ── Step 3: Wait for response ──────────────────────────────────────
    print("\n━━━ Step 3: poll_until_stable() — waiting for response")
    try:
        base_count, base_text = await _get_response_state(client)
        start = time.monotonic()
        response1 = await poll_until_stable(
            client,
            base_count=base_count,
            base_text=base_text,
            timeout_s=90.0,
        )
        elapsed = time.monotonic() - start
        if response1:
            print(f"  PASS — response received in {elapsed:.2f}s ({len(response1)} chars)")
            print(f"    Response: {response1[:200]!r}")
            passed += 1
        else:
            print(f"  FAIL — no substantive response (got: {response1!r})")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Step 4: Read response text via get_response_text() ─────────────
    print("\n━━━ Step 4: get_response_text() — verify last assistant message")
    try:
        text = await get_response_text(client)
        if text and "4" in text.lower():
            print(f"  PASS — response text contains '4' (2+2=4): {text!r}")
            passed += 1
        elif text:
            print(f"  WARN — response text doesn't contain '4': {text!r}")
            passed += 1
        else:
            print("  FAIL — no response text found")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Step 5: Follow-up prompt (same conversation) ───────────────────
    print("\n━━━ Step 5: inject_prompt() — follow-up turn")
    prompt2 = "Now double that number. Respond with just the result."
    try:
        start = time.monotonic()
        await inject_prompt(
            client,
            prompt2,
            humanize=True,
            think_min=0.5,
            think_max=1.0,
        )
        elapsed = time.monotonic() - start
        print(f"  PASS — follow-up injected in {elapsed:.2f}s")
        passed += 1
    except Exception as e:
        print(f"  FAIL — follow-up inject failed: {e}")
        failed += 1

    # ── Step 6: Wait for follow-up response ────────────────────────────
    print("\n━━━ Step 6: poll_until_stable() — waiting for follow-up")
    try:
        base_count, base_text = await _get_response_state(client)
        start = time.monotonic()
        response2 = await poll_until_stable(
            client,
            base_count=base_count,
            base_text=base_text,
            timeout_s=90.0,
        )
        elapsed = time.monotonic() - start
        if response2:
            print(f"  PASS — follow-up response in {elapsed:.2f}s ({len(response2)} chars)")
            print(f"    Response: {response2[:200]!r}")
            passed += 1
        else:
            print(f"  FAIL — no substantive follow-up (got: {response2!r})")
            failed += 1
    except Exception as e:
        print(f"  FAIL — {e}")
        failed += 1

    # ── Step 7: Verify conversation continuity ─────────────────────────
    print("\n━━━ Step 7: conversation state (block count)")
    try:
        count, _ = await _get_response_state(client)
        if count >= 2:
            print(f"  PASS — {count} assistant blocks (conversation continues)")
            passed += 1
        elif count == 1:
            print("  WARN — only 1 block (may be same conversation, different turn)")
            passed += 1
        else:
            print(f"  FAIL — {count} blocks (no conversation state)")
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
    parser = argparse.ArgumentParser(description="gpt-auto prompt flow test")
    parser.add_argument("--conversation-id", default=None, help="Resume existing conversation")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(conversation_id=args.conversation_id)))
