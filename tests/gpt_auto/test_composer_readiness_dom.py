"""Exercise submission JavaScript in an isolated headless page, never GPT."""
import pytest
from playwright.async_api import async_playwright

from audiagentic.components.providers.adapters.gpt_auto.gpt_auto_cdp import (
    ComposerSubmissionTimeout, GptAutoCdpBrowserController,
)
from audiagentic.components.providers.adapters.gpt_auto.cdp.cdp_browser import CdpPageRef


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("paragraphs", [False, True])
async def test_real_dom_readiness_and_exact_prompt(monkeypatch, mismatch, paragraphs):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content('''<div id="prompt-textarea" contenteditable="true"></div>
                <button data-testid="send-button" disabled>Send</button>
                <script>
                window.clicks=0; window.insertions=0;
                const editor=document.querySelector('#prompt-textarea');
                const button=document.querySelector('button');
                button.onclick=()=>window.clicks++;
                const exec=document.execCommand.bind(document);
                document.execCommand=(...args)=>{window.insertions++; return exec(...args)};
                </script>''')
            await page.evaluate('''({mismatch,paragraphs})=>{
                if(paragraphs) {
                    const original=document.execCommand;
                    document.execCommand=(command,ui,text)=>{
                        window.insertions++;
                        const editor=document.querySelector('#prompt-textarea');
                        editor.replaceChildren(...text.split('\\n').map(line=>{
                            const p=document.createElement('p');
                            if(line) p.textContent=line; else p.append(document.createElement('br'));
                            return p;
                        }));
                        return true;
                    };
                }
                document.querySelector('#prompt-textarea').addEventListener('input',()=>{
                    setTimeout(()=>{
                        if(mismatch) document.querySelector('#prompt-textarea').textContent='wrong text';
                        document.querySelector('button').disabled=false;
                    },350);
                },{once:true});
            }''', {"mismatch": mismatch, "paragraphs": paragraphs})
            controller = GptAutoCdpBrowserController(object())
            async def evaluate(ref, function, argument=None):
                return await page.evaluate(function, argument)
            monkeypatch.setattr(controller, "evaluate", evaluate)
            prompt = 'Review the repository.\n\nPreserve case and punctuation.\n' + ('Real content, not a repeated-character task. ' * 100)
            if mismatch:
                with pytest.raises(ComposerSubmissionTimeout) as raised:
                    await controller.submit(CdpPageRef('test', 'test'), prompt, timeout=0.8)
                assert raised.value.send_attempted is False
            else:
                result = await controller.submit(CdpPageRef('test', 'test'), prompt, timeout=3)
                assert result['sendButtonClicked'] is True
            assert await page.evaluate('window.clicks') == (0 if mismatch else 1)
            assert await page.evaluate('window.insertions') == 1
        finally:
            await browser.close()
