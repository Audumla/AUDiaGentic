"""The test-only descriptor cache must never hide a change or a failure."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audiagentic.components.providers.descriptors import loader
from tests.helpers import provider_descriptor_cache as cache


@pytest.fixture
def descriptors(tmp_path: Path) -> Path:
    source = Path(loader.get_providers_config_dir())
    target = tmp_path / "providers"
    target.mkdir()
    for name in sorted(p.name for p in source.glob("*.yaml") if not p.name.startswith("_"))[:3]:
        shutil.copy(source / name, target / name)
    cache.clear()
    return target


def test_second_load_is_served_from_the_cache(descriptors, monkeypatch):
    first = loader.load_providers_from_directory(descriptors)
    calls = []
    monkeypatch.setattr(loader, "load_descriptor", loader.load_descriptor)  # keep identity guard honest
    original = cache._ORIGINAL_LOAD
    monkeypatch.setattr(cache, "_ORIGINAL_LOAD", lambda d: calls.append(d) or original(d))
    second = loader.load_providers_from_directory(descriptors)
    assert calls == [] and second == first and second is not first  # same descriptors, own dict


def test_editing_a_descriptor_invalidates_the_entry(descriptors):
    before = loader.load_providers_from_directory(descriptors)
    victim = sorted(descriptors.glob("*.yaml"))[0]
    victim.write_text(victim.read_text() + "\n# touched\n", encoding="utf-8")
    victim.touch()
    after = loader.load_providers_from_directory(descriptors)
    assert after.keys() == before.keys()
    assert cache._key(descriptors) in cache._CACHE and len(cache._CACHE) == 2  # new key, old one kept


def test_removing_a_descriptor_changes_the_result(descriptors):
    before = loader.load_providers_from_directory(descriptors)
    sorted(descriptors.glob("*.yaml"))[0].unlink()
    assert len(loader.load_providers_from_directory(descriptors)) == len(before) - 1


def test_load_errors_are_replayed_on_a_hit(descriptors):
    (descriptors / "broken.yaml").write_text("provider_id: [unterminated\n", encoding="utf-8")
    loader.load_providers_from_directory(descriptors)
    first_errors = [path.name for path, _ in loader.get_load_errors()]
    assert "broken.yaml" in first_errors
    loader.load_providers_from_directory(descriptors)  # cache hit
    assert [path.name for path, _ in loader.get_load_errors()] == first_errors


def test_a_patched_parser_bypasses_the_cache(descriptors, monkeypatch):
    loader.load_providers_from_directory(descriptors)  # populate
    def boom(path, spec):
        raise ValueError("injected parse failure")
    monkeypatch.setattr(loader, "load_descriptor", boom)
    assert loader.load_providers_from_directory(descriptors) == {}
    assert len(loader.get_load_errors()) >= 1
