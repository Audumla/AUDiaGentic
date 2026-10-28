"""Keep config_inventory.yaml an exact inventory of env vars and path builders.

Configuration readers have spread across environment variables and hand-built
.audiagentic paths. The inventory is what the configuration redesign (plan
config-setup, CFG02) migrates from, so it must not silently drift: anything new
must be classified, and anything removed must be dropped from the inventory.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "src"
INVENTORY = Path(__file__).with_name("config_inventory.yaml")
ENV_NAME = re.compile(r"AUDIAGENTIC_[A-Z0-9_]*[A-Z0-9]\Z")


def _scan() -> tuple[set[str], set[str]]:
    env_names: set[str] = set()
    path_builders: set[str] = set()
    for path in sorted((SOURCE / "audiagentic").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if ENV_NAME.match(node.value):
                env_names.add(node.value)
            elif node.value == ".audiagentic":
                path_builders.add(path.relative_to(SOURCE).as_posix())
    return env_names, path_builders


def _inventory() -> tuple[dict[str, list[str]], set[str]]:
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    return data["env"], set(data["path-builders"])


def test_env_classes_are_disjoint() -> None:
    env, _ = _inventory()
    seen: dict[str, str] = {}
    duplicates = []
    for kind, names in env.items():
        for name in names:
            if name in seen:
                duplicates.append(f"{name} ({seen[name]}, {kind})")
            seen[name] = kind
    assert duplicates == [], f"classified more than once: {duplicates}"


def test_every_env_name_is_classified() -> None:
    found, _ = _scan()
    env, _ = _inventory()
    listed = {name for names in env.values() for name in names}
    assert sorted(found - listed) == [], (
        "classify new AUDIAGENTIC_* names in tests/unit/architecture/config_inventory.yaml"
    )
    assert sorted(listed - found) == [], "remove AUDIAGENTIC_* names that no longer exist from the inventory"


def test_every_path_builder_is_listed() -> None:
    _, found = _scan()
    _, listed = _inventory()
    assert sorted(found - listed) == [], (
        "new modules build .audiagentic paths themselves; use the configuration core or list them"
    )
    assert sorted(listed - found) == [], "remove modules that no longer build .audiagentic paths from the inventory"
