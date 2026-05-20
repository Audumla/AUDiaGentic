from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml


def _load_yaml_resource(name: str) -> dict[str, Any]:
    text = files("audiagentic.knowledge.runtime_data").joinpath(name).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def get_capability_profiles() -> dict[str, dict[str, Any]]:
    return _load_yaml_resource("capability_profiles.yml").get("capability_profiles", {})


def get_host_profiles() -> dict[str, dict[str, Any]]:
    return _load_yaml_resource("host_profiles.yml").get("host_profiles", {})


def get_capability_contract() -> dict[str, Any]:
    return _load_yaml_resource("capability_contract.yml").get("capability_contract", {})
