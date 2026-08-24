"""Strict project-owned configuration for the gpt-auto provider runtime."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.workflow import EvidencePolicy

from .urls import parse_project_id

_DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")

# gpt-auto only connects to an already-running browser via CDP -- it never
# launches one -- so there is nothing to "install" here. These are just the
# well-known install locations for CDP-capable Chromium browsers per
# platform, used to turn a bare "file not found" into an actionable
# suggestion (or confirm the machine has no candidate at all).
_WINDOWS_BROWSER_CANDIDATES = (
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)
_MACOS_BROWSER_CANDIDATES = (
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
_LINUX_BROWSER_CANDIDATES = (
    "/usr/bin/brave-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/brave",
    "/snap/bin/chromium",
)


def discover_browser_candidates() -> tuple[Path, ...]:
    """Probe well-known install locations for a CDP-capable browser.

    Detection only -- gpt-auto never launches or installs a browser, it
    connects to one already running with --remote-debugging-port. Returns
    every candidate that actually exists on this machine, most-preferred
    first (Brave before Chrome, matching the packaged default).
    """
    if sys.platform == "win32":
        raw_candidates = _WINDOWS_BROWSER_CANDIDATES
    elif sys.platform == "darwin":
        raw_candidates = _MACOS_BROWSER_CANDIDATES
    else:
        raw_candidates = _LINUX_BROWSER_CANDIDATES
    found: list[Path] = []
    for raw in raw_candidates:
        candidate = Path(os.path.expandvars(raw))
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return tuple(found)

# GP21: contract-version is the real schema contract, distinct from the
# resolved GptAutoConfig.contract_version this module always produces.
# v1 predates GP07's two submission-proof fields; v2 requires them
# explicitly. migrate_v1_to_v2() lets an older project config keep working
# (filling sane defaults) instead of hard-failing the whole shared gateway
# the moment gpt_auto's own schema grows -- the exact bigcherry incident
# GP09 was raised about.
CURRENT_CONTRACT_VERSION = "v2"
SUPPORTED_CONTRACT_VERSIONS = ("v1", "v2")
_V1_SUBMISSION_PROOF_DEFAULTS = {
    "submission-proof-progress-lease-seconds": 300,
    "submission-proof-absolute-ceiling-seconds": 900,
}


def migrate_v1_to_v2(settings: dict[str, Any]) -> dict[str, Any]:
    """Fill v2's two new required turn fields with v1-era defaults if absent.

    Only fills keys that are genuinely missing -- an explicit v1 config that
    already happens to set these (unusual, but not invalid) keeps its own
    values rather than being silently overridden.
    """
    turn_data = settings.get("turn")
    if not isinstance(turn_data, dict):
        return settings
    missing = {
        key: value
        for key, value in _V1_SUBMISSION_PROOF_DEFAULTS.items()
        if key not in turn_data
    }
    if not missing:
        return settings
    result = dict(settings)
    result["turn"] = {**turn_data, **missing}
    return result


class ExistingBrowserPolicy(StrEnum):
    FAIL = "fail"
    RESTART = "restart"


@dataclass(frozen=True)
class BrowserConfig:
    executable: Path
    remote_debugging_port: int
    existing_browser_policy: ExistingBrowserPolicy
    shutdown_timeout_seconds: float
    force_kill: bool
    dedicated_window: bool
    close_tabs_on_session_close: bool


@dataclass(frozen=True)
class CdpConfig:
    connect_timeout_seconds: float
    protocol_timeout_seconds: float
    recovery_timeout_seconds: float
    devtools_active_port_file: Path | None


@dataclass(frozen=True)
class ChatConfig:
    ready_timeout_seconds: float
    navigation_timeout_seconds: float


@dataclass(frozen=True)
class TurnConfig:
    submission_timeout_seconds: float
    response_start_timeout_seconds: float
    response_stall_timeout_seconds: float
    response_timeout_seconds: float
    poll_interval_seconds: float
    response_stability_seconds: float
    response_generating_override_stability_seconds: float
    # GP07: submission-proof's observation clock must be activity-aware, not
    # a single fixed deadline from action-start -- submission_timeout_seconds
    # remains the raw type+send CDP-call timeout and this phase's start-bound
    # (did we see ANY sign of it at all); these two govern everything after.
    submission_proof_progress_lease_seconds: float
    submission_proof_absolute_ceiling_seconds: float


class DomSignalScope(StrEnum):
    DOCUMENT = "document"
    LATEST_ASSISTANT_TURN = "latest-assistant-turn"


@dataclass(frozen=True)
class DomSignalConfig:
    name: str
    scope: DomSignalScope
    selectors: tuple[str, ...]
    visible: bool
    text_contains_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnWorkflowConfig:
    dom_signals: tuple[DomSignalConfig, ...]
    evidence_policies: tuple[tuple[str, EvidencePolicy], ...]

    def policy(self, name: str) -> EvidencePolicy:
        for policy_name, policy in self.evidence_policies:
            if policy_name == name:
                return policy
        raise KeyError(name)

    def bridge_signals(self) -> list[dict[str, Any]]:
        return [
            {
                "name": signal.name,
                "scope": signal.scope.value,
                "selectors": list(signal.selectors),
                "visible": signal.visible,
                "textContainsAny": list(signal.text_contains_any),
            }
            for signal in self.dom_signals
        ]


@dataclass(frozen=True)
class GptAutoConfig:
    contract_version: str
    project_url: str | None
    browser: BrowserConfig
    cdp: CdpConfig
    chat: ChatConfig
    turn: TurnConfig
    workflow: TurnWorkflowConfig

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.browser.remote_debugging_port}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GptAutoConfig:
        settings = data.get("settings", data)
        if not isinstance(settings, dict):
            _invalid("settings must be a mapping")
        _exact_keys(
            settings,
            {"contract-version", "project-url", "browser", "cdp", "chat", "turn", "workflow"},
            "settings",
            required={"contract-version", "browser", "cdp", "chat", "turn", "workflow"},
        )
        declared_version = settings.get("contract-version")
        if declared_version not in SUPPORTED_CONTRACT_VERSIONS:
            _invalid(
                f"contract-version must be one of {SUPPORTED_CONTRACT_VERSIONS}, "
                f"got {declared_version!r}"
            )
        if declared_version == "v1":
            settings = migrate_v1_to_v2(settings)
        project_url = (
            _chatgpt_url(settings.get("project-url"))
            if settings.get("project-url") is not None
            else None
        )

        browser_data = _mapping(settings, "browser")
        _exact_keys(
            browser_data,
            {
                "executable",
                "remote-debugging-port",
                "existing-browser-policy",
                "shutdown-timeout-seconds",
                "force-kill",
                "dedicated-window",
                "close-tabs-on-session-close",
            },
            "browser",
            required={
                "executable",
                "remote-debugging-port",
                "existing-browser-policy",
                "shutdown-timeout-seconds",
                "force-kill",
                "dedicated-window",
            },
        )
        executable = Path(_string(browser_data, "executable"))
        if not executable.is_file():
            candidates = discover_browser_candidates()
            if candidates:
                hint = "; detected on this machine: " + ", ".join(str(c) for c in candidates)
            else:
                hint = "; no supported browser (Brave/Chrome) was detected on this machine"
            _invalid(f"browser.executable must name an existing file (got {executable}){hint}")
        port = _integer(browser_data, "remote-debugging-port")
        if not 1 <= port <= 65535:
            _invalid("browser.remote-debugging-port must be between 1 and 65535")
        try:
            policy = ExistingBrowserPolicy(_string(browser_data, "existing-browser-policy"))
        except ValueError:
            _invalid("browser.existing-browser-policy is invalid")
        browser = BrowserConfig(
            executable=executable,
            remote_debugging_port=port,
            existing_browser_policy=policy,
            shutdown_timeout_seconds=_positive(browser_data, "shutdown-timeout-seconds"),
            force_kill=_boolean(browser_data, "force-kill"),
            dedicated_window=_boolean(browser_data, "dedicated-window"),
            # Keep provider tabs available for explicit gateway resume by
            # default.  Closing them remains an opt-in destructive action.
            close_tabs_on_session_close=_optional_boolean(
                browser_data, "close-tabs-on-session-close", default=False
            ),
        )

        cdp_data = _mapping(settings, "cdp")
        _exact_keys(
            cdp_data,
            {
                "connect-timeout-seconds",
                "protocol-timeout-seconds",
                "recovery-timeout-seconds",
                "devtools-active-port-file",
            },
            "cdp",
        )
        active_port = cdp_data.get("devtools-active-port-file")
        if active_port is not None and (
            not isinstance(active_port, str) or not active_port or "\x00" in active_port
        ):
            _invalid("cdp.devtools-active-port-file must be null or a valid path string")
        cdp = CdpConfig(
            connect_timeout_seconds=_positive(cdp_data, "connect-timeout-seconds"),
            protocol_timeout_seconds=_positive(cdp_data, "protocol-timeout-seconds"),
            recovery_timeout_seconds=_positive(cdp_data, "recovery-timeout-seconds"),
            devtools_active_port_file=Path(active_port) if active_port else None,
        )

        chat_data = _mapping(settings, "chat")
        _exact_keys(chat_data, {"ready-timeout-seconds", "navigation-timeout-seconds"}, "chat")
        chat = ChatConfig(
            ready_timeout_seconds=_positive(chat_data, "ready-timeout-seconds"),
            navigation_timeout_seconds=_positive(chat_data, "navigation-timeout-seconds"),
        )

        turn_data = _mapping(settings, "turn")
        _exact_keys(
            turn_data,
            {
                "submission-timeout-seconds",
                "response-start-timeout-seconds",
                "response-stall-timeout-seconds",
                "response-timeout-seconds",
                "poll-interval-seconds",
                "response-stability-seconds",
                "response-generating-override-stability-seconds",
                "submission-proof-progress-lease-seconds",
                "submission-proof-absolute-ceiling-seconds",
            },
            "turn",
        )
        turn = TurnConfig(
            submission_timeout_seconds=_positive(turn_data, "submission-timeout-seconds"),
            response_start_timeout_seconds=_non_negative(
                turn_data, "response-start-timeout-seconds"
            ),
            response_stall_timeout_seconds=_non_negative(
                turn_data, "response-stall-timeout-seconds"
            ),
            response_timeout_seconds=_non_negative(turn_data, "response-timeout-seconds"),
            poll_interval_seconds=_positive(turn_data, "poll-interval-seconds"),
            response_stability_seconds=_positive(turn_data, "response-stability-seconds"),
            response_generating_override_stability_seconds=_positive(
                turn_data, "response-generating-override-stability-seconds"
            ),
            submission_proof_progress_lease_seconds=_positive(
                turn_data, "submission-proof-progress-lease-seconds"
            ),
            submission_proof_absolute_ceiling_seconds=_positive(
                turn_data, "submission-proof-absolute-ceiling-seconds"
            ),
        )
        workflow = _workflow_config(_mapping(settings, "workflow"))
        return cls(CURRENT_CONTRACT_VERSION, project_url, browser, cdp, chat, turn, workflow)

    @classmethod
    def from_project_dict(cls, data: dict[str, Any]) -> GptAutoConfig:
        """Resolve a project's sparse settings overlay against packaged defaults.

        GP09/GP20: project config files previously had to restate the full
        settings schema, including the workflow dom-signals/evidence-policies
        block that is genuinely shared across every project on this machine
        (confirmed near-identical across gpt-auto.yaml/gpt-auto-t1.yaml/
        gpt-auto-t2.yaml by diff, 2026-08-17) -- duplicating it risked exactly
        the schema-drift incident GP09 was raised about. A project overlay may
        specify project-url when the profile is intentionally pinned to a
        known ChatGPT project; when it is absent, the admitted project name
        drives discovery. Everything else is inherited from defaults.yaml.

        Tolerant of both a full ``{"settings": {...}}``-wrapped payload
        (the on-disk shape of every provider config file) and an
        already-unwrapped bare settings dict (what some callers, e.g. the
        live stress test harness, pass directly) -- mirrors from_dict()'s
        own ``data.get("settings", data)`` tolerance. Merging a wrapped
        defaults.yaml against an unwrapped project dict without unwrapping
        both first would silently discard every project override (found
        live, 2026-08-17: project-url disappeared, falling back to a
        generic project-name search instead of the configured URL).
        """
        return resolve_gpt_auto_config(data, provider_id="gpt-auto")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override onto base, returning a new dict.

    A dict value merges key-by-key; any other value (including a list --
    e.g. dom-signal selectors) is replaced wholesale by override's value,
    never concatenated. Neither input is mutated.
    """
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


# ── GP26: machine-level drift detection entry points ────────────────────────


def machine_gpt_auto_override_path(provider_id: str = "gpt-auto") -> Path:
    """Return the optional machine-scoped provider override file path.

    Mirrors the gateway's own machine scope: a settings file here applies to
    every project on this machine that resolves this provider, matching GP20's
    ``load defaults -> load optional machine override -> project overlay`` flow.
    """
    from audiagentic.foundation.paths.home import global_config_dir

    return global_config_dir() / "providers" / f"{provider_id}.yaml"


def _load_machine_override(provider_id: str = "gpt-auto") -> dict[str, Any]:
    """Load the optional machine override file as a bare settings dict.

    Returns ``{}`` when absent or unreadable-as-mapping -- a missing machine
    override is not drift; the packaged defaults alone are the machine baseline.
    """
    path = machine_gpt_auto_override_path(provider_id)
    if not path.exists():
        return {}
    try:
        payload = load_yaml_file(path)
    except Exception:  # noqa: BLE001
        # A corrupt machine override must not be silently treated as absent by
        # this resolver alone -- the startup validation below re-reads it and
        # will surface the parse failure as the drift it is.
        return {}
    return provider_settings(payload)


def resolve_gpt_auto_config(
    project_settings: dict[str, Any],
    *,
    provider_id: str = "gpt-auto",
) -> GptAutoConfig:
    """Resolve packaged defaults + machine override + project overlay.

    The single three-tier resolution used by production session creation
    (via :meth:`GptAutoConfig.from_project_dict`) and by GP26's startup drift
    validation, so the scan always evaluates the SAME effective config the
    gateway would actually use.
    """
    default_settings = provider_settings(_load_packaged_defaults())
    machine_settings = _load_machine_override(provider_id)
    project_settings = provider_settings(project_settings)
    merged = deep_merge(deep_merge(default_settings, machine_settings), project_settings)
    return GptAutoConfig.from_dict(merged)


def _check_gpt_auto_dependencies() -> None:
    """Fail with an actionable message if the gpt-auto extra isn't installed.

    gpt-auto's CDP transport requires ``websockets``, which lives in the
    optional ``gpt-auto`` extra (not a base dependency, so plain installs
    stay lean). A project that has actually configured gpt-auto needs it
    though -- catch the gap here, at config validation, rather than letting
    it surface as an ImportError deep inside a session turn.
    """
    try:
        import websockets  # noqa: F401
    except ImportError as exc:
        raise AudiaGenticError(
            code="VAL-GPTAUTO-002",
            kind="providers",
            message=(
                "gpt-auto is configured but the 'gpt-auto' extra is not installed. "
                "Run: pip install \"audiagentic[gpt-auto]\""
            ),
            details={"missing-dependency": "websockets"},
        ) from exc


def validate_machine_gpt_auto_config() -> None:
    """Resolve packaged defaults + machine override and validate compatibility.

    GP26: invalid MACHINE-level config fails gateway startup entirely -- it is
    the shared foundation every project on this machine builds on. Raises
    :class:`~audiagentic.foundation.contracts.errors.AudiaGenticError`
    (VAL-GPTAUTO-001) when the machine-level gpt-auto config is invalid.

    Runs unconditionally on every gateway startup regardless of whether any
    project uses gpt-auto, so it must NOT gate on the optional 'gpt-auto'
    extra being installed -- that would make gpt-auto's dependency mandatory
    for the whole shared gateway. See validate_project_gpt_auto_config for
    the per-project, non-fatal dependency check.
    """
    GptAutoConfig.from_dict(
        deep_merge(provider_settings(_load_packaged_defaults()), _load_machine_override())
    )


def validate_project_gpt_auto_config(project_root: Path) -> GptAutoConfig:
    """Resolve a project's full gpt-auto config and validate compatibility.

    GP26: an invalid PROJECT config blocks only that project, never the shared
    gateway. Returns the effective :class:`GptAutoConfig` (the scan records
    compatibility from the loader's verdict, never a hand-rolled version check).
    """
    from audiagentic.components.providers.services.config.provider_config import (
        load_provider_settings,
    )

    _check_gpt_auto_dependencies()
    settings = load_provider_settings(project_root, "gpt-auto")
    return resolve_gpt_auto_config(settings, provider_id="gpt-auto")


@lru_cache(maxsize=1)
def _load_packaged_defaults() -> dict[str, Any]:
    return load_yaml_file(_DEFAULTS_PATH)


def provider_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Return the provider runtime settings, excluding provider metadata.

    Provider files may be metadata-only stubs (for example a project that
    declares gpt-auto but relies entirely on the packaged defaults):
    ``install-mode``, ``access-mode``, and the derived ``enabled`` flag are
    provider-descriptor metadata, not gpt-auto runtime settings. Treating
    that wrapper as the settings mapping
    makes the strict runtime schema reject an otherwise valid project with
    ``VAL-GPTAUTO-001``.  Wrapped settings remain authoritative; for legacy
    unwrapped files, strip only the known metadata keys so genuine unknown
    runtime keys still fail closed in ``GptAutoConfig.from_dict``.
    """
    if "settings" in data:
        settings = data["settings"]
    else:
        settings = {
            key: value
            for key, value in data.items()
            if key not in {"install-mode", "access-mode", "enabled"}
        }
    if not isinstance(settings, dict):
        _invalid("settings must be a mapping")
    return dict(settings)


def _invalid(message: str) -> NoReturn:
    raise AudiaGenticError(code="VAL-GPTAUTO-001", kind="providers", message=message, details={})


def _exact_keys(
    data: dict[str, Any],
    expected: set[str],
    section: str,
    *,
    required: set[str] | None = None,
) -> None:
    unknown = set(data) - expected
    missing = (expected if required is None else required) - set(data)
    if unknown or missing:
        _invalid(f"{section} has unknown or missing keys")


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        _invalid(f"{key} must be a mapping")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        _invalid(f"{key} must be a non-empty string")
    return value


def _integer(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(f"{key} must be an integer")
    return value


def _boolean(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        _invalid(f"{key} must be a boolean")
    return value


def _optional_boolean(data: dict[str, Any], key: str, *, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        _invalid(f"{key} must be a boolean")
    return value


def _positive(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        _invalid(f"{key} must be positive")
    return float(value)


def _non_negative(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        _invalid(f"{key} must be non-negative")
    return float(value)


def _workflow_config(data: dict[str, Any]) -> TurnWorkflowConfig:
    _exact_keys(data, {"dom-signals", "evidence-policies"}, "workflow")
    signal_data = _mapping(data, "dom-signals")
    signals: list[DomSignalConfig] = []
    for name, raw in signal_data.items():
        if not isinstance(name, str) or not name or not isinstance(raw, dict):
            _invalid("workflow.dom-signals must map names to signal definitions")
        allowed = {"scope", "selectors", "visible", "text-contains-any"}
        if set(raw) - allowed or {"scope", "selectors", "visible"} - set(raw):
            _invalid(f"workflow.dom-signals.{name} has unknown or missing keys")
        try:
            scope = DomSignalScope(_string(raw, "scope"))
        except ValueError:
            _invalid(f"workflow.dom-signals.{name}.scope is invalid")
        selectors = raw.get("selectors")
        if not isinstance(selectors, list) or not selectors or any(
            not isinstance(selector, str) or not selector for selector in selectors
        ):
            _invalid(f"workflow.dom-signals.{name}.selectors must be non-empty strings")
        text_contains = raw.get("text-contains-any", [])
        if not isinstance(text_contains, list) or any(
            not isinstance(fragment, str) or not fragment for fragment in text_contains
        ):
            _invalid(f"workflow.dom-signals.{name}.text-contains-any must be strings")
        signals.append(
            DomSignalConfig(
                name,
                scope,
                tuple(selectors),
                _boolean(raw, "visible"),
                tuple(text_contains),
            )
        )

    policy_data = _mapping(data, "evidence-policies")
    required = {"response-started", "response-active", "response-complete", "response-failed"}
    if set(policy_data) != required:
        _invalid("workflow.evidence-policies has unknown or missing policies")
    known_facts = {signal.name for signal in signals} | {
        "assistant-fresh",
        "text-present",
        "text-changed",
        "composer-present",
        "composer-editable",
        "composer-unavailable",
        # GP34 code-review follow-up: derived from ChatSnapshot.generating
        # directly (the raw stop/streaming/thinking/aria-busy check), not a
        # dom-signal selector. Lets a policy require the ABSENCE of active
        # generation without using stop-control in none-of (stop-control is
        # deliberately excluded there -- proven live to stick indefinitely
        # after real completion for the standard chat bubble, GP17).
        "not-generating",
    }
    policies: list[tuple[str, EvidencePolicy]] = []
    for name, raw in policy_data.items():
        if not isinstance(raw, dict):
            _invalid(f"workflow.evidence-policies.{name} must be a mapping")
        try:
            policy = EvidencePolicy.from_mapping(raw)
        except ValueError as exc:
            _invalid(f"workflow.evidence-policies.{name}: {exc}")
        referenced = policy.all_of | policy.any_of | policy.none_of
        for group in policy.any_of_groups:
            referenced = referenced | group
        unknown = referenced - known_facts
        if unknown:
            _invalid(f"workflow.evidence-policies.{name} references unknown facts")
        policies.append((name, policy))
    return TurnWorkflowConfig(tuple(signals), tuple(policies))


def _chatgpt_url(value: Any) -> str:
    if not isinstance(value, str):
        _invalid("project-url must be a ChatGPT URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "chat.openai.com"}:
        _invalid("project-url must be a ChatGPT URL")
    if not parse_project_id(value):
        _invalid("project-url must identify a ChatGPT Project")
    return value.rstrip("/")

