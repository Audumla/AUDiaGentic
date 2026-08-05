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

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient
from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
    wait_for_response,
)
from audiagentic.components.providers.adapters.gpt_auto.humanize import (
    between_requests_delay,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
    inject_prompt,
    wait_for_chatgpt_ready,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_pool import (
    pick_plan_review_prompt,
    pick_prompt,
)
from audiagentic.components.providers.adapters.gpt_auto.workspace import (
    ensure_workspace,
)

PROJECT_NAME = "AUDiaGentic"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


async def main(conversation_id: str | None = None) -> None:
    client = CdpClient(cdp_url="http://127.0.0.1:9222")

    try:
        await client.start()
        print("[1/7] Connected to browser via CDP")

        tabs_before = await client.list_tabs()
        chat_tabs_before = [t for t in tabs_before if "chatgpt.com" in t.url]
        print(f"    ChatGPT tabs before: {len(chat_tabs_before)}")

        if conversation_id:
            print(f"    Resuming conversation: {conversation_id}")

        # Find workspace — opens /projects and navigates to workspace
        ws = await ensure_workspace(
            client,
            PROJECT_NAME,
            conversation_id=conversation_id,
            project_root=REPO_ROOT,
        )
        if ws:
            print(f"[2/7] Workspace found: '{ws.name}' -> {ws.url}")
            print(f"    Session ID: {ws.session_id}")
            print(f"    Conversation ID: {ws.conversation_id}")
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

        # --- First prompt (random plan-item review — no reuse across runs) ---
        test_prompt = pick_plan_review_prompt()
        followup_prompt = pick_prompt()
        print(f"    Prompt: {test_prompt[:80]}{'...' if len(test_prompt) > 80 else ''}")
        print(f"    Follow-up: {followup_prompt[:80]}{'...' if len(followup_prompt) > 80 else ''}")

        await inject_prompt(client, test_prompt, typing_delay=0.03)
        print("[4/7] Prompt injected — waiting for response...")

        response1 = await wait_for_response(
            client,
            timeout=120.0,
            interval=2.0,
            prompt_text=test_prompt,
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

        # Validate first response — any substantive answer
        if len(response1) > 40:
            print(f"  OK: Response is substantive ({len(response1)} chars)")
        else:
            print(f"  WARN: Response seems short. Got: {response1[:200]}")

        # --- Follow-up prompt (same chat window) with a human pause between turns ---
        pause = between_requests_delay()
        print(f"    Waiting {pause:.1f}s before follow-up (human-like gap)...")
        await asyncio.sleep(pause)

        await inject_prompt(client, followup_prompt, typing_delay=0.03)
        print("[6/7] Follow-up injected — waiting for response...")

        response2 = await wait_for_response(
            client,
            timeout=120.0,
            interval=2.0,
            baseline_length=len(response1),
            prompt_text=followup_prompt,
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

        # Validate second response — should be substantive and different from response 1
        if len(response2) > 40 and response2.strip() != response1.strip():
            print(f"  OK: Follow-up response is substantive and distinct ({len(response2)} chars)")
        else:
            print(f"  WARN: Follow-up response looks off. Got: {response2[:200]}")

        print(f"\nFinal chat URL: {final_url}")
        print(f"Final conversation ID: {final_conv_id}")

        # Tab reuse validation: mapped tab should mean no new ChatGPT tab appeared
        tabs_after = await client.list_tabs()
        chat_tabs_after = [t for t in tabs_after if "chatgpt.com" in t.url]
        print(f"    ChatGPT tabs after: {len(chat_tabs_after)}")
        if len(chat_tabs_after) <= len(chat_tabs_before):
            print("  OK: No new ChatGPT tab opened (tab reuse working)")
        else:
            print(f"  WARN: {len(chat_tabs_after) - len(chat_tabs_before)} new ChatGPT tab(s) opened")

        print("SUCCESS: Full conversation with follow-up completed")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gpt-auto full conversation test")
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Resume an existing conversation by ID (else start a new chat)",
    )
    args = parser.parse_args()
    asyncio.run(main(conversation_id=args.conversation_id))
