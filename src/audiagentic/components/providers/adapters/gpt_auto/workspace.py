"""Project management for ChatGPT — find or create workspace by project name."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

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


async def find_workspace(client: Any, project_name: str) -> WorkspaceInfo | None:
    """Search for an existing ChatGPT workspace matching the project name.

    Opens https://chatgpt.com/projects in a new tab, finds the project row
    by name, clicks it with a mouse click, then navigates to the workspace URL.
    If we land on /project (project home), starts a new chat within the workspace
    so subsequent submissions are scoped to the project rather than free-floating.
    """
    # 1. Already in right workspace? Check by page title
    try:
        current_url = await client.get_url()
    except RuntimeError:
        current_url = ""

    if is_in_workspace(current_url):
        title = await client.evaluate("() => document.title;")
        if project_name.lower() in (title or "").lower():
            logger.info("Already in workspace '%s'", project_name)
            return WorkspaceInfo(name=project_name, url=workspace_base_url(current_url))

    # 2. Open /projects in a new tab
    logger.info("Opening /projects to find '%s'", project_name)
    await client.new_tab("https://chatgpt.com/projects")

    # Wait for page to load
    await asyncio.sleep(3)

    url = await client.get_url()
    logger.debug("Projects page URL: %s", url)

    # 3. Find the project row and click it with a mouse click
    result = await client.evaluate(_FIND_PROJECT_ROW_JS, project_name)
    if not result:
        logger.warning("Project '%s' not found on /projects page", project_name)
        return None

    logger.info("Found project '%s' at (%d, %d)", project_name, result["centerX"], result["centerY"])

    # Click with mouse emulation (proper pointer event for React handler)
    await client.mouse_click(result["centerX"], result["centerY"])

    # Wait for navigation to workspace — stay on this tab, DON'T use find_tab
    # (find_tab switches back to the first ChatGPT tab and loses the navigation)
    for _ in range(20):
        await asyncio.sleep(0.5)
        new_url = await client.get_url()
        if is_in_workspace(new_url):
            break

    # /project IS the project's new chat page — submitting from there creates a chat
    # scoped to this project.  No need to navigate anywhere else.
    final_url = await client.get_url()
    if is_in_workspace(final_url):
        logger.info("Workspace URL: %s", final_url)
        return WorkspaceInfo(name=project_name, url=final_url)

    return None


async def ensure_workspace(client: Any, project_name: str) -> WorkspaceInfo | None:
    """Find a ChatGPT workspace for the given project name.

    If found, navigates to it from /projects and starts a new chat within the
    workspace.  Returns None if not found (workspace creation is unreliable
    via CDP — user must create manually).
    """
    logger.info("Ensuring ChatGPT workspace '%s'", project_name)

    ws = await find_workspace(client, project_name)
    if ws:
        return ws

    logger.warning("Workspace '%s' not found", project_name)
    return None
