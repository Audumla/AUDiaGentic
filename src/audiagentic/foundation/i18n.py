"""I18n registry — config-driven string lookup with locale switching and pluralization.

The canonical access mechanism for all externalized user-facing text. Loads translation
catalogs from per-component YAML files at startup. Provides key-based lookup with
fallback chain, interpolation, and babel.plural-based plural form selection.

Key convention: component-scoped dot-notation keys (e.g. "planning.item_plan_required",
"lsp.symbol_kind.class"). The first segment before the first dot is the component name;
remaining segments traverse nested YAML.

Catalog layout: per-component translations live in their own subdirectory under
``config/locales/<component>/en.yaml``, ``config/locales/<component>/de.yaml``, etc. at
project scope; package defaults live in the same path under the installed package.

Usage:
    >>> I18n.t("planning.item_plan_required")
    "The 'plan' field is required for plan items."
    >>> I18n.t("planning.item_not_found", item_id="CC01")
    "item not found: 'CC01'"
    >>> I18n.t_plural("files.one", "files.other", count=3, count=3)
    "3 files found"
    >>> I18n.set_locale("de")
    >>> I18n.get_locale()
    "de"
"""
from __future__ import annotations

import logging
import string
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file

logger = logging.getLogger(__name__)


def _deep_get(data: dict[str, Any], key: str) -> Any:
    """Resolve a dot-notation key into nested dicts. Returns None if not found."""
    parts = key.split(".", 1)
    first = parts[0]
    value = data.get(first)
    if len(parts) == 1 or value is None:
        return value
    if not isinstance(value, dict):
        return None
    return _deep_get(value, parts[1])


def _safe_interpolate(template: str, ctx: dict[str, Any]) -> str:
    """Apply string interpolation via :meth:`str.format_map`, safe for missing keys."""
    try:
        return template.format_map(ctx)
    except KeyError:

        class _SafeFormatter(string.Formatter):
            def get_value(self, key: Any, args: Any, kwargs: Any) -> Any:
                if isinstance(key, int) and key < len(args):
                    return args[key]
                return kwargs.get(str(key), "{" + str(key) + "}")

        return _SafeFormatter().format(template, **ctx)


def _english_plural(n: int) -> str:
    """Fallback plural rule for English (one/other)."""
    return "one" if n == 1 else "other"


# ── Singleton instance ────────────────────────────────────────────────

_i18n_instance: _I18n | None = None


class _I18n:
    """Internal translation registry implementation.

    Not meant for direct use — access through the module-level ``I18n`` object or
    the public convenience functions.
    """

    _catalogs: dict[str, dict]  # per-locale merged catalog (component -> data)
    _default_locale: str
    _fallback_chain: list[str]

    def __init__(self) -> None:
        self._catalogs = {}
        self._default_locale = "en"
        self._fallback_chain = ["en"]

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def initialize(self, config_dirs: list[Path] | None = None) -> None:
        """Load translation catalogs from all component locale directories."""
        import os

        from audiagentic.foundation.paths.names import get_component_config_dirs

        self._default_locale = os.environ.get("AUDIAGENTIC_LOCALE", "en")
        unique_fallbacks: list[str] = []
        for loc in [self._default_locale, "en"]:
            if loc not in unique_fallbacks:
                unique_fallbacks.append(loc)
        self._fallback_chain = unique_fallbacks

        targets = config_dirs or get_component_config_dirs()

        for config_dir in targets:
            locales_dir = config_dir / "locales"
            if not locales_dir.exists():
                continue
            self._load_from_locales_dir(locales_dir)

        # Also load package-level defaults (the installed package locale files)
        _PACKAGE_LOCALES = Path(__file__).resolve().parents[0] / "config" / "locales"
        if _PACKAGE_LOCALES.exists():
            self._load_from_locales_dir(_PACKAGE_LOCALES)

        logger.debug(
            "I18n initialized",
            extra={"locale": self._default_locale, "catalogs": sorted(self._catalogs.keys())},
        )

    def _load_from_locales_dir(self, locales_dir: Path) -> None:
        """Load YAML files from a locales directory tree.

        Expected structure::

            <component>/en.yaml
            <component>/de.yaml

        Data is nested under the component name so that keys like
        ``planning.item_plan_required`` resolve to the entry at key
        ``item_plan_required`` inside the ``planning/`` subdirectory.
        """
        for component_dir in sorted(locales_dir.iterdir()):
            if not component_dir.is_dir():
                continue
            component = component_dir.name
            for yaml_path in sorted(component_dir.glob("*.yaml")):
                locale = yaml_path.stem
                try:
                    data = load_yaml_file(yaml_path)
                except Exception:
                    logger.warning(
                        "Failed to load I18n catalog",
                        extra={"component": component, "locale": locale, "path": str(yaml_path)},
                    )
                    continue
                if not isinstance(data, dict):
                    logger.warning(
                        "I18n catalog is not a mapping",
                        extra={"component": component, "locale": locale},
                    )
                    continue
                if locale not in self._catalogs:
                    self._catalogs[locale] = {}
                locale_catalog = self._catalogs[locale]
                # Nest under the component name for dot-notation lookup
                if component not in locale_catalog or not isinstance(locale_catalog[component], dict):
                    locale_catalog[component] = data
                else:
                    _deep_merge(locale_catalog[component], data)

    # ── Locale management ────────────────────────────────────────────────────

    def set_locale(self, locale: str) -> None:
        """Change the process-wide default locale."""
        self._default_locale = locale
        unique_fallbacks: list[str] = []
        for loc in [locale, "en"]:
            if loc not in unique_fallbacks:
                unique_fallbacks.append(loc)
        self._fallback_chain = unique_fallbacks
        logger.debug("Locale changed", extra={"locale": locale})

    def get_locale(self) -> str:
        """Return the current process-wide default locale."""
        return self._default_locale

    # ── Translation lookup ───────────────────────────────────────────────────

    def t(self, key: str, locale: str | None = None, **ctx: Any) -> str:
        """Look up a translation key with optional interpolation."""
        raw = self._lookup(key, locale)
        if ctx:
            return _safe_interpolate(raw, ctx)
        return raw

    def t_plural(
        self,
        key_singular: str,
        key_plural: str,
        count: int,
        locale: str | None = None,
        plural_func: Any = None,
        **ctx: Any,
    ) -> str:
        """Look up a pluralized translation."""
        target_locale = locale or self._default_locale

        try:
            from babel.plural import get_plural_rule  # type: ignore[attr-defined]

            rule = plural_func or get_plural_rule(target_locale)
        except (ImportError, LookupError):
            rule = _english_plural

        category = rule(count)  # e.g. "one", "few", "many", "other"

        ctx_with_count = {**ctx, "count": count}

        if category == "one":
            raw = self._lookup(key_singular, locale)
        else:
            raw = self._lookup(key_plural, locale)

        return _safe_interpolate(raw, ctx_with_count)

    def _lookup(self, key: str, locale: str | None = None) -> str:
        """Internal lookup with fallback chain."""
        locales_to_try: list[str]
        if locale:
            seen: set[str] = {locale}
            locales_to_try = [locale]
            for loc in self._fallback_chain:
                if loc not in seen:
                    seen.add(loc)
                    locales_to_try.append(loc)
        else:
            locales_to_try = list(self._fallback_chain)

        for loc in locales_to_try:
            catalog = self._catalogs.get(loc, {})
            value = _deep_get(catalog, key)
            if isinstance(value, str):
                return value

        # Key not found in any locale — fall back to the key itself
        return key

    def get_catalog(self, locale: str) -> dict:
        """Return the raw catalog for a given locale (for testing/debugging)."""
        return self._catalogs.get(locale, {})


def _get_instance() -> _I18n:
    """Return the singleton instance, creating it lazily."""
    global _i18n_instance
    if _i18n_instance is None:
        _i18n_instance = _I18n()
    return _i18n_instance


# ── Public API (delegates to singleton) ──────────────────────────────

class I18n:
    """I18n translation registry — use the class directly.

    All methods delegate to a singleton instance. Call ``initialize()`` once at
    startup (done automatically during component registration).

    >>> I18n.t("planning.item_plan_required")
    >>> I18n.t_plural("files.one", "files.other", count=3, count=3)
    >>> I18n.set_locale("de")
    """

    @staticmethod
    def t(key: str, locale: str | None = None, **ctx: Any) -> str:
        """Look up a translation key with optional interpolation."""
        return _get_instance().t(key, locale=locale, **ctx)

    @staticmethod
    def t_plural(
        key_singular: str,
        key_plural: str,
        count: int,
        locale: str | None = None,
        plural_func: Any = None,
        **ctx: Any,
    ) -> str:
        """Look up a pluralized translation using babel.plural rules."""
        return _get_instance().t_plural(
            key_singular, key_plural, count, locale=locale, plural_func=plural_func, **ctx
        )

    @staticmethod
    def set_locale(locale: str) -> None:
        """Change the process-wide default locale."""
        _get_instance().set_locale(locale)

    @staticmethod
    def get_locale() -> str:
        """Return the current process-wide default locale."""
        return _get_instance().get_locale()


def initialize(config_dirs: list[Path] | None = None) -> None:
    """Initialize the I18n singleton with locale catalogs from config directories.

    Called during component registration. Safe to call multiple times.
    """
    _get_instance().initialize(config_dirs)


def get_instance() -> _I18n:
    """Return the internal singleton instance for programmatic access."""
    return _get_instance()


# ── Error helper ─────────────────────────────────────────────────────

#: Maps error-code middle segment (e.g. "PLN" from "VAL-PLN-003") to component
#: name for I18n key resolution. Add new entries as new components are created.
_ERROR_CODE_PREFIX_MAP: dict[str, str] = {
    # Foundation / cross-cutting
    "COMP": "foundation",  # VAL-COMP-*
    "AGW": "foundation",   # RES-AGW-*, VAL-AGW-* (agent gateway)
    "AGP": "foundation",   # RES-AGP-*, VAL-AGP-* (agent profiles)
    "FTR": "foundation",   # VAL-FTR-*

    # Agents
    "AGT": "agents",       # AGENT-* (agent errors)

    # Agent jobs
    "JOB": "agent_jobs",   # JOB-*

    # Ledger
    "LDR": "ledger",       # LDR-*

    # Memory
    "MEM": "memory",       # MEM-*

    # Planning
    "PLN": "planning",     # VAL-PLN-*

    # Providers
    "PROV": "providers",   # PROV-*
    "SVC": "providers",    # SVC-* (service errors)

    # Project
    "PRJ": "project",      # PRJ-*

    # Release
    "REL": "release",      # REL-*

    # Rig
    "RIG": "rig",          # RIG-*

    # Session
    "SES": "session",      # SES-*

    # Source control
    "SRC": "source_control",  # SRC-*
}


def _t_err(code: str, **ctx: Any) -> str:
    """Resolve a translated error message from an error code.

    Looks up the I18n key ``<component>.errors.<code>`` where *component* is
    determined by the middle segment of the error code (e.g. ``VAL-PLN-003``
    maps to component ``planning``, yielding key ``planning.errors.VAL-PLN-003``).

    If the key is not found, falls back to the error code itself — ensuring the
    raise site never silently produces an empty message.

    Usage:
        >>> raise AudiaGenticError(code="VAL-PLN-003", message=_t_err("VAL-PLN-003"))
        >>> raise AudiaGenticError(code="PROV-001", message=_t_err("PROV-001", provider_id="claude"))

    Returns:
        Translated message string, or the error code if no translation exists.
    """
    prefix = code.split("-")[1] if "-" in code else code[:3].upper()
    component = _ERROR_CODE_PREFIX_MAP.get(prefix)
    if component:
        i18n_key = f"{component}.errors.{code}"
        return I18n.t(i18n_key, **ctx)
    # No component mapping — fall back to code itself
    return code


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Deep-merge *override* into *base* in-place."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
