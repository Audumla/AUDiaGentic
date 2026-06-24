"""Shared error factories for the runtime rig modules.

Consolidates all rig error factories that previously lived as private
functions in individual modules (http.py, resolution.py, process.py,
launch.py, config.py, models.py, binaries.py).

Each factory wraps ``make_error()`` with the correct component code so
that callers only supply the prefix, error number, message, and details.
"""
from __future__ import annotations

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error


def make_rig_http_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for http.py operations."""
    return make_error(
        prefix=prefix,
        component="RIGHTEPT",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_resolution_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for resolution.py operations."""
    return make_error(
        prefix=prefix,
        component="RIGRES",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_process_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for process.py operations."""
    return make_error(
        prefix=prefix,
        component="RIGPROC",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_launch_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for launch.py operations (prefix must be supplied)."""
    return make_error(
        prefix=prefix,
        component="RIGLAUNCH",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_launch_error_ext(
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for launch.py operations with prefix="EXT" baked in."""
    return make_error(
        prefix="EXT",
        component="RIGLAUNCH",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_config_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for config.py operations (prefix must be supplied)."""
    return make_error(
        prefix=prefix,
        component="RIGCFG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_config_error_cfg(
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for config.py operations with prefix="CFG" baked in."""
    return make_error(
        prefix="CFG",
        component="RIGCFG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_model_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for models.py operations (prefix must be supplied)."""
    return make_error(
        prefix=prefix,
        component="RIG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_model_error_cfg(
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for models.py operations with prefix="CFG" baked in."""
    return make_error(
        prefix="CFG",
        component="RIG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def make_rig_binary_error(
    prefix: str,
    code_number: int,
    message: str,
    **details: object,
) -> AudiaGenticError:
    """Error factory for binaries.py operations."""
    return make_error(
        prefix=prefix,
        component="RIGBIN",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )
