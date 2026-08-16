"""Strict project-owned configuration for the gpt-auto provider runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow import EvidencePolicy


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
        if settings.get("contract-version") != "v1":
            _invalid("contract-version must be v1")
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
            _invalid("browser.executable must name an existing file")
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
            submission_proof_progress_lease_seconds=_positive(
                turn_data, "submission-proof-progress-lease-seconds"
            ),
            submission_proof_absolute_ceiling_seconds=_positive(
                turn_data, "submission-proof-absolute-ceiling-seconds"
            ),
        )
        workflow = _workflow_config(_mapping(settings, "workflow"))
        return cls("v1", project_url, browser, cdp, chat, turn, workflow)


def provider_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Return the one project-owned settings mapping without aliases."""
    settings = data.get("settings", data)
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
    return value.rstrip("/")
