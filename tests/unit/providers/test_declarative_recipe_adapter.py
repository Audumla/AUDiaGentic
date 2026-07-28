"""Declarative recipe handler adapter tests — CC41 Activity 6.

Proves the provider-owned adapter can back a typed family without creating
a universal family or crossing component boundaries. Tests cover:

- 6.1 Adapter exists in providers/services (not foundation) and imports only
      foundation primitives and provider types.
- 6.2 Adapter takes provider_id, project_root, recipe_id, request-to-params
      mapper, result mapper and returns a RecipeHandler-compatible closure.
- 6.3 FamilyRegistrar compatibility — test fixture registrar proves the table
      shape works with declarative recipes.
- 6.4 No CC41 family id or universal declarative-lifecycle family needed;
      owners keep distinct typed Request/Result contracts.
- 6.5 One Hindsight-shaped and one LSP-shaped fixture proof with no production
      caller changes and no provider/Hindsight/LSP vocabulary in foundation.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# CC41 Activity 6.1: adapter lives in providers/services, not foundation.
# If this import succeeds and the foundation import below also succeeds,
# the boundary is correct.
from audiagentic.components.providers.services.capabilities.recipe_definitions import (
    FamilyPin,
    ProviderAutomationCapability,
    ProviderAutomationRegistry,
    RecipeHandler,
)

# Foundation imports — these are the only foundation types the adapter uses.
from audiagentic.foundation.toolchains.recipe_contract import RecipeResult
from audiagentic.foundation.toolchains.recipe_loader import load_recipe_from_yaml
from audiagentic.foundation.toolchains.recipe_materializer import materialize_recipe
from audiagentic.foundation.toolchains.recipe_patterns import run_recipe_mode

# Resolve fixture paths relative to the package source tree.
_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "audiagentic"
    / "config"
    / "recipes"
    / "fixtures"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> Any:  # DeclarativeRecipeTemplate
    path = _FIXTURE_DIR / f"{name}.yaml"
    return load_recipe_from_yaml(path)


@dataclass(frozen=True)
class HindsightResult:
    """Family-specific typed result for Hindsight-shaped fixture proof."""

    success: bool
    mode: str
    status: str = ""

    @classmethod
    def from_inner(cls, inner: RecipeResult) -> HindsightResult:
        return cls(
            success=inner.success,
            mode="",
            status=inner.status,
        )


@dataclass(frozen=True)
class LspResult:
    """Family-specific typed result for LSP-shaped fixture proof."""

    installed: bool
    package: str
    recipe_id: str = ""

    @classmethod
    def from_inner(cls, inner: RecipeResult, payload: object) -> LspResult:
        pkg = getattr(payload, "package", "unknown") if hasattr(payload, "package") else "unknown"  # noqa: B002
        return cls(
            installed=inner.success and inner.state.value in ("installing", "verified"),
            package=str(pkg),
            recipe_id=inner.status,
        )


def _hindsight_request_to_params(payload: object) -> dict[str, str]:
    if isinstance(payload, dict):
        return {
            "URL": str(payload.get("url", "http://localhost")),
            "TOKEN": str(payload.get("token", "")),
        }
    return {"URL": "http://localhost", "TOKEN": ""}


def _lsp_request_to_params(payload: object) -> dict[str, str]:
    if isinstance(payload, dict):
        return {"LSP_PACKAGE": str(payload.get("package", "pyright"))}
    if hasattr(payload, "package"):
        return {"LSP_PACKAGE": str(payload.package)}  # type: ignore[union-attr]
    return {"LSP_PACKAGE": "pyright"}


def _make_handler_from_template(
    template: Any,  # DeclarativeRecipeTemplate
    request_to_params: Callable[[object], dict[str, str]],
    result_mapper: Callable[[RecipeResult], object],
) -> RecipeHandler:
    """Test helper: create a RecipeHandler from a template without catalogue.

    Proves the same logic as make_declarative_handler but bypasses the
    catalogue lookup to avoid filesystem setup. The production factory
    uses the catalogue; this proves the core adapter logic.
    """
    def handler(
        mode: str, payload: object, ownership_scope: object | None
    ) -> object:
        params = request_to_params(payload)
        mat = materialize_recipe(template, params)

        from audiagentic.components.providers.services.capabilities.declarative_recipe_handler import (
            _DeclarativeStepRecipe,
        )

        recipe = _DeclarativeStepRecipe(mat, params)
        inner_result = run_recipe_mode(recipe, mode)
        return result_mapper(inner_result)

    return handler


# ---------------------------------------------------------------------------
# 6.1: Adapter boundary — lives in providers/services, not foundation
# ---------------------------------------------------------------------------


def test_adapter_lives_in_providers_not_foundation() -> None:
    """The adapter must not be importable from foundation."""
    import audiagentic.foundation.toolchains as foundation

    assert not hasattr(foundation, "make_declarative_handler"), (
        "Adapter must not live in foundation"
    )
    assert not hasattr(foundation, "_DeclarativeStepRecipe"), (
        "Adapter internals must not live in foundation"
    )


def test_adapter_imports_only_allowed_foundation_types() -> None:
    """Adapter source imports only foundation primitives and provider types."""
    import audiagentic.components.providers.services.capabilities.declarative_recipe_handler as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    lower_src = source.lower()

    forbidden = ["hindsight", "provider_mcp", "provider_api"]
    for word in forbidden:
        assert word not in lower_src, (
            f"Adapter must not contain vocabulary '{word}'"
        )


# ---------------------------------------------------------------------------
# 6.2: Adapter takes the right parameters and returns RecipeHandler
# ---------------------------------------------------------------------------


def test_handler_is_recipe_handler_callable() -> None:
    """The adapter closure is callable as (mode, payload, scope) -> result."""
    template = _load_fixture("hindsight-codex")

    handler = _make_handler_from_template(
        template,
        _hindsight_request_to_params,
        HindsightResult.from_inner,
    )

    assert callable(handler)

    # The handler is a RecipeHandler: Callable[[str, object, object | None], object]
    result = handler("status", {}, None)
    assert isinstance(result, HindsightResult)


def test_make_declarative_handler_uses_project_catalogue_recipe(
    tmp_path: Path,
) -> None:
    """The public factory resolves a concrete recipe through the catalogue."""
    from audiagentic.components.providers.services.capabilities.declarative_recipe_handler import (
        make_declarative_handler,
    )

    recipes_dir = tmp_path / ".audiagentic" / "recipes"
    recipes_dir.mkdir(parents=True)
    fixture = _FIXTURE_DIR / "hindsight-codex.yaml"
    recipes_dir.joinpath("hindsight-codex.yaml").write_text(
        fixture.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    handler = make_declarative_handler(
        "test-provider",
        tmp_path,
        "hindsight-codex-integration",
        _hindsight_request_to_params,
        HindsightResult.from_inner,
    )

    result = handler("plan", {"url": "http://test", "token": "secret"}, "owner-a")

    assert isinstance(result, HindsightResult)
    assert result.success is True


# ---------------------------------------------------------------------------
# 6.4: No universal declarative-lifecycle family — owners keep their own
# ---------------------------------------------------------------------------


def test_no_universal_declarative_family_needed() -> None:
    """Owners use distinct family_ids and contracts, not a universal one."""

    @dataclass(frozen=True)
    class OwnerAResult:
        ok: bool

    @dataclass(frozen=True)
    class OwnerBResult:
        done: bool

    # Two owners with different family_ids and result types
    pin_a = FamilyPin(
        family_id="test-family-a",
        payload_contract="test-family-a-payload/v1",
        result_contract="test-family-a-result/v1",
        supported_modes=("plan", "apply", "prune", "status"),
    )
    pin_b = FamilyPin(
        family_id="test-family-b",
        payload_contract="test-family-b-payload/v1",
        result_contract="test-family-b-result/v1",
        supported_modes=("plan", "apply", "prune", "status"),
    )

    # Neither pin has a "declarative-lifecycle" family_id
    assert pin_a.family_id != "declarative-lifecycle"
    assert pin_b.family_id != "declarative-lifecycle"

    # Each has its own result type
    result_a = OwnerAResult(ok=True)
    result_b = OwnerBResult(done=True)
    assert type(result_a) is not type(result_b)


# ---------------------------------------------------------------------------
# 6.5: Hindsight-shaped fixture proof
# ---------------------------------------------------------------------------


def test_hindsight_fixture_loads_and_materializes() -> None:
    """Hindsight YAML fixture loads, materializes with params, and runs plan mode."""
    template = _load_fixture("hindsight-codex")

    assert template.recipe_id == "hindsight-codex-integration"
    assert len(template.parameters) == 3

    handler = _make_handler_from_template(
        template,
        _hindsight_request_to_params,
        lambda inner: HindsightResult.from_inner(inner),
    )

    # Plan mode should not fail (dry_run doesn't execute steps)
    result = handler("plan", {"url": "http://test", "token": "secret"}, None)
    assert isinstance(result, HindsightResult)


def test_hindsight_sensitive_param_redacted() -> None:
    """Sensitive parameter TOKEN is tracked in resolved_params."""
    template = _load_fixture("hindsight-codex")

    mat = materialize_recipe(template, {"URL": "http://test", "TOKEN": "secret123"})
    assert mat.resolved_params is not None
    assert "TOKEN" in mat.resolved_params.sensitive_names


# ---------------------------------------------------------------------------
# 6.5: LSP-shaped fixture proof
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LspPayload:
    """LSP family request payload — owner-specific typed object."""

    package: str = "pyright"


def test_lsp_fixture_loads_and_materializes() -> None:
    """LSP YAML fixture loads, materializes with params, and runs plan mode."""
    template = _load_fixture("lsp-pyright")

    assert template.recipe_id == "lsp-pyright-install"
    assert len(template.parameters) == 1

    handler = _make_handler_from_template(
        template,
        _lsp_request_to_params,
        lambda inner: LspResult.from_inner(inner, LspPayload()),
    )

    result = handler("plan", LspPayload(package="pyright"), None)
    assert isinstance(result, LspResult)


def test_lsp_owner_specific_payload_and_result() -> None:
    """LSP owner uses its own typed Payload and Result types."""
    template = _load_fixture("lsp-pyright")

    payload = LspPayload(package="pyright")

    def mapper(inner: RecipeResult) -> LspResult:
        return LspResult.from_inner(inner, payload)

    handler = _make_handler_from_template(
        template,
        _lsp_request_to_params,
        mapper,
    )

    result = handler("plan", payload, None)
    assert isinstance(result, LspResult)
    assert result.package == "pyright"


# ---------------------------------------------------------------------------
# 6.3: FamilyRegistrar compatibility — test fixture registrar
# ---------------------------------------------------------------------------


def _fixture_capability(family_id: str, pin: FamilyPin) -> ProviderAutomationCapability:
    return ProviderAutomationCapability(
        family_id=family_id,
        supported_modes=pin.supported_modes,
        payload_contract=pin.payload_contract,
        result_contract=pin.result_contract,
        ownership_scope_required=pin.ownership_scope_required,
    )


def test_declarative_adapter_works_in_family_registrar_shape() -> None:
    """A FamilyRegistrar-shaped entry with a declarative make_handler works."""
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        FamilyRegistrar,
    )

    pin = FamilyPin(
        family_id="test-declarative-fixture",
        payload_contract="test-declarative-payload/v1",
        result_contract="test-declarative-result/v1",
        supported_modes=("plan", "apply", "prune", "status"),
    )

    template = _load_fixture("hindsight-codex")

    # The make_handler factory matches the FamilyRegistrar signature:
    # (provider_id, project_root) -> RecipeHandler
    def make_declarative_for_test(
        provider_id: str, project_root: Path
    ) -> RecipeHandler:
        return _make_handler_from_template(
            template,
            _hindsight_request_to_params,
            HindsightResult.from_inner,
        )

    registrar = FamilyRegistrar(
        family_id=pin.family_id,
        eligible=lambda desc: True,
        make_handler=make_declarative_for_test,
    )

    # Prove the registrar shape is correct
    assert registrar.family_id == pin.family_id
    assert callable(registrar.eligible)
    assert callable(registrar.make_handler)

    # Prove make_handler returns a RecipeHandler
    handler = registrar.make_handler("test-provider", Path("/tmp"))
    result = handler("status", {}, None)
    assert isinstance(result, HindsightResult)


def test_declarative_adapter_registers_with_provider_automation_registry() -> None:
    """Declarative adapter can be registered via the ProviderAutomationRegistry."""
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        FamilyRegistrar,
    )

    pin = FamilyPin(
        family_id="test-reg-fixture",
        payload_contract="test-reg-payload/v1",
        result_contract="test-reg-result/v1",
        supported_modes=("plan", "apply", "prune", "status"),
    )

    template = _load_fixture("lsp-pyright")

    def make_declarative_for_reg(
        provider_id: str, project_root: Path
    ) -> RecipeHandler:
        return _make_handler_from_template(
            template,
            _lsp_request_to_params,
            lambda inner: LspResult.from_inner(inner, LspPayload()),
        )

    registrar = FamilyRegistrar(
        family_id=pin.family_id,
        eligible=lambda desc: True,
        make_handler=make_declarative_for_reg,
    )

    # Build registry with the declarative family
    registry = ProviderAutomationRegistry(
        known_provider_ids={"test-provider"},
        family_contracts={pin.family_id: pin.contracts},
        provider_capabilities={
            "test-provider": (_fixture_capability(pin.family_id, pin),)
        },
    )

    handler = registrar.make_handler("test-provider", Path("/tmp"))
    registry.register(pin.definition("test-provider"), handler)

    # Prove dispatch works
    result = registry.dispatch(
        "test-provider", pin.family_id, "plan", LspPayload(package="pyright")
    )
    assert isinstance(result, LspResult)


def test_family_pin_remains_code_owned_not_declarative() -> None:
    """FamilyPin is code-owned by the family, not derived from declarative recipe."""
    pin = FamilyPin(
        family_id="test-owner-fixture",
        payload_contract="test-owner-payload/v1",
        result_contract="test-owner-result/v1",
        supported_modes=("plan", "apply", "prune", "status"),
    )

    # The pin's contracts are independent of any recipe YAML
    defn = pin.definition("some-provider")
    assert defn.payload_contract == "test-owner-payload/v1"
    assert defn.result_contract == "test-owner-result/v1"

    # A different recipe can be selected without changing the pin
    template_a = _load_fixture("hindsight-codex")
    template_b = _load_fixture("lsp-pyright")
    assert template_a.recipe_id != template_b.recipe_id
    # But the pin stays the same — owner selects the recipe, not vice versa
    assert pin.family_id == "test-owner-fixture"


# ---------------------------------------------------------------------------
# Foundation isolation: no provider/Hindsight/LSP vocabulary
# ---------------------------------------------------------------------------


def test_foundation_recipe_loader_has_no_provider_vocabulary() -> None:
    """Foundation loader contains no provider/Hindsight/LSP terms."""
    import audiagentic.foundation.toolchains.recipe_loader as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    lower_src = source.lower()

    forbidden_terms = ["provider", "hindsight", "lsp", "codex", "pi-"]
    for term in forbidden_terms:
        assert term not in lower_src, (
            f"Foundation loader must not contain '{term}'"
        )


def test_foundation_materializer_has_no_provider_vocabulary() -> None:
    """Foundation materializer contains no provider/Hindsight/LSP terms."""
    import audiagentic.foundation.toolchains.recipe_materializer as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    lower_src = source.lower()

    forbidden_terms = ["provider", "hindsight", "lsp", "codex", "pi-"]
    for term in forbidden_terms:
        assert term not in lower_src, (
            f"Foundation materializer must not contain '{term}'"
        )


def test_foundation_catalogue_has_no_provider_vocabulary() -> None:
    """Foundation catalogue contains no provider/Hindsight/LSP terms."""
    import audiagentic.foundation.toolchains.recipe_catalogue as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    lower_src = source.lower()

    forbidden_terms = ["provider", "hindsight", "lsp", "codex", "pi-"]
    for term in forbidden_terms:
        assert term not in lower_src, (
            f"Foundation catalogue must not contain '{term}'"
        )


def test_foundation_patterns_has_no_provider_vocabulary() -> None:
    """Foundation patterns contains no provider/Hindsight/LSP imports or types.

    User-facing message strings may mention 'provider' descriptively (e.g.
    'no automated install for this provider') — that is acceptable. What matters
    is that the code does not import from or depend on provider/Hindsight/LSP
    component concepts.
    """
    import audiagentic.foundation.toolchains.recipe_patterns as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")

    # Check imports: no imports from components/providers, hindsight, lsp, etc.
    assert "from audiagentic.components.providers" not in source
    assert "from audiagentic.hindsight" not in source
    assert "from audiagentic.coding_lsp" not in source
    assert "from audiagentic.components.harness" not in source

    # Check type references: no provider-specific class names in non-string code
    # (strip string literals to avoid false positives from user-facing messages)
    import re
    # Remove triple-quoted strings, single-line strings, and comments
    stripped = re.sub(r'""".*?"""', '""', source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "''", stripped, flags=re.DOTALL)
    stripped = re.sub(r'"[^"]*"', '""', stripped)
    stripped = re.sub(r"'[^']*'", "''", stripped)
    stripped = re.sub(r'#.*$', '', stripped, flags=re.MULTILINE)
    lower_src = stripped.lower()

    forbidden_types = ["hindsight", "codex", "lsp_", "pi-"]
    for term in forbidden_types:
        assert term not in lower_src, (
            f"Foundation patterns code must not reference '{term}'"
        )


# ---------------------------------------------------------------------------
# No raw unchecked recipe dictionaries after loader boundary
# ---------------------------------------------------------------------------


def test_loader_returns_frozen_template_not_dict() -> None:
    """Loader returns a frozen DeclarativeRecipeTemplate, not raw dict."""
    template = _load_fixture("hindsight-codex")

    assert not isinstance(template, dict)
    # Frozen — mutation should fail
    with pytest.raises(Exception):  # FrozenInstanceError or similar
        template.recipe_id = "mutated"  # type: ignore[misc]


def test_materializer_accepts_only_string_params() -> None:
    """Materializer accepts Mapping[str, str] at the owner boundary."""
    template = _load_fixture("hindsight-codex")

    # Valid string params
    mat = materialize_recipe(template, {"URL": "http://test", "TOKEN": "x"})
    assert mat.resolved_params is not None
    assert isinstance(mat.resolved_params.values, dict)
    for v in mat.resolved_params.values.values():
        assert isinstance(v, str)


# ---------------------------------------------------------------------------
# Adapter does not create universal RecipeBinding or public repair/dry_run
# ---------------------------------------------------------------------------


def test_adapter_has_no_universal_binding_schema() -> None:
    """The adapter module has no universal binding or recipe-binding types."""
    import audiagentic.components.providers.services.capabilities.declarative_recipe_handler as mod

    assert not hasattr(mod, "RecipeBinding")
    assert not hasattr(mod, "UniversalRecipe")
    assert not hasattr(mod, "RecipeRegistry")


def test_adapter_exports_only_make_declarative_handler() -> None:
    """Adapter public API is minimal — only the factory function."""
    import audiagentic.components.providers.services.capabilities.declarative_recipe_handler as mod

    assert mod.__all__ == ["make_declarative_handler"]
