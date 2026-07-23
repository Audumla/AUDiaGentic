"""Provider credential-reference parsing and resolution.

References are opaque until the narrow call site that needs a value.  V1
supports ambient environment variables only; callers must never persist or log
the returned value.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.registry_utils import Registry

_secret_error = make_error_factory("VAL", "SEC", "secret")
_secret_connection_error = make_error_factory("CON", "SEC", "secret")
_ENV_NAME = re.compile(r"^[A-Z0-9_]+$")

SecretResolver = Callable[[str], str]


@dataclass(frozen=True)
class SecretRef:
    """Parsed secret reference; never stores a resolved secret value."""

    scheme: str
    locator: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.locator}"


def parse_secret_ref(value: str) -> SecretRef:
    """Validate the shared ``env:NAME`` secret-reference grammar."""
    scheme, separator, locator = value.partition(":")
    if not separator or not scheme or not locator:
        raise _secret_error(1, "secret reference must use scheme:locator syntax")
    if scheme == "env" and not _ENV_NAME.fullmatch(locator):
        raise _secret_error(1, "environment secret reference has an invalid variable name")
    if _resolvers.get(scheme) is None:
        raise _secret_error(1, f"secret reference scheme {scheme!r} is not registered")
    return SecretRef(scheme=scheme, locator=locator)


def register_secret_scheme(scheme: str, resolver: SecretResolver, *, replace: bool = False) -> None:
    """Register a resolver without changing callers or dispatch code."""
    _resolvers.register(scheme, resolver, replace=replace)


def resolve_secret_ref(value: str | SecretRef) -> str:
    """Resolve a reference only at the immediate consuming boundary."""
    ref = parse_secret_ref(value) if isinstance(value, str) else value
    resolver = _resolvers.get(ref.scheme)
    if resolver is None:  # Defensive: handles test registry resets.
        raise _secret_error(1, f"secret reference scheme {ref.scheme!r} is not registered")
    return resolver(ref.locator)


def is_registered_scheme(scheme: str) -> bool:
    """True when *scheme* has a registered resolver.

    Lets callers distinguish "this string is a secret reference" from "this
    string is a literal that happens to contain a colon" without swallowing
    parse errors for genuinely malformed references.
    """
    return _resolvers.get(scheme) is not None


def has_ambient_value(value: str | SecretRef) -> bool:
    """Check availability without resolving or returning a secret."""
    ref = parse_secret_ref(value) if isinstance(value, str) else value
    if ref.scheme != "env":
        return False
    return bool(os.environ.get(ref.locator))


def _resolve_environment(locator: str) -> str:
    value = os.environ.get(locator)
    if not value:
        raise _secret_connection_error(1, "referenced environment variable is unset", env_name=locator)
    return value


def _load_builtin_schemes() -> None:
    register_secret_scheme("env", _resolve_environment)


_resolvers: Registry[SecretResolver] = Registry(loader=_load_builtin_schemes)
