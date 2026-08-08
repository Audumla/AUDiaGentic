"""Demo: real plan-item review + follow-up via CDP — one tab only.

Pick a random plan item, ask ChatGPT to review it, then send a follow-up in
the same conversation. You'll see the typing and responses in your browser.

    python tests/gpt_auto/test_demo_plan_review.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient
from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
    _get_response_state,
    wait_for_response,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
    inject_prompt,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_pool import (
    pick_plan_review_prompt,
)

# ── Main ──────────────────────────────────────────────────────────────


async def run_turn(client: CdpClient, label: str, prompt: str) -> str | None:
    """Inject *prompt* and wait for the response using the production reader.

    No artificial pre-wait before calling wait_for_response(): it captures
    its own baseline the instant it's called, which must happen as close to
    the submit as possible -- sleeping first risks the response already
    starting (or finishing, for a short one) during that window and being
    mistaken for the baseline instead of the new content. wait_for_response's
    own internal 15s "wait for start" phase is what actually absorbs the
    post-submit navigation settle, and dom_reader's evaluate calls now retry
    through the detached-context window that navigation causes.
    """
    t0 = time.monotonic()
    await inject_prompt(client, prompt, humanize=True)
    print(f"  [{label}] Prompt injected ({time.monotonic() - t0:.1f}s)")

    t0 = time.monotonic()
    response = await wait_for_response(client, timeout=120.0)
    elapsed = time.monotonic() - t0

    if response:
        print(f"  [{label}] Response in {elapsed:.1f}s ({len(response)} chars)")
        print(f"  [{label}] Preview: {response[:300]!r}")
    else:
        print(f"  [{label}] No response received")
    return response


async def main():
    client = CdpClient(cdp_url="http://127.0.0.1:9222")
    await client.start()

    # Find a ChatGPT tab with an editor, preferring workspace tabs (/g/g-p-...)
    WORKSPACE_NAME = "AUDiaGentic"
    tabs = await client.list_tabs()
    found_tab = None

    # First pass: workspace tabs
    for t in tabs:
        url_lower = t.url.lower()
        if "chatgpt.com" in url_lower and "/g/g-p-" in url_lower:
            r = await client.activate_tab(t.tab_id)
            if not r:
                continue
            try:
                ready = await client.evaluate(
                    "() => { const e = document.querySelector('.ProseMirror'); return !!e; }"
                )
            except Exception:
                continue
            if ready:
                found_tab = r
                print(f"→ Working on workspace: {r.url}")
                break

    # Second pass: any ChatGPT tab with editor (not /projects)
    if not found_tab:
        for t in tabs:
            if "chatgpt.com" in t.url and "/projects" not in t.url.lower():
                r = await client.activate_tab(t.tab_id)
                if not r:
                    continue
                try:
                    ready = await client.evaluate(
                        "() => { const e = document.querySelector('.ProseMirror'); return !!e; }"
                    )
                except Exception:
                    continue
                if ready:
                    found_tab = r
                    print(f"→ Using tab: {r.url}")
                    break

    if not found_tab:
        print(f"FAIL — no ChatGPT tab with editor. Open {WORKSPACE_NAME} workspace first.")
        await client.stop()
        return 1

    # ── Turn 1: Plan item review ───────────────────────────────────────
    prompt1 = pick_plan_review_prompt()
    title_preview = prompt1.split("\n\n")[0] if "\n\n" in prompt1 else prompt1[:80]
    print(f"\n{'=' * 60}")
    print(f"Turn 1: {title_preview}...")
    response1 = await run_turn(client, "Turn 1", prompt1)

    # ── Turn 2: Follow-up in same conversation ────────────────────────
    prompt2 = "What is the single biggest risk you identified? What would be your top recommendation to mitigate it?"
    print(f"\n{'=' * 60}")
    print("Turn 2: Follow-up")
    response2 = await run_turn(client, "Turn 2", prompt2)

    # ── Verify continuity and distinctness ────────────────────────────
    count, _ = await _get_response_state(client)
    print(f"\n{'=' * 60}")
    print(f"Conversation state: {count} assistant block(s)")

    ok = True
    if not response1:
        print("FAIL: Turn 1 had no response")
        ok = False
    if not response2:
        print("FAIL: Turn 2 had no response")
        ok = False
    if response1 and response2 and response1 == response2:
        print("FAIL: Turn 2 returned identical text to Turn 1 — stale read, not a new response")
        ok = False
    if count < 2:
        print(f"WARN: Only {count} block(s) — conversation may not have continued")
    else:
        print("OK: Conversation has multiple turns (continuity confirmed)")

    await client.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
