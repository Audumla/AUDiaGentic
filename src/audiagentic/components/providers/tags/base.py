"""ActionDescriptor — metadata for a single prompt-trigger action."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ActionFile:
    """A project file managed by this action."""
    rel_path: str
    lifecycle: str
    description: str = ""


@dataclass(frozen=True)
class ActionInstruction:
    """An instruction block pushed into every installed provider surface."""
    contribution_id: str
    title: str
    body: str
    preferred_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionPrompt:
    """A prompt template shipped with this action."""
    name: str
    content_file: str   # relative to the action's config directory


@dataclass(frozen=True)
class ActionDescriptor:
    """Full definition of a prompt-trigger action.

    Loaded from a component's declared actions config YAML.
    Neither the action nor the loading code references specific providers.
    """
    tag_id: str
    display_name: str
    description: str
    skill_content_file: str
    config_dir: Path
    aliases: tuple[str, ...] = ()
    directives: tuple[str, ...] = ()
    files: tuple[ActionFile, ...] = ()
    instructions: tuple[ActionInstruction, ...] = ()
    prompts: tuple[ActionPrompt, ...] = ()
    requires_body: bool = True
    is_generic_tag: bool = False
    is_review_tag: bool = False
    # Component that declared this action in its config YAML. Drives surface/skill
    # lifecycle: the action's contributions and generated skill files are only active
    # while this component is installed and enabled. Empty = unknown owner (treated active).
    owner_component_id: str = ""

    @property
    def skill_path(self) -> Path:
        return self.config_dir / self.skill_content_file

    def skill_content(self) -> str:
        return self.skill_path.read_text(encoding="utf-8")

