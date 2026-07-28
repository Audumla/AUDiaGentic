"""Adds a ``--mcp-exclusive`` flag to the system-installed pi-mcp-adapter.

Vanilla pi-mcp-adapter always merges four MCP config sources (shared-global
``~/.config/mcp/mcp.json``, the ``--mcp-config`` override, the project's own
``.mcp.json``, and a project-level pi override) — confirmed against the
installed adapter's ``getConfigSources`` and against upstream's own docs
(pi.dev/packages/pi-mcp-adapter). There is no flag, setting, or env var to make
``--mcp-config`` exclusive; it's a documented, intentional design choice, not a
version-specific quirk. AUDiaGentic needs the launched session to see ONLY its
own curated MCP config, so this adds a new, additive flag: when BOTH
``--mcp-config <path>`` and ``--mcp-exclusive`` are passed, only that path is
loaded. Without ``--mcp-exclusive``, behavior is completely unchanged —
including for a user who passes ``--mcp-config`` manually themselves.

Two files need patching, not one — confirmed empirically, not assumed:
``getConfigPathFromArgv`` reads ``process.argv`` directly for ``--mcp-config``
(not through pi's flag system), so it was tempting to make
``getConfigSources`` check ``process.argv`` for ``--mcp-exclusive`` the same
way with no other changes. That alone does NOT work: pi's own top-level CLI
parser rejects any flag that hasn't been registered via
``pi.registerFlag(...)`` before it even reaches the extension's argv-reading
code — confirmed by testing (``Error: Unknown option: --mcp-exclusive``,
launch aborted) before the flag was registered. So this patches:

1. ``config.ts``: ``getConfigSources`` — short-circuit to the override alone
   when ``process.argv`` contains ``--mcp-exclusive``.
2. ``index.ts``: register ``mcp-exclusive`` as a boolean flag via
   ``pi.registerFlag`` (right alongside the existing ``mcp-config``
   registration) so pi's parser accepts it at all.

Version-robust and fail-closed, matching the ``direct-tools.ts`` ctx-fix
discipline: anchors on stable landmarks (function name / existing flag
registration), not exact surrounding text, and applies NEITHER file's edit if
either anchor can't be found — a half-applied state (flag unregistered but
config.ts checks for it, or vice versa) is worse than no patch at all.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Supported pi-mcp-adapter versions — patch anchors must be validated against
# each version before inclusion. Versions are ranges (>=2.10.0, <3.0.0) to
# cover the range where anchor text has been confirmed present.
_SUPPORTED_ADAPTER_VERSIONS: list[str] = ["^2.10.0"]

# Anchor text that must exist for the patch to apply — if upstream changes
# these, the patch fails closed and reports which anchor is missing.
_CONFIG_ANCHOR_DESC = "function getConfigSources"
_INDEX_ANCHOR_DESC = 'pi.registerFlag("mcp-config"'

_MARKER = "AUDIAGENTIC_MCP_EXCLUSIVE_PATCH"


def _patch_config_source(text: str) -> str | None:
    if _MARKER in text:
        return text
    # Greedy `.*` without DOTALL stays confined to one physical line (this
    # declaration is single-line) and correctly backtracks past nested parens
    # in default values like `cwd = process.cwd()` to find the real closing
    # paren immediately before the optional return type and opening brace.
    match = re.search(
        r"function getConfigSources\(.*\)(\s*:\s*[\w\[\]]+)?\s*\{",
        text,
    )
    if match is None:
        return None
    injection = (
        f"\n  // {_MARKER}: when an explicit override is given together with\n"
        "  // --mcp-exclusive, load ONLY that override — skip shared-global,\n"
        "  // shared-project, and pi-project discovery entirely. Inert unless both\n"
        "  // flags are present; existing --mcp-config behavior is unchanged.\n"
        '  if (overridePath && process.argv.includes("--mcp-exclusive")) {\n'
        "    const exclusivePath = resolve(overridePath);\n"
        "    return [{\n"
        '      id: "pi-global",\n'
        '      label: "AUDiaGentic exclusive runtime MCP config",\n'
        "      readPath: exclusivePath,\n"
        "      writePath: exclusivePath,\n"
        '      kind: "user",\n'
        "      shared: false,\n"
        '      scope: "global",\n'
        "    }];\n"
        "  }\n"
    )
    return text[: match.end()] + injection + text[match.end() :]


def _patch_flag_registration(text: str) -> str | None:
    if _MARKER in text:
        return text
    match = re.search(
        r'pi\.registerFlag\(\s*"mcp-config"\s*,\s*\{[^}]*\}\s*\)\s*;',
        text,
    )
    if match is None:
        return None
    injection = (
        f"\n  // {_MARKER}: registers the flag so pi's own CLI parser accepts it "
        "— an unregistered flag is rejected before the extension ever runs.\n"
        '  pi.registerFlag("mcp-exclusive", {\n'
        '    description: "With --mcp-config, load ONLY that file (AUDiaGentic launch surface)",\n'
        '    type: "boolean",\n'
        "  });"
    )
    return text[: match.end()] + injection + text[match.end() :]


def _read_adapter_version(system_package_root: Path) -> str | None:
    """Read pi-mcp-adapter version from package.json; returns None if not found."""
    pkg_json = system_package_root / "pi-mcp-adapter" / "package.json"
    if not pkg_json.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(pkg_json.read_text(encoding="utf-8"))
        return data.get("version")
    except (json.JSONDecodeError, OSError):
        return None


def _version_supported(version: str) -> bool:
    """Check *version* (``major.minor.patch``) against the supported ranges.

    Ranges are expressed npm-caret-style (``^2.10.0`` means ``>=2.10.0,<3.0.0``).
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    for spec in _SUPPORTED_ADAPTER_VERSIONS:
        caret_match = re.match(r"^\^(\d+)\.(\d+)\.(\d+)$", spec)
        if caret_match is None:
            continue
        floor_major, floor_minor, floor_patch = (int(part) for part in caret_match.groups())
        if major != floor_major:
            continue
        if (minor, patch) >= (floor_minor, floor_patch):
            return True
    return False


def apply_mcp_exclusive_patch(system_package_root: Path) -> bool:
    """Patch both ``config.ts`` and ``index.ts`` under *system_package_root*.

    Version-robust, fail-closed, idempotent:

    1. **Version check**: reads pi-mcp-adapter version from package.json and
       rejects (fail-closed) if the version is outside supported ranges or
       cannot be determined.
    2. **Anchor detection**: uses regex anchors on stable landmarks (function
       name / existing flag registration), not exact surrounding text.
    3. **Fail-closed**: returns False if either anchor isn't found — never
       writes just one of the two files.
    4. **Idempotent**: checks `_MARKER` in both files before applying.
    5. **Both-file atomic**: either both succeed or neither changes.

    Returns True only if both edits are present after this call (already
    applied, or freshly applied together). Logs detailed diagnostics on failure.
    """
    config_target = system_package_root / "pi-mcp-adapter" / "config.ts"
    index_target = system_package_root / "pi-mcp-adapter" / "index.ts"
    if not config_target.exists() or not index_target.exists():
        logger.warning(
            "mcp-exclusive patch: target files missing (config: %s, index: %s)",
            config_target.exists(),
            index_target.exists(),
        )
        return False

    adapter_version = _read_adapter_version(system_package_root)
    if adapter_version is None:
        logger.warning(
            "mcp-exclusive patch: cannot determine pi-mcp-adapter version from %s; "
            "refusing to patch (fail-closed)",
            system_package_root / "pi-mcp-adapter" / "package.json",
        )
        return False
    if not _version_supported(adapter_version):
        logger.warning(
            "mcp-exclusive patch: pi-mcp-adapter version %s is outside supported "
            "ranges %s; refusing to patch (fail-closed)",
            adapter_version,
            _SUPPORTED_ADAPTER_VERSIONS,
        )
        return False
    logger.debug("mcp-exclusive patch: pi-mcp-adapter version %s", adapter_version)

    config_source = config_target.read_text(encoding="utf-8")
    index_source = index_target.read_text(encoding="utf-8")

    if _MARKER in config_source and _MARKER in index_source:
        return True

    patched_config = _patch_config_source(config_source)
    patched_index = _patch_flag_registration(index_source)
    if patched_config is None or patched_index is None:
        missing = "config.ts" if patched_config is None else "index.ts"
        anchor = _CONFIG_ANCHOR_DESC if patched_config is None else _INDEX_ANCHOR_DESC
        logger.warning(
            "mcp-exclusive patch: anchor '%s' not found in %s; "
            "skipping both edits (fail-closed) — upstream may have changed",
            anchor,
            missing,
        )
        return False

    config_target.write_text(patched_config, encoding="utf-8")
    index_target.write_text(patched_index, encoding="utf-8")
    logger.info("mcp-exclusive patch applied successfully to %s", system_package_root)
    return True


__all__ = ["apply_mcp_exclusive_patch", "_read_adapter_version"]
