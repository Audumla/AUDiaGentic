"""ChatGPT-specific browser operations over the generic CDP controller."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from .cdp.cdp_browser import CdpBrowserController, CdpPageRef, CdpWindowBounds
from .cdp.client import CdpError
from .urls import parse_project_id

_PROJECTS_URL = "https://chatgpt.com/projects"


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
  const messageEntries = [];
  for (const el of allRoleNodes) {
    const role = el.getAttribute("data-message-author-role");
    if (role === "assistant" && (el.getAttribute("data-message-id") || "").startsWith("request-placeholder-request-")) continue;
    messageEntries.push({role, el, messageId: el.getAttribute("data-message-id") || null});
  }
  const users = messageEntries.filter(m => m.role === "user").map(m => m.el);
  const assistants = messageEntries.filter(m => m.role === "assistant").map(m => m.el);
  const latestAssistant = assistants.length ? assistants[assistants.length - 1] : null;
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
  const assistantTurn = latestAssistant ? (
    latestAssistant.closest(".agent-turn") || latestAssistant.closest("article") || latestAssistant.parentElement?.parentElement
  ) : latestAgentTurn;
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
  const visibleTextDigest = (node, directOnly = false) => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const parts = ["visible-text-v1"];
    let visited = 0;
    let included = 0;
    let textNode;
    while ((textNode = walker.nextNode())) {
      visited += 1;
      if (visited > 256) return null;
      if (!progressShown(textNode.parentElement) || (directOnly && textNode.parentElement !== node)) continue;
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
  const visibleChildCount = node =>
    Array.from(node.children || []).filter(progressShown).length;
  const semanticNodeDigest = (node, structural = false) => {
    const textDigest = visibleTextDigest(node, structural);
    if (textDigest === null) return null;
    return progressDigest([
      String(node.tagName || ""),
      attributeMaterial(node),
      String(visibleChildCount(node)),
      textDigest
    ].join("\x1c"));
  };
  const semanticStateDigest = node => {
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
      const lexical = progressKind(boundedTextForKind(descendant));
      if (progressShown(descendant) && descendant.matches(semanticSelector) &&
          !(structuralKind(node) && lexicalKinds.has(lexical) && !structuralKind(descendant))) {
        descendants.push(descendant);
      }
    }
    const selected = descendants.slice(0, 32);
    const tail = descendants.slice(-32);
    const selectedNodes = [...selected, ...tail.filter(child => !selected.includes(child))];
    // Every contribution is fixed-size; the final aggregate is therefore
    // intrinsically below progressDigest's input bound.
    const rootStructural = Boolean(structuralKind(node));
    const rootDigest = semanticNodeDigest(node, rootStructural);
    const nodeDigests = selectedNodes.map(child => semanticNodeDigest(child, Boolean(structuralKind(child))));
    if (rootDigest === null || nodeDigests.some(digest => digest === null)) return null;
    return progressDigest([
      "semantic-state-v2",
      rootDigest,
      String(descendants.length),
      ...nodeDigests
    ].join("\x1e"));
  };
  const userEntries = messageEntries.filter(entry => entry.role === "user" && entry.messageId);
  let ownerUserIndex = userEntries.length - 1;
  const ownerPromptFor = node => {
    while (ownerUserIndex >= 0) {
      const entry = userEntries[ownerUserIndex];
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
  const progressBlocks = [];
  const MAX_PROGRESS_TURNS = 8;
  const MAX_PROGRESS_VISIBLE_NODES = 2048;
  const MAX_PROGRESS_CANDIDATES = 256;
  let inspectedNodes = 0;
  let inspectedCandidates = 0;
  // Historical turns can contain persistent tables and tool cards. Inspect
  // newest turns first and stop at fixed turn/node/candidate budgets.
  for (let turnIndex = agentTurns.length - 1, turnsInspected = 0;
       turnIndex >= 0 && turnsInspected < MAX_PROGRESS_TURNS && progressBlocks.length < 128;
       turnIndex--, turnsInspected++) {
    const turn = agentTurns[turnIndex];
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
      if (inspectedCandidates >= MAX_PROGRESS_CANDIDATES) {
        turnComplete = false;
        break;
      }
      const structural = node.matches(structuralProgressSelector);
      // Structural identity wins for structural nodes. Their visible text may
      // contain a lexical child, but the parent must remain an independent
      // candidate so changes to tool/connector/status state are observable.
      const kind = structuralKind(node) || progressKind(boundedTextForKind(node), structural);
      if (!kind) continue;
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
    for (const {node, kind} of canonicalCandidates) {
      if (progressBlocks.length >= 128) break;
      if (!progressShown(node) || node.closest('[data-message-author-role="user"]')) continue;
      const digest = semanticStateDigest(node);
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
  ) ? (latestAssistant?.getAttribute("data-message-id") || null) : null;
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
  const userCorrelation = (element) => {
    const source = element?.querySelector('[data-testid="collapsible-user-message-content"]') || element;
    if (!source) return {text: null, hrCount: 0};
    const clone = source.cloneNode(true);
    // The visible message node may contain presentation-only controls when a
    // long prompt is collapsed.  Remove those elements from the clone rather
    // than stripping their labels from the resulting string: a real prompt is
    // allowed to contain words such as "Show more".
    clone.querySelectorAll('button, [role="button"], [aria-label*="show more" i], [aria-label*="show less" i]').forEach(el => el.remove());
    const hrs = Array.from(clone.querySelectorAll('hr'));
    for (const hr of hrs) hr.replaceWith(document.createTextNode("\n---\n"));
    const text = ((clone.innerText || clone.textContent || "").trim()).slice(0, 200000) || null;
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
  // a misdirected prompt submission. #prompt-textarea is the real
  // composer's own stable, unique id; confirmed present across every
  // observed page state, canvas or not.
  const composer = document.querySelector("#prompt-textarea");
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
  const messageRefs = messageEntries.map((m, sequence) => ({
    role: m.role,
    messageId: m.messageId,
    text: m.role === "user" ? userText(m.el) : boundedText(m.el),
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
    latestAssistantId: latestAssistant?.getAttribute("data-message-id") || null,
    latestUserText: lastText(userRefs), latestAssistantText: lastText(assistantRefs), generating, domSignals,
    terminalWitnessAssistantId,
    toolActivityCounts,
    progressBlocks: progressBlocks.slice(-128),
    errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
  };
}
"""


class GptAutoCdpBrowserController(CdpBrowserController):
    """ChatGPT-specific selectors, composites, and conversation operations."""

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
                typed = await self.evaluate(
                    page,
                    """(text) => {
                      const editor = document.querySelector('#prompt-textarea');
                      if (!editor) throw new Error('composer not found');
                      editor.focus();
                      const selection = window.getSelection(); selection.removeAllRanges();
                      const range = document.createRange(); range.selectNodeContents(editor); selection.addRange(range);
                      if (!document.execCommand('insertText', false, text)) throw new Error('browser rejected atomic composer insertion');
                      editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
                      return (editor.innerText || editor.textContent || '').trim();
                    }""",
                    text,
                )
                while True:
                    # One synchronous DOM operation verifies both readiness
                    # conditions and clicks once. No browser-side timer survives
                    # a React navigation, and no Enter bypasses a disabled Send.
                    stage = "send-button"
                    send_attempted = True
                    sent = await self.evaluate(
                        page,
                        r"""(text) => {
                          // innerText includes layout whitespace between rich-editor
                          // paragraphs. Compare content without that presentation
                          // whitespace; never rewrite the submitted prompt itself.
                          const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                          const editor = document.querySelector('#prompt-textarea');
                          if (!editor || !editor.isContentEditable) return false;
                          if (normalize(editor.innerText || editor.textContent || '') !== normalize(text)) return false;
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
        result = await self.evaluate(
            page,
            r"""async (name) => {
              const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
              const wanted = normalize(name).toLowerCase();
              const matchingProjectLink = () => Array.from(document.querySelectorAll('a[href]')).find(anchor => {
                const label = normalize(anchor.innerText || anchor.textContent || anchor.getAttribute('aria-label'));
                if (label.toLowerCase() !== wanted) return false;
                try { return /\/g\/g-p-[^/]+\/project\/?$/.test(new URL(anchor.href, location.origin).pathname); }
                catch (_) { return false; }
              });
              for (let i = 0; i < 120; i++) {
                const projectLink = matchingProjectLink();
                if (projectLink) return {url: new URL(projectLink.href, location.origin).href, name};
                const row = Array.from(document.querySelectorAll('[role=row]')).find(row => {
                  const values = [...Array.from(row.querySelectorAll('[role=cell], [role=gridcell]')).map(c => c.innerText || c.textContent), ...(row.innerText || '').split(/\r?\n/)].map(normalize);
                  return values.some(value => value.toLowerCase() === wanted);
                });
                if (row) {
                  row.click();
                  let projectLocation = null;
                  for (let j = 0; j < 120; j++) {
                    const hydratedLink = matchingProjectLink();
                    if (hydratedLink) return {url: new URL(hydratedLink.href, location.origin).href, name};
                    if (/\/g\/g-p-[^/]+/.test(location.pathname)) projectLocation = location.href;
                    await new Promise(r => setTimeout(r, 100));
                  }
                  if (projectLocation) return {url: projectLocation, name};
                }
                await new Promise(r => setTimeout(r, 100));
              }
              throw new Error(`ChatGPT project not found: ${name}`);
            }""",
            project_name,
        )
        return {"url": str(result["url"]), "name": str(result.get("name") or project_name)}

    async def open_project_page(
        self,
        *,
        project_name: str,
        project_url: str | None,
        anchor_page: CdpPageRef | None,
        navigation_timeout: float,
        ready_timeout: float,
    ) -> dict[str, Any]:
        """Open a genuinely new chat through ChatGPT's Projects UI.

        A configured URL is validation data only. New sessions always select
        the exact visible project name from /projects; existing sessions use
        their persisted /c/ URL and never enter this method.
        """
        expected_project_id = parse_project_id(project_url or "")
        page = await self.new_tab(in_window=anchor_page) if anchor_page else await self.new_window()
        try:
            async with asyncio.timeout(navigation_timeout):
                page = await self.navigate(page, _PROJECTS_URL)
            known_targets = {candidate.target_id for candidate in await self.pages()}
            deadline = asyncio.get_running_loop().time() + navigation_timeout
            clicked = False
            while asyncio.get_running_loop().time() < deadline:
                clicked = await self.evaluate(
                    page,
                    r"""(name) => {
                      const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                      const wanted = normalize(name).toLowerCase();
                      const exact = value => normalize(value).toLowerCase() === wanted;
                      const anchor = Array.from(document.querySelectorAll('a[href]')).find(item =>
                        exact(item.innerText || item.textContent || item.getAttribute('aria-label'))
                      );
                      if (anchor) { anchor.click(); return true; }
                      const row = Array.from(document.querySelectorAll('[role="row"]')).find(item =>
                        (item.innerText || item.textContent || '').split(/\r?\n/).some(exact)
                      );
                      if (row) { row.click(); return true; }
                      return false;
                    }""",
                    project_name,
                )
                if clicked is True:
                    break
                await asyncio.sleep(0.1)
            if not clicked:
                raise RuntimeError(f"ChatGPT project not found: {project_name}")

            # ChatGPT may navigate the Projects target or open the selected
            # project in a new target. Adopt whichever target the UI created;
            # never leave the session watcher attached to stale /projects.
            source_page = page
            deadline = asyncio.get_running_loop().time() + navigation_timeout
            selected_url = ""
            observed_wrong_project = False
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
            await self.close(page)
            raise RuntimeError(
                f"gpt-auto project page open failed: {type(exc).__name__}: {exc}"
            ) from exc


__all__ = ["GptAutoCdpBrowserController", "CdpPageRef", "CdpWindowBounds"]
