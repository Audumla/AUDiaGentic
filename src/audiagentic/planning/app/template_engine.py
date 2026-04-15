from __future__ import annotations

from typing import Any


class TemplateEngine:
    """Render document body templates from config.

    This class provides a centralized way to generate document body templates
    based on planning kind and guidance level, eliminating hardcoded templates
    in individual managers.
    """

    def __init__(self, config: Any):
        """Initialize with config instance.

        Args:
            config: Config instance with document_templates and guidance levels
        """
        self.config = config

    def render(self, kind: str, guidance: str | None = None) -> str:
        """Render a document body template.

        Args:
            kind: Planning kind ('spec', 'task', 'plan', 'wp', 'standard', 'request')
            guidance: Optional guidance level ('light', 'standard', 'deep').
                     If not provided, uses the default template.

        Returns:
            Template string with section headers and spacing
        """
        return self.config.document_template(kind, guidance)

    def render_for_guidance(self, kind: str, guidance_name: str) -> str:
        """Render template for a specific guidance level.

        Args:
            kind: Planning kind
            guidance_name: Guidance level name ('light', 'standard', 'deep')

        Returns:
            Template string for the specified guidance level
        """
        return self.config.document_template(kind, guidance_name)

    def render_default(self, kind: str) -> str:
        """Render default template for a kind.

        Args:
            kind: Planning kind

        Returns:
            Default template string
        """
        return self.config.document_template(kind, None)
