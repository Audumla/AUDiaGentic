"""Validation for planning path and record identities."""
from __future__ import annotations

import re

from audiagentic.foundation.contracts.errors import AudiaGenticError

_PLAN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ITEM_RE = re.compile(r"^[A-Z]+[0-9]+$")
_REVIEW_RE = re.compile(r"^RV[0-9]+$")


def _validate(value: object, pattern: re.Pattern[str], kind: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AudiaGenticError(
            code="VAL-PLN-035",
            kind="validation",
            message=f"invalid planning {kind}",
            details={"kind": kind},
        )
    return value


def validate_plan_slug(value: object) -> str:
    return _validate(value, _PLAN_RE, "plan slug")


def validate_item_id(value: object) -> str:
    result = _validate(value, _ITEM_RE, "item ID")
    if result.startswith("RV"):
        raise AudiaGenticError(code="VAL-PLN-035", kind="validation", message="review IDs are not item IDs")
    return result


def validate_review_id(value: object) -> str:
    return _validate(value, _REVIEW_RE, "review ID")


def validate_record_id(value: object) -> str:
    if isinstance(value, str) and value.startswith("RV"):
        return validate_review_id(value)
    return validate_item_id(value)
