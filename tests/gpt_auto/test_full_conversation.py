"""Full end-to-end conversation test via CDP client.

Flows through:
  1. Connect to browser, open ChatGPT
  2. Find workspace for the project from /projects page
  3. Inject prompt into ProseMirror and read response
  4. Send a follow-up question in the same chat window
  5. Read and validate second response

Prerequisites:
  - Brave/Chrome running with --remote-debugging-port=9222
  - ChatGPT logged in at chatgpt.com
  - Workspace "AUDiaGentic" created manually

Usage:
    python tests/gpt_auto/test_full_conversation.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient
from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
    wait_for_response,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
    inject_prompt,
    wait_for_chatgpt_ready,
)
from audiagentic.components.providers.adapters.gpt_auto.workspace import (
    ensure_workspace,
)

TEST_PROMPT = "What is the capital of France?"
FOLLOWUP_PROMPT = "And what is its population?"
PROJECT_NAME = "AUDiaGentic"


async def main() -> None:
    client = CdpClient(cdp_url="http://127.0.0.1:9222")

    try:
        await client.start()
        print("[1/7] Connected to browser via CDP")

        # Find workspace — this opens /projects and navigates to workspace
        ws = await ensure_workspace(client, PROJECT_NAME)
        if ws:
            print(f"[2/7] Workspace found: '{ws.name}' -> {ws.url}")
        else:
            print("[2/7] FAIL: Workspace not found")
            return

        current_url = await client.get_url()
        print(f"    Current page: {current_url}")

        # Wait for ChatGPT ready
        ready = await wait_for_chatgpt_ready(client, timeout=30.0, login_timeout=60.0)
        if not ready:
            await client.screenshot(path="/tmp/test-convo-not-ready.png")
            print("FAIL: ChatGPT not ready")
            return
        print("[3/7] ChatGPT is ready")

        # --- First prompt ---
        await inject_prompt(client, TEST_PROMPT, typing_delay=0.03)
        print("[4/7] Prompt injected — waiting for response...")

        response1 = await wait_for_response(
            client,
            timeout=120.0,
            interval=2.0,
            prompt_text=TEST_PROMPT,
        )

        if not response1:
            print("FAIL: No response received before timeout")
            return

        # Capture conversation ID after first response
        chat_url = await client.get_url()
        conv_id = chat_url.split("/c/")[-1].rstrip("/") if "/c/" in chat_url else "project-home"
        session_id = f"ws-{chat_url.split('/g/g-p-')[1].split('/')[0]}" if "/g/g-p-" in chat_url else "unknown"
        print(f"    Conversation ID: {conv_id}")
        print(f"    Session ID: {session_id}")

        print(f"[5/7] Response 1 ({len(response1)} chars):")
        print("-" * 60)
        print(response1[:400])
        if len(response1) > 400:
            print(f"... ({len(response1) - 400} more chars)")
        print("-" * 60)

        # Validate first response
        if "paris" in response1.lower():
            print("  OK: Response contains 'Paris'")
        else:
            print(f"  WARN: Expected 'Paris'. Got: {response1[:200]}")

        # --- Follow-up prompt (same chat window) ---
        await inject_prompt(client, FOLLOWUP_PROMPT, typing_delay=0.03)
        print("[6/7] Follow-up injected — waiting for response...")

        response2 = await wait_for_response(
            client,
            timeout=120.0,
            interval=2.0,
            prompt_text=FOLLOWUP_PROMPT,
        )

        if not response2:
            print("FAIL: No follow-up response before timeout")
            return

        # Final conversation URL
        final_url = await client.get_url()
        final_conv_id = final_url.split("/c/")[-1].rstrip("/") if "/c/" in final_url else "project-home"
        print(f"[7/7] Response 2 ({len(response2)} chars):")
        print("-" * 60)
        print(response2[:400])
        if len(response2) > 400:
            print(f"... ({len(response2) - 400} more chars)")
        print("-" * 60)

        # Validate second response — should mention a number (population)
        has_number = any(c.isdigit() for c in response2)
        if has_number and ("million" in response2.lower() or "paris" in response2.lower()):
            print("  OK: Follow-up response mentions population")
        else:
            print(f"  WARN: Expected population data. Got: {response2[:200]}")

        print(f"\nFinal chat URL: {final_url}")
        print(f"Final conversation ID: {final_conv_id}")
        print("SUCCESS: Full conversation with follow-up completed")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
