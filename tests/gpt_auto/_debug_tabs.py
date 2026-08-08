"""Debug: list ChatGPT tabs and their editor state."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient


async def main():
    c = CdpClient(cdp_url="http://127.0.0.1:9222")
    await c.start()
    tabs = await c.list_tabs()
    for t in tabs:
        print(f"Tab: {t.url} (id={t.tab_id})")
        if "chatgpt.com" in t.url:
            r = await c.activate_tab(t.tab_id)
            if not r:
                print("  Could not activate")
                continue
            try:
                ready = await c.evaluate("() => !!document.querySelector('.ProseMirror')")
                print(f"  Editor: {ready}")
            except Exception as e:
                print(f"  Error: {e}")
    await c.stop()


if __name__ == "__main__":
    asyncio.run(main())
