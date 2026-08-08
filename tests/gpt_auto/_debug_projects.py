"""Debug: find workspace links on /projects page."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient

# Find project cards by their row class
_FIND_WORKSPACES = """() => {
    const items = [];
    document.querySelectorAll('[class*="project-unfurl-row"]').forEach(el => {
        const text = (el.textContent || '').trim().substring(0, 80);
        let href = null;
        el.querySelectorAll('a').forEach(a => { if (!href) href = a.href; });
        if (!href) {
            const parent = el.closest('a');
            if (parent) href = parent.href;
        }
        items.push({ href, text, tag: el.tagName, cls: (el.className || '').substring(0, 60) });
    });
    return items;
}"""

# Find workspace by name — returns info about the first match
_FIND_WORKSPACE_BY_NAME = """(name) => {
    const target = name.toLowerCase();
    const rows = document.querySelectorAll('[class*="project-unfurl-row"]');
    for (let i = 0; i < rows.length; i++) {
        const el = rows[i];
        const text = (el.textContent || '').trim().toLowerCase();
        if (text.includes(target)) {
            let href = null;
            el.querySelectorAll('a').forEach(a => { if (!href) href = a.href; });
            return { found: true, text: (el.textContent || '').trim().substring(0, 80), href };
        }
    }
    return { found: false };
}"""

async def main():
    c = CdpClient(cdp_url="http://127.0.0.1:9222")
    await c.start()
    tabs = await c.list_tabs()

    for t in tabs:
        if "chatgpt.com" in t.url:
            r = await c.activate_tab(t.tab_id)
            if not r:
                continue

            # Navigate to /projects
            await c.evaluate("() => window.location.href = 'https://chatgpt.com/projects'")
            await asyncio.sleep(3.0)

            # Find all workspaces
            result = await c.evaluate(_FIND_WORKSPACES)
            print(f"\nWorkspaces found: {len(result)}")
            for item in result[:20]:
                print(f"  {item['href']} -> {item['text']}")

            # Find AUDiaGentic workspace specifically
            name = "AUDiaGentic"
            ws_href = await c.evaluate(_FIND_WORKSPACE_BY_NAME, name)
            print(f"\nFound '{name}' at: {ws_href}")

            break

    await c.stop()

if __name__ == "__main__":
    asyncio.run(main())
