"""Live multi-turn session test via the AgentSessionTransport seam (BR04).

SMOKE TEST — NOT run during normal test runs (pytest collects no test
functions here).  Run manually exactly like the other gpt_auto smoke scripts:

    python tests/gpt_auto/test_session_transport_live.py [--conversation-id ID]

Flows through:
  1. Build the CDP session transport via build_gpt_auto_session_transport
  2. open() the session (resumes --conversation-id or starts a new chat)
  3. prompt() with a random plan-item review prompt (fresh task each run)
  4. prompt() again with a follow-up — proves multi-turn continuity in the
     same conversation through the transport seam
  5. close() — browser tab stays open (external ownership)

Prerequisites:
  - Brave/Chrome running with --remote-debugging-port=9222
  - ChatGPT logged in at chatgpt.com
  - Workspace "AUDiaGentic" created manually
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - not all consoles support reconfigure
    pass

from audiagentic.components.providers.adapters.gpt_auto.humanize import (
    between_requests_delay,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_pool import (
    pick_plan_review_prompt,
    pick_prompt,
)
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    build_gpt_auto_session_transport,
)
from audiagentic.foundation.transports.agent_session import (
    SessionPrompt,
    SessionTurnResult,
)

PROJECT_NAME = "AUDiaGentic"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _print_turn(tag: str, result: SessionTurnResult) -> None:
    body = result.final_summary or ""
    print(f"{tag}: stop_reason={result.stop_reason} ({len(body)} chars)")
    print("-" * 60)
    print(body[:400])
    if len(body) > 400:
        print(f"... ({len(body) - 400} more chars)")
    print("-" * 60)


async def main(conversation_id: str | None = None) -> int:
    transport = build_gpt_auto_session_transport(
        REPO_ROOT,
        project_name=PROJECT_NAME,
        resume_provider_ref=conversation_id,
    )

    async def sink(obs) -> None:
        kind = getattr(obs, "kind", type(obs).__name__)
        attrs = getattr(obs, "attributes", None) or {}
        print(f"    obs: {kind} {attrs}")

    try:
        print("[1/6] Building transport and opening session...")
        opened = await transport.open()
        ref = str(opened)
        print(f"      session ref: {ref}")

        print("[2/6] Turn 1 — random plan-item review...")
        prompt1 = pick_plan_review_prompt()
        print(f"      prompt: {prompt1[:100]}{'...' if len(prompt1) > 100 else ''}")
        result1 = await transport.prompt(
            SessionPrompt(turn_id="live-1", body=prompt1),
            sink=sink,
        )
        _print_turn("[3/6] Response 1", result1)

        pause = between_requests_delay()
        print(f"      Waiting {pause:.1f}s before follow-up (human-like gap)...")
        await asyncio.sleep(pause)

        print("[4/6] Turn 2 — follow-up in the same conversation...")
        prompt2 = pick_prompt()
        print(f"      prompt: {prompt2[:100]}{'...' if len(prompt2) > 100 else ''}")
        result2 = await transport.prompt(
            SessionPrompt(turn_id="live-2", body=prompt2),
            sink=sink,
        )
        _print_turn("[5/6] Response 2", result2)

        summary1 = (result1.final_summary or "").strip()
        summary2 = (result2.final_summary or "").strip()
        failures = 0

        if result1.stop_reason != "end_turn" or len(summary1) <= 40:
            print("  FAIL: Turn 1 did not produce a substantive end_turn response")
            failures += 1
        else:
            print(f"  OK: Turn 1 substantive ({len(summary1)} chars)")

        if result2.stop_reason != "end_turn" or len(summary2) <= 40:
            print("  FAIL: Turn 2 did not produce a substantive end_turn response")
            failures += 1
        elif summary2 == summary1:
            print("  FAIL: Turn 2 echoed Turn 1 — conversation did not continue")
            failures += 1
        else:
            print(f"  OK: Turn 2 substantive and distinct ({len(summary2)} chars)")

        if transport.is_alive():
            print("  OK: transport still alive after two turns")
        else:
            print("  FAIL: transport not alive after two turns")
            failures += 1

        return 1 if failures else 0

    except Exception as exc:
        print(f"ERROR: {exc}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        print("[6/6] Closing session (browser tab stays open)...")
        await transport.close()
        if transport.is_alive():
            print("  WARN: transport alive after close (close is idempotent — harmless)")
        else:
            print("  OK: transport closed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gpt-auto session transport live test")
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Resume an existing conversation by ID (else start a new chat)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(conversation_id=args.conversation_id)))
