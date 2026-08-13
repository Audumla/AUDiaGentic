from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.providers.adapters.gpt_auto.browser_process import (
    BrowserProcessController,
)
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime_registry import (
    _runtimes,
    get_runtime,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


@pytest.mark.asyncio
async def test_browser_reuses_connectable_cdp_without_process_mutation():
    config = GptAutoConfig.from_dict(valid_config()).browser
    lookups = []
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _true(),
        process_lookup=lambda path: lookups.append(path) or [],
        port_owner=lambda port: 42,
    )
    evidence = await controller.ensure_browser_for_cdp()
    assert evidence.pid == 42
    assert not evidence.launched_by_provider
    assert lookups == []


@pytest.mark.asyncio
async def test_unknown_process_on_cdp_port_fails_without_kill():
    config = GptAutoConfig.from_dict(valid_config()).browser
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _false(),
        process_lookup=lambda path: [],
        port_owner=lambda port: 777,
    )
    with pytest.raises(RuntimeError, match="occupied"):
        await controller.ensure_browser_for_cdp()


@pytest.mark.asyncio
async def test_running_configured_browser_fail_policy_does_not_terminate():
    config = GptAutoConfig.from_dict(valid_config()).browser
    controller = BrowserProcessController(
        config,
        cdp_probe=lambda: _false(),
        process_lookup=lambda path: [123],
        port_owner=lambda port: None,
    )
    with pytest.raises(RuntimeError, match="running without usable CDP"):
        await controller.ensure_browser_for_cdp()


def test_runtime_registry_shares_machine_runtime_but_allows_project_turn_policy(tmp_path):
    _runtimes.clear()
    config = GptAutoConfig.from_dict(valid_config())
    assert get_runtime(tmp_path, config) is get_runtime(tmp_path, config)
    changed = valid_config()
    changed["turn"]["poll-interval-seconds"] = 2
    assert get_runtime(tmp_path, GptAutoConfig.from_dict(changed)) is get_runtime(tmp_path, config)
    changed["cdp"]["protocol-timeout-seconds"] = 31
    with pytest.raises(RuntimeError, match="machine runtime configuration"):
        get_runtime(tmp_path, GptAutoConfig.from_dict(changed))
    _runtimes.clear()


def test_delayed_binding_is_idempotent_and_conflict_fails(tmp_path: Path):
    record = sessions_store.build_session_record(
        session_id="ses-lazy-binding",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        surface_id="gpt-auto-cdp",
        provider_session_ref=None,
    )
    sessions_store.write_session_record(tmp_path, record)
    kwargs = {
        "provider_id": "gpt-auto",
        "surface_id": "gpt-auto-cdp",
        "provider_session_ref": "conversation-1",
        "metadata": {"chat-url": "https://chatgpt.com/g/g-p-project/c/conversation-1"},
    }
    first = sessions_store.install_initial_provider_binding(tmp_path, "ses-lazy-binding", **kwargs)
    second = sessions_store.install_initial_provider_binding(tmp_path, "ses-lazy-binding", **kwargs)
    assert first["binding"]["binding-id"] == second["binding"]["binding-id"]
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.install_initial_provider_binding(
            tmp_path,
            "ses-lazy-binding",
            **{**kwargs, "provider_session_ref": "conversation-2"},
        )
    assert raised.value.code == "CON-AGW-120"


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False
