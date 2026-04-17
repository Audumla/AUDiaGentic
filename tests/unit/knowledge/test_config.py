"""Unit tests for knowledge config loading."""

from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.knowledge.config import KnowledgeConfig, load_config

ROOT = Path(__file__).resolve().parents[3]


def _seed_project(root: Path) -> None:
    shutil.copytree(ROOT / ".audiagentic" / "knowledge", root / ".audiagentic" / "knowledge", dirs_exist_ok=True)


def test_load_config_returns_knowledge_config(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert isinstance(config, KnowledgeConfig)
    assert config.root == tmp_path


def test_config_paths_are_absolute(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert config.pages_root.is_absolute()
    assert config.meta_root.is_absolute()
    assert config.proposals_root.is_absolute()
    assert config.state_root.is_absolute()


def test_config_defaults_knowledge_root(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    # knowledge_root should be under the project root
    assert config.knowledge_root.is_relative_to(tmp_path)


def test_config_search_weights_has_required_keys(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    weights = config.search_weights
    assert "title" in weights
    assert "body" in weights
    assert isinstance(weights["title"], (int, float))
    assert isinstance(weights["body"], (int, float))


def test_config_proposal_default_mode_is_string(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert isinstance(config.proposal_default_mode, str)
    assert config.proposal_default_mode in ("deterministic", "review_only")


def test_config_raw_is_dict(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert isinstance(config.raw, dict)


def test_config_auto_flags_are_bool(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert isinstance(config.auto_apply_proposals, bool)
    assert isinstance(config.auto_mark_stale, bool)


def test_config_event_state_file_path(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert config.event_state_file.suffix == ".yml"
    assert config.event_state_file.is_absolute()


def test_config_event_adapter_file_path(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    assert config.event_adapter_file.is_absolute()
