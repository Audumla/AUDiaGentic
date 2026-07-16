"""Provider config loading tolerates the freshly-installed state.

Regression: the installer writes .audiagentic/config/runtime/providers.yaml as a
bare comment ("# Installation marker"). YAML parses that to an empty mapping,
which strict validation rejected for missing required properties — so every
agent launch failed with VAL-PCFG-001 on a file the installer itself wrote,
while a MISSING file was handled fine. An existing-but-empty file means the same
thing as no file: no providers configured.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.provider_config import (
    load_provider_config,
    load_provider_config_lenient,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

_DEFAULT = {"contract-version": "v1", "providers": {}}


def _write(root, text: str):
    path = root / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_returns_default(tmp_path):
    assert load_provider_config(tmp_path) == _DEFAULT


@pytest.mark.parametrize(
    "content",
    [
        "# Installation marker",  # exactly what the installer writes
        "",
        "\n\n",
        "# a comment\n# another\n",
    ],
    ids=["install-marker", "empty", "blank-lines", "comments-only"],
)
def test_empty_or_comment_only_file_is_the_same_as_no_file(tmp_path, content):
    _write(tmp_path, content)
    assert load_provider_config(tmp_path) == _DEFAULT


def test_lenient_and_strict_agree_on_the_installed_state(tmp_path):
    """The two loaders must not disagree about a freshly-installed project."""
    _write(tmp_path, "# Installation marker")
    assert load_provider_config(tmp_path) == load_provider_config_lenient(tmp_path)


def test_populated_config_still_loads(tmp_path):
    _write(
        tmp_path,
        "contract-version: v1\n"
        "providers:\n"
        "  opencode:\n"
        "    enabled: true\n"
        "    access-mode: none\n"
        "    auth-ref: \"env:OPENCODE_API_KEY\"\n"
        "    install-mode: toolchain\n",
    )
    # The point is only that a schema-valid file still passes validation and is
    # returned — enablement itself is derived elsewhere, not read from here.
    config = load_provider_config(tmp_path)
    assert "opencode" in config["providers"]


def test_genuinely_invalid_config_still_fails(tmp_path):
    """Tolerating empty must not tolerate wrong — a populated but malformed
    file is a real error and must still raise."""
    _write(tmp_path, "contract-version: v1\nproviders: not-a-mapping\n")
    with pytest.raises(AudiaGenticError) as excinfo:
        load_provider_config(tmp_path)
    assert excinfo.value.code == "VAL-PCFG-001"
