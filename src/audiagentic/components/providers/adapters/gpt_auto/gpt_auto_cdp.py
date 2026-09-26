"""ChatGPT-specific browser operations over the generic CDP controller."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from .cdp.bridge import PythonCdpBridge
from .cdp.cdp_browser import CdpBrowserController, CdpPageRef, CdpWindowBounds
from .cdp.client import CdpError
from .urls import parse_project_id

logger = logging.getLogger(__name__)

_CHATGPT_HOME_URL = "https://chatgpt.com/"

_CLICK_PROJECTS_TAB_FN = r"""() => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  };
  const label = element => normalize(
    element.getAttribute('aria-label') || element.innerText ||
    element.textContent || element.getAttribute('title')
  );
  const node = Array.from(document.querySelectorAll('*')).find(
    element => visible(element) && label(element) === 'projects'
  );
  if (!node) return false;
  const candidate = node.closest('a, button, [role], [tabindex]') || node;
  candidate.click();
  return true;
}"""

_CLICK_PROJECT_NAME_FN = r"""(name) => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = normalize(name);
  const visible = element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  };
  const label = element => normalize(
    element.getAttribute('aria-label') || element.innerText ||
    element.textContent || element.getAttribute('title')
  );
  const selectors = [
    '[data-testid*="project" i] a',
    '[data-testid*="project" i] button',
    '[data-project-name]',
    'a[href*="/g/"]',
    'button',
    '[role="link"]',
    '[role="button"]',
  ];
  for (const selector of selectors) {
    const candidate = Array.from(document.querySelectorAll(selector)).find(
      element => visible(element) && label(element) === wanted
    );
    if (candidate) {
      candidate.click();
      return true;
    }
  }
  const node = Array.from(document.querySelectorAll('*')).find(
    element => visible(element) && label(element) === wanted
  );
  if (node) {
    const candidate = node.closest('a, button, [role], [tabindex]') || node;
    candidate.click();
    return true;
  }
  return false;
}"""

_CLICK_PROJECT_NEW_CHAT_FN = r"""(name) => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = normalize(name);
  const row = Array.from(document.querySelectorAll('[data-project-row="true"]')).find(
    candidate => Array.from(candidate.querySelectorAll('span')).some(
      element => normalize(element.textContent) === wanted
    )
  );
  if (!row) return false;
  const button = Array.from(row.querySelectorAll('button')).find(
    candidate => normalize(candidate.getAttribute('aria-label')) === 'start new chat in project'
      && candidate.getClientRects().length
  );
  if (!button) return false;
  button.click();
  return true;
}"""


class ComposerSubmissionTimeout(TimeoutError):
    """Preserve whether a send-capable operation was dispatched before timeout."""

    def __init__(self, *, send_attempted: bool, stage: str) -> None:
        super().__init__(f"composer operation timed out during {stage}")
        self.send_attempted = send_attempted
        self.stage = stage

_SNAPSHOT_FN = r"""
(signalSpecs) => {
  const shown = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" &&
      s.visibility !== "hidden" && s.opacity !== "0";
  };
  const progressShown = (el) => {
    if (!shown(el)) return false;
    let depth = 0;
    for (let parent = el.parentElement; parent && depth < 64; parent = parent.parentElement, depth++) {
      const style = getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden" || Number.parseFloat(style.opacity || "1") === 0) return false;
    }
    if (el.parentElement && depth >= 64) return false;
    return true;
  };
  // GP08 slice 1: walk user+assistant DOM nodes together in ONE pass, in
  // true document order, instead of two separately-filtered
  // querySelectorAll calls. Two role-specific passes cannot tell you
  // whether a user message landed before or after a given assistant
  // message when both appear between polls -- exactly the ordering the
  // GP08 correlation boundary rule needs. This also fixes a latent id/text
  // desync: collecting ids and texts via separately-filtered passes let an
  // empty/transient text node fall out of one array but not the other.
  const allRoleNodes = Array.from(document.querySelectorAll('[data-message-author-role="user"], [data-message-author-role="assistant"]'));
  const usingFallbackMessages = allRoleNodes.length === 0;
  // The labelled fallback renderer can mount a live "Thinking"/tool block
  // after the latest user block before it assigns the eventual
  // `ChatGPT said:` label or assistant message id. Keep the block inventory
  // outside the message-id extraction so that the live block can be used as
  // the request-owned observation root during that gap.
  const fallbackBlocks = usingFallbackMessages
    ? Array.from(document.querySelectorAll('.block-BQZwFn'))
    : [];
  const fallbackBlockLabel = block => String(
    block.querySelector('h4.sr-only')?.innerText || ''
  ).trim().toLowerCase();
  const latestFallbackUserBlock = usingFallbackMessages
    ? fallbackBlocks.slice().reverse().find(block => fallbackBlockLabel(block) === 'you said:') || null
    : null;
  const latestFallbackUserIndex = latestFallbackUserBlock
    ? fallbackBlocks.indexOf(latestFallbackUserBlock)
    : -1;
  const latestFallbackActivityBlock = latestFallbackUserIndex >= 0
    ? fallbackBlocks.slice(latestFallbackUserIndex + 1).reverse()[0] || null
    : null;
  const latestFallbackAssistantBlock = usingFallbackMessages
    ? fallbackBlocks.slice().reverse().find(block => fallbackBlockLabel(block) === 'chatgpt said:') || null
    : null;
  const fallbackHasUnansweredPrompt = Boolean(
    latestFallbackUserBlock &&
    (!latestFallbackAssistantBlock ||
      fallbackBlocks.indexOf(latestFallbackUserBlock) > fallbackBlocks.indexOf(latestFallbackAssistantBlock))
  );
  const messageEntries = [];
  if (allRoleNodes.length) {
    for (const el of allRoleNodes) {
      const role = el.getAttribute("data-message-author-role");
      if (role === "assistant" && (el.getAttribute("data-message-id") || "").startsWith("request-placeholder-request-")) continue;
      messageEntries.push({role, el, messageId: el.getAttribute("data-message-id") || null});
    }
  } else {
    // The current ChatGPT renderer (2026-09) replaced data-message-author-role
    // with labelled turn blocks. Keep the same ordered prompt/response model
    // and derive bounded synthetic IDs from the stable DOM order when the new
    // renderer does not expose message UUIDs.
    let userIndex = 0;
    let assistantIndex = 0;
    for (const block of fallbackBlocks) {
      const label = fallbackBlockLabel(block);
      if (label === 'you said:') {
        const content = block.querySelector('[data-user-message-bubble="true"]') || block;
        const messageId = content.getAttribute('data-chatgpt-search-message-ids') || `fallback-user-${userIndex++}`;
        messageEntries.push({role: 'user', el: content, messageId});
      } else if (label === 'chatgpt said:') {
        messageEntries.push({role: 'assistant', el: block, messageId: `fallback-assistant-${assistantIndex++}`});
      }
    }
  }
  const userMessageEntries = messageEntries.filter(m => m.role === "user");
  const assistantMessageEntries = messageEntries.filter(m => m.role === "assistant");
  const users = userMessageEntries.map(m => m.el);
  const assistants = assistantMessageEntries.map(m => m.el);
  const latestAssistantRef = assistantMessageEntries.length
    ? assistantMessageEntries[assistantMessageEntries.length - 1]
    : null;
  const latestAssistant = latestAssistantRef?.el || null;
  // During a streamed response ChatGPT can render connector/tool rows inside
  // the current `.agent-turn` before it materializes the assistant message
  // node (`data-message-author-role="assistant"`).  The old implementation
  // made the assistant node the only anchor, which reduced tool activity to
  // an empty set for the whole early streaming phase.  Prefer the assistant
  // anchor when it exists, but retain the latest semantic turn as a
  // streaming-safe fallback so activity can renew the gateway lease from the
  // first visible tool row.
  const agentTurns = Array.from(document.querySelectorAll('.agent-turn'));
  const latestAgentTurn = agentTurns.length ? agentTurns[agentTurns.length - 1] : null;
  // GP41 (2026-08-17): .agent-turn is a semantically meaningful, real
  // wrapper class confirmed present (via closest()) on two independent
  // live conversations tonight -- prefer it over the old fixed-depth
  // parentElement.parentElement walk, which only worked by coincidence
  // for the specific DOM depths tested and has no structural guarantee
  // for a differently-nested turn. <article> has never been observed to
  // exist in current ChatGPT markup; kept as a legacy fallback only.
  // Prefer the fallback block mounted after the latest prompt. Falling back
  // to the previous assistant wrapper here makes a live pre-assistant
  // "Thinking" turn look idle/complete and assigns its DOM digest to the
  // previous prompt.
  const assistantTurn = usingFallbackMessages
    ? (latestFallbackActivityBlock || (latestAssistant ? (
        latestAssistant.closest("[data-turn-key]") ||
        latestAssistant.closest(".agent-turn") ||
        latestAssistant.closest("article") ||
        latestAssistant.parentElement?.parentElement
      ) : null))
    : (latestAssistant ? (
        latestAssistant.closest("[data-turn-key]") ||
        latestAssistant.closest(".agent-turn") ||
        latestAssistant.closest("article") ||
        latestAssistant.parentElement?.parentElement
      ) : latestAgentTurn);
  // Progress rows are rendered as visible, short-lived status blocks in the
  // assistant turn. They may say "Inspected ...", "Fetching ...",
  // "Analyzing ...", or "Evaluated ..." without changing the assistant
  // message text. Return only a bounded kind/digest projection: raw paths,
  // tool names, arguments, and results never cross the CDP boundary.
  const normalizeProgress = value => String(value || "").replace(/\s+/g, " ").trim();
  const progressKind = (value, structural = false) => {
    const text = normalizeProgress(value).toLowerCase();
    if (!text) return null;
    const prefixes = [
      ["inspected", "inspected"],
      ["fetching", "fetching"],
      ["analyzing", "analyzing"],
      ["analysing", "analyzing"],
      ["evaluated", "evaluated"],
      ["thinking", "thinking"]
    ];
    for (const [prefix, kind] of prefixes) {
      if (text === prefix || text.startsWith(prefix + " ") || text.startsWith(prefix + ".") || text.startsWith(prefix + "…")) return kind;
    }
    if (structural) {
      if (text.includes("called tool")) return "called-tool";
      if (text.includes("talked to app")) return "talked-to-app";
      if (text.includes("searching the web") || text.includes("search the web") || text.includes("web search")) return "searching-web";
      if (text.includes("read resource") || text.includes("reading resource")) return "read-resource";
    }
    return null;
  };
  const lexicalKinds = new Set(["inspected", "fetching", "analyzing", "evaluated", "thinking"]);
  const progressDigest = value => {
    const text = normalizeProgress(value).slice(0, 4096);
    let a = 0x811c9dc5 >>> 0;
    let b = 0x9e3779b9 >>> 0;
    for (let i = 0; i < text.length; i++) {
      const code = text.charCodeAt(i);
      a = Math.imul((a ^ code) >>> 0, 0x01000193) >>> 0;
      b = Math.imul((b ^ code) >>> 0, 0x85ebca6b) >>> 0;
    }
    return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
  };
  const progressDigestParts = parts => {
    let a = 0x811c9dc5 >>> 0;
    let b = 0x9e3779b9 >>> 0;
    for (const part of parts) {
      const text = String(part);
      for (let i = 0; i < text.length; i++) {
        const code = text.charCodeAt(i);
        a = Math.imul((a ^ code) >>> 0, 0x01000193) >>> 0;
        b = Math.imul((b ^ code) >>> 0, 0x85ebca6b) >>> 0;
      }
      a = Math.imul((a ^ 0x1e) >>> 0, 0x01000193) >>> 0;
      b = Math.imul((b ^ 0x1e) >>> 0, 0x85ebca6b) >>> 0;
    }
    return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
  };
  const structuralProgressSelector = [
    '[class~="group/tool-message"]',
    '[data-testid*="tool" i]',
    '[data-testid*="connector" i]',
    '[data-testid*="progress" i]',
    '[data-testid*="citation" i]',
    '[data-testid="writing-block-container"]',
    'table',
    '[role="status"]',
    '[aria-live="polite"]',
    '[aria-live="assertive"]',
    '[aria-valuenow]',
    '[aria-valuetext]',
    '[data-phase]',
    '[data-progress]'
  ].join(",");
  const structuralKind = node => {
    if (node.matches('[data-testid="writing-block-container"]')) return "dom-materialization";
    if (node.matches('[data-testid*="citation" i]')) return "dom-citation";
    if (node.matches("table")) return "dom-table";
    if (node.matches('[data-testid*="connector" i]')) return "dom-connector";
    if (node.matches('[class~="group/tool-message"], [data-testid*="tool" i]')) return "dom-tool-result";
    if (node.matches('[role="status"], [aria-live="polite"], [aria-live="assertive"]')) return "dom-status";
    if (node.matches('[data-testid*="progress" i], [aria-valuenow], [aria-valuetext], [data-phase], [data-progress]')) return "dom-progress";
    return null;
  };
  const semanticAttrs = [
    "role", "data-testid", "aria-label", "aria-busy", "aria-expanded",
    "aria-valuenow", "aria-valuetext", "data-state", "data-status",
    "data-phase", "data-progress"
  ];
  const boundedScalarMaterial = value => {
    const raw = String(value || "");
    const sample = raw.length > 1024 ? raw.slice(0, 512) + " " + raw.slice(-512) : raw;
    const text = normalizeProgress(sample);
    return [String(raw.length), text.slice(0, 256), text.slice(-256)].join("\x1d");
  };
  const excludedByLexicalRoot = (element, root, excludedRoots) => {
    if (!excludedRoots) return false;
    let current = element;
    for (let depth = 0; current && depth < 64; depth++, current = current.parentElement) {
      if (current === root) return false;
      if (excludedRoots.has(current)) return true;
    }
    return null;
  };
  const childContainsCanonicalLexical = (child, canonicalLexicalRoots) => {
    for (const root of canonicalLexicalRoots) {
      if (child === root || child.contains(root)) return true;
    }
    return false;
  };
  const boundedTextForKind = node => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const parts = [];
    const maxMaterial = 2048;
    let materialLength = 0;
    let visited = 0;
    let textNode;
    while ((textNode = walker.nextNode())) {
      visited += 1;
      if (visited > 256) return null;
      if (progressShown(textNode.parentElement) && materialLength < maxMaterial) {
        // This channel is only for lexical classification. Hashing uses the
        // separate fixed-size visibleTextDigest channel below.
        const raw = String(textNode.nodeValue || "");
        const sampled = raw.length > 1024 ? raw.slice(0, 512) + " " + raw.slice(-512) : raw;
        const piece = normalizeProgress(sampled);
        const remaining = maxMaterial - materialLength;
        parts.push(piece.slice(0, remaining));
        materialLength += Math.min(piece.length, remaining);
      }
    }
    return parts.join(" ");
  };
  const visibleTextDigest = (node, excludedRoots = null) => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const parts = ["visible-text-v1"];
    let visited = 0;
    let included = 0;
    let textNode;
    while ((textNode = walker.nextNode())) {
      visited += 1;
      if (visited > 256) return null;
      if (!progressShown(textNode.parentElement)) continue;
      const excluded = excludedByLexicalRoot(textNode.parentElement, node, excludedRoots);
      if (excluded === null) return null;
      if (excluded) continue;
      const raw = String(textNode.nodeValue || "");
      parts.push(String(raw.length));
      parts.push(progressDigest(boundedScalarMaterial(raw)));
      included += 1;
    }
    // Hidden text participates in the traversal budget, but not in the
    // digest. This keeps hidden mutation/insertion/removal inert while still
    // failing closed when an oversized hidden subtree crosses the limit.
    parts.push(String(included));
    return progressDigestParts(parts);
  };
  const attributeDigest = (node, name) => progressDigest(
    boundedScalarMaterial(node.getAttribute(name))
  );
  const attributeMaterial = node => semanticAttrs
    .map(name => `${name}=${attributeDigest(node, name)}`)
    .join("\x1d");
  const visibleChildCount = (node, excludedRoots = null, lexicalCarriers = null, canonicalLexicalRoots = []) => {
    let visited = 0;
    let visible = 0;
    for (let child = node.firstElementChild; child; child = child.nextElementSibling) {
      visited += 1;
      if (visited > 256) return null;
      if (!progressShown(child)) continue;
      const excluded = excludedByLexicalRoot(child, node, excludedRoots);
      if (excluded === null) return null;
      if (lexicalCarriers?.has(child) || childContainsCanonicalLexical(child, canonicalLexicalRoots)) continue;
      if (!excluded) visible += 1;
    }
    return visible;
  };
  const semanticNodeDigest = (node, excludedRoots = null, lexicalCarriers = null, canonicalLexicalRoots = []) => {
    const textDigest = visibleTextDigest(node, excludedRoots);
    if (textDigest === null) return null;
    const childCount = visibleChildCount(node, excludedRoots, lexicalCarriers, canonicalLexicalRoots);
    if (childCount === null) return null;
    return progressDigest([
      String(node.tagName || ""),
      attributeMaterial(node),
      String(childCount),
      textDigest
    ].join("\x1c"));
  };
  const semanticStateDigest = (node, excludedRoots = null, lexicalCarriers = null, canonicalLexicalRoots = []) => {
    const semanticSelector = [
      "[role]", "[data-testid]", "[aria-busy]", "[aria-expanded]",
      "[aria-valuenow]", "[aria-valuetext]", "[data-state]", "[data-status]",
      "[data-phase]", "[data-progress]", "tr", "td", "th", "a[href]",
      "canvas", "svg", "img"
    ].join(",");
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT);
    const descendants = [];
    let visited = 0;
    let descendant;
    while ((descendant = walker.nextNode())) {
      visited += 1;
      if (visited > 256) return null;
      if (!progressShown(descendant)) continue;
      const excluded = excludedByLexicalRoot(descendant, node, excludedRoots);
      if (excluded === null) return null;
      if (!excluded && descendant.matches(semanticSelector)) descendants.push(descendant);
    }
    const selected = descendants.slice(0, 32);
    const tail = descendants.slice(-32);
    const selectedNodes = [...selected, ...tail.filter(child => !selected.includes(child))];
    // Every contribution is fixed-size; the final aggregate is therefore
    // intrinsically below progressDigest's input bound.
    const rootDigest = semanticNodeDigest(node, excludedRoots, lexicalCarriers, canonicalLexicalRoots);
    const nodeDigests = selectedNodes.map(child => semanticNodeDigest(child, excludedRoots, lexicalCarriers, canonicalLexicalRoots));
    if (rootDigest === null || nodeDigests.some(digest => digest === null)) return null;
    return progressDigest([
      "semantic-state-v2",
      rootDigest,
      String(descendants.length),
      ...nodeDigests
    ].join("\x1e"));
  };
  // ChatGPT frequently mutates a current agent turn without changing the
  // assistant text, known tool labels, or one of the configured DOM signals.
  // Keep a bounded structural/text digest as a final activity channel.  It
  // is a digest only: no provider payload crosses CDP, and truncation is
  // represented explicitly so a large DOM cannot silently look unchanged.
  const activityStateDigest = node => {
    if (!node) return null;
    const parts = ["dom-activity-v1", String(node.tagName || ""), attributeMaterial(node)];
    const elementWalker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT);
    const firstNodes = [];
    const lastNodes = [];
    let elementCount = 0;
    let element;
    while ((element = elementWalker.nextNode())) {
      if (!progressShown(element)) continue;
      elementCount += 1;
      const material = [
        String(element.tagName || ""),
        attributeMaterial(element),
        boundedScalarMaterial(element.innerText || element.textContent || "")
      ].join("\x1d");
      if (firstNodes.length < 32) firstNodes.push(material);
      lastNodes.push(material);
      if (lastNodes.length > 32) lastNodes.shift();
    }
    parts.push("elements=" + String(elementCount), ...firstNodes, ...lastNodes);
    const textWalker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const firstText = [];
    const lastText = [];
    let textCount = 0;
    let textLength = 0;
    let textNode;
    while ((textNode = textWalker.nextNode())) {
      if (!progressShown(textNode.parentElement)) continue;
      const raw = String(textNode.nodeValue || "");
      textCount += 1;
      textLength += raw.length;
      const material = boundedScalarMaterial(raw);
      if (firstText.length < 32) firstText.push(material);
      lastText.push(material);
      if (lastText.length > 32) lastText.shift();
    }
    parts.push("texts=" + String(textCount), "text-length=" + String(textLength), ...firstText, ...lastText);
    return progressDigestParts(parts);
  };
  const MAX_PROGRESS_TURNS = 8;
  const MAX_PROGRESS_VISIBLE_NODES = 2048;
  const MAX_PROGRESS_CANDIDATES = 256;
  const MAX_PROGRESS_OWNER_USERS = MAX_PROGRESS_TURNS * 2;
  const userEntries = messageEntries.filter(entry => entry.role === "user" && entry.messageId);
  const progressUserEntries = userEntries.slice(-MAX_PROGRESS_OWNER_USERS);
  let ownerUserIndex = progressUserEntries.length - 1;
  const ownerPromptFor = node => {
    while (ownerUserIndex >= 0) {
      const entry = progressUserEntries[ownerUserIndex];
      if (entry.el === node || entry.el.contains(node)) return entry.messageId;
      const relation = entry.el.compareDocumentPosition(node);
      if (relation & Node.DOCUMENT_POSITION_FOLLOWING) return entry.messageId;
      if (relation & Node.DOCUMENT_POSITION_PRECEDING) {
        ownerUserIndex -= 1;
        continue;
      }
      return null;
    }
    return null;
  };
  const ownerPromptIdFor = node => {
    if (!node) return null;
    for (let index = progressUserEntries.length - 1; index >= 0; index--) {
      const entry = progressUserEntries[index];
      if (entry.el === node || entry.el.contains(node)) return entry.messageId;
      const relation = entry.el.compareDocumentPosition(node);
      if (relation & Node.DOCUMENT_POSITION_FOLLOWING) return entry.messageId;
    }
    return null;
  };
  const domActivityRoot = latestAgentTurn || assistantTurn;
  const domActivityDigest = activityStateDigest(domActivityRoot);
  const domActivityOwnerPromptMessageId = ownerPromptIdFor(domActivityRoot);
  const progressBlocks = [];
  const progressTurns = agentTurns.length
    ? agentTurns
    : (assistantTurn ? [assistantTurn] : []);
  let inspectedNodes = 0;
  let inspectedCandidates = 0;
  // Historical turns can contain persistent tables and tool cards. Inspect
  // newest turns first and stop at fixed turn/node/candidate budgets.
  for (let turnIndex = progressTurns.length - 1, turnsInspected = 0;
       turnIndex >= 0 && turnsInspected < MAX_PROGRESS_TURNS && progressBlocks.length < 128;
       turnIndex--, turnsInspected++) {
    const turn = progressTurns[turnIndex];
    const ownerPromptMessageId = ownerPromptFor(turn);
    if (!ownerPromptMessageId) continue;
    const candidates = [];
    let ownerAssistantMessageId = null;
    const walker = document.createTreeWalker(turn, NodeFilter.SHOW_ELEMENT);
    let node;
    let turnComplete = true;
    while ((node = walker.nextNode())) {
      inspectedNodes += 1;
      if (inspectedNodes > MAX_PROGRESS_VISIBLE_NODES) {
        turnComplete = false;
        break;
      }
      if (!progressShown(node)) continue;
      if (node.matches('[data-message-author-role="assistant"]')) {
        const id = node.getAttribute("data-message-id") || null;
        if (id && !id.startsWith("request-placeholder-request-")) {
          if (ownerAssistantMessageId && ownerAssistantMessageId !== id) {
            ownerAssistantMessageId = null;
            turnComplete = false;
            break;
          }
          ownerAssistantMessageId = id;
        }
      }
      const structural = node.matches(structuralProgressSelector);
      // Structural identity wins for structural nodes. Their visible text may
      // contain a lexical child, but the parent must remain an independent
      // candidate so changes to tool/connector/status state are observable.
      const kind = structuralKind(node) || progressKind(boundedTextForKind(node), structural);
      if (!kind) continue;
      if (inspectedCandidates >= MAX_PROGRESS_CANDIDATES) {
        turnComplete = false;
        break;
      }
      inspectedCandidates += 1;
      candidates.push({node, kind});
    }
    if (!turnComplete) break;
    // Deduplicate nested lexical labels only. Structural candidates remain
    // independent so a changing tool/connector/status parent is observable
    // even when it contains a lexical child such as "Fetching source".
    const canonicalCandidates = [
      ...candidates.filter(candidate => !lexicalKinds.has(candidate.kind)),
      ...candidates.filter(candidate =>
        lexicalKinds.has(candidate.kind) && !candidates.some(child =>
          child !== candidate && lexicalKinds.has(child.kind) && candidate.node.contains(child.node)
        )
      )
    ];
    const canonicalLexicalNodes = new WeakSet();
    const canonicalLexicalRoots = [];
    const lexicalCarrierNodes = new WeakSet();
    for (const candidate of candidates) {
      if (lexicalKinds.has(candidate.kind)) lexicalCarrierNodes.add(candidate.node);
    }
    for (const candidate of canonicalCandidates) {
      if (lexicalKinds.has(candidate.kind)) {
        canonicalLexicalNodes.add(candidate.node);
        canonicalLexicalRoots.push(candidate.node);
      }
    }
    for (const {node, kind} of canonicalCandidates) {
      if (progressBlocks.length >= 128) break;
      if (!progressShown(node) || node.closest('[data-message-author-role="user"]')) continue;
      const structural = !lexicalKinds.has(kind);
      const excludedRoots = structural ? canonicalLexicalNodes : null;
      const carriers = structural ? lexicalCarrierNodes : null;
      const roots = structural ? canonicalLexicalRoots : [];
      const digest = semanticStateDigest(node, excludedRoots, carriers, roots);
      if (!digest) continue;
      progressBlocks.push({
        ownerPromptMessageId: String(ownerPromptMessageId).slice(0, 256),
        ownerAssistantMessageId: ownerAssistantMessageId ? String(ownerAssistantMessageId).slice(0, 256) : null,
        kind,
        digest
      });
    }
  }
  // ChatGPT renders connector/tool work as bounded affordances such as
  // "Called tool", "Talked to App", "Searching the web", "Read resource",
  // and "Thinking" inside the current .agent-turn. These nodes often appear
  // while assistant text is unchanged and the stop/busy widget is absent, so
  // count only their stable labels as activity evidence. Do not return their
  // expanded contents, tool names, arguments, or results.
  const toolActivityCounts = {};
  const activityLabels = [
    ["talked to app", "talked-to-app"],
    ["called tool", "called-tool"],
    ["searching the web", "searching-web"],
    ["search the web", "searching-web"],
    ["web search", "searching-web"],
    ["read resource", "read-resource"],
    ["reading resource", "read-resource"],
    ["thinking", "thinking"]
  ];
  const knownLabel = (value) => {
    const label = (value || "").trim().toLowerCase();
    if (!label || label.length > 80) return null;
    for (const [needle, kind] of activityLabels) {
      if (label === needle) return kind;
    }
    return null;
  };
  const toolNodes = assistantTurn
    ? Array.from(new Set([
        ...assistantTurn.querySelectorAll(
          '[class~="group/tool-message"], [data-testid*="tool" i], [data-testid*="connector" i], ' +
          '[aria-label*="search" i], [aria-label*="resource" i]'
        ),
        // A few UI revisions render the affordance as an unadorned short
        // label. Include those exact-label nodes without scanning arbitrary
        // response prose as activity.
        ...Array.from(assistantTurn.querySelectorAll("*"))
          .filter(node => knownLabel(node.innerText || node.textContent || ""))
      ]))
    : [];
  for (const node of toolNodes) {
    const label = (node.innerText || node.textContent || "").trim().toLowerCase();
    let kind = null;
    for (const [needle, value] of activityLabels) {
      if (label.includes(needle)) { kind = value; break; }
    }
    if (!kind) kind = knownLabel(label);
    if (kind) toolActivityCounts[kind] = (toolActivityCounts[kind] || 0) + 1;
  }
  const domSignals = {};
  for (const spec of signalSpecs) {
    const root = spec.scope === "latest-assistant-turn" ? assistantTurn : document;
    // ChatGPT currently leaves `.streaming-animation` on completed assistant
    // messages.  It describes the renderer, not an active generation, so it
    // must never be allowed to make the provider appear busy during resume.
    const selectors = spec.name === "streaming-indicator"
      ? spec.selectors.filter(selector => selector !== ".streaming-animation")
      : spec.selectors;
    domSignals[spec.name] = !!root && selectors.some(selector =>
      Array.from(root.querySelectorAll(selector)).some(el => {
        if (spec.visible && !shown(el)) return false;
        const fragments = spec.textContainsAny || [];
        const exact = spec.textEqualsAny || [];
        const content = (el.innerText || el.textContent || "").trim();
        if (exact.length && exact.some(fragment => content === String(fragment).trim())) return true;
        if (!fragments.length) return !exact.length;
        const lowered = content.toLowerCase();
        return fragments.some(fragment => lowered.includes(String(fragment).toLowerCase()));
      })
    );
  }
  // Bind structural completion evidence to the assistant turn whose action
  // bar was inspected. A later unrelated turn must not complete an earlier
  // request merely because its controls are document-global.
  const terminalWitnessAssistantId = (
    domSignals["completion-control"] || domSignals["more-actions-menu"] ||
    domSignals["canvas-edit-control"] || domSignals["canvas-open-editor-control"]
  ) && !fallbackHasUnansweredPrompt ? (latestAssistantRef?.messageId || null) : null;
  // GP19: this bound was 20000, which is small enough that a genuinely
  // long real prompt/response can never satisfy exact-text correlation
  // matching even with otherwise-perfect DOM extraction (a distinct latent
  // bug from GP19's main Markdown-rendering finding). Raised well beyond
  // any realistic single ChatGPT message so it functions as a sanity
  // ceiling, not a correlation-breaking truncation. The deeper fix (a
  // correlation-specific fingerprint computed before any truncation,
  // separate from a bounded display/preview string) is part of GP19's
  // still-open shared prompt-correlation primitive work.
  const boundedText = (element) => ((element?.innerText || element?.textContent || "").trim()).slice(0, 200000) || null;
  // User messages are collapsible in the ChatGPT UI.  Reading the outer
  // message node includes the presentation controls ("Show more" /
  // "Show less"), which makes a durable prompt digest fail to match after a
  // resume even though the submitted text is unchanged.  Hash only the
  // message-content node when it exists.
  const userText = (element) => boundedText(
    element?.querySelector('[data-testid="collapsible-user-message-content"]') || element
  );
  // ChatGPT renders a standalone Markdown thematic break as an <hr>.  The
  // element is visible but contributes no characters to innerText, so retain
  // a second, user-only correlation representation when one is actually
  // present.  Visible text remains untouched for diagnostics and display;
  // correlationText is used only with the existing prompt fingerprint and
  // freshness/order/terminal proof gates.
  // ``innerText`` on a detached clone falls back to ``textContent`` in
  // Chromium, which drops the paragraph boundaries that are present in the
  // rendered user message.  Walk the cloned DOM instead so the correlation
  // representation preserves semantic line boundaries without depending on
  // layout being painted.  This is deliberately structural rather than a
  // general whitespace normalizer: prompt_fingerprint.py owns the bounded
  // Markdown/renderer tolerance after this extraction.
  const structuralText = (root) => {
    const blockTags = new Set([
      "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "DD", "DIV", "DL", "DT",
      "FIELDSET", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3", "H4",
      "H5", "H6", "HEADER", "LI", "MAIN", "NAV", "OL", "P", "PRE",
      "SECTION", "TABLE", "TR", "UL"
    ]);
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
      if (node.nodeType !== Node.ELEMENT_NODE) return "";
      const element = /** @type {Element} */ (node);
      if (element.getAttribute("data-markdown-copy") === "exclude") return "";
      if (element.matches("button, [role=button]")) return "";
      if (element.tagName === "BR") return "\n";
      let value = "";
      for (const child of element.childNodes) value += walk(child);
      if (blockTags.has(element.tagName) && !value.endsWith("\n")) value += "\n";
      return value;
    };
    return walk(root)
      .replace(/[ \t\f\v]+/g, " ")
      .replace(/[ ]*\n[ ]*/g, "\n")
      .replace(/\n+/g, "\n")
      .replace(/\n+$/, "")
      .trim();
  };
  const userCorrelation = (element) => {
    const source = element?.querySelector('[data-testid="collapsible-user-message-content"]') || element;
    if (!source) return {text: null, hrCount: 0};
    const clone = source.cloneNode(true);
    // The visible message node may contain presentation-only controls when a
    // long prompt is collapsed.  Remove those elements from the clone rather
    // than stripping their labels from the resulting string: a real prompt is
    // allowed to contain words such as "Show more".
    clone.querySelectorAll('button, [role="button"], [aria-label*="show more" i], [aria-label*="show less" i]').forEach(el => el.remove());
    clone.querySelectorAll('[aria-hidden="true"]').forEach(el => {
      if (String(el.innerText || el.textContent || "").trim() === "…") el.remove();
    });
    const hrs = Array.from(clone.querySelectorAll('hr'));
    for (const hr of hrs) hr.replaceWith(document.createTextNode("\n---\n"));
    const text = structuralText(clone).slice(0, 200000) || null;
    return {text, hrCount: hrs.length};
  };
  // generating mirrors the same per-signal-scoped evidence the domSignals
  // walk above already computes -- stop-control stays document-scoped (the
  // stop button lives outside the assistant-turn subtree, per
  // gpt-auto-defaults.yaml), while streaming/thinking/busy-indicator stay scoped to
  // latest-assistant-turn (so a stale class on an OLDER, already-finished
  // message elsewhere in a long conversation can't pin generating=true for
  // the CURRENT turn). Previously this was a second, always-document-wide
  // selector string that duplicated and drifted from the config-driven
  // signals (it was even missing button[aria-label*="stop" i] and
  // [data-busy="true"], both already covered by domSignals).
  const generating = !!(domSignals["stop-control"] || domSignals["streaming-indicator"] || domSignals["thinking-indicator"] || domSignals["busy-indicator"]);
  // GP35: a canvas/writing-block turn (seen live 2026-08-17) renders its
  // OWN .ProseMirror-based contenteditable inline in the conversation
  // history (data-testid="writing-block-container"), positioned BEFORE
  // the real chat composer in DOM order. A plain '.ProseMirror' query
  // matches that canvas editor instead of the real composer whenever any
  // canvas turn exists anywhere in the conversation -- live-reproduced as
  // a misdirected prompt submission. #prompt-textarea is the stable
  // conversation composer. A project landing page reached through the
  // sidebar's "New chat in <project>" control uses a contenteditable with an
  // aria-label instead. Prefer the id and otherwise accept only the
  // project-labelled editor so a canvas editor cannot receive the prompt.
  const composer = document.querySelector("#prompt-textarea") || Array.from(
    document.querySelectorAll('[contenteditable="true"]')
  ).find(el => /^(new chat in\b|ask chatgpt$|message chatgpt$)/i.test(String(el.getAttribute("aria-label") || "").trim()));
  // ChatGPT assigns a short conversation label in the left navigation.  The
  // label can be generated/renamed while a turn is running, so resolve it by
  // the active conversation URL on every snapshot rather than relying on the
  // document title (which describes the whole app).  Only return a bounded
  // visible anchor label; never expose sidebar markup or arbitrary URLs.
  const conversationId = (() => {
    try { return new URL(location.href).pathname.match(/\/c\/([^/?#]+)/)?.[1] || null; }
    catch (_) { return null; }
  })();
  const compactLabel = (value) => {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text && text.length <= 256 ? text : (text ? text.slice(0, 256) : null);
  };
  const conversationTitle = conversationId
    ? (() => {
        const anchors = Array.from(document.querySelectorAll("a[href]"));
        const matches = [];
        for (const anchor of anchors) {
          let href;
          try { href = new URL(anchor.href, location.origin); } catch (_) { continue; }
          if (href.pathname !== `/c/${conversationId}` &&
              !href.pathname.endsWith(`/c/${conversationId}`)) continue;
          matches.push({anchor, visible: shown(anchor)});
        }
        // A background tab may keep the matching sidebar anchor mounted but
        // not painted. Prefer a painted anchor when there are duplicates,
        // while still accepting the mounted one so title capture does not
        // require focusing the browser first.
        matches.sort((left, right) => Number(right.visible) - Number(left.visible));
        const genericLabel = /^(skip to content|chat history|open sidebar|close sidebar)$/i;
        for (const {anchor} of matches) {
          // Prefer the rendered sidebar text. Generic navigation anchors
          // (notably "Skip to content") can share the conversation URL in
          // ChatGPT's mounted DOM and are not conversation titles.
          const candidates = [
            compactLabel(anchor.innerText || anchor.textContent),
            compactLabel(anchor.getAttribute("aria-label"))
          ];
          for (const label of candidates) {
            if (label && !genericLabel.test(label)) return label;
          }
        }
        return null;
      })()
    : null;
  // GP08 slice 1: text extraction happens exactly once per node here, so
  // an id and its text can never desync between two independently-filtered
  // arrays the way the old users.map(...)/assistants.map(...) pairs could.
  const assistantText = (element) => {
    if (!element) return null;
    const clone = element.cloneNode(true);
    clone.querySelectorAll('h4.sr-only').forEach(el => el.remove());
    return boundedText(clone);
  };
  const messageRefs = messageEntries.map((m, sequence) => ({
    role: m.role,
    messageId: m.messageId,
    text: m.role === "user" ? userText(m.el) : assistantText(m.el),
    ...(m.role === "user" ? (() => {
      const correlation = userCorrelation(m.el);
      return correlation.text ? {
        correlationText: correlation.text,
        structuralHrCount: correlation.hrCount
      } : {};
    })() : {}),
    sequence
  }));
  const userRefs = messageRefs.filter(m => m.role === "user");
  const assistantRefs = messageRefs.filter(m => m.role === "assistant");
  const lastText = (refs) => refs.length ? refs[refs.length - 1].text : null;
  return {
    url: location.href, conversationTitle, composerPresent: !!composer,
    composerEditable: !!composer && composer.isContentEditable && !composer.hasAttribute("disabled"),
    userCount: userRefs.length, assistantCount: assistantRefs.length,
    // GP08 slice 1: messageRefs is the single true DOM-order sequence this
    // adapter derives everything else from -- it is what lets a caller
    // later tell "A-A then U-human" apart from "U-human then A-A" within
    // one poll, which the four legacy arrays below cannot express on their
    // own (they only carry per-role order, not cross-role interleaving).
    messageRefs,
    userMessageIds: userRefs.map(m => m.messageId).filter(Boolean),
    userMessageTexts: userRefs.map(m => m.text).filter(Boolean).slice(-64),
    // GP08: the ordered assistant-message sequence, mirroring the
    // user-message arrays above. "Latest assistant" alone cannot answer
    // "what was the response to request A" once a later, unrelated turn
    // (from any actor) has entered the same conversation -- this ordered
    // list is the raw data a request-addressable correlation layer needs.
    assistantMessageIds: assistantRefs.map(m => m.messageId).filter(Boolean),
    assistantMessageTexts: assistantRefs.map(m => m.text).filter(Boolean).slice(-64),
    latestUserId: userRefs.length ? userRefs[userRefs.length - 1].messageId : null,
    latestAssistantId: latestAssistantRef?.messageId || null,
    latestUserText: lastText(userRefs), latestAssistantText: lastText(assistantRefs), generating, domSignals,
    terminalWitnessAssistantId,
    toolActivityCounts,
    progressBlocks: progressBlocks.slice(-128),
    domActivityDigest,
    domActivityOwnerPromptMessageId,
    errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
  };
}
"""


class GptAutoCdpBrowserController(CdpBrowserController):
    """ChatGPT-specific selectors, composites, and conversation operations."""

    def __init__(self, bridge: PythonCdpBridge) -> None:
        super().__init__(bridge)
        # Project new-chat creation is a shared-window operation.  Without a
        # single critical section, two sessions can both observe the other's
        # newly-created target and adopt the wrong conversation.
        self._project_open_lock = asyncio.Lock()

    async def wait_for_composer(self, page: CdpPageRef, *, timeout: float) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        next_retry_probe = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            snapshot = await self.snapshot(page)
            if snapshot.get("composerPresent") and snapshot.get("composerEditable"):
                return snapshot
            now = asyncio.get_running_loop().time()
            if now >= next_retry_probe:
                retry_focused = await self.evaluate(
                    page,
                    r"""() => {
                      const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
                      const button = Array.from(document.querySelectorAll('button')).find(
                        candidate => normalize(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label')) === 'try again'
                          && !candidate.disabled && candidate.getClientRects().length
                      );
                      if (!button) return false;
                      button.focus();
                      return true;
                    }""",
                )
                if retry_focused:
                    await self.activate(page)
                    await self.press_enter(page)
                next_retry_probe = deadline if retry_focused else now + 1.0
            await asyncio.sleep(0.25)
        raise TimeoutError("ChatGPT composer did not become ready")

    async def snapshot(
        self, page: CdpPageRef, *, signals: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return await self.evaluate(page, _SNAPSHOT_FN, signals or [])

    async def retry_delivery_timeout(self, page: CdpPageRef) -> bool:
        """Click the known conversation delivery Retry control once.

        This action never types or submits a prompt; it only activates the
        provider-owned recovery control for a visible delivery timeout.
        """
        result = await self.evaluate(
            page,
            r"""() => {
              const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
              const candidates = Array.from(document.querySelectorAll(
                'button[data-testid="regenerate-thread-error-button"], button[aria-label="Retry"], button[data-testid*="regenerate"][data-testid*="error"]'
              ));
              const button = candidates.find(candidate => {
                if (candidate.disabled || !candidate.getClientRects().length) return false;
                const text = normalize(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label'));
                // Keep the exact retry-text guard explicit: text !== 'retry'
                // must never be treated as a provider recovery control.
                return text === 'retry';
              });
              if (!button) return false;
              button.click();
              return true;
            }""",
        )
        return bool(result)

    async def materialize_latest_assistant_turn(self, page: CdpPageRef) -> bool:
        """Bring the current assistant turn into the rendered viewport.

        ChatGPT virtualizes long conversations.  In that mode the latest
        answer can have text in the DOM while its end-of-turn action bar is
        not mounted while a background tab is renderer-inactive. Temporarily
        emulate an active/focused page while scrolling and yielding rendering.
        This does not activate the target or foreground the browser window.
        """
        try:
            try:
                await self.bridge.call(
                    "set_focus_emulation",
                    {"pageHandle": page.handle, "enabled": True},
                )
            except CdpError:
                # Older Chromium/CDP implementations may not expose this
                # experimental command. Preserve the existing scroll fallback.
                pass

            scrolled = bool(
                await self.evaluate(
                    page,
                    r"""() => {
                      const assistants = Array.from(
                        document.querySelectorAll('[data-message-author-role="assistant"]')
                      ).filter(el => !(el.getAttribute('data-message-id') || '')
                        .startsWith('request-placeholder-request-'));
                      const latest = assistants.length ? assistants[assistants.length - 1] : null;
                      if (!latest) return false;
                      const turn = latest.closest('.agent-turn') || latest.closest('article')
                        || latest.parentElement?.parentElement || latest;
                      if (!turn || typeof turn.scrollIntoView !== 'function') return false;
                      turn.scrollIntoView({block: 'end', inline: 'nearest'});
                      return true;
                    }""",
                )
            )
            if not scrolled:
                await self.release_focus_emulation(page)
                return False

            try:
                await self.evaluate(
                    page,
                    r"""() => new Promise(resolve => {
                          let settled = false;
                          const done = () => {
                            if (settled) return;
                            settled = true;
                            resolve(true);
                          };
                          if (typeof requestAnimationFrame === 'function') {
                            requestAnimationFrame(() => requestAnimationFrame(done));
                          }
                          setTimeout(done, 250);
                        })""",
                )
            except Exception:
                # Rendering synchronization is best-effort; the caller still
                # takes a fresh authoritative snapshot.
                pass
            # Keep emulation enabled until the caller has taken its fresh
            # authoritative snapshot. Disabling it here can immediately
            # unmount the action bar again in a background renderer.
            return True
        except Exception:
            await self.release_focus_emulation(page)
            raise

    async def release_focus_emulation(self, page: CdpPageRef) -> None:
        """Disable temporary renderer focus emulation after observation."""
        try:
            await self.bridge.call(
                "set_focus_emulation",
                {"pageHandle": page.handle, "enabled": False},
            )
        except Exception:
            # Focus emulation is an observation aid; cleanup must never turn a
            # completed provider response into a gateway failure.
            pass

    async def stop_generation(self, page: CdpPageRef) -> dict[str, bool]:
        stopped = await self.evaluate(
            page,
            r"""() => {
              const selectors = [
                '[data-testid="stop-button"]',
                '[data-testid="stop-generating"]',
                'button[aria-label*="Stop generating" i]',
                'button[aria-label*="Stop response" i]',
                'button[title*="Stop generating" i]',
                'button[title*="Stop response" i]'
              ];
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                  s.visibility !== 'hidden' && s.opacity !== '0';
              };
              const button = selectors.flatMap(s => Array.from(document.querySelectorAll(s)))
                .find(el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true');
              if (!button) return false;
              button.click();
              return true;
            }""",
        )
        return {"stopped": bool(stopped)}

    _SUBMIT_POLL_SECONDS = 0.1
    _SUBMIT_DEFAULT_TIMEOUT_SECONDS = 15.0

    async def submit(
        self, page: CdpPageRef, text: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        send_attempted = False
        stage = "composer-insertion"
        try:
            async with asyncio.timeout(timeout if timeout is not None else self._SUBMIT_DEFAULT_TIMEOUT_SECONDS):
                await self.evaluate(
                    page,
                    r"""(text) => {
                       const editor = document.querySelector('#prompt-textarea') || Array.from(
                         document.querySelectorAll('[contenteditable="true"]')
                       ).find(el => /^(new chat in\b|ask chatgpt$|message chatgpt$)/i.test(String(el.getAttribute('aria-label') || '').trim()));
                      if (!editor) throw new Error('composer not found');
                      editor.focus();
                      const selection = window.getSelection(); selection.removeAllRanges();
                      const range = document.createRange(); range.selectNodeContents(editor); selection.addRange(range);
                      return true;
                    }""",
                    text,
                )
                await self.insert_text(page, text)
                # The send-side DOM check below re-reads and compares the
                # composer text.  Input.insertText has already delivered the
                # exact caller text to the focused editor, so a second read
                # here only adds another CDP race window.
                typed = text
                while True:
                    # One synchronous DOM operation verifies both readiness
                    # conditions and clicks once. No browser-side timer survives
                    # a React navigation, and no Enter bypasses a disabled Send.
                    stage = "send-button"
                    send_attempted = True
                    sent = await self.evaluate(
                        page,
                        r"""(text) => {
                           // Read the editor's semantic DOM rather than innerText.
                           // ChatGPT's rich-link widget owns the presentation
                           // whitespace around its URL, so replace only that
                           // provider-owned node with its stable link value.
                           // Preserve caller whitespace everywhere else: this is
                           // the final fail-closed guard before button.click().
                           const renderedText = root => {
                             const blockTags = new Set([
                               'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DD', 'DIV', 'DL', 'DT',
                               'FIELDSET', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3', 'H4',
                               'H5', 'H6', 'HEADER', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE',
                               'SECTION', 'TABLE', 'TR', 'UL'
                             ]);
                             const walk = node => {
                               if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
                               if (node.nodeType !== Node.ELEMENT_NODE) return '';
                               const element = node;
                               const link = element.getAttribute('text-link-href');
                               if (link) return link;
                               if (element.getAttribute('data-markdown-copy') === 'exclude') return '';
                               if (element.matches('button, [role=button]')) return '';
                               if (element.tagName === 'BR') return '\n';
                               let value = '';
                               for (const child of element.childNodes) value += walk(child);
                               if (element.tagName === 'DIV' && value === '\n') return '\n\n';
                               if (blockTags.has(element.tagName) && !value.endsWith('\n')) value += '\n';
                               return value;
                             };
                             return walk(root)
                               .replace(/\u00a0/g, ' ')
                               .replace(/([`])\s+(https?:\/\/)/g, '$1$2')
                               .replace(/(https?:\/\/[^\s`]+)\s+([`])/g, '$1$2')
                               .replace(/\n+$/, '');
                           };
                           const sourceText = value => String(value || '')
                             .replace(/\r\n/g, '\n')
                             .replace(/\r/g, '\n')
                             .replace(/\n+$/, '');
                           const editor = document.querySelector('#prompt-textarea') || Array.from(
                             document.querySelectorAll('[contenteditable="true"]')
                           ).find(el => /^(new chat in\b|ask chatgpt$|message chatgpt$)/i.test(String(el.getAttribute('aria-label') || '').trim()));
                          if (!editor || !editor.isContentEditable) return false;
                           if (renderedText(editor) !== sourceText(text)) return false;
                          const button = document.querySelector('[data-testid="send-button"], button[aria-label*="Send" i]');
                          if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true' || !button.getClientRects().length) return false;
                          button.click(); return true;
                        }""",
                        text,
                    )
                    if sent is True:
                        return {"actionComplete": True, "typedText": typed,
                                "sendButtonClicked": True, "enterDispatched": False}
                    send_attempted = False
                    stage = "composer-readiness"
                    await asyncio.sleep(self._SUBMIT_POLL_SECONDS)
        except TimeoutError as exc:
            raise ComposerSubmissionTimeout(send_attempted=send_attempted, stage=stage) from exc

    async def find_project_url(self, page: CdpPageRef, project_name: str) -> dict[str, str]:
        projects_tab_opened = await self._open_projects_tab(page, timeout=12.0)
        if projects_tab_opened:
            clicked = await self._select_project_from_projects_page(
                page, project_name, timeout=12.0
            )
            if clicked:
                for _ in range(120):
                    current = await self.page_by_handle(page.handle)
                    if re.match(r"^/g/g-p-[^/]+/project/?$", urlsplit(current.url).path):
                        return {"url": current.url, "name": project_name}
                    await asyncio.sleep(0.1)
        result = await self.evaluate(
            page,
            r"""async (name) => {
              const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
              const wanted = normalize(name).toLowerCase();
              const matchingProjectRow = () => Array.from(
                document.querySelectorAll('[data-app-action-sidebar-project-row]')
              ).find(row => normalize(row.getAttribute('data-app-action-sidebar-project-label')).toLowerCase() === wanted);
              for (let i = 0; i < 120; i++) {
                const row = matchingProjectRow();
                if (row) {
                  if (row.getAttribute('aria-expanded') !== 'true') row.click();
                  const button = Array.from(row.querySelectorAll('button')).find(candidate =>
                    normalize(candidate.getAttribute('aria-label')).toLowerCase() === `new chat in ${wanted}`
                      && candidate.getClientRects().length
                  );
                  if (button) button.click();
                  if (button) {
                    for (let j = 0; j < 120; j++) {
                      if (/\/g\/g-p-[^/]+\/project\/?$/.test(location.pathname)) {
                        return {url: location.href, name};
                      }
                      await new Promise(r => setTimeout(r, 100));
                    }
                  }
                }
                await new Promise(r => setTimeout(r, 100));
              }
              throw new Error(`ChatGPT project not found: ${name}`);
            }""",
            project_name,
        )
        return {"url": str(result["url"]), "name": str(result.get("name") or project_name)}

    async def _open_projects_tab(self, page: CdpPageRef, *, timeout: float) -> bool:
        """Use the current sidebar Explore hover menu when it is available."""
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while asyncio.get_running_loop().time() < deadline:
            if await self.hover_text(page, "Explore"):
                if await self.click_text(page, "Projects"):
                    if await self._wait_for_projects_route(page, timeout=1.0):
                        return True
                if await self.evaluate(page, _CLICK_PROJECTS_TAB_FN):
                    if await self._wait_for_projects_route(page, timeout=1.0):
                        return True
            await asyncio.sleep(0.1)
        return False

    async def _wait_for_projects_route(self, page: CdpPageRef, *, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while asyncio.get_running_loop().time() < deadline:
            try:
                current = await self.page_by_handle(page.handle)
            except Exception:  # noqa: BLE001 - navigation may replace the target briefly
                current = page
            if urlsplit(current.url).path.rstrip("/") == "/projects":
                return True
            await asyncio.sleep(0.1)
        return False

    async def _select_project_from_projects_page(
        self, page: CdpPageRef, project_name: str, *, timeout: float
    ) -> bool:
        """Select a project using its project-page new-chat control.

        The current Projects page renders project names as non-link text. The
        action that actually creates a project-scoped chat is the
        ``Start new chat in project`` button inside that exact project row.
        """
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while asyncio.get_running_loop().time() < deadline:
            if await self.evaluate(page, _CLICK_PROJECT_NEW_CHAT_FN, project_name):
                return True
            await asyncio.sleep(0.1)
        return False

    async def open_project_page(
        self,
        *,
        project_name: str,
        project_url: str | None,
        anchor_page: CdpPageRef | None,
        navigation_timeout: float,
        ready_timeout: float,
    ) -> dict[str, Any]:
        async with self._project_open_lock:
            return await self._open_project_page_unlocked(
                project_name=project_name,
                project_url=project_url,
                anchor_page=anchor_page,
                navigation_timeout=navigation_timeout,
                ready_timeout=ready_timeout,
            )

    async def _open_project_page_unlocked(
        self,
        *,
        project_name: str,
        project_url: str | None,
        anchor_page: CdpPageRef | None,
        navigation_timeout: float,
        ready_timeout: float,
    ) -> dict[str, Any]:
        """Open a genuinely new chat through ChatGPT's sidebar UI.

        A configured URL is validation data only. New sessions always select
        the exact visible project name from ChatGPT's sidebar; existing sessions use
        their persisted /c/ URL and never enter this method.
        """
        expected_project_id = parse_project_id(project_url or "")
        page = await self.new_tab(in_window=anchor_page) if anchor_page else await self.new_window()
        try:
            async with asyncio.timeout(navigation_timeout):
                page = await self.navigate(page, _CHATGPT_HOME_URL)
            known_targets = {candidate.target_id for candidate in await self.pages()}
            projects_tab_opened = await self._open_projects_tab(page, timeout=navigation_timeout)
            deadline = asyncio.get_running_loop().time() + navigation_timeout
            clicked = False
            if projects_tab_opened:
                clicked = await self._select_project_from_projects_page(
                    page, project_name, timeout=navigation_timeout
                )
            while asyncio.get_running_loop().time() < deadline:
                if clicked:
                    break
                clicked = await self.evaluate(
                    page,
                    r"""(name) => {
                       const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                       const wanted = normalize(name).toLowerCase();
                       const row = Array.from(document.querySelectorAll('[data-app-action-sidebar-project-row]')).find(item =>
                         normalize(item.getAttribute('data-app-action-sidebar-project-label')).toLowerCase() === wanted
                       );
                       if (!row) return false;
                       if (row.getAttribute('aria-expanded') !== 'true') row.click();
                       const button = Array.from(row.querySelectorAll('button')).find(candidate =>
                         normalize(candidate.getAttribute('aria-label')).toLowerCase() === `new chat in ${wanted}`
                           && candidate.getClientRects().length
                       );
                       if (button) { button.click(); return true; }
                       return false;
                     }""",
                    project_name,
                )
                if clicked is True:
                    break
                await asyncio.sleep(0.1)
            if not clicked:
                raise RuntimeError(f"ChatGPT project not found: {project_name}")

            # ChatGPT may navigate the sidebar-selected project in-place or
            # briefly reuse the home route. Adopt whichever target the UI
            # created; never leave the session watcher attached to the stale
            # home page.
            source_page = page
            deadline = asyncio.get_running_loop().time() + navigation_timeout
            selected_url = ""
            observed_wrong_project = False
            wrong_project_pages: dict[str, CdpPageRef] = {}
            while asyncio.get_running_loop().time() < deadline:
                candidates: list[CdpPageRef] = []
                try:
                    candidates.append(await self.page_by_handle(source_page.handle))
                except Exception:
                    pass
                candidates.extend(
                    candidate
                    for candidate in await self.pages()
                    if candidate.target_id not in known_targets
                )
                for candidate in candidates:
                    candidate_project_id = parse_project_id(candidate.url)
                    if candidate_project_id is None:
                        continue
                    if expected_project_id and candidate_project_id != expected_project_id:
                        observed_wrong_project = True
                        if candidate.target_id != source_page.target_id:
                            wrong_project_pages[candidate.handle] = candidate
                        continue
                    page = candidate
                    selected_url = candidate.url
                    break
                if selected_url:
                    break
                await asyncio.sleep(0.1)
            if not selected_url:
                if observed_wrong_project:
                    raise RuntimeError(
                        "selected ChatGPT Project does not match configured project identity"
                    )
                raise TimeoutError("ChatGPT project selection did not open a project page")
            if page.target_id != source_page.target_id:
                await self.close(source_page)
            await self.wait_for_composer(page, timeout=ready_timeout)
            parts = urlsplit(selected_url)
            project_landing_url = f"https://chatgpt.com{parts.path.rstrip('/')}"
            return {"page": page, "projectUrl": project_landing_url}
        except Exception as exc:
            wrong_pages = (
                wrong_project_pages.values()
                if "wrong_project_pages" in locals()
                else ()
            )
            for wrong_page in wrong_pages:
                if wrong_page.handle == page.handle:
                    continue
                try:
                    await self.close(wrong_page)
                except Exception:
                    logger.debug(
                        "gpt-auto failed to close wrong-project target",
                        extra={"page-handle": wrong_page.handle},
                        exc_info=True,
                    )
            await self.close(page)
            raise RuntimeError(
                f"gpt-auto project page open failed: {type(exc).__name__}: {exc}"
            ) from exc


__all__ = ["GptAutoCdpBrowserController", "CdpPageRef", "CdpWindowBounds"]
