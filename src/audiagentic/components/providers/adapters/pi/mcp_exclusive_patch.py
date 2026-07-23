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

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

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
        "  if (overridePath && process.argv.includes(\"--mcp-exclusive\")) {\n"
        "    const exclusivePath = resolve(overridePath);\n"
        "    return [{\n"
        "      id: \"pi-global\",\n"
        "      label: \"AUDiaGentic exclusive runtime MCP config\",\n"
        "      readPath: exclusivePath,\n"
        "      writePath: exclusivePath,\n"
        "      kind: \"user\",\n"
        "      shared: false,\n"
        "      scope: \"global\",\n"
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
        "  pi.registerFlag(\"mcp-exclusive\", {\n"
        "    description: \"With --mcp-config, load ONLY that file (AUDiaGentic launch surface)\",\n"
        "    type: \"boolean\",\n"
        "  });"
    )
    return text[: match.end()] + injection + text[match.end() :]


def apply_mcp_exclusive_patch(system_package_root: Path) -> bool:
    """Patch both ``config.ts`` and ``index.ts`` under *system_package_root*.

    Returns True only if both edits are present after this call (already
    applied, or freshly applied together) — False if either anchor couldn't be
    found. Fails closed: never writes just one of the two files, since a
    half-applied state is worse than no patch (the flag would be either
    unregistered-but-checked, or registered-but-ignored).
    """
    config_target = system_package_root / "pi-mcp-adapter" / "config.ts"
    index_target = system_package_root / "pi-mcp-adapter" / "index.ts"
    if not config_target.exists() or not index_target.exists():
        return False

    config_source = config_target.read_text(encoding="utf-8")
    index_source = index_target.read_text(encoding="utf-8")

    if _MARKER in config_source and _MARKER in index_source:
        return True

    patched_config = _patch_config_source(config_source)
    patched_index = _patch_flag_registration(index_source)
    if patched_config is None or patched_index is None:
        logger.warning(
            "mcp-exclusive patch: anchor not found in %s; skipping both edits (fail-closed)",
            config_target if patched_config is None else index_target,
        )
        return False

    config_target.write_text(patched_config, encoding="utf-8")
    index_target.write_text(patched_index, encoding="utf-8")
    return True


__all__ = ["apply_mcp_exclusive_patch"]
