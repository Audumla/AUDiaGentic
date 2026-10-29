"""Parse provider descriptors once per test process instead of once per call.

Hundreds of tests ask the provider loader about the shipped descriptor
directory, and each call re-reads and re-validates every YAML file (782 file
loads for one 26 s test in the profile that motivated this). The parse is a
pure function of the files, so a result is reused while the directory's file
names, sizes and modification times are unchanged. Descriptors are frozen
dataclasses, so sharing them across tests is safe; each caller still gets its
own dict.

Safeguards, because tests deliberately break loading:
- a hit replays the load errors the original load recorded, so
  ``get_load_errors()`` behaves as if the load had happened;
- the cache is bypassed whenever a test has replaced ``load_descriptor`` or
  ``PROVIDER_SPEC`` (the two seams used to inject parse failures);
- editing, adding or removing a descriptor file changes the key.

Test-only: production loading is untouched.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors import loader

_ORIGINAL_LOAD = loader._load_providers_from_directory_diagnostic
_ORIGINAL_LOAD_DESCRIPTOR = loader.load_descriptor
_ORIGINAL_SPEC = loader.PROVIDER_SPEC
_CACHE: dict[tuple, tuple[dict, tuple]] = {}


def _key(directory: Path) -> tuple:
    files = loader.iter_descriptor_files(Path(directory))
    stats = []
    for path in files:
        stat = path.stat()
        stats.append((path.name, stat.st_mtime_ns, stat.st_size))
    return (str(Path(directory).resolve()), tuple(stats))


def _cached_load(directory: Path) -> dict:
    if loader.load_descriptor is not _ORIGINAL_LOAD_DESCRIPTOR or loader.PROVIDER_SPEC is not _ORIGINAL_SPEC:
        return _ORIGINAL_LOAD(directory)
    try:
        key = _key(directory)
    except OSError:
        return _ORIGINAL_LOAD(directory)
    hit = _CACHE.get(key)
    if hit is None:
        before = len(loader._load_errors)
        providers = _ORIGINAL_LOAD(directory)
        hit = (providers, tuple(loader._load_errors[before:]))
        _CACHE[key] = hit
    else:
        loader._load_errors.extend(hit[1])
    return dict(hit[0])


def install() -> None:
    loader._load_providers_from_directory_diagnostic = _cached_load


def clear() -> None:
    _CACHE.clear()
