"""Recipe catalogue — indexed, source-ordered recipe selection.

Explicit sources in fixed precedence (lowest to highest):

    1. packaged   — shipped with the audiagentic package
    2. project    — project_root/.audiagentic/recipes/
    3. profile    — project_root/.audiagentic/<profile>/recipes/

Index is keyed by recipe-id. Whole-definition replacement only: a higher-
precedence entry replaces a lower one entirely (no deep merge). A replacing
recipe must declare ``replaces-version`` matching the replaced recipe's
version, otherwise replacement is rejected.

Duplicate ids at the same source level fail immediately with VAL-RCG.
No caching — load-on-first-access only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.names import (
    get_active_profile,
    get_package_config_dir,
)

from .recipe_loader import DeclarativeRecipeTemplate, load_recipe_from_yaml

_rcg_err = make_error_factory("VAL", "RCG", "recipe-catalogue")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECIPE_DIR_NAME = "recipes"
"""Subdirectory name within each source root that holds recipe YAML files."""


# ---------------------------------------------------------------------------
# Provenance and entry tracking
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecipeSource:
    """Where a recipe definition was loaded from."""

    level: str  # "packaged", "project", "profile"
    profile_name: str | None = None  # set only when level == "profile"

    def __repr__(self) -> str:
        if self.profile_name:
            return f"{self.level}/{self.profile_name}"
        return self.level


@dataclass(frozen=True)
class CatalogueEntry:
    """A recipe template with its source provenance."""

    template: DeclarativeRecipeTemplate
    source: RecipeSource


class RecipeCatalogue:
    """Load recipes from explicit sources, index by id, resolve precedence.

    Construction is lazy: ``_templates`` stays empty until ``get_recipe`` or
    ``list_recipes`` is called. No caching layer — each call reads the YAML
    files and resolves on demand. This avoids the stale-state hazard of RV496/
    RV503 where a cached registry entry masked an updated definition.
    """

    def __init__(self, project_root: str | Path) -> None:
        self._project_root = Path(project_root).resolve()
        self._templates: dict[str, CatalogueEntry] | None = None

    # ------------------------------------------------------------------
    # Source resolution
    # ------------------------------------------------------------------

    def _package_recipe_dir(self) -> Path:
        """Return the packaged recipes directory shipped with the package."""
        return get_package_config_dir() / _RECIPE_DIR_NAME

    def _project_recipe_dir(self) -> Path:
        """Return project-level recipe override directory."""
        return self._project_root / ".audiagentic" / _RECIPE_DIR_NAME

    def _profile_recipe_dir(self) -> Path | None:
        """Return the active component-profile recipe directory, or None."""
        profile_name = get_active_profile()
        if not profile_name:
            return None
        return (
            self._project_root
            / ".audiagentic"
            / profile_name
            / _RECIPE_DIR_NAME
        )

    # ------------------------------------------------------------------
    # YAML loading per source level
    # ------------------------------------------------------------------

    def _load_level(
        self,
        recipe_dir: Path | None,
        source: RecipeSource,
    ) -> dict[str, DeclarativeRecipeTemplate]:
        """Load all recipes from one source directory into an id-keyed map.

        Duplicate recipe-ids at the same level raise VAL-RCG-001.
        """
        if not recipe_dir or not recipe_dir.is_dir():
            return {}

        result: dict[str, DeclarativeRecipeTemplate] = {}
        yaml_files = sorted(recipe_dir.glob("*.yaml"))

        for yf in yaml_files:
            # Skip fixture subdirectories (they are schema examples, not recipes)
            if yf.parent != recipe_dir:
                continue

            try:
                template = load_recipe_from_yaml(yf)
            except Exception as exc:  # noqa: BLE001 — surface loader error
                raise _rcg_err(
                    3,
                    f"failed to load {yf.name} from {source}",
                    path=str(yf),
                    error=repr(exc),
                )

            rid = template.recipe_id
            if rid in result:
                raise _rcg_err(
                    1,
                    f"duplicate recipe-id {rid!r} at {source} level "
                    f"({yf.name} vs existing)",
                    recipe_id=rid,
                    source=str(source),
                )
            result[rid] = template

        return result

    # ------------------------------------------------------------------
    # Precedence resolution with version-checked replacement
    # ------------------------------------------------------------------

    def _resolve_precedence(
        self,
        levels: list[tuple[dict[str, DeclarativeRecipeTemplate], RecipeSource]],
    ) -> dict[str, CatalogueEntry]:
        """Merge source levels in ascending precedence.

        Whole-definition replacement only. A higher-level recipe replaces a
        lower one if and only if:

        - It is present at the higher level (by recipe-id)
        - It declares ``replaces-version`` matching the lower-level recipe's
          version, OR the lower-level recipe has no entry (first definition)

        No deep merge: the higher-level entry wins entirely.
        """
        merged: dict[str, CatalogueEntry] = {}

        for templates, source in levels:
            for rid, template in templates.items():
                replaces_version = template.provenance_ref
                if rid in merged:
                    existing = merged[rid]
                    existing_version = existing.template.recipe_version

                    if replaces_version and replaces_version == existing_version:
                        logger.info(
                            "Recipe %s replaced by %s (version %s)",
                            rid, source, replaces_version,
                        )
                        merged[rid] = CatalogueEntry(template=template, source=source)
                    elif replaces_version and replaces_version != existing_version:
                        raise _rcg_err(
                            2,
                            f"version mismatch replacing recipe {rid!r}: "
                            f"existing version {existing_version!r}, "
                            f"proposed replaces-version {replaces_version!r}",
                            recipe_id=rid,
                            existing_version=existing_version,
                            proposed_version=replaces_version,
                        )
                    else:
                        # Higher-level entry does not declare replaces-version;
                        # replace since higher precedence wins.
                        logger.info(
                            "Recipe %s replaced by %s (no replaces-version declared)",
                            rid, source,
                        )
                        merged[rid] = CatalogueEntry(template=template, source=source)
                else:
                    merged[rid] = CatalogueEntry(template=template, source=source)

        return merged

    # ------------------------------------------------------------------
    # Lazy build
    # ------------------------------------------------------------------

    def _build(self) -> dict[str, CatalogueEntry]:
        """Load all sources in precedence order and resolve."""
        pkg_dir = self._package_recipe_dir()
        proj_dir = self._project_recipe_dir()
        prof_dir = self._profile_recipe_dir()

        levels: list[tuple[dict[str, DeclarativeRecipeTemplate], RecipeSource]] = [
            (
                self._load_level(pkg_dir, RecipeSource(level="packaged")),
                RecipeSource(level="packaged"),
            ),
            (
                self._load_level(proj_dir, RecipeSource(level="project")),
                RecipeSource(level="project"),
            ),
        ]

        if prof_dir is not None:
            levels.append(
                (
                    self._load_level(
                        prof_dir,
                        RecipeSource(level="profile", profile_name=get_active_profile()),
                    ),
                    RecipeSource(level="profile", profile_name=get_active_profile()),
                )
            )

        return self._resolve_precedence(levels)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_recipe(self, recipe_id: str) -> CatalogueEntry:
        """Return the resolved recipe entry by id.

        Raises VAL-RCG-004 if the recipe is not found in any source.
        """
        if self._templates is None:
            self._templates = self._build()

        entry = self._templates.get(recipe_id)
        if entry is None:
            raise _rcg_err(
                4,
                f"recipe {recipe_id!r} not found in catalogue",
                recipe_id=recipe_id,
                sources=(
                    sorted(str(e.source) for e in self._templates.values())
                    if self._templates
                    else []
                ),
            )
        return entry

    def list_recipes(self) -> dict[str, CatalogueEntry]:
        """Return all resolved recipe entries.

        The returned dict is keyed by recipe-id and reflects the current
        precedence resolution (package < project < profile).
        """
        if self._templates is None:
            self._templates = self._build()
        return dict(self._templates)

    def has_recipe(self, recipe_id: str) -> bool:
        """Check if a recipe exists in the catalogue without loading."""
        if self._templates is None:
            self._templates = self._build()
        return recipe_id in self._templates


def make_catalogue(project_root: str | Path) -> RecipeCatalogue:
    """Convenience constructor for RecipeCatalogue.

    Reuses the existing one-profile-per-process selection from the active
    component profile (via AUDIAGENTIC_COMPONENT_PROFILE env var). Does not
    add a second profile mechanism or its own cache.
    """
    return RecipeCatalogue(project_root)


__all__ = [
    "CatalogueEntry",
    "RecipeCatalogue",
    "RecipeSource",
    "make_catalogue",
]
