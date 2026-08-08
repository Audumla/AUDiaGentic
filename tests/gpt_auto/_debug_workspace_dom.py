"""Debug: examine DOM structure of /projects workspace cards."""
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
        if "chatgpt.com" in t.url:
            r = await c.activate_tab(t.tab_id)
            if not r:
                continue

            print("Navigating to /projects...")
            await c.evaluate("() => window.location.href = 'https://chatgpt.com/projects'")
            await asyncio.sleep(3.0)

            # Dump DOM structure around AUDiaGentic card
            result = await c.evaluate(
                "(name) => { "
                "const target = name.toLowerCase(); "
                "const rows = document.querySelectorAll('[class*=\\\"project-unfurl-row\\\"]'); "
                "for (let i = 0; i < rows.length; i++) { "
                "  const text = (rows[i].textContent || '').trim().toLowerCase(); "
                "  if (text.includes(target)) { "
                "    const el = rows[i]; "
                "    return { "
                "      html: el.outerHTML.substring(0, 2000), "
                "      children: Array.from(el.children).map(c => ({ tag: c.tagName, cls: (c.className || '').substring(0, 80) })), "
                "    }; "
                "  } "
                "} "
                "return null; }",
                "AUDiaGentic",
            )
            if result:
                print(f"\nAUDiaGentic card HTML:\n{result['html'][:500]}")
                print(f"\nChildren:\n{result['children']}")

            # Also check if there are any clickable elements (buttons, links) inside or nearby
            clickable = await c.evaluate(
                "(name) => { "
                "const target = name.toLowerCase(); "
                "const rows = document.querySelectorAll('[class*=\\\"project-unfurl-row\\\"]'); "
                "for (let i = 0; i < rows.length; i++) { "
                "  const text = (rows[i].textContent || '').trim().toLowerCase(); "
                "  if (text.includes(target)) { "
                "    const el = rows[i]; "
                "    // Check for buttons, links inside "
                "    const btns = Array.from(el.querySelectorAll('button, a, [role=button]')).map(b => ({ tag: b.tagName, href: b.href || null, text: (b.textContent || '').trim().substring(0, 50) })); "
                "    // Check for __menu-item siblings "
                "    const menuItems = Array.from(document.querySelectorAll('[class*=\\\"__menu-item\\\"]')).filter(m => m.textContent.toLowerCase().includes(target)).map(m => ({ tag: m.tagName, cls: (m.className || '').substring(0, 80), html: m.outerHTML.substring(0, 500) })); "
                "    return { buttons: btns, menuItems }; "
                "  } "
                "} "
                "return null; }",
                "AUDiaGentic",
            )
            if clickable:
                print(f"\nClickable elements:\n{clickable.get('buttons', [])}")
                print(f"\nMenu items:\n{clickable.get('menuItems', [])}")

            break

    await c.stop()

if __name__ == "__main__":
    asyncio.run(main())
