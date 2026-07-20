"""Generic LSP enablement configuration system.

Provides a centralized, recipe-based configuration system for LSP enablement
that maps language IDs to harness-specific server names and aliases. This
centralizes the LSP-to-harness config in the LSP component (like we do for
hindsight) and makes the LSP config generic to blocks/managed config items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.toolchains.managed_config import ManagedConfigFragment


@dataclass(frozen=True)
class LspEnablementMapping:
    """Mapping for a language to harness-specific server names and aliases."""

    language_id: str
    server_names: list[str]
    aliases: list[str] = field(default_factory=list)


class LspEnablementConfig:
    """Generic LSP enablement configuration system."""

    # Default mappings for common languages to harness-specific server names
    _DEFAULT_MAPPINGS: dict[str, LspEnablementMapping] = {
        "python": LspEnablementMapping(
            language_id="python",
            server_names=["pyright", "pyright-langserver"],
            aliases=["python", "pyright"],
        ),
        "python-ruff": LspEnablementMapping(
            language_id="python-ruff",
            server_names=["ruff", "ruff-server"],
            aliases=["python-ruff", "ruff"],
        ),
        "cpp": LspEnablementMapping(
            language_id="cpp",
            server_names=["clangd"],
            aliases=["cpp", "clangd"],
        ),
        "rust": LspEnablementMapping(
            language_id="rust",
            server_names=["rust-analyzer", "rust"],
            aliases=["rust", "rust-analyzer"],
        ),
        "typescript": LspEnablementMapping(
            language_id="typescript",
            server_names=["typescript-language-server", "tsserver"],
            aliases=["typescript", "typescript-language-server"],
        ),
        "toml": LspEnablementMapping(
            language_id="toml",
            server_names=["taplo"],
            aliases=["toml", "taplo"],
        ),
        "yaml": LspEnablementMapping(
            language_id="yaml",
            server_names=["yaml-language-server", "yaml-ls"],
            aliases=["yaml", "yaml-language-server", "yaml-ls"],
        ),
        "markdown": LspEnablementMapping(
            language_id="markdown",
            server_names=["marksman"],
            aliases=["markdown", "marksman"],
        ),
    }

    @classmethod
    def get_mapping(cls, language_id: str) -> LspEnablementMapping | None:
        """Get the LSP enablement mapping for a language."""
        return cls._DEFAULT_MAPPINGS.get(language_id)

    @classmethod
    def get_server_names(cls, language_id: str) -> list[str]:
        """Get the server names for a language."""
        mapping = cls.get_mapping(language_id)
        if not mapping:
            return [language_id]
        return mapping.server_names

    @classmethod
    def get_aliases(cls, language_id: str) -> set[str]:
        """Get the aliases for a language."""
        mapping = cls.get_mapping(language_id)
        if not mapping:
            return {language_id}
        return set(mapping.aliases) | {language_id}

    @classmethod
    def to_harness_key(cls, language_id: str, harness: str) -> str:
        """Convert a language ID to a harness-specific key."""
        mapping = cls.get_mapping(language_id)
        if not mapping:
            return language_id

        # For opencode, use the first server name or the language id
        if harness == "opencode":
            return mapping.server_names[0] if mapping.server_names else language_id

        # For codex, use the language id directly
        if harness == "codex":
            return language_id

        # Default fallback
        return language_id


def create_lsp_enablement_fragment(
    language_id: str, server_names: list[str], file_extensions: list[str]
) -> ManagedConfigFragment:
    """Create a managed config fragment for LSP enablement."""
    return ManagedConfigFragment(
        fragment_type="lsp-enablement",
        language_id=language_id,
        data={
            "server_names": server_names,
            "file_extensions": file_extensions,
        },
    )


def parse_lsp_enablement_fragment(fragment: ManagedConfigFragment) -> dict[str, Any] | None:
    """Parse a managed config fragment for LSP enablement."""
    if fragment.fragment_type != "lsp-enablement":
        return None

    data = fragment.data or {}
    return {
        "language_id": fragment.language_id,
        "server_names": data.get("server_names", []),
        "file_extensions": data.get("file_extensions", []),
    }
