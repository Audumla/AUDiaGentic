"""Provider-owned packaged prompt profiles for agent execution."""
from __future__ import annotations

import hashlib
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError

_ROOT = Path(__file__).with_name("templates") / "agents"
_PROFILE_VARIANTS = {
    "default": ("default", "default-with-body"),
    "review": ("review", "review-with-body"),
}


def template_name_for_profile(profile_id: str, *, has_body: bool) -> str:
    variants = _PROFILE_VARIANTS.get(profile_id)
    if variants is None:
        raise AudiaGenticError(
            code="CFG-APT-001", kind="agents",
            message="unknown prompt profile",
            details={"profile-id": profile_id, "known": sorted(_PROFILE_VARIANTS)},
        )
    return variants[1 if has_body else 0]


def load_profile_template(profile_id: str, *, has_body: bool) -> tuple[str, str, str]:
    """Return (template text, logical name, sha256 digest)."""
    name = template_name_for_profile(profile_id, has_body=has_body)
    path = _ROOT / f"{name}.md"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AudiaGenticError(
            code="IO-APT-001", kind="agents",
            message="packaged prompt profile template is missing",
            details={"profile-id": profile_id, "template-name": name},
        ) from exc
    # Source files carry a readability newline; compatibility templates are
    # defined without that terminal byte, matching the legacy builder.
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    digest = hashlib.sha256(raw).hexdigest()
    return raw.decode("utf-8"), name, digest


def verify_template_digest(template_name: str, expected_digest: str) -> str:
    path = _ROOT / f"{template_name}.md"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AudiaGenticError(
            code="IO-APT-001", kind="agents",
            message="packaged prompt profile template is missing",
            details={"template-name": template_name},
        ) from exc
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_digest:
        raise AudiaGenticError(
            code="CON-APT-001", kind="agents",
            message="packaged prompt profile template digest changed",
            details={"template-name": template_name, "expected": expected_digest, "actual": actual},
        )
    return raw.decode("utf-8")


def known_profile_ids() -> tuple[str, ...]:
    return tuple(sorted(_PROFILE_VARIANTS))
