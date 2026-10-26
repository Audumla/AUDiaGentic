"""Admission-time materialisation of a global agent prompt definition."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.components.agents.models.prompt_definition import (
    PromptDefinition,
    PromptFilePart,
    PromptIncludePart,
    PromptTextPart,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.templates import render_template


@dataclass(frozen=True, slots=True)
class ExpandedPrompt:
    """Frozen expanded, unrendered text and its exact UTF-8 content identity."""

    content: str
    sha256: str = field(init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", hashlib.sha256(self.content.encode("utf-8")).hexdigest())


def expand_agent_prompt(
    prompt: PromptDefinition,
    *,
    prompts: tuple[PromptDefinition, ...],
    config_root: Path,
) -> ExpandedPrompt:
    """Expand selected includes/files once, retaining placeholders without rendering."""
    by_id = {item.prompt_id: item for item in prompts}

    def expand(current: PromptDefinition, stack: tuple[str, ...] = ()) -> str:
        if current.prompt_id in stack:
            raise AudiaGenticError(
                code="VAL-AGW-110",
                kind="agents",
                message="agent prompt include cycle",
                details={"prompt-id": current.prompt_id},
            )
        fragments: list[str] = []
        for part in current.content:
            if isinstance(part, PromptTextPart):
                fragments.append(part.text)
            elif isinstance(part, PromptIncludePart):
                included = by_id.get(part.prompt_id)
                if included is None:
                    raise AudiaGenticError(
                        code="RES-AGW-110",
                        kind="agents",
                        message="agent prompt includes an unknown prompt",
                        details={
                            "prompt-id": current.prompt_id,
                            "included-prompt-id": part.prompt_id,
                        },
                    )
                fragments.append(expand(included, stack + (current.prompt_id,)))
            elif isinstance(part, PromptFilePart):
                candidate = (config_root / part.path).resolve()
                if config_root.resolve() not in candidate.parents:
                    raise AudiaGenticError(
                        code="VAL-AGW-111",
                        kind="agents",
                        message="agent prompt file must remain inside the global config root",
                        details={"prompt-id": current.prompt_id},
                    )
                try:
                    fragments.append(candidate.read_text(encoding="utf-8"))
                except OSError as exc:
                    raise AudiaGenticError(
                        code="RES-AGW-111",
                        kind="agents",
                        message="agent prompt file could not be read",
                        details={"prompt-id": current.prompt_id, "path": part.path},
                    ) from exc
        return "\n".join(fragment for fragment in fragments if fragment)

    return ExpandedPrompt(expand(prompt))


def render_expanded_prompt(
    prompt: ExpandedPrompt,
    *,
    template_context: dict[str, Any],
) -> str:
    """Render frozen content without consulting files or mutable prompt definitions."""
    return render_template(prompt.content, template_context)


def materialize_agent_prompt(
    prompt: PromptDefinition,
    *,
    prompts: tuple[PromptDefinition, ...],
    config_root: Path,
    template_context: dict[str, Any],
) -> str:
    """Resolve one prompt and its contained includes against frozen context.

    This is deliberately admission-only: callers persist the request snapshot
    and dispatch the returned text without consulting mutable agent config.
    """
    expanded = expand_agent_prompt(prompt, prompts=prompts, config_root=config_root)
    return render_expanded_prompt(expanded, template_context=template_context)


__all__ = [
    "ExpandedPrompt",
    "expand_agent_prompt",
    "render_expanded_prompt",
    "materialize_agent_prompt",
]
