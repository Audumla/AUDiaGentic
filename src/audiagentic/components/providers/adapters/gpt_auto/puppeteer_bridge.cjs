"use strict";

const readline = require("readline");
const puppeteer = require("puppeteer-core");

let browser = null;
let nextPage = 1;
const pages = new Map();

function send(value) { process.stdout.write(JSON.stringify(value) + "\n"); }
function bindPage(page) {
  for (const [handle, known] of pages) if (known === page) return handle;
  const handle = `page-${nextPage++}`;
  pages.set(handle, page);
  page.once("close", () => { pages.delete(handle); send({event:"page_closed", pageHandle:handle}); });
  page.once("error", () => send({event:"page_crashed", pageHandle:handle}));
  return handle;
}
function requirePage(handle) {
  const page = pages.get(handle);
  if (!page || page.isClosed()) throw new Error("unknown or closed page handle");
  return page;
}

async function snapshot(page, signalSpecs = []) {
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      return await page.evaluate((signalSpecs) => {
        const shown = (el) => {
          if (!el) return false;
          const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden" && s.opacity !== "0";
        };
        const users = Array.from(document.querySelectorAll('[data-message-author-role="user"]'));
        const assistants = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
          .filter(e => !(e.getAttribute("data-message-id") || "").startsWith("request-placeholder-request-"));
        const latestAssistant = assistants.length ? assistants[assistants.length - 1] : null;
        const assistantTurn = latestAssistant && (latestAssistant.closest("article") || latestAssistant.parentElement?.parentElement);
        const domSignals = {};
        for (const spec of signalSpecs) {
          const root = spec.scope === "latest-assistant-turn" ? assistantTurn : document;
          domSignals[spec.name] = !!root && spec.selectors.some(selector =>
            Array.from(root.querySelectorAll(selector)).some(el => {
              if (spec.visible && !shown(el)) return false;
              const fragments = spec.textContainsAny || [];
              if (!fragments.length) return true;
              const content = (el.innerText || el.textContent || "").toLowerCase();
              return fragments.some(fragment => content.includes(String(fragment).toLowerCase()));
            })
          );
        }
        const text = (list) => list.length ? ((list[list.length - 1].innerText || "").trim() || null) : null;
        const selectors = '[data-testid="stop-button"], [data-testid="stop-generating"], .result-streaming, .result-thinking, [aria-busy="true"]';
        const generating = Array.from(document.querySelectorAll(selectors)).some(shown);
        const composer = document.querySelector(".ProseMirror");
        return {
          url: location.href, composerPresent: !!composer,
          composerEditable: !!composer && composer.isContentEditable && !composer.hasAttribute("disabled"),
          userCount: users.length, assistantCount: assistants.length,
          latestAssistantId: latestAssistant?.getAttribute("data-message-id") || null,
          latestUserText: text(users), latestAssistantText: text(assistants), generating, domSignals,
          errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
        };
      }, signalSpecs);
    } catch (error) {
      const message = String(error && error.message || error).toLowerCase();
      if (attempt === 4 || (!message.includes("context") && !message.includes("detached"))) throw error;
      await new Promise(resolve => setTimeout(resolve, 200 * (attempt + 1)));
    }
  }
}

async function handle(method, params) {
  switch (method) {
    case "connect": {
      const common = {defaultViewport:null, protocolTimeout:params.protocolTimeoutMs};
      try {
        browser = await puppeteer.connect({...common, browserURL:params.browserURL});
      } catch (error) {
        if (!params.browserWSEndpoint) throw error;
        browser = await puppeteer.connect({...common, browserWSEndpoint:params.browserWSEndpoint});
      }
      browser.once("disconnected", () => send({event:"browser_disconnected"}));
      for (const page of await browser.pages()) bindPage(page);
      return {connected:true};
    }
    case "disconnect": if (browser) await browser.disconnect(); browser = null; pages.clear(); return {disconnected:true};
    case "list_pages": return Promise.all(Array.from(pages, async ([pageHandle,page]) => ({pageHandle,url:await page.url(),title:await page.title()})));
    case "create_page": { const page = await browser.newPage(); return {pageHandle:bindPage(page)}; }
    case "create_window_page": { const page = await browser.newPage(); return {pageHandle:bindPage(page)}; }
    case "close_page": await requirePage(params.pageHandle).close(); return {closed:true};
    case "navigate": await requirePage(params.pageHandle).goto(params.url, {waitUntil:"domcontentloaded",timeout:params.timeoutMs}); return {url:requirePage(params.pageHandle).url()};
    case "find_project_url": {
      const p=requirePage(params.pageHandle);
      const wanted=String(params.projectName || "").trim().toLowerCase();
      if (!wanted) throw new Error("project name is required");
      await p.waitForFunction((name) => {
        const normalize = value => String(value || "").replace(/\s+/g, " ").trim();
        const wantedName = normalize(name).toLowerCase();
        return Array.from(document.querySelectorAll('[role="row"]')).some(row =>
          [
            ...Array.from(row.querySelectorAll('[role="cell"], [role="gridcell"]')).map(cell => cell.innerText || cell.textContent),
            ...(row.innerText || row.textContent || "").split(/\r?\n/),
          ].map(normalize).some(value => value.toLowerCase() === wantedName)
        );
      }, {timeout:params.timeoutMs}, params.projectName);
      const rows = await p.$$('[role="row"]');
      let matchedRow = null;
      let matchedName = null;
      for (const row of rows) {
        const texts = await row.evaluate(element => {
          const normalize = value => String(value || "").replace(/\s+/g, " ").trim();
          return [
            ...Array.from(element.querySelectorAll('[role="cell"], [role="gridcell"]')).map(cell => cell.innerText || cell.textContent),
            ...(element.innerText || element.textContent || "").split(/\r?\n/),
          ].map(normalize).filter(Boolean);
        });
        const exact = texts.find(value => value.toLowerCase() === wanted);
        if (exact) { matchedRow = row; matchedName = exact; break; }
      }
      if (!matchedRow) throw new Error(`ChatGPT project not found: ${params.projectName}`);
      await p.bringToFront();
      const box = await matchedRow.boundingBox();
      if (!box) throw new Error(`ChatGPT project row is not visible: ${params.projectName}`);
      await p.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await p.waitForFunction(() => /\/g\/g-p-[^/]+/.test(location.pathname), {timeout:params.timeoutMs});
      return {url:p.url(), name:matchedName};
    }
    case "page_url": return {url:requirePage(params.pageHandle).url()};
    case "keep_page_active": { const p=requirePage(params.pageHandle); await p.bringToFront(); await p.evaluate(() => { window.focus(); document.dispatchEvent(new Event("visibilitychange")); }); return {ok:true}; }
    case "snapshot": return snapshot(requirePage(params.pageHandle), params.signals || []);
    case "submit_prompt": {
      const p=requirePage(params.pageHandle);
      await p.waitForSelector(".ProseMirror", {visible:true, timeout:params.timeoutMs});
      const stillGenerating = await p.$('[data-testid="stop-button"], [data-testid="stop-generating"]');
      if (stillGenerating) throw new Error("provider is still generating; refusing follow-up submission");
      const editor=await p.$(".ProseMirror");
      // execCommand(insertText) is one synchronous contenteditable mutation
      // and emits the input event ProseMirror expects. It avoids delayed
      // keyboard events and transient per-command CDP sessions, either of
      // which can corrupt or stall a follow-up. Enter is forbidden until the
      // exact DOM text has been read back.
      const typedText = await editor.evaluate((el, text) => {
        el.focus();
        const selection = window.getSelection();
        selection.removeAllRanges();
        const range = document.createRange();
        range.selectNodeContents(el);
        selection.addRange(range);
        if (!document.execCommand("insertText", false, text)) {
          throw new Error("browser rejected atomic composer insertion");
        }
        return (el.innerText || el.textContent || "").trim();
      }, params.text);
      const normalize = value => String(value || "").replace(/\s+/g, " ").trim();
      if (normalize(typedText) !== normalize(params.text)) {
        throw new Error("composer text verification failed; prompt was not submitted");
      }
      await p.keyboard.press("Enter");
      return {actionComplete:true, typedText};
    }
    case "stop_generation": return requirePage(params.pageHandle).evaluate(() => { const b=document.querySelector('[data-testid="stop-button"], [data-testid="stop-generating"]'); if(b){b.click();return true;} return false; });
    default: throw new Error(`unknown method: ${method}`);
  }
}

const rl = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
rl.on("line", line => {
  let msg; try { msg=JSON.parse(line); } catch(error) { return send({error:String(error)}); }
  Promise.resolve(handle(msg.method, msg.params || {})).then(result => send({id:msg.id,result}), error => send({id:msg.id,error:String(error && error.message || error)}));
});
