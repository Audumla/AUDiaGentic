"""TagDescriptor — metadata for a single prompt-trigger tag."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TagFile:
    """A project file managed by this tag."""
    rel_path: str
    lifecycle: str
    description: str = ""


@dataclass(frozen=True)
class TagSurfaceContribution:
    """A rule/content block pushed into every installed provider surface."""
    contribution_id: str
    kind: str
    title: str
    body: str
    preferred_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagPrompt:
    """A prompt template shipped with this tag."""
    name: str
    content_file: str   # relative to the tag's config directory


@dataclass(frozen=True)
class TagDescriptor:
    """Full definition of a prompt-trigger tag.

    Loaded from config/agent-actions/tags/<name>/descriptor.yaml.
    Neither the tag nor the loading code references specific providers.
    """
    tag_id: str
    display_name: str
    description: str
    # skill.md path, relative to this tag's config directory
    skill_content_file: str
    # absolute path to the tag's config directory (set by loader)
    config_dir: Path
    aliases: tuple[str, ...] = ()
    directives: tuple[str, ...] = ()
    files: tuple[TagFile, ...] = ()
    surface_contributions: tuple[TagSurfaceContribution, ...] = ()
    prompts: tuple[TagPrompt, ...] = ()
    requires_body: bool = True
    is_generic_tag: bool = False
    is_review_tag: bool = False

    @property
    def skill_path(self) -> Path:
        return self.config_dir / self.skill_content_file

    def skill_content(self) -> str:
        return self.skill_path.read_text(encoding="utf-8")
