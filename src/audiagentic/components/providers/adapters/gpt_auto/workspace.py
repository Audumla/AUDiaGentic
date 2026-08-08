"""Project management for ChatGPT — find or create workspace by project name."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from . import tab_state

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceInfo:
    """Information about a ChatGPT workspace (project)."""

    name: str
    url: str

    @property
    def session_id(self) -> str:
        """Unique identifier for this chat session.

        On the /project new-chat page, this is the workspace URL itself.
        Once a conversation is created, ChatGPT may assign a /c/{conv-id}.
        Either way, this value uniquely identifies the session for logging
        and persistent agent tracking.

        E.g. https://chatgpt.com/g/g-p-{id}-{slug}/project  → {id}
             https://chatgpt.com/g/g-p-{id}-{slug}/c/{conv}  → {conv}
        """
        if "/c/" in self.url:
            return self.url.split("/c/")[-1].rstrip("/")
        # On /project page, use the workspace g-p- segment as session ID
        if "/g/g-p-" in self.url:
            rest = self.url.split("/g/g-p-")[1]
            return f"ws-{rest.split('/')[0]}"  # g-p-{id}-{slug}
        return "unknown"

    @property
    def conversation_id(self) -> str | None:
        """Extract the conversation ID from the URL, if present.

        E.g. https://chatgpt.com/g/g-p-{id}-{slug}/c/{conv-id} → {conv-id}
             https://chatgpt.com/g/g-p-{id}-{slug}/project       → None (new chat)
        """
        if "/c/" in self.url:
            return self.url.split("/c/")[-1].rstrip("/")
        return None


def is_in_workspace(url: str) -> bool:
    """Return True if the URL is inside a ChatGPT workspace."""
    return "/g/g-p-" in url


def workspace_base_url(url: str) -> str:
    """Extract the workspace root URL — everything up to and including the g-p- segment.

    E.g. https://chatgpt.com/g/g-p-{id}-{slug}/project → https://chatgpt.com/g/g-p-{id}-{slug}
         https://chatgpt.com/g/g-p-{id}-{slug}/c/xxx     → https://chatgpt.com/g/g-p-{id}-{slug}
    """
    if "/g/g-p-" in url:
        # Everything up to the g-p- segment, then include just that segment (no /project, /c/, etc.)
        prefix = url.split("/g/g-p-")[0]
        rest = url.split("/g/g-p-")[1]
        # The g-p-{id}-{slug} is the next path component after "g-p-"
        g_p_segment = rest.split("/")[0]
        return f"{prefix}/g/g-p-{g_p_segment}"
    return url.rstrip("/")


def _resolve_target_url(base: str, conversation_id: str | None) -> str:
    """Compute the URL to navigate a reused tab to.

    ``base`` is the workspace root URL (…/g/g-p-{id}-{slug}).  With a
    conversation_id we continue that conversation; otherwise we land on the
    project's new-chat page (…/project).
    """
    if not base:
        return ""
    if conversation_id:
        return f"{base}/c/{conversation_id}"
    return f"{base}/project"


# ---------------------------------------------------------------------------
# JS snippets — verified against ChatGPT DOM (Aug 2026)
# ---------------------------------------------------------------------------

# Navigate to ChatGPT home page
_NAVIGATE_HOME_JS = """() => { window.location.href = 'https://chatgpt.com'; }"""

# Find a project row on the /projects page by name. Row text is concatenated
# without spaces (e.g. "AUDiaGenticPinnedApr 1Apr 1"), so we use substring match.
_FIND_PROJECT_ROW_JS = """(projectName) => {
    const main = document.querySelector('main');
    if (!main) return null;

    const rows = main.querySelectorAll('[role="row"]');
    for (const row of rows) {
        const text = row.textContent.trim();
        if (text.toLowerCase().includes(projectName.toLowerCase())) {
            const rect = row.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                return {
                    name: projectName,
                    centerX: Math.round(rect.x + rect.width / 2),
                    centerY: Math.round(rect.y + rect.height / 2),
                };
            }
        }
    }
    return null;
}"""


async def find_workspace(
    client: Any,
    project_name: str,
    conversation_id: str | None = None,
    project_root: Any = None,
) -> WorkspaceInfo | None:
    """Search for an existing ChatGPT workspace matching the project name.

    Reuses an already-open tab mapped to *project_name* (see tab_state) instead
    of always opening a fresh /projects tab.  Only when the mapped tab can no
    longer be re-found does it open a new one.

    Without a reusable tab: opens https://chatgpt.com/projects in a new tab,
    finds the project row by name, clicks it with a mouse click, then navigates
    to the workspace URL.  If we land on /project (project home), starts a new
    chat within the workspace so subsequent submissions are scoped to the
    project rather than free-floating.

    When ``conversation_id`` is provided, the workspace chat URL is rebuilt to
    ``/c/{conversation_id}`` so the same conversation is continued rather than
    starting a fresh chat.  Falls back to the project new-chat page (/project)
    if the conversation URL is unreachable.
    """
    # 1. Try to reuse a tab already mapped to this project
    mapped = (
        tab_state.get_mapping(project_name, project_root)
        if project_root is not None
        else tab_state.get_mapping(project_name)
    )
    if mapped and mapped.get("tab_id"):
        resumed = await client.activate_tab(mapped["tab_id"])
        if resumed:
            try:
                current_url = await client.get_url()
            except RuntimeError:
                current_url = ""
            # The tab is alive — navigate to the workspace (or the conversation)
            base = (
                workspace_base_url(current_url)
                if is_in_workspace(current_url)
                else mapped.get("workspace_url", "")
            )
            target = _resolve_target_url(base, conversation_id)
            if target and target != current_url:
                logger.info(
                    "Reusing mapped tab %s for '%s' -> %s", resumed.tab_id, project_name, target
                )
                await client.evaluate(f'() => {{ window.location.href = "{target}"; }}')
                # Event-based: waitForFunction on workspace URL match
                try:
                    await client.wait_for_function(
                        '() => window.location.href.includes("/g/g-p-")',
                        timeout_ms=10000,
                    )
                    final_url = await client.get_url()
                    if is_in_workspace(final_url):
                        return WorkspaceInfo(name=project_name, url=final_url)
                except Exception:
                    pass
                    # Fallback to polling (should rarely be needed)
                    for _ in range(20):
                        await asyncio.sleep(0.5)
                        try:
                            final_url = await client.get_url()
                        except RuntimeError:
                            final_url = ""
                        if is_in_workspace(final_url):
                            return WorkspaceInfo(name=project_name, url=final_url)
            else:
                # Already on the right page
                return WorkspaceInfo(name=project_name, url=current_url or base)
        else:
            logger.info(
                "Mapped tab %s for '%s' no longer exists — opening a new one",
                mapped["tab_id"],
                project_name,
            )

    # 2. Already in right workspace? Check by page title
    try:
        current_url = await client.get_url()
    except RuntimeError:
        current_url = ""

    if is_in_workspace(current_url):
        title = await client.evaluate("() => document.title;")
        if project_name.lower() in (title or "").lower():
            logger.info("Already in workspace '%s'", project_name)
            return WorkspaceInfo(name=project_name, url=workspace_base_url(current_url))

    # 3. Open /projects in a new tab
    logger.info("Opening /projects to find '%s'", project_name)
    tab = await client.new_tab("https://chatgpt.com/projects")

    # Wait for page to load
    await asyncio.sleep(3)

    url = await client.get_url()
    logger.debug("Projects page URL: %s", url)

    # 4. Find the project row and click it with a mouse click
    result = await client.evaluate(_FIND_PROJECT_ROW_JS, project_name)
    if not result:
        logger.warning("Project '%s' not found on /projects page", project_name)
        return None

    logger.info(
        "Found project '%s' at (%d, %d)", project_name, result["centerX"], result["centerY"]
    )

    # Click with mouse emulation (proper pointer event for React handler)
    await client.mouse_click(result["centerX"], result["centerY"])

    # Wait for navigation to workspace — stay on this tab, DON'T use find_tab
    # (find_tab switches back to the first ChatGPT tab and loses the navigation)
    # Event-based: waitForFunction on workspace URL match
    try:
        await client.wait_for_function(
            '() => window.location.href.includes("/g/g-p-")',
            timeout_ms=10000,
        )
    except Exception:
        # Fallback to polling (should rarely be needed)
        for _ in range(20):
            await asyncio.sleep(0.5)
            new_url = await client.get_url()
            if is_in_workspace(new_url):
                break

    # /project IS the project's new chat page — submitting from there creates a chat
    # scoped to this project.  No need to navigate anywhere else.
    final_url = await client.get_url()
    if is_in_workspace(final_url):
        # 5. Continue an existing conversation if one was requested
        if conversation_id:
            base = workspace_base_url(final_url)
            chat_url = f"{base}/c/{conversation_id}"
            logger.info("Resuming conversation %s at %s", conversation_id, chat_url)
            await client.evaluate(f'() => {{ window.location.href = "{chat_url}"; }}')
            # Event-based: waitForFunction on conversation URL match
            try:
                await client.wait_for_function(
                    f'() => window.location.href.includes("/c/{conversation_id}")',
                    timeout_ms=10000,
                )
                resumed_url = await client.get_url()
                if f"/c/{conversation_id}" in resumed_url:
                    return WorkspaceInfo(name=project_name, url=resumed_url)
            except Exception:
                # Fallback to polling
                for _ in range(20):
                    await asyncio.sleep(0.5)
                    try:
                        resumed_url = await client.get_url()
                    except RuntimeError:
                        resumed_url = ""
                    if f"/c/{conversation_id}" in resumed_url:
                        return WorkspaceInfo(name=project_name, url=resumed_url)
            logger.warning(
                "Could not reach conversation %s — falling back to project new chat",
                conversation_id,
            )
            return WorkspaceInfo(name=project_name, url=final_url)

        # Remember which tab holds this workspace so the next run reuses it
        if project_root is not None:
            tab_state.update_mapping(
                project_name,
                tab_id=tab.tab_id if hasattr(tab, "tab_id") else "",
                workspace_url=final_url,
                project_root=project_root,
            )
        logger.info("Workspace URL: %s", final_url)
        return WorkspaceInfo(name=project_name, url=final_url)

    return None


async def ensure_workspace(
    client: Any,
    project_name: str,
    conversation_id: str | None = None,
    project_root: Any = None,
) -> WorkspaceInfo | None:
    """Find a ChatGPT workspace for the given project name.

    If found, navigates to it from /projects.  When ``conversation_id`` is
    given, resumes that conversation; otherwise starts a new chat within the
    workspace.  Returns None if not found (workspace creation is unreliable
    via CDP — user must create manually).
    """
    logger.info("Ensuring ChatGPT workspace '%s'", project_name)

    ws = await find_workspace(
        client, project_name, conversation_id=conversation_id, project_root=project_root
    )
    if ws:
        return ws

    logger.warning("Workspace '%s' not found", project_name)
    return None
