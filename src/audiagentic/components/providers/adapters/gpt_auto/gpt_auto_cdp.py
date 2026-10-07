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


def _canonical_project_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return parse_project_id(f"https://chatgpt.com/g/{value.strip()}/project")


def _selection_project_id(selection: object, expected_project_id: str | None) -> str | None:
    if isinstance(selection, dict):
        return _canonical_project_id(selection.get("projectId"))
    if selection is True and expected_project_id:
        return expected_project_id
    return None

logger = logging.getLogger(__name__)

_CHATGPT_HOME_URL = "https://chatgpt.com/"
_CHATGPT_PROJECTS_URL = "https://chatgpt.com/projects"

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

_PROJECT_NEW_CHAT_POINT_FN = r"""(input) => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const canonicalProjectId = value => {
    const raw = String(value || '').trim();
    const match = raw.match(/^(g-p-[0-9a-f]{32})(?:-.*)?$/i);
    return match ? match[1].toLowerCase() : raw;
  };
  const wanted = normalize(input.name);
  const expectedProjectId = canonicalProjectId(input.expectedProjectId);
  const visible = element => {
    if (!element || !element.getClientRects().length) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  };
  // The Projects listing currently renders project rows without an id or
  // project link. Do not manufacture an identity from the display name. A
  // unique exact-name row is still a provider-owned selection witness; the
  // resulting project landing URL is the authoritative source of the id.
  const sidebarProjectIdsForName = () => Array.from(
    new Set(Array.from(document.querySelectorAll('[data-app-action-sidebar-project-row]'))
      .filter(candidate => normalize(
        candidate.getAttribute('data-app-action-sidebar-project-label')
      ) === wanted)
      .map(candidate => canonicalProjectId(
        candidate.getAttribute('data-app-action-sidebar-project-id')
      ))
      .filter(Boolean))
  );
  const sidebarProjectIdForName = () => {
    const ids = sidebarProjectIdsForName();
    if (expectedProjectId) {
      const matchingExpected = ids.filter(id => id === expectedProjectId);
      return matchingExpected.length === 1 ? matchingExpected[0] : '';
    }
    return ids.length === 1 ? ids[0] : '';
  };
  const projectIdForRow = row => {
    const href = row.querySelector('a[href*="/g/g-p-"]')?.getAttribute('href') || '';
    const hrefMatch = href.match(/\/g\/(g-p-[^/?#]+)/);
    return canonicalProjectId(
      row.getAttribute('data-project-id') || (hrefMatch ? hrefMatch[1] : '') ||
      sidebarProjectIdForName()
    );
  };
  const sidebarIds = sidebarProjectIdsForName();
  // A visible sidebar identity that is ambiguous or contradicts the
  // configured identity is a hard failure, not permission to fall back to a
  // display-name-only row.
  if ((!expectedProjectId && sidebarIds.length > 1) ||
      (expectedProjectId && sidebarIds.length && !sidebarIds.includes(expectedProjectId))) return null;
  const candidates = Array.from(document.querySelectorAll('[data-project-row="true"]'))
    .filter(row => visible(row))
    .filter(row => Array.from(row.querySelectorAll('span')).some(
      element => visible(element) && normalize(element.textContent) === wanted
    ))
    .map(row => ({row, projectId: projectIdForRow(row)}));
  let matching = candidates;
  if (expectedProjectId) {
    const known = candidates.filter(candidate => candidate.projectId);
    // If the provider exposes row ids, require the configured id now. When
    // every exact-name row omits identity, allow the unique row-action witness
    // and defer the authoritative check to the resulting landing URL.
    matching = known.length
      ? known.filter(candidate => candidate.projectId === expectedProjectId)
      : candidates;
  }
  if (matching.length !== 1) return null;
  const {row, projectId} = matching[0];
  const button = Array.from(row.querySelectorAll('button')).find(
    candidate => visible(candidate) &&
      normalize(candidate.getAttribute('aria-label')) === 'start new chat in project'
  );
  if (!button) return null;
  button.scrollIntoView({block: 'center', inline: 'nearest'});
  if (!visible(button)) return null;
  const rect = button.getBoundingClientRect();
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
  // Re-check the trusted hit target after scrolling. React can reflow the
  // page between discovery and the native pointer dispatch; accepting an
  // occluded point would report a click that never reached the provider
  // action.
  const hit = document.elementFromPoint(x, y);
  if (!hit || !(hit === button || button.contains(hit))) return null;
  return {x, y, projectId: projectId || null, identitySource: projectId ? 'row' : 'row-action'};
}"""
_COMPOSER_READY_FN = r"""() => {
  const composer = document.querySelector("#prompt-textarea") || Array.from(
    document.querySelectorAll('[contenteditable="true"]')
  ).find(element => /^(new chat in\b|ask chatgpt$|message chatgpt$)/i.test(
    String(element.getAttribute("aria-label") || "").trim()
  ));
  if (!composer) return {composerPresent: false, composerEditable: false};
  const rect = composer.getBoundingClientRect();
  const style = getComputedStyle(composer);
  return {
    composerPresent: true,
    composerEditable: composer.isContentEditable && !composer.hasAttribute("disabled"),
    visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden"
      && style.display !== "none" && style.opacity !== "0"
  };
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
  let fallbackBlocks = usingFallbackMessages
    ? Array.from(document.querySelectorAll('.block-BQZwFn'))
        .map((block, domIndex) => ({
          block,
          domIndex,
          visualTop: block.getBoundingClientRect().top
        }))
        .sort((left, right) => {
          // The current virtualized renderer keeps newest turns first in DOM
          // order while laying them out in normal conversation order. Use
          // visual order when it is available, retaining DOM order for
          // detached/zero-layout fixtures and exact ties.
          const delta = left.visualTop - right.visualTop;
          return Number.isFinite(delta) && Math.abs(delta) > 0.5
            ? delta
            : left.domIndex - right.domIndex;
        })
        .map(entry => entry.block)
    : [];
  // Only an h4.sr-only owned by this exact block (not a nested .block-BQZwFn)
  // may label it -- otherwise an unlabelled outer wrapper around a labelled
  // inner block would silently adopt the inner block's label, turning one
  // semantic message into two messageEntries.
  const fallbackBlockLabel = block => {
    const heading = Array.from(block.querySelectorAll('h4.sr-only'))
      .find(h => h.closest('.block-BQZwFn') === block);
    return String(heading?.innerText || '').trim().toLowerCase();
  };
  // The current renderer keeps the semantic role on a content-search unit
  // instead of rendering the legacy "You said:"/"ChatGPT said:" heading on
  // every message block.  Resolve the role from a unit owned by this block,
  // while retaining the heading fallback for older snapshots.
  const fallbackBlockRole = block => {
    const label = fallbackBlockLabel(block);
    if (label === 'you said:') return 'user';
    if (label === 'chatgpt said:') return 'assistant';
    const roles = new Set(Array.from(block.querySelectorAll('[data-content-search-unit-key]'))
      .map(unit => String(unit.getAttribute('data-content-search-unit-key') || '').match(/:(user|assistant)$/)?.[1])
      .filter(Boolean));
    return roles.size === 1 ? [...roles][0] : null;
  };
  const fallbackTurnIdentity = block => {
    const owner = block.closest('[data-content-search-turn-key]');
    const value = owner?.getAttribute('data-content-search-turn-key');
    return value ? String(value) : null;
  };
  // The virtualized renderer can expose both completed blocks with zero
  // geometry and newest-first DOM order. In that black-and-white case the
  // provider's shared content-turn key is stronger than either layout or DOM
  // order: it explicitly pairs this prompt and assistant response.
  fallbackBlocks = fallbackBlocks.slice().sort((left, right) => {
    const leftTurn = fallbackTurnIdentity(left);
    const rightTurn = fallbackTurnIdentity(right);
    if (!leftTurn || leftTurn !== rightTurn) return 0;
    const leftRole = fallbackBlockRole(left);
    const rightRole = fallbackBlockRole(right);
    if (leftRole === rightRole) return 0;
    if (leftRole === 'user' && rightRole === 'assistant') return -1;
    if (leftRole === 'assistant' && rightRole === 'user') return 1;
    return 0;
  });
  const latestFallbackUserBlock = usingFallbackMessages
    ? fallbackBlocks.slice().reverse().find(block => fallbackBlockRole(block) === 'user') || null
    : null;
  const latestFallbackUserIndex = latestFallbackUserBlock
    ? fallbackBlocks.indexOf(latestFallbackUserBlock)
    : -1;
  const latestFallbackActivityAfterPrompt = latestFallbackUserIndex >= 0
    ? fallbackBlocks.slice(latestFallbackUserIndex + 1).reverse()[0] || null
    : null;
  // The current renderer can mount the live agent-activity block before the
  // submitted `You said:` block (the visible order is correct, but the
  // virtualized DOM order is not).  The old after-prompt-only lookup then
  // discarded every live progress update and left the gateway activity lease
  // frozen.  Adopt a pre-prompt unlabelled block only with an active Stop
  // control; without that provider-owned liveness witness, fail closed rather
  // than attributing an older assistant block to the current request.
  const activeStopControlVisible = Array.from(document.querySelectorAll(
    '[data-testid="stop-button"], [data-testid="stop-generating"], button[aria-label*="stop" i], button'
  )).some(element => {
    if (!shown(element)) return false;
    const text = String(element.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const aria = String(element.getAttribute('aria-label') || '').trim().toLowerCase();
    return text === 'stop' || aria === 'stop' || aria.includes('stop generating');
  });
  const latestFallbackActivityBeforePrompt = latestFallbackUserIndex >= 0 && activeStopControlVisible
    ? fallbackBlocks.slice(0, latestFallbackUserIndex).reverse().find(block =>
        !fallbackBlockLabel(block) &&
        !block.querySelector('[data-user-message-bubble="true"]')
      ) || null
    : null;
  const latestFallbackActivityBlock = latestFallbackActivityAfterPrompt || latestFallbackActivityBeforePrompt;
  const latestFallbackAssistantBlock = usingFallbackMessages
    ? fallbackBlocks.slice().reverse().find(block => fallbackBlockRole(block) === 'assistant') || null
    : null;
  // The current labelled renderer places the assistant action bar beside the
  // labelled block, inside the encompassing data-turn-key wrapper. Scoping
  // only to the .block-BQZwFn content misses More actions/Regenerate response
  // and leaves a completed answer looking permanently in-progress.
  const fallbackTurnRoot = block => block
    ? (block.closest('[data-turn-key]') || block.closest('[data-content-search-turn-key]'))
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
    // The real ChatGPT message UUID rides in `data-chatgpt-search-message-ids`
    // on a descendant of the labelled block, not on the block itself and not
    // on `[data-user-message-bubble="true"]` (that attribute is no longer
    // rendered by the current renderer). Read it from whichever element in
    // the block actually carries it before falling back to a synthetic id.
    // Collect every candidate carrier (self plus all descendants), keep only
    // the ones actually owned by this block (nearest `.block-BQZwFn`
    // ancestor is this block, not a nested/foreign one -- a querySelector
    // that stopped at the first match could silently shadow a later owned
    // carrier with an earlier foreign one, or pick an arbitrary one of two
    // disagreeing owned carriers), and fail closed to null (never guess)
    // unless every owned carrier resolves to exactly one single-id value.
    const realMessageId = block => {
      const carriers = block.hasAttribute('data-chatgpt-search-message-ids')
        ? [block, ...block.querySelectorAll('[data-chatgpt-search-message-ids]')]
        : Array.from(block.querySelectorAll('[data-chatgpt-search-message-ids]'));
      const owned = carriers.filter(carrier => carrier.closest('.block-BQZwFn') === block);
      const ids = new Set();
      for (const carrier of owned) {
        const raw = (carrier.getAttribute('data-chatgpt-search-message-ids') || '').trim();
        if (!raw) continue;
        // The current renderer repeats the same UUID in one attribute.  A
        // repeated identical token is still one proven identity; only
        // genuinely different tokens are ambiguous.
        const tokens = [...new Set(raw.split(/\s+/))];
        // A carrier's own value is ambiguous (more than one space-separated
        // id, no proven canonical token) -- fail the whole block closed
        // rather than silently pick a token from it.
        if (tokens.length !== 1) return null;
        ids.add(tokens[0]);
      }
      return ids.size === 1 ? [...ids][0] : null;
    };
    for (const block of fallbackBlocks) {
      const role = fallbackBlockRole(block);
      if (role === 'user') {
        const content = block.querySelector('[data-user-message-bubble="true"]') || block;
        // Advance the ordinal for every user block regardless of whether a
        // real id was found: the ordinal must stay a stable, non-reused
        // identity across polls, independent of which blocks happen to
        // expose a real id on a given poll.
        const synthetic = `fallback-user-${userIndex++}`;
        messageEntries.push({role: 'user', el: content, messageId: realMessageId(block) || synthetic});
      } else if (role === 'assistant') {
        const synthetic = `fallback-assistant-${assistantIndex++}`;
        messageEntries.push({role: 'assistant', el: block, messageId: realMessageId(block) || synthetic});
      }
    }
  }
  let fallbackActivityOwnerPromptMessageId = null;
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
    ? (fallbackTurnRoot(latestFallbackActivityBlock) || latestFallbackActivityBlock || (latestAssistant ? (
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
  const activityAttrs = [...semanticAttrs, "class"];
  const animationClassToken = /^(?:animate|animation|transition|duration|ease|delay|shimmer|pulse|spin|blink|caret)(?:-|$)/i;
  const classMutationIsAnimationOnly = value => {
    const tokens = normalizeProgress(value).split(/\s+/).filter(Boolean);
    return tokens.length > 0 && tokens.every(token => animationClassToken.test(token));
  };
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
    const key = '__audiagenticActivityObserverV2';
    if (!node) {
      window[key]?.observer.disconnect();
      delete window[key];
      return null;
    }
    // A request-root observer catches interior and between-poll changes that
    // bounded head/tail snapshots cannot see. Keep only one observer per page;
    // changing the root disconnects old-turn observation. Animation classes
    // are deliberately excluded from meaningful work activity.
    let observed = window[key];
    if (!observed || observed.root !== node) {
      if (observed) observed.observer.disconnect();
      observed = {root: node, revision: 0};
      observed.consume = records => {
        if (records.some(record => {
          const target = record.target.nodeType === Node.ELEMENT_NODE
            ? record.target : record.target.parentElement;
          if (!target || !progressShown(target)) return false;
          if (record.type === 'attributes' && record.attributeName === 'class') {
            const currentClass = target.getAttribute('class') || '';
            const previousClass = record.oldValue || '';
            // Renderer animation classes are visual shimmer/caret noise. A
            // class edge that carries any non-animation token is meaningful
            // DOM state and must renew activity.
            if (
              (classMutationIsAnimationOnly(currentClass) &&
                (!previousClass || classMutationIsAnimationOnly(previousClass))) ||
              (classMutationIsAnimationOnly(previousClass) &&
                (!currentClass || classMutationIsAnimationOnly(currentClass)))
            ) return false;
            return true;
          }
          if (record.type !== 'childList') return true;
          const addedVisible = Array.from(record.addedNodes).some(child =>
            child.nodeType === Node.TEXT_NODE
              ? Boolean(child.nodeValue)
              : child.nodeType === Node.ELEMENT_NODE && progressShown(child)
          );
          const removedVisible = Array.from(record.removedNodes).some(child => {
            if (child.nodeType === Node.TEXT_NODE) return Boolean(child.nodeValue);
            if (child.nodeType !== Node.ELEMENT_NODE) return false;
            // Detached nodes have no geometry. Preserve real removals while
            // excluding explicitly hidden bookkeeping subtrees.
            return !child.hidden && child.getAttribute('aria-hidden') !== 'true'
              && child.style.display !== 'none' && child.style.visibility !== 'hidden';
          });
          return addedVisible || removedVisible;
        })) observed.revision += 1;
      };
      observed.observer = new MutationObserver(observed.consume);
      observed.observer.observe(node, {
        subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: activityAttrs, attributeOldValue: true
      });
      window[key] = observed;
    }
    observed.consume(observed.observer.takeRecords());
    const parts = ["dom-activity-v2", String(observed.revision), String(node.tagName || ""), attributeMaterial(node)];
    const elementWalker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT);
    const firstNodes = [];
    const lastNodes = [];
    let elementCount = 0;
    let visitedElements = 0;
    let element;
    while ((element = elementWalker.nextNode())) {
      if (++visitedElements > 256) break;
      if (!progressShown(element)) continue;
      elementCount += 1;
      const material = [
        String(element.tagName || ""),
        attributeMaterial(element),
        String(element.childElementCount)
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
    let visitedTexts = 0;
    while ((textNode = textWalker.nextNode())) {
      if (++visitedTexts > 256) break;
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
  // Stop is only conversation-level liveness.  For a fallback activity block
  // that renders before the current prompt, require a second observation in
  // which that same block mutates while the same prompt remains current.  A
  // static older/manual generation therefore stays unowned instead of
  // resetting the current request's recovery clock.
  if (latestFallbackActivityBeforePrompt && latestFallbackUserBlock && activeStopControlVisible) {
    const promptId = messageEntries.find(entry =>
      entry.role === 'user' && latestFallbackUserBlock.contains(entry.el)
    )?.messageId || null;
    if (promptId) {
      const stateKey = '__audiagenticPrePromptActivityState';
      const state = window[stateKey] instanceof WeakMap
        ? window[stateKey]
        : (window[stateKey] = new WeakMap());
      const digest = activityStateDigest(latestFallbackActivityBeforePrompt);
      const prior = state.get(latestFallbackActivityBeforePrompt);
      if (prior && prior.promptId === promptId && prior.digest !== digest) {
        fallbackActivityOwnerPromptMessageId = promptId;
      }
      state.set(latestFallbackActivityBeforePrompt, {promptId, digest});
    }
  }
  const fallbackActivityOwnerFor = node => {
    if (!fallbackActivityOwnerPromptMessageId || !latestFallbackActivityBeforePrompt || !node) return null;
    return node === latestFallbackActivityBeforePrompt ||
      latestFallbackActivityBeforePrompt.contains(node) ||
      node.contains(latestFallbackActivityBeforePrompt)
      ? fallbackActivityOwnerPromptMessageId
      : null;
  };
  const ownerPromptFor = node => {
    const fallbackOwner = fallbackActivityOwnerFor(node);
    if (fallbackOwner) return fallbackOwner;
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
    const fallbackOwner = fallbackActivityOwnerFor(node);
    if (fallbackOwner) return fallbackOwner;
    for (let index = progressUserEntries.length - 1; index >= 0; index--) {
      const entry = progressUserEntries[index];
      if (entry.el === node || entry.el.contains(node)) return entry.messageId;
      const relation = entry.el.compareDocumentPosition(node);
      if (relation & Node.DOCUMENT_POSITION_FOLLOWING) return entry.messageId;
    }
    return null;
  };
  // `error-alert` is document-scoped and can survive from an earlier turn.
  // Keep a bounded occurrence projection so the Python turn can distinguish a
  // new alert from a stale one without receiving alert text or DOM handles.
  const errorAlertSpec = signalSpecs.find(spec => spec.name === "error-alert");
  const errorAlertOccurrences = [];
  if (errorAlertSpec) {
    const structuralOwnerFor = node => {
      // Document-global alerts have no structural owner. Only claim an owner
      // inside one bounded turn/message wrapper containing exactly one prompt;
      // DOM order alone is not ownership proof.
      const wrapper = node.closest('[data-turn-key], .agent-turn, .block-BQZwFn, article');
      if (!wrapper) return null;
      const owners = progressUserEntries.filter(entry => wrapper.contains(entry.el));
      return owners.length === 1 ? owners[0].messageId : null;
    };
    const matchingAlerts = Array.from(document.querySelectorAll('[role="alert"]'))
      .filter(element => {
        if (errorAlertSpec.visible && !shown(element)) return false;
        const content = (element.innerText || element.textContent || "").trim();
        const fragments = errorAlertSpec.textContainsAny || [];
        const exact = errorAlertSpec.textEqualsAny || [];
        if (exact.length && exact.some(fragment => content === String(fragment).trim())) return true;
        if (!fragments.length) return !exact.length;
        const lowered = content.toLowerCase();
        return fragments.some(fragment => lowered.includes(String(fragment).toLowerCase()));
      })
      .slice(-32);
    matchingAlerts.forEach(element => {
      const ownerPromptMessageId = structuralOwnerFor(element);
      const content = String(element.innerText || element.textContent || "")
        .replace(/\s+/g, " ").trim().slice(0, 2048);
      const attrs = Array.from(element.attributes || [])
        .filter(attribute => attribute.name !== "class" && attribute.name !== "style")
        .map(attribute => `${attribute.name}=${String(attribute.value).slice(0, 160)}`)
        .sort();
      errorAlertOccurrences.push({
        // Identity deliberately excludes ownerPromptMessageId. Ownership is
        // recomputed from the current DOM and must not turn a stale alert
        // into a new occurrence merely because a later prompt was inserted.
        // Use a position-independent semantic signature. Python compares the
        // resulting projections as a multiset/count delta, so reordering or
        // inserting a foreign alert cannot rename a stale occurrence.
        digest: progressDigestParts(["error-alert", content, ...attrs]),
        ownerPromptMessageId: ownerPromptMessageId || null
      });
    });
  }
  // A live GPT-auto turn can briefly expose only an unlabeled fallback block:
  // the renderer has mounted visible Thinking/tool activity, but has not yet
  // assigned either a role node or the "ChatGPT said:" label. Keep that
  // newest block as a provisional DOM root so progress renews the lease. It
  // cannot claim prompt ownership (ownerPromptIdFor remains null) and is
  // therefore never sufficient evidence for completion or failure.
  const domActivityRoot = latestAgentTurn || assistantTurn ||
    latestFallbackActivityBlock || fallbackBlocks.slice(-1)[0] || null;
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
  // The labelled renderer places its response action bar next to the
  // block-list, not inside the assistant block. Admit only a direct sibling
  // toolbar whose bounded wrapper ends with this exact latest assistant.
  let fallbackResponseControls = null;
  if (usingFallbackMessages && latestAssistant && !fallbackHasUnansweredPrompt) {
    // The fallback renderer has used three action-bar placements in live DOMs:
    // a direct sibling of the message list, a descendant of the assistant
    // block, and (2026-09) a descendant of the outer turn wrapper.  The user
    // block can have its own "Copy message" bar, so a document-wide query is
    // unsafe. Walk only ancestors of the latest assistant and choose a control
    // bar that is inside/after that assistant; this binds the bar to the
    // response without assuming one renderer-specific depth.
    let wrapper = latestAssistant;
    for (let depth = 0; wrapper && depth < 8; depth++, wrapper = wrapper.parentElement) {
      const controls = Array.from(wrapper.querySelectorAll('.turn-action-controls')).filter(control => {
        // A user block can be inside the same ancestor and carries its own
        // Copy message / Edit message toolbar.  Select only a bar that has
        // an assistant-response action, otherwise the first user toolbar
        // masks the sibling response controls and completion evidence stays
        // false even though the tab is visibly finished.
        const labels = Array.from(control.querySelectorAll('button')).map(button =>
          String(button.getAttribute('aria-label') || button.innerText || '').trim().toLowerCase()
        );
        return labels.some(label => ['copy', 'more actions', 'regenerate response', 'read aloud'].includes(label));
      }).find(control => {
        if (latestAssistant.contains(control)) return true;
        return Boolean(latestAssistant.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      if (controls) { fallbackResponseControls = controls; break; }
    }
  }
  const documentTextFailureSignals = new Set([
    "conversation-load-failed",
    "network-error-alert",
    "stream-cache-expired"
  ]);
  const textMatchesSignal = (element, spec) => {
    const fragments = spec.textContainsAny || [];
    const exact = spec.textEqualsAny || [];
    const content = (element.innerText || element.textContent || "").trim();
    if (exact.length && exact.some(fragment => content === String(fragment).trim())) return true;
    if (!fragments.length) return !exact.length;
    const lowered = content.toLowerCase();
    return fragments.some(fragment => lowered.includes(String(fragment).toLowerCase()));
  };
  const outsideMessageTextMatches = (spec, selectors) => {
    const messageNodes = messageEntries.map(entry => entry.el);
    const candidates = new Set();
    for (const selector of selectors) {
      for (const root of document.querySelectorAll(selector)) {
        candidates.add(root);
        root.querySelectorAll("*").forEach(element => candidates.add(element));
      }
    }
    return Array.from(candidates).some(element => {
      if (spec.visible && !shown(element)) return false;
      // Provider failure text rendered outside the conversation is actionable;
      // the same words inside a submitted prompt or assistant response are not.
      if (messageNodes.some(message => message === element || message.contains(element))) return false;
      if (messageNodes.some(message => element.contains(message))) return false;
      return textMatchesSignal(element, spec);
    });
  };
  for (const spec of signalSpecs) {
    const completionAction = spec.name === 'completion-control' || spec.name === 'more-actions-menu';
    const root = spec.scope === "latest-assistant-turn"
      ? (completionAction && fallbackResponseControls ? fallbackResponseControls : assistantTurn)
      : document;
    // ChatGPT currently leaves `.streaming-animation` on completed assistant
    // messages.  It describes the renderer, not an active generation, so it
    // must never be allowed to make the provider appear busy during resume.
    const selectors = spec.name === "streaming-indicator"
      ? spec.selectors.filter(selector => selector !== ".streaming-animation")
      : spec.selectors;
    domSignals[spec.name] = documentTextFailureSignals.has(spec.name) && spec.scope === "document"
      ? outsideMessageTextMatches(spec, selectors)
      : !!root && selectors.some(selector =>
          Array.from(root.querySelectorAll(selector)).some(el => {
            if (spec.visible && !shown(el)) return false;
            return textMatchesSignal(el, spec);
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
  const MARKDOWN_MAX_CHARS = 200000;
  const longestRun = (value, character) => {
    let longest = 0, current = 0;
    for (const ch of String(value || "")) {
      if (ch === character) { current += 1; longest = Math.max(longest, current); }
      else current = 0;
    }
    return longest;
  };
  const normalizeInlineText = value => String(value || "").replace(/\u00a0/g, " ").replace(/[ \t\r\n\f\v]+/g, " ");
  const escapeMarkdownText = value => normalizeInlineText(value).replace(/\\/g, "\\\\").replace(/([*_~\[\]#>])/g, "\\$1");
  const safeHref = raw => {
    const href = String(raw || "").trim();
    return href && !/^(?:javascript|data|vbscript):/i.test(href) ? href : null;
  };
  const codeFence = code => "`".repeat(Math.max(3, longestRun(code, "`") + 1));
  const inlineCode = code => {
    const raw = String(code || ""), delimiter = "`".repeat(Math.max(1, longestRun(raw, "`") + 1));
    const pad = raw.startsWith("`") || raw.endsWith("`") ? " " : "";
    return delimiter + pad + raw + pad + delimiter;
  };
  const blockTag = tag => new Set(["P","H1","H2","H3","H4","H5","H6","PRE","UL","OL","BLOCKQUOTE","HR","TABLE"]).has(tag);
  const directChildren = (element, tag) => Array.from(element.children).filter(child => child.tagName === tag);
  const languageForPre = pre => {
    const code = pre.querySelector("code"), candidates = [code?.getAttribute("data-language"), pre.getAttribute("data-language"), ...Array.from(code?.classList || []).filter(n => n.startsWith("language-")).map(n => n.slice(9))];
    const language = candidates.find(v => /^[A-Za-z0-9_+.#-]{1,64}$/.test(String(v || "")));
    return language ? String(language) : "";
  };
  const normalizeMarkdown = value => String(value || "").split("\n").map(line => line.replace(/[ \t]+$/g, "")).join("\n").replace(/\n{3,}/g, "\n\n").trim();
  const assistantMarkdown = element => {
    if (!element) return null;
    try {
      const root = element.cloneNode(true);
      root.querySelectorAll('h4.sr-only, button, [role="button"], [data-markdown-copy="exclude"]').forEach(node => node.remove());
      root.querySelectorAll('[aria-hidden="true"]').forEach(node => { if (String(node.innerText || node.textContent || "").trim() === "…") node.remove(); });
      let renderList, renderChildren;
      const renderInline = node => {
        if (node.nodeType === Node.TEXT_NODE) return escapeMarkdownText(node.nodeValue || "");
        if (node.nodeType !== Node.ELEMENT_NODE) return "";
        const el = node, tag = el.tagName;
        if (tag === "BR") return "\n";
        if (tag === "CODE" && el.parentElement?.tagName !== "PRE") return inlineCode(el.textContent || "");
        const inner = Array.from(el.childNodes).map(renderInline).join("");
        if (tag === "STRONG" || tag === "B") return inner ? "**" + inner + "**" : "";
        if (tag === "EM" || tag === "I") return inner ? "*" + inner + "*" : "";
        if (tag === "DEL" || tag === "S") return inner ? "~~" + inner + "~~" : "";
        if (tag === "A") { const href = safeHref(el.getAttribute("href")); const label = normalizeMarkdown(inner) || (href || ""); return href ? "[" + label + "](" + href + ")" : label; }
        return inner;
      };
      const renderListItem = (li, ordered, index, depth) => {
        const nested = Array.from(li.children).filter(child => child.tagName === "UL" || child.tagName === "OL"), clone = li.cloneNode(true);
        Array.from(clone.children).forEach(child => { if (child.tagName === "UL" || child.tagName === "OL") child.remove(); });
        const head = normalizeMarkdown(Array.from(clone.childNodes).map(renderInline).join("")), prefix = ordered ? String(index + 1) + ". " : "- ", lines = ["  ".repeat(depth) + prefix + head];
        for (const child of nested) lines.push(renderList(child, depth + 1));
        return lines.filter(Boolean).join("\n");
      };
      renderList = (list, depth = 0) => (list.tagName === "OL" ? directChildren(list, "LI") : directChildren(list, "LI")).map((li, index) => renderListItem(li, list.tagName === "OL", index, depth)).filter(Boolean).join("\n");
      const renderTable = table => {
        const rows = Array.from(table.querySelectorAll("tr")); if (!rows.length) return "";
        const cells = row => Array.from(row.querySelectorAll(":scope > th, :scope > td")).map(cell => normalizeMarkdown(Array.from(cell.childNodes).map(renderInline).join("")).replace(/\n+/g, " ").replace(/\|/g, "\\|"));
        const headRow = table.querySelector("thead tr") || rows[0], head = cells(headRow); if (!head.length) return "";
        const body = rows.filter(row => row !== headRow && !row.closest("thead")), fit = values => Array.from({length: head.length}, (_, i) => values[i] || "");
        return ["| " + fit(head).join(" | ") + " |", "| " + Array(head.length).fill("---").join(" | ") + " |", ...body.map(row => "| " + fit(cells(row)).join(" | ") + " |")].join("\n");
      };
      const renderBlock = node => {
        if (node.nodeType === Node.TEXT_NODE) return normalizeMarkdown(renderInline(node));
        if (node.nodeType !== Node.ELEMENT_NODE) return "";
        const el = node, tag = el.tagName;
        if (/^H[1-6]$/.test(tag)) return "#".repeat(Number(tag[1])) + " " + normalizeMarkdown(Array.from(el.childNodes).map(renderInline).join(""));
        if (tag === "P") return normalizeMarkdown(Array.from(el.childNodes).map(renderInline).join(""));
        if (tag === "PRE") { const code = el.querySelector("code")?.textContent ?? el.textContent ?? "", fence = codeFence(code); return fence + languageForPre(el) + "\n" + code.replace(/\n$/, "") + "\n" + fence; }
        if (tag === "UL" || tag === "OL") return renderList(el);
        if (tag === "BLOCKQUOTE") return renderChildren(el).split("\n").map(line => line ? "> " + line : ">").join("\n");
        if (tag === "HR") return "---";
        if (tag === "TABLE") return renderTable(el);
        return renderChildren(el);
      };
      renderChildren = parent => { const parts = [], flush = () => { const normalized = normalizeMarkdown(inline); if (normalized) parts.push(normalized); inline = ""; }; let inline = ""; for (const child of parent.childNodes) { if (child.nodeType === Node.ELEMENT_NODE && blockTag(child.tagName)) { flush(); const block = normalizeMarkdown(renderBlock(child)); if (block) parts.push(block); } else inline += renderInline(child); } flush(); return parts.join("\n\n"); };
      const markdown = normalizeMarkdown(renderChildren(root));
      return markdown && markdown.length <= MARKDOWN_MAX_CHARS ? markdown : null;
    } catch (_) { return null; }
  };
  const messageRefs = messageEntries.map((m, sequence) => ({
    role: m.role,
    messageId: m.messageId,
    text: m.role === "user" ? userText(m.el) : assistantText(m.el),
    ...(m.role === "assistant" ? {markdown: assistantMarkdown(m.el)} : {}),
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
    errorAlertOccurrences,
    errorPresent: !!document.querySelector('.error-page, [data-testid*="error"]')
  };
}
"""

# Module-level so browser-fixture tests can evaluate the exact production
# logic (mirrors _SNAPSHOT_FN above) instead of re-deriving it inline.
_RETRY_DELIVERY_TIMEOUT_FN = r"""() => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const isRetryButton = candidate => {
    if (candidate.disabled || !candidate.getClientRects().length) return false;
    const text = normalize(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label'));
    // Keep the exact retry-text guard explicit: text !== 'retry' must never
    // be treated as a provider recovery control.
    return text === 'retry';
  };
  const attributeCandidates = Array.from(document.querySelectorAll(
    'button[data-testid="regenerate-thread-error-button"], button[aria-label="Retry"], button[data-testid*="regenerate"][data-testid*="error"]'
  ));
  let button = attributeCandidates.find(isRetryButton);
  if (!button) {
    // The current renderer's Retry control has neither aria-label nor
    // data-testid (live-captured 2026-09-27 as a stuck "ChatGPT stream
    // recovery polling timed out" alert), so it cannot be found by button
    // attributes at all. Identify the alert by its own known message text
    // instead of matching any role="alert" button generically -- a
    // generic match would also fire on an unrelated alert's differently
    // meant Retry-labelled control, and the exact-text guard alone cannot
    // tell the two apart. Only the exact-text "retry" button inside this
    // specific, identified alert is ever clicked.
    const knownDeliveryMessages = [
      'stream recovery polling timed out',
      'resume stream unavailable',
    ];
    const knownAlert = Array.from(document.querySelectorAll('[role="alert"]')).find(alert => {
      const text = normalize(alert.innerText || alert.textContent);
      return knownDeliveryMessages.some(message => text.includes(message));
    });
    if (knownAlert) {
      button = Array.from(knownAlert.querySelectorAll('button')).find(isRetryButton);
    }
  }
  if (!button) return false;
  button.click();
  return true;
}"""


_RETRY_CONVERSATION_LOAD_FN = r"""() => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const loadText = 'could not load this chatgpt conversation';
  const bodyText = normalize(document.body && (document.body.innerText || document.body.textContent));
  const structuralRoots = Array.from(document.querySelectorAll(
    '.error-page, [role="alert"], [data-testid*="error"]'
  )).filter(root => root.getClientRects().length);
  const errorRoots = structuralRoots.filter(root => {
    const text = normalize(root.innerText || root.textContent);
    return text.includes(loadText);
  });
  let retryRoot = null;
  if (errorRoots.length === 1) {
    retryRoot = errorRoots[0];
  } else if (errorRoots.length === 0) {
    // Some current renderer revisions expose only body text. Allow that
    // fallback only when the exact provider message occurs once and no
    // conversation-message node owns the text; never use a generic body-wide
    // match when transcript content could be the source.
    const occurrences = bodyText.split(loadText).length - 1;
    const messageNodes = Array.from(document.querySelectorAll(
      '[data-message-author-role], [data-testid*="conversation-turn"], article, main'
    ));
    const transcriptMatch = messageNodes.some(node =>
      normalize(node.innerText || node.textContent).includes(loadText)
    );
    if (occurrences === 1 && !transcriptMatch) retryRoot = document.body;
  }
  if (!retryRoot) return false;
  const buttons = Array.from(retryRoot.querySelectorAll('button')).filter(candidate => {
    if (candidate.disabled || !candidate.getClientRects().length) return false;
    const text = normalize(candidate.innerText || candidate.textContent || candidate.getAttribute('aria-label'));
    return text === 'retry';
  });
  if (buttons.length !== 1) return false;
  buttons[0].click();
  return true;
}"""

class GptAutoCdpBrowserController(CdpBrowserController):
    """ChatGPT-specific selectors, composites, and conversation operations."""

    _ACTION_PAUSE_SECONDS = 0.15  # compatibility default; resolved config overrides it
    _PAGE_READY_PAUSE_SECONDS = 1.0
    _TYPED_PAUSE_SECONDS = 1.0

    def __init__(
        self, bridge: PythonCdpBridge, *, action_pause_seconds: float | None = None
    ) -> None:
        super().__init__(bridge)
        self._action_pause_seconds = max(
            0.0,
            float(
                self._ACTION_PAUSE_SECONDS
                if action_pause_seconds is None
                else action_pause_seconds
            ),
        )

        self._project_open_lock = asyncio.Lock()

    async def wait_for_composer(self, page: CdpPageRef, *, timeout: float) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        next_retry_probe = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            # Do not run the full message/activity snapshot as a readiness
            # probe. Project landing pages can contain a large history, and a
            # full DOM walk can time out even while the composer is already
            # interactive. The first authoritative turn snapshot happens after
            # admission and remains responsible for identity/activity proof.
            readiness = await self.evaluate(page, _COMPOSER_READY_FN)
            if (
                isinstance(readiness, dict)
                and readiness.get("composerPresent")
                and readiness.get("composerEditable")
                and readiness.get("visible")
            ):
                return readiness
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
        result = await self.evaluate(page, _RETRY_DELIVERY_TIMEOUT_FN)
        return bool(result)

    async def retry_conversation_load(self, page: CdpPageRef) -> bool:
        """Click the provider conversation-load Retry control only."""
        result = await self.evaluate(page, _RETRY_CONVERSATION_LOAD_FN)
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
    # A successful Send click can navigate the ChatGPT SPA before CDP returns
    # the Runtime.evaluate result. Do not let a lost acknowledgement consume
    # the turn-scale submission timeout: the caller must reconcile the now
    # ambiguous send against authoritative DOM state without clicking again.
    _SEND_CLICK_ACK_TIMEOUT_SECONDS = 3.0
    # Give React's controlled composer a realistic render/input turn between
    # insertion and the synthetic Send click.  Keeping this outside the DOM
    # evaluator avoids batching both browser actions into one CDP task.
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
                # ChatGPT can expose an editable composer before the newly
                # selected project chat has completed its React mount. Keep a
                # human-scale boundary between page readiness and text input.
                stage = "composer-readiness"
                await asyncio.sleep(self._PAGE_READY_PAUSE_SECONDS)
                stage = "composer-insertion"
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
                # Let controlled-editor input settle before the Send control
                # is queried or clicked. This is deliberately independent of
                # the shorter generic browser-action pause.
                await asyncio.sleep(self._TYPED_PAUSE_SECONDS)
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
                    await asyncio.sleep(self._action_pause_seconds)
                    async with asyncio.timeout(self._SEND_CLICK_ACK_TIMEOUT_SECONDS):
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
                        # Let the provider renderer process the synthetic click
                        # before the caller takes its first submission-proof
                        # snapshot.  This is deliberately a small, configurable
                        # browser-action pause rather than a turn timeout: the
                        # click has already happened, and the next DOM read
                        # must not race React's route/message insertion.
                        await asyncio.sleep(self._action_pause_seconds)
                        return {"actionComplete": True, "typedText": typed,
                                "sendButtonClicked": True, "enterDispatched": False}
                    send_attempted = False
                    stage = "composer-readiness"
                    await asyncio.sleep(self._SUBMIT_POLL_SECONDS)
        except TimeoutError as exc:
            raise ComposerSubmissionTimeout(send_attempted=send_attempted, stage=stage) from exc

    async def find_project_url(self, page: CdpPageRef, project_name: str) -> dict[str, str]:
        """Discover a project URL only after proving the selected row identity."""
        projects_page = await self._open_projects_tab(page, timeout=12.0)
        if projects_page is not None:
            page = projects_page
        selection = await self._select_project_from_projects_page(
            page, project_name, timeout=12.0
        )
        selected_project_id = _selection_project_id(selection, None)
        if not selected_project_id:
            selection = await self._select_project_from_sidebar(
                page, project_name, expected_project_id=None, timeout=12.0
            )
            selected_project_id = _selection_project_id(selection, None)
        if not selected_project_id:
            raise RuntimeError(f"ChatGPT project identity could not be proven: {project_name}")
        for _ in range(120):
            current = await self.page_by_handle(page.handle)
            current_project_id = parse_project_id(current.url)
            if (
                re.match(r"^/g/g-p-[^/]+/project/?$", urlsplit(current.url).path)
                and current_project_id == selected_project_id
            ):
                return {"url": current.url, "name": project_name}
            await asyncio.sleep(0.1)
        raise RuntimeError(f"ChatGPT project selection did not open the selected project: {project_name}")
    async def _open_projects_tab(self, page: CdpPageRef, *, timeout: float) -> CdpPageRef | None:
        """Navigate directly to ChatGPT's complete Projects listing.

        Return the refreshed immutable page reference. The bridge may keep the
        same target handle while replacing its URL, so callers must not retain
        the pre-navigation ``CdpPageRef`` for diagnostics or later selection.
        """
        await self.bridge.call("keep_page_active", {"pageHandle": page.handle})
        await self.navigate(page, _CHATGPT_PROJECTS_URL)
        return await self._wait_for_projects_route(page, timeout=timeout)

    async def _select_project_from_sidebar(
        self,
        page: CdpPageRef,
        project_name: str,
        *,
        expected_project_id: str | None,
        timeout: float,
    ) -> bool:
        """Open one exact sidebar project using trusted pointer input.

        Project rows can appear under either Projects or Pinned. A collapsed
        project row is expanded at most once; if no exact visible project is
        present, the caller falls back to the complete Projects listing.
        """
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        expanded_once = False
        hovered_once = False
        last_observation: dict[str, Any] = {"action": "not-hydrated"}
        while asyncio.get_running_loop().time() < deadline:
            action = await self.evaluate(
                page,
                r"""(input) => {
                  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
                  const wanted = normalize(input.name).toLowerCase();
                  const canonicalProjectId = value => { const raw = normalize(value); const match = raw.match(/^(g-p-[0-9a-f]{32})(?:-.*)?$/i); return match ? match[1].toLowerCase() : raw; };
                  const expectedProjectId = canonicalProjectId(input.expectedProjectId);
                  const visible = element => {
                    if (!element || !element.getClientRects().length) return false;
                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  };
                  const point = element => {
                    const rect = element.getBoundingClientRect();
                    const x = rect.x + rect.width / 2;
                    const y = rect.y + rect.height / 2;
                    if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
                    return {x, y};
                  };
                  const safeRowPoint = row => {
                    const label = Array.from(row.querySelectorAll('span, div')).find(candidate =>
                      visible(candidate) && normalize(candidate.textContent).toLowerCase() === wanted
                        && !candidate.closest('button, a')
                    );
                    if (label) return point(label);
                    const rect = row.getBoundingClientRect();
                    const x = rect.x + Math.min(Math.max(24, rect.width * 0.25), Math.max(1, rect.width - 48));
                    const y = rect.y + rect.height / 2;
                    if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
                    return {x, y};
                  };
                   const rows = Array.from(document.querySelectorAll('[data-app-action-sidebar-project-row]'))
                     .filter(candidate => visible(candidate) && normalize(
                       candidate.getAttribute('data-app-action-sidebar-project-label')
                     ).toLowerCase() === wanted);
                   // A newly opened tab can expose the home shell before the
                   // authenticated sidebar has hydrated. Treat that as a
                   // transient render state and keep polling until the caller's
                   // bounded timeout; otherwise a slow but healthy project is
                   // falsely reported as not found and the request never gets
                   // as far as prompt submission.
                   if (!rows.length) return {action: 'waiting'};
                   const matchingRows = expectedProjectId
                     ? rows.filter(candidate => canonicalProjectId(
                         candidate.getAttribute('data-app-action-sidebar-project-id')
                       ) === expectedProjectId)
                     : rows;
                   if (matchingRows.length !== 1) {
                     return {action: expectedProjectId ? 'project-id-mismatch' : 'ambiguous'};
                   }
                   const row = matchingRows[0];
                   const actualProjectId = canonicalProjectId(
                     row.getAttribute('data-app-action-sidebar-project-id')
                   );
                   if (!actualProjectId) return {action: 'project-id-missing'};
                   if (expectedProjectId && actualProjectId !== expectedProjectId) {
                     return {action: 'project-id-mismatch', actualProjectId};
                   }
                   const button = Array.from(row.querySelectorAll('button')).find(candidate =>
                    visible(candidate) && normalize(candidate.getAttribute('aria-label')).toLowerCase() === `new chat in ${wanted}`
                  );
                  if (button) {
                    const clickPoint = point(button);
                    if (clickPoint && button.contains(document.elementFromPoint(clickPoint.x, clickPoint.y))) {
                      return {action: 'selected', projectId: actualProjectId, ...clickPoint};
                    }
                    const hoverPoint = safeRowPoint(row);
                    return hoverPoint ? {action: 'hover', ...hoverPoint} : {action: 'waiting'};
                  }
                  if (row.getAttribute('aria-expanded') !== 'true') {
                    const clickPoint = safeRowPoint(row);
                    return clickPoint ? {action: 'expand', ...clickPoint} : {action: 'waiting'};
                  }
                  return {action: 'waiting'};
                }""",
                {"name": project_name, "expectedProjectId": expected_project_id or ""},
            )
            action_name = action.get("action") if isinstance(action, dict) else None
            if isinstance(action, dict):
                last_observation = dict(action)
            if action_name == "hover":
                if hovered_once:
                    return {"action": "occluded", "last": last_observation}
                hovered_once = True
                await self.bridge.call("keep_page_active", {"pageHandle": page.handle})
                await self.bridge.call(
                    "hover",
                    {"pageHandle": page.handle, "x": action["x"], "y": action["y"]},
                )
                await asyncio.sleep(self._action_pause_seconds)
                continue
            if action_name in {"selected", "expand"}:
                if action_name == "expand" and expanded_once:
                    return {"action": "expand-not-effective", "last": last_observation}
                await self.bridge.call("keep_page_active", {"pageHandle": page.handle})
                await asyncio.sleep(self._action_pause_seconds)
                await self.bridge.call(
                    "click",
                    {"pageHandle": page.handle, "x": action["x"], "y": action["y"]},
                )
                if action_name == "selected":
                    return {"clicked": True, "projectId": _canonical_project_id(action.get("projectId"))}
                expanded_once = True
                await asyncio.sleep(max(self._PAGE_READY_PAUSE_SECONDS, self._action_pause_seconds))
                continue
            if action_name in {"missing", "project-id-mismatch", "project-id-missing", "ambiguous"}:
                return {"action": action_name, **({k: v for k, v in action.items() if k != "action"} if isinstance(action, dict) else {})}
            await asyncio.sleep(0.1)
        return {"action": "timeout", "last": last_observation}

    async def _wait_for_projects_route(self, page: CdpPageRef, *, timeout: float) -> CdpPageRef | None:
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while asyncio.get_running_loop().time() < deadline:
            try:
                current = await self.page_by_handle(page.handle)
            except Exception:  # noqa: BLE001 - navigation may replace the target briefly
                current = page
            if urlsplit(current.url).path.rstrip("/") == "/projects":
                return current
            await asyncio.sleep(0.1)
        return None

    async def _select_project_from_projects_page(
        self,
        page: CdpPageRef,
        project_name: str,
        *,
        expected_project_id: str | None = None,
        timeout: float,
    ) -> dict[str, Any] | None:
        """Select a project and return the canonical identity of its DOM row."""
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while asyncio.get_running_loop().time() < deadline:
            point = await self.evaluate(
                page,
                _PROJECT_NEW_CHAT_POINT_FN,
                {"name": project_name, "expectedProjectId": expected_project_id or ""},
            )
            if (
                isinstance(point, dict)
                and isinstance(point.get("x"), (int, float))
                and isinstance(point.get("y"), (int, float))
            ):
                project_id = _canonical_project_id(point.get("projectId"))
                await self.bridge.call("keep_page_active", {"pageHandle": page.handle})
                await asyncio.sleep(self._action_pause_seconds)
                await self.bridge.call(
                    "click",
                    {"pageHandle": page.handle, "x": point["x"], "y": point["y"]},
                )
                return {"clicked": True, "projectId": project_id}
            await asyncio.sleep(0.1)
        return None
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
        anchor_target_ids: set[str] | None = None
        if anchor_page:
            try:
                anchor_target_ids = {candidate.target_id for candidate in await self.pages()}
            except Exception:  # noqa: BLE001 - fresh-tab fallback remains safe
                logger.debug("gpt-auto could not baseline anchor window targets", exc_info=True)
        if anchor_page:
            # Same-window creation uses window.open on the dashboard anchor.
            # A stale/contended CDP session can block that attach for the
            # bridge's full command timeout even though a fresh browser target
            # is available. Keep the normal same-window path, but fail over
            # quickly to a fresh tab so request creation remains bounded.
            try:
                async with asyncio.timeout(min(5.0, max(0.1, navigation_timeout))):
                    page = await self.new_tab(in_window=anchor_page)
            except TimeoutError:
                logger.warning(
                    "gpt-auto dashboard anchor did not accept same-window tab creation; "
                    "falling back to a fresh browser tab"
                )
                await self._close_late_anchor_targets(anchor_page, anchor_target_ids)
                page = await self.new_tab()
        else:
            page = await self.new_window()
        try:
            startup_deadline = asyncio.get_running_loop().time() + max(0.1, navigation_timeout)
            remaining_startup = lambda: max(0.1, startup_deadline - asyncio.get_running_loop().time())
            async with asyncio.timeout(remaining_startup()):
                page = await self.navigate(page, _CHATGPT_HOME_URL)
            known_targets = {candidate.target_id for candidate in await self.pages()}
            fallback_bounds = "not-attempted"
            sidebar_selection = await self._select_project_from_sidebar(
                page,
                project_name,
                expected_project_id=expected_project_id,
                # Sidebar hydration, route navigation, and Projects-row
                # selection share one startup budget. A hydrated-but-absent
                # project must fall back promptly instead of paying three
                # independent full timeouts.
                timeout=remaining_startup(),
            )
            selection = sidebar_selection
            selected_project_id = _selection_project_id(selection, expected_project_id)
            projects_tab_opened = False
            selection_clicked = selection is True or (
                isinstance(selection, dict) and selection.get("clicked") is True
            )
            if not selection_clicked:
                # New-window CDP targets can inherit a compact browser window.
                # ChatGPT's full Projects page places its trusted New Chat
                # control at the far right, so ensure the fallback has a usable
                # viewport before asking the DOM for pointer coordinates.
                try:
                    await self.set_bounds(page, CdpWindowBounds(window_state="maximized"))
                    fallback_bounds = "succeeded"
                except Exception as exc:  # noqa: BLE001 - selection remains fail-closed
                    fallback_bounds = f"failed:{type(exc).__name__}"
                    logger.debug("gpt-auto could not maximize project fallback window", exc_info=True)
                projects_page_result = await self._open_projects_tab(
                    page, timeout=remaining_startup()
                )
                # Keep compatibility with test doubles and older bridge
                # implementations that returned only a boolean. Production
                # returns a refreshed CdpPageRef so diagnostics retain the
                # actual /projects URL.
                if isinstance(projects_page_result, CdpPageRef):
                    projects_page = projects_page_result
                elif projects_page_result is True:
                    projects_page = page
                else:
                    projects_page = None
                projects_tab_opened = projects_page is not None
                if not projects_page:
                    raise RuntimeError("ChatGPT Projects page did not become available")
                page = projects_page
                selection = await self._select_project_from_projects_page(
                    page,
                    project_name,
                    expected_project_id=expected_project_id,
                    timeout=remaining_startup(),
                )
                selected_project_id = _selection_project_id(selection, expected_project_id)
            selection_clicked = selection is True or (
                isinstance(selection, dict) and selection.get("clicked") is True
            )
            if not selection_clicked:
                raise RuntimeError(
                    f"ChatGPT project identity could not be proven: {project_name}; "
                    f"sidebar-selection={sidebar_selection!r}; "
                    f"projects-page-opened={projects_tab_opened!r}; "
                    f"projects-selection={selection!r}; "
                    f"fallback-bounds={fallback_bounds!r}; "
                    f"page-url={page.url!r}"
                )
            if expected_project_id and selected_project_id and selected_project_id != expected_project_id:
                raise RuntimeError("selected ChatGPT Project does not match configured project identity or selected row")

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
                fresh_candidates = [
                    candidate
                    for candidate in await self.pages()
                    if candidate.target_id not in known_targets
                ]
                fresh_candidates.sort(
                    key=lambda candidate: candidate.opener_id != source_page.target_id
                )
                candidates.extend(fresh_candidates)
                for candidate in candidates:
                    candidate_project_id = parse_project_id(candidate.url)
                    candidate_path = urlsplit(candidate.url).path
                    if (
                        candidate_project_id is None
                        or not re.match(r"^/g/g-p-[^/]+/project/?$", candidate_path)
                    ):
                        continue
                    if (
                        (selected_project_id and candidate_project_id != selected_project_id)
                        or (expected_project_id and candidate_project_id != expected_project_id)
                    ):
                        observed_wrong_project = True
                        if candidate.target_id != source_page.target_id:
                            wrong_project_pages[candidate.handle] = candidate
                        continue
                    # A Projects row may have no id/link at all. The
                    # provider-owned landing URL is the first authoritative
                    # identity witness in that case; never derive the id from
                    # the display name.
                    if selected_project_id is None:
                        selected_project_id = candidate_project_id
                    page = candidate
                    selected_url = candidate.url
                    break
                if selected_url:
                    break
                await asyncio.sleep(0.1)
            if not selected_url:
                if observed_wrong_project:
                    raise RuntimeError(
                        "selected ChatGPT Project does not match configured project identity or selected row"
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

    async def _close_late_anchor_targets(
        self, anchor_page: CdpPageRef, known_target_ids: set[str] | None
    ) -> None:
        """Close only proven-late blank targets left by a timed-out ``window.open``.

        A failed baseline enumeration is unknown, not an empty baseline: doing
        destructive cleanup in that case could close a pre-existing blank tab.
        A short bounded grace period catches a target whose creation completes
        just after the outer CDP command timeout.
        """
        if known_target_ids is None:
            return
        seen: set[str] = set()
        for scan in range(3):
            try:
                candidates = await self.pages()
            except Exception:  # noqa: BLE001 - cleanup is best effort
                logger.debug("gpt-auto could not enumerate late anchor targets", exc_info=True)
                return
            for candidate in candidates:
                if candidate.target_id in known_target_ids or candidate.target_id in seen:
                    continue
                if candidate.opener_id != anchor_page.target_id:
                    continue
                if candidate.url not in {"", "about:blank"}:
                    continue
                seen.add(candidate.target_id)
                try:
                    await self.close(candidate)
                except Exception:  # noqa: BLE001 - isolate one late target
                    logger.debug(
                        "gpt-auto failed to close late blank anchor target",
                        extra={"target-id": candidate.target_id},
                        exc_info=True,
                    )
            if scan < 2:
                await asyncio.sleep(0.2)


__all__ = ["GptAutoCdpBrowserController", "CdpPageRef", "CdpWindowBounds"]