"""Admission-time materialisation of a global agent prompt definition."""

from __future__ import annotations

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
                        details={"prompt-id": current.prompt_id, "included-prompt-id": part.prompt_id},
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

    return render_template(expand(prompt), template_context)


__all__ = ["materialize_agent_prompt"]
