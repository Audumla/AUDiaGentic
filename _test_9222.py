"""Test session transport against CDP on port 9222."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    build_gpt_auto_session_transport,
)
from audiagentic.foundation.transports.agent_session import SessionPrompt

REPO = Path(__file__).resolve().parent


async def main():
    transport = build_gpt_auto_session_transport(
        REPO,
        config={"browser_port": 9222, "browser_autostart": False},
        project_name="AUDiaGentic",
    )

    print("Opening session...")
    try:
        result = await transport.open()
        ref = str(result)
        print(f"Session ref: {ref}")
        if hasattr(result, "metadata"):
            for k, v in result.metadata.items():
                print(f"  {k}: {v}")

        print("\nSending prompt...")

        async def sink(observation):
            kind = getattr(observation, "kind", type(observation).__name__)
            attrs = getattr(observation, "attributes", None) or {}
            print(f"  obs: {kind} {attrs}")

        r2 = await transport.prompt(
            SessionPrompt(turn_id="test-1", body="Say hello in three words"),
            sink=sink,
        )
        length = len(r2.final_summary) if r2.final_summary else 0
        print(f"Response ({length} chars):")
        if r2.final_summary:
            print(r2.final_summary[:300])
    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        await transport.close()


asyncio.run(main())
