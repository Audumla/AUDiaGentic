"""Quick CDP smoke test - connect to existing browser on port 9224."""
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
        config={"browser_port": 9224, "browser_autostart": False},
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
    except Exception as e:
        print(f"Error opening session: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\nSending prompt...")
    try:
        async def sink(observation):
            kind = getattr(observation, "kind", type(observation).__name__)
            attrs = getattr(observation, "attributes", None) or {}
            print(f"  obs: {kind} {attrs}")

        result2 = await transport.prompt(
            SessionPrompt(turn_id="test-1", body="Say hello in three words"),
            sink=sink,
        )
        print(f"Response ({len(result2.final_summary or '')} chars):")
        if result2.final_summary:
            print(result2.final_summary[:500])
    except Exception as e:
        print(f"Error sending prompt: {e}")
        import traceback
        traceback.print_exc()

    await transport.close()
    print("\nDone.")


asyncio.run(main())
