from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.secrets import has_ambient_value, parse_secret_ref, resolve_secret_ref


def test_environment_secret_resolves_without_value_in_reference(monkeypatch) -> None:
    monkeypatch.setenv("TEST_SECRET_VALUE", "canary-secret")

    ref = parse_secret_ref("env:TEST_SECRET_VALUE")

    assert str(ref) == "env:TEST_SECRET_VALUE"
    assert has_ambient_value(ref) is True
    assert resolve_secret_ref(ref) == "canary-secret"
    assert "canary-secret" not in repr(ref)


def test_unset_environment_secret_reports_name_not_value(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_TEST_SECRET", raising=False)

    with pytest.raises(AudiaGenticError) as raised:
        resolve_secret_ref("env:MISSING_TEST_SECRET")

    assert raised.value.code == "CON-SEC-001"
    assert "MISSING_TEST_SECRET" in str(raised.value)


@pytest.mark.parametrize("value", ["missing-colon", "env:lowercase", "unknown:value"])
def test_invalid_or_unknown_secret_reference_is_rejected(value: str) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        parse_secret_ref(value)

    assert raised.value.code == "VAL-SEC-001"
