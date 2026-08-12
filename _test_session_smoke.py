"""Integration: managed browser launch -> session transport open."""

# type: ignore[import]
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "src")

from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.foundation.system.browser_manager import (  # type: ignore[import]
    BrowserConfig,
    BrowserManager,
)


async def main() -> None:  # pragma: no cover
    port = 9225  # isolated

    bm = BrowserManager(config=BrowserConfig(port=port))
    print(f"1. Starting managed browser on port {port}...")
    cdp_url = await bm.start()
    print(f"   OK: {cdp_url}, PID={bm._evidence.pid if bm._evidence else 'N/A'}")

    cfg = GptAutoConfig(
        browser_port=port,
        cdp_url=f"http://127.0.0.1:{port}",
        tab_selection_timeout=15,
    )
    transport = GptAutoSessionTransport(
        project_root=Path("."),
        config=cfg,
        project_name="AUDiaGentic",
    )

    print("\n2. Opening session (CDP -> workspace -> ChatGPT)...")
    try:
        result = await transport.open()
        print(f"   Session opened: {result.ag_session_id}")
        print(f"   Metadata keys: {list(result.metadata.keys()) if result.metadata else 'none'}")
    except Exception as exc:
        print(f"   Expected failure (clean profile, no ChatGPT login): {exc}")
    finally:
        print("\n3. Closing session + stopping browser...")
        await transport.close()
        await bm.stop()
        print("   OK — clean shutdown")


asyncio.run(main())
