"""A provider descriptor can extend another: the base is merged first, the extender's fields win."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers.descriptors.loader import (
    get_load_errors,
    load_providers_diagnostic,
)
from audiagentic.foundation.paths.names import get_package_providers_config_dir

_REAL = get_package_providers_config_dir()


def _copy_real(tmp_path: Path, *names: str) -> Path:
    for name in names:
        (tmp_path / name).write_text((_REAL / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _alias(tmp_path: Path, name: str, **fields) -> None:
    (tmp_path / name).write_text(yaml.safe_dump({"extends": "gpt-auto", **fields}), encoding="utf-8")


def test_the_shipped_aliases_inherit_everything_but_their_own_fields() -> None:
    providers = load_providers_diagnostic(_REAL)
    base, alias = providers["gpt-auto"], providers["gpt-auto-t1"]
    assert alias.extends == "gpt-auto" and base.extends is None
    assert alias.display_name == "gpt-auto-t1 (GP05 test project)" and alias.prompt_aliases == ()
    assert alias.session_surfaces == base.session_surfaces  # inherited, so it cannot drift from the base
    assert len(alias.capabilities) == len(base.capabilities)  # the base capabilities, with the alias message


def test_the_extender_wins_and_lists_replace_whole(tmp_path: Path) -> None:
    _copy_real(tmp_path, "gpt_auto.yaml")
    _alias(tmp_path, "mine.yaml", provider_id="gpt-auto-mine", display_name="Mine", prompt_aliases=["m"])
    mine = load_providers_diagnostic(tmp_path)["gpt-auto-mine"]
    assert mine.display_name == "Mine" and mine.prompt_aliases == ("m",)  # replaced, not appended to ("gpt",)
    assert mine.url == load_providers_diagnostic(tmp_path)["gpt-auto"].url  # inherited


@pytest.mark.parametrize("case", ["missing base", "chained"])
def test_a_bad_extends_skips_only_that_descriptor_and_reports_it(tmp_path: Path, case: str) -> None:
    _copy_real(tmp_path, "gpt_auto.yaml")
    if case == "missing base":
        (tmp_path / "orphan.yaml").write_text(yaml.safe_dump({"provider_id": "orphan", "extends": "nope"}), encoding="utf-8")
    else:
        _alias(tmp_path, "mid.yaml", provider_id="gpt-auto-mid")
        (tmp_path / "leaf.yaml").write_text(yaml.safe_dump({"provider_id": "leaf", "extends": "gpt-auto-mid"}), encoding="utf-8")
    providers = load_providers_diagnostic(tmp_path)
    assert "gpt-auto" in providers  # the healthy descriptors still load
    assert "orphan" not in providers and "leaf" not in providers
    assert any("VAL-PCAP-014" in str(error) or getattr(error, "code", "") == "VAL-PCAP-014" for _, error in get_load_errors())
