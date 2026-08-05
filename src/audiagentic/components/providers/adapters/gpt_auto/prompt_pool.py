"""Pool of realistic prompts for gpt-auto testing.

Reusing the same obvious test prompt ("What is the capital of France?")
repeatedly is a bot-detection tell.  This module provides a large pool of
natural, developer-flavoured prompts drawn at random (never reused in a
predictable cycle), plus a plan-item review prompt generator for starting
fresh conversations, with graceful fallback to the local pool.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

# Curated pool of realistic prompts.  Drawing at random looks like a human
# using the tool for varied tasks rather than a harness hitting one canned
# string.  Categories keep follow-ups on-topic.
_PROMPT_POOL: list[tuple[str, list[str]]] = [
    (
        "code-review",
        [
            "What are the common pitfalls when naming Python functions?",
            "Review this idea: should helper utilities live in a shared module or be duplicated per component?",
            "What's a good way to structure configuration files for a multi-provider CLI tool?",
            "When is it appropriate to introduce an abstract base class versus a protocol?",
            "What should a linter catch that a type checker cannot?",
            "Explain the trade-off between dataclasses and Pydantic models for internal tooling.",
            "What is a good signature for a function that runs browser automation with a timeout?",
            "How would you lay out a Python package with an adapter layer for multiple providers?",
        ],
    ),
    (
        "planning",
        [
            "Draft a short design for a component that records release ledger events.",
            "What steps would you take to make a test suite resilient to network flakiness?",
            "Sketch a plan for migrating a project from one provider to another behind a common interface.",
            "How should we sequence enabling an MCP server in a staging environment?",
            "Outline a validation strategy for a headless browser integration.",
            "What belongs in a plan item versus a review for a multi-session implementation?",
        ],
    ),
    (
        "debugging",
        [
            "What are the usual causes of an event loop being busy inside an asyncio CDP client?",
            "A script passes locally but fails in CI with a timeout — what should we check first?",
            "How do you debug a React app where dispatched keyboard events are ignored?",
            "What does it mean when a browser page navigates but the previous execution context is gone?",
            "Suggest a way to diagnose flaky text extraction from a streaming chat UI.",
        ],
    ),
    (
        "architecture",
        [
            "Compare executing a CLI command versus driving a browser over CDP for a chatbot provider.",
            "When should a job queue be introduced over plain synchronous execution?",
            "How would you keep provenance metadata through a chain of plan and ledger records?",
            "What are the trade-offs of keeping browser state persistent across agent runs?",
            "Describe how you'd design a configuration layer with profile overrides.",
        ],
    ),
    (
        "general",
        [
            "Summarize the benefits of a release ledger that is authoritative over release notes.",
            "What makes good automated test feedback when a browser automation step fails?",
            "Explain why typing speed variability matters for automated browser interactions.",
            "How would you log a long-running conversation so a human can pick it up later?",
            "What's the value of keeping session and conversation identifiers in job metadata?",
        ],
    ),
]

_FLAT_POOL = [p for _cat, prompts in _PROMPT_POOL for p in prompts]


def pool_size() -> int:
    return len(_FLAT_POOL)


def pick_prompt(category: str | None = None) -> str:
    """Return a random prompt from the pool.

    Selection is fully random so consecutive runs do not repeat the same
    prompts (the old itertools.cycle restarted every process and always
    produced the same first two prompts).

    ``category`` restricts to one topic category.
    """
    pool = _FLAT_POOL
    if category:
        pool = [p for cat, prompts in _PROMPT_POOL if cat == category for p in prompts]
        if not pool:
            pool = _FLAT_POOL
    return random.choice(pool)


def pick_plan_review_prompt(
    planning_root: str | None = None,
    max_chars: int = 2000,
) -> str:
    """Return a prompt asking ChatGPT to review a random plan item.

    Globs ``docs/planning/active/**/*.md`` and ``docs/planning/completed/**/*.md``,
    picks one at random, and builds a self-contained review prompt from the
    item's full body (all sections, minus YAML frontmatter).  ChatGPT is a pure
    chat provider with no repo access, so every detail it needs must be in the
    prompt.  Falls back to a pool prompt when no plan items are found.  This
    gives each run a fresh, meaningful review task instead of a repeated canned
    prompt.
    """
    root = Path(planning_root) if planning_root else None
    if root is None:
        # Default: repo docs/planning relative to this package's project root.
        # audiagentic.__file__ = <repo>/src/audiagentic/__init__.py → three
        # parents up lands on the repo root.
        import audiagentic
        root = Path(audiagentic.__file__).resolve().parent.parent.parent / "docs" / "planning"

    candidates: list[Path] = []
    for sub in ("active", "completed"):
        base = root / sub
        if base.exists():
            candidates.extend(p for p in base.glob("**/*.md") if _is_plan_item(p))

    if not candidates:
        logger.warning("No plan items found under %s — using pool prompt", root)
        return pick_prompt()

    item = random.choice(candidates)
    title, body = _read_plan_item(item)
    if not title:
        return pick_prompt()

    prompt = (
        "Review the following plan item for technical soundness, risks, and "
        "missing validation. Point out anything that would block implementation, "
        "and suggest what tests would prove it works.\n\n"
        f"Plan item: {title}"
    )
    if body:
        prompt += f"\n\n{body[:max_chars]}"
    return prompt


def _is_plan_item(path) -> bool:
    name = path.stem
    return not name.lower().startswith(("template", "readme", "creating"))


def _read_plan_item(path) -> tuple[str, str]:
    """Extract the markdown H1 title and the full body (all sections).

    The body is everything after the frontmatter block, with the frontmatter
    itself removed.  Sections use ``## Heading`` so the whole item (Goal, Work,
    Validation, Acceptance criteria, …) is included — not just a Description
    section that many items don't have.  Returns ``("", "")`` on read failure.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    lines = text.splitlines()

    # Strip the YAML frontmatter block
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                lines = lines[idx + 1:]
                break

    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if line.startswith("# "):
            in_body = True
            continue
        if in_body:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return title, body


async def fetch_random_online_prompt(
    timeout: float = 5.0,
    max_chars: int = 200,
) -> str | None:
    """Fetch a random natural-language text from an online source.

    Returns None (caller falls back to the local pool) on any failure or if
    the fetched text is unusable.  Uses an asyncio-safe fetch; if the request
    library is unavailable, degrades to None.
    """
    sources = [
        "https://api.quotable.io/random",
        "https://api.adviceslip.com/advice",
    ]
    for url in sources:
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
            text = _extract_online_text(url, payload)
            if text and 20 < len(text) <= max_chars:
                return text
        except Exception as exc:  # noqa: BLE001 - any source failure is a fallback
            logger.debug("online prompt source %s failed: %s", url, exc)
    return None


def _extract_online_text(url: str, payload: str) -> str | None:
    """Best-effort extraction of a sentence from a JSON API payload."""
    import json

    try:
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        return None

    if isinstance(data, dict):
        if "content" in data and isinstance(data["content"], str):
            return data["content"].strip()
        if "slip" in data and isinstance(data["slip"], dict):
            advice = data["slip"].get("advice")
            if isinstance(advice, str):
                return advice.strip()
        for key in ("text", "quote", "sentence", "prompt"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
