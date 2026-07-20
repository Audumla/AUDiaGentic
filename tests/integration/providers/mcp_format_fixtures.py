"""Template fixtures for MCP config corruption testing, keyed by the wire
``format`` string each provider descriptor's ``mcp_config`` declares.

One row per format, shared across every provider that uses it. Provider ids
are never hand-enumerated here or in the tests that consume this table —
they're discovered from the live descriptor registry (see
test_managed_config_capability_matrix_e2e.py's ``_mcp_provider_ids``), so a
new provider reusing an existing format is covered automatically, and a
brand-new format only needs one new row here rather than a new per-provider
test.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpFormatFixture:
    corrupt: str
    write_is_safe: bool
    """True: the format's writer raises on unparseable existing content
    (correct — matches the ManagedFragmentRegistry/CON-MCFG-001 precedent).
    False: the writer silently treats corrupt content as empty and overwrites
    it, permanently discarding whatever was there (RV713). RV713's fix
    (foundation/io.py:load_json_file, foundation/mcp/json_format.py,
    codex/hooks_format.py, codex/language_servers.py, opencode/mcp_format.py,
    continue_/mcp_format.py, openhands/toml_format.py) made every format here
    write_is_safe=True; keep this flag per-format rather than deleting it so
    a future format that reintroduces the swallow pattern is caught by
    test_managed_config_capability_matrix_e2e.py automatically."""


# Corruption payloads are crafted to reliably fail their format's parser:
# unbalanced JSON braces, an unterminated TOML table header, and a tab
# character in YAML block indentation (illegal per the YAML spec, so PyYAML
# always raises rather than guessing).
MCP_FORMAT_FIXTURES: dict[str, McpFormatFixture] = {
    "mcp-json": McpFormatFixture('{"mcpServers": { not valid json', write_is_safe=True),
    "codex-toml": McpFormatFixture("[mcp_servers\nbroken=\n", write_is_safe=True),
    "goose-yaml": McpFormatFixture("foo:\n\tbad_tab_indent: true\n", write_is_safe=True),
    "continue-json": McpFormatFixture('{"mcpServers": [ not valid json', write_is_safe=True),
    "opencode-mcp": McpFormatFixture('{"mcp": { not valid json', write_is_safe=True),
    "mcp-toml": McpFormatFixture("[mcp_servers\nbroken=\n", write_is_safe=True),
}


__all__ = ["McpFormatFixture", "MCP_FORMAT_FIXTURES"]
