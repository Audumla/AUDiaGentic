"""AS61 architecture invariants for Role.

Checked by source inspection rather than behaviour, per this repo's
established pattern (see foundation/composition's own architecture tests):
a boundary violation is a defect a passing behavioural test would not notice.
"""
from __future__ import annotations

from audiagentic.foundation.paths.package import PACKAGE_ROOT

_ROLES_MODULE = PACKAGE_ROOT / "components" / "agents" / "models" / "role.py"
_PROVIDERS_PKG = PACKAGE_ROOT / "components" / "providers"


# Pre-existing, unrelated to AS61's Role type: OpenAI chat-message "role"
# fields, a ChatGPT DOM attribute, and a model capability flag. Frozen, not
# a permissive baseline to add to -- a new hit outside this set means AS61
# leaked a runtime tool/MCP/permission field into providers.
_KNOWN_UNRELATED_ROLE_HITS = frozenset({
    "components/providers/adapters/gpt_auto/dom_reader.py",
    "components/providers/adapters/local_openai/adapter.py",
    "components/providers/adapters/pi/model_entry.py",
    "components/providers/providers_api.py",
})


def test_no_provider_runtime_tool_mcp_or_permission_field_added_by_roles() -> None:
    """AS61 validation: grep providers for a 'role' hit this item might have leaked in.

    Not an absolute zero-hits check -- "role" already appears legitimately
    for unrelated reasons (OpenAI chat-message roles, DOM attributes, a
    capability flag). The check is that the set of files never grows beyond
    the frozen, audited baseline above.
    """
    hits: set[str] = set()
    for path in sorted(_PROVIDERS_PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "role" in text.lower():
            hits.add(path.relative_to(PACKAGE_ROOT).as_posix())
    assert hits <= _KNOWN_UNRELATED_ROLE_HITS, hits - _KNOWN_UNRELATED_ROLE_HITS


def test_role_domain_code_imports_no_concrete_store_or_composition() -> None:
    """Role storage is deliberately not composed (AS61 step 7) -- roles.py stays
    ordinary Python with no graph lookup and no concrete-store import beyond
    its own I/O boundary."""
    text = _ROLES_MODULE.read_text(encoding="utf-8")
    assert "audiagentic.foundation.composition" not in text
    assert ".root(" not in text
    assert "get_gateway_registry" not in text


def test_role_has_no_provider_model_or_runtime_fields() -> None:
    """Acceptance criteria: no provider/runtime configuration leaks into Role."""
    from audiagentic.components.agents.models.role import Role

    fields = set(Role.__dataclass_fields__)
    forbidden = {"provider_id", "model_id", "model_alias", "params", "is_default"}
    assert fields & forbidden == set()
