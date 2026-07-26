"""Runtime system environment utilities.

Platform detection, process identity, and other runtime environment
information that foundation and components may consume.

Uses the stdlib :mod:`platform` module for accurate detection — no
third-party dependencies required.  All public functions are cached
via ``lru_cache`` so repeated calls carry no overhead.

Usage::

    from audiagentic.runtime.system.platform import get_platform_info

    info = get_platform_info()          # → PlatformInfo(key='linux', ...)
    if info.is_linux:
        d = info.linux_distro            # → LinuxDistroInfo(id='ubuntu', ...)
        print(d.pretty_name)             # → "Ubuntu 24.04.1 LTS"
    elif info.is_windows:
        w = info.windows                 # → WindowsEditionInfo(edition='Professional', ...)
        print(w.edition)                 # → "Professional"
    elif info.is_macos:
        m = info.macos_version           # → MacOsVersionInfo(version='14.4.1', codename='Sonoma')
        print(m.codename)                # → "Sonoma"

Backward-compatible helper::

    from audiagentic.runtime.system.platform import platform_key
    key = platform_key()                 # → 'win' | 'darwin' | 'linux'
"""

from __future__ import annotations

import logging
import platform as _platform
import sys
from dataclasses import dataclass
from functools import lru_cache

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

# ---------------------------------------------------------------------------
# Error factory
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def _platform_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    """Build a platform-detection error (VAL-PLAT-###)."""
    return make_error(
        prefix="VAL",
        component="PLAT",
        number=code_number,
        kind="platform",
        message=message,
        details=details or None,
    )


# ---------------------------------------------------------------------------
# Platform-specific detail types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowsEditionInfo:
    """Structured Windows edition information.

    Sourced from :func:`platform.win32_ver` and :func:`platform.win32_edition`.
    """

    release: str | None = None  # e.g. "10", "11"
    build: str | None = None  # e.g. "19041"
    service_pack: str | None = None  # e.g. "Service Pack 1" (legacy)
    is_server: bool | None = None  # True for Server editions, False for client
    edition: str | None = None  # e.g. "Professional", "Enterprise", "Home"


@dataclass(frozen=True)
class MacOsVersionInfo:
    """Structured macOS version information.

    Sourced from :func:`platform.mac_ver` with an inferred codename.
    """

    version: str | None = None  # e.g. "14.4.1"
    major: int | None = None  # e.g. 14
    minor: int | None = None  # e.g. 4
    patch: int | None = None  # e.g. 1
    codename: str | None = None  # e.g. "Monterey", "Sequoia"
    processor: str | None = None  # e.g. "i386", "arm"


@dataclass(frozen=True)
class LinuxDistroInfo:
    """Structured distro information from ``/etc/os-release``.

    Fields correspond to the freedesktop os-release spec.
    All fields are optional — not every distro populates every key.
    """

    id: str | None = None  # e.g. "ubuntu", "fedora"
    id_like: str | None = None  # e.g. "debian"
    name: str | None = None  # e.g. "Ubuntu"
    pretty_name: str | None = None  # e.g. "Ubuntu 24.04.1 LTS"
    version: str | None = None  # human-friendly, e.g. "24.04.1 LTS"
    version_id: str | None = None  # machine-friendly, e.g. "24.04"
    version_codename: str | None = None  # e.g. "noble"
    build_id: str | None = None
    variant: str | None = None  # e.g. "Server"
    variant_id: str | None = None
    home_url: str | None = None
    documentation_url: str | None = None
    support_url: str | None = None
    bug_report_url: str | None = None
    privacy_policy_url: str | None = None
    icon: str | None = None


# ---------------------------------------------------------------------------
# Unified platform info
# ---------------------------------------------------------------------------

# Internal — canonical key for each ``platform.system()`` value.
_PLATFORM_MAP: dict[str, str] = {
    "Windows": "win",
    "Darwin": "darwin",
    "Linux": "linux",
}

# macOS release codenames mapped from major version number (internal).
_MACOS_CODENAMES: dict[int, str] = {
    16: "Sequoia",
    15: "Ventura",
    14: "Sonoma",
    13: "Monterey",
    12: "Monterey",
    11: "Big Sur",
    10: "Catalina",
}

@dataclass(frozen=True)
class PlatformInfo:
    """Structured platform information.

    Generic fields are always populated. Platform-specific detail is
    available via :attr:`windows`, :attr:`macos_version`, and
    :attr:`linux_distro` — only one will be non-``None``.

    Example::

        info = get_platform_info()          # → PlatformInfo(key='linux', os='Linux', ...)
        if info.is_linux:
            d = info.linux_distro           # → LinuxDistroInfo(id='ubuntu', version_id='24.04')
            print(d.pretty_name)            # → "Ubuntu 24.04.1 LTS"
    """

    key: str  # 'win', 'darwin', 'linux'

    # Generic fields — always populated
    os: str  # 'Windows', 'Darwin', 'Linux'
    release: str  # e.g. "10", "23.4.0", "6.5.0-generic"
    version: str  # full version string
    machine: str  # e.g. "AMD64", "arm64"
    processor: str  # e.g. "Intel64 Family 6 Model 154"
    python_version: str  # e.g. "3.12.4"
    is_wsl: bool  # True under WSL

    # Platform-specific detail — only one is non-None
    windows: WindowsEditionInfo | None = None
    macos_version: MacOsVersionInfo | None = None
    linux_distro: LinuxDistroInfo | None = None

    @property
    def is_windows(self) -> bool:
        return self.key == "win"

    @property
    def is_macos(self) -> bool:
        return self.key == "darwin"

    @property
    def is_linux(self) -> bool:
        return self.key == "linux"


# ---------------------------------------------------------------------------
# Internal builders — each is resilient; failures log and return None.
# ---------------------------------------------------------------------------


def _detect_wsl() -> bool:
    """Detect whether we are running under WSL (Windows Subsystem for Linux).

    Checks :file:`/proc/version` for the ``microsoft`` substring.
    Returns ``False`` on non-Linux platforms or when the file is unreadable.
    """
    if _platform.system() != "Linux":
        return False
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("WSL detection failed: %s", exc)
        return False


def _build_windows_info() -> WindowsEditionInfo | None:
    """Build a :class:`WindowsEditionInfo` from stdlib platform calls."""
    try:
        release, version, csd, ptype = _platform.win32_ver()
        edition = _platform.win32_edition() or None
        is_server = "Server" in ptype if ptype else None
        return WindowsEditionInfo(
            release=release or None,
            build=version or None,
            service_pack=(csd.strip() if csd and csd.strip() else None),
            is_server=is_server,
            edition=edition,
        )
    except Exception as exc:  # noqa: BLE001 — log and degrade gracefully
        logger.debug("Windows edition detection failed: %s", exc)
        return None


def _build_macos_info() -> MacOsVersionInfo | None:
    """Build a :class:`MacOsVersionInfo` from stdlib platform calls."""
    try:
        ver, machine_info, _ = _platform.mac_ver()
        version = ver.strip() if ver else ""
        if not version:
            return MacOsVersionInfo()
        parts = list(map(int, version.split(".")[:3]))
        major = parts[0] if parts else None
        codename = _MACOS_CODENAMES.get(major) if major is not None else None
        # machine_info is a 3-tuple: (machine, processor, hw_machine)
        proc = machine_info[1] if machine_info and len(machine_info) > 1 else None
        return MacOsVersionInfo(
            version=version or None,
            major=major,
            minor=parts[1] if len(parts) > 1 else None,
            patch=parts[2] if len(parts) > 2 else None,
            codename=codename,
            processor=proc or None,
        )
    except Exception as exc:  # noqa: BLE001 — log and degrade gracefully
        logger.debug("macOS version detection failed: %s", exc)
        return None


def _build_distro_info(release: dict[str, str]) -> LinuxDistroInfo:
    """Map an os-release ``dict`` to :class:`LinuxDistroInfo`."""
    return LinuxDistroInfo(
        id=release.get("ID"),
        id_like=release.get("ID_LIKE"),
        name=release.get("NAME"),
        pretty_name=release.get("PRETTY_NAME"),
        version=release.get("VERSION"),
        version_id=release.get("VERSION_ID"),
        version_codename=release.get("VERSION_CODENAME"),
        build_id=release.get("BUILD_ID"),
        variant=release.get("VARIANT"),
        variant_id=release.get("VARIANT_ID"),
        home_url=release.get("HOME_URL"),
        documentation_url=release.get("DOCUMENTATION_URL"),
        support_url=release.get("SUPPORT_URL"),
        bug_report_url=release.get("BUG_REPORT_URL"),
        privacy_policy_url=release.get("PRIVACY_POLICY_URL"),
        icon=release.get("ICON"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def platform_key() -> str:
    """Return a stable platform identifier: ``'win'``, ``'darwin'``, or ``'linux'``.

    Canonical source for platform detection across the codebase.
    Backward-compatible — returns the same strings as before.

    Returns::

        platform_key()    # → 'win' | 'darwin' | 'linux'

    Raises:
        AudiaGenticError (VAL-PLAT-001): If ``platform.system()`` returns an
            unrecognized value and no fallback can be determined.
    """
    key = _PLATFORM_MAP.get(_platform.system())
    if key is None:
        raise _platform_error(
            1,
            "unrecognized platform",
            system=_platform.system(),
        )
    return key


@lru_cache(maxsize=1)
def get_platform_info() -> PlatformInfo:
    """Return a :class:`PlatformInfo` snapshot (cached after first call).

    The single entry point for all platform detection.  Platform-specific
    sub-structures (:attr:`PlatformInfo.windows`, :attr:`PlatformInfo.macos_version`,
    :attr:`PlatformInfo.linux_distro`) are populated only on the matching OS.
    """
    uname = _platform.uname()
    key = platform_key()  # raises VAL-PLAT-001 if unrecognized

    windows: WindowsEditionInfo | None = None
    macos_version: MacOsVersionInfo | None = None
    linux_distro: LinuxDistroInfo | None = None

    if key == "win":
        windows = _build_windows_info()
    elif key == "darwin":
        macos_version = _build_macos_info()
    else:  # linux — including WSL
        try:
            release = _platform.freedesktop_os_release()
            if release:
                linux_distro = _build_distro_info(dict(release))
        except AttributeError:
            pass  # Python < 3.10 — freedesktop_os_release not available

    return PlatformInfo(
        key=key,
        os=uname.system,
        release=uname.release,
        version=uname.version.strip(),
        machine=uname.machine or "",
        processor=_platform.processor() or "",
        python_version=sys.version.split()[0],
        is_wsl=_detect_wsl(),
        windows=windows,
        macos_version=macos_version,
        linux_distro=linux_distro,
    )


# Release binaries for external providers (opencode, pi, ...) are published
# under GitHub release asset names like "windows-amd64", "darwin-arm64" —
# distinct from platform_key()'s internal 'win'/'darwin'/'linux' vocabulary.
_RELEASE_OS_NAMES: dict[str, str] = {"win": "windows", "darwin": "darwin", "linux": "linux"}
_RELEASE_ARCH_NAMES: dict[str, str] = {"x86_64": "amd64", "aarch64": "arm64", "x86": "386"}


def release_platform_name() -> str:
    """Return the current host as a provider release-asset platform name.

    Matches the ``os-arch`` naming external providers publish their release
    binaries under (e.g. ``"windows-amd64"``, ``"darwin-arm64"``) — used to
    select the correct download asset and to match ``platform_evidence``
    entries in provider descriptors. Derived from :func:`get_platform_info`.
    """
    info = get_platform_info()
    raw_arch = info.machine.lower()
    arch = _RELEASE_ARCH_NAMES.get(raw_arch, raw_arch)
    return f"{_RELEASE_OS_NAMES[info.key]}-{arch}"


# ---------------------------------------------------------------------------
# Public symbols
# ---------------------------------------------------------------------------

__all__ = [
    "AudiaGenticError",
    "get_platform_info",
    "LinuxDistroInfo",
    "MacOsVersionInfo",
    "PlatformInfo",
    "platform_key",
    "release_platform_name",
    "WindowsEditionInfo",
]
