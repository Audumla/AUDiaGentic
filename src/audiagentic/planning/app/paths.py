from __future__ import annotations

from pathlib import Path

import yaml

from ..domain.states import KIND_MAP


class Paths:
    def __init__(self, root: Path, test_dir: str | None = None):
        self.root = root
        self.test_dir = test_dir
        if test_dir:
            self.config_dir = root / test_dir / "planning" / "config"
        else:
            self.config_dir = root / ".audiagentic" / "planning" / "config"
        self.planning_cfg = yaml.safe_load(
            (self.config_dir / "planning.yaml").read_text(encoding="utf-8")
        )
        self.kinds = self.planning_cfg["planning"].get("kinds", {})
        self.dirs = self.planning_cfg["planning"]["dirs"]

    def kind_dir(self, kind: str, domain: str | None = None) -> Path:
        """Get directory for a kind from config - fully config-driven.

        Args:
            kind: Planning kind (request, spec, plan, task, wp, standard, or custom)
            domain: Optional domain for kinds that support it (task, wp)

        Returns:
            Path to kind directory

        Raises:
            ValueError: If kind is not defined in config
        """
        kind = KIND_MAP.get(kind, kind)
        kind_config = self.kinds.get(kind)

        if not kind_config:
            raise ValueError(f"Unknown kind '{kind}'. Defined kinds: {list(self.kinds.keys())}")

        base_dir = self.dirs.get("base", "docs/planning")
        kind_dir_name = kind_config["dir"]

        if self.test_dir:
            p = self.root / self.test_dir / base_dir / kind_dir_name
        else:
            p = self.root / base_dir / kind_dir_name

        if kind_config.get("has_domain") and domain:
            p = p / domain

        return p

    def kind_file(self, kind: str, id_: str, label: str, domain: str | None = None) -> Path:
        """Get full file path for a planning item.

        Args:
            kind: Planning kind
            id_: Item ID (e.g., 'request-001')
            label: Item label for slugified filename
            domain: Optional domain for kinds that support it

        Returns:
            Full path to the item's markdown file
        """
        from .util import slugify

        kind_dir = self.kind_dir(kind, domain)

        # Requests and tasks use ID-only filenames
        if kind in {"request", "task"}:
            return kind_dir / f"{id_}.md"

        # Other kinds use ID-label format
        return kind_dir / f"{id_}-{slugify(label)}.md"

    def support_dir(self, name: str) -> Path:
        if self.test_dir:
            return self.root / self.test_dir / self.dirs[name]
        return self.root / self.dirs[name]

    def get_kind_config(self, kind: str) -> dict:
        """Get configuration for a kind.

        Args:
            kind: Planning kind

        Returns:
            Kind config dict with dir, id_prefix, counter_file, has_domain, required_refs

        Raises:
            ValueError: If kind is not defined in config
        """
        kind = KIND_MAP.get(kind, kind)
        kind_config = self.kinds.get(kind)

        if not kind_config:
            raise ValueError(f"Unknown kind '{kind}'. Defined kinds: {list(self.kinds.keys())}")

        return kind_config

    def get_all_kinds(self) -> list[str]:
        """Get all defined kind names.

        Returns:
            List of kind names from config
        """
        return list(self.kinds.keys())
