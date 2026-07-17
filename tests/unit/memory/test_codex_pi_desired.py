"""Tests for frozen Codex/Pi Hindsight desired state and boundary parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from audiagentic.components.memory.hindsight.codex_pi_desired import (
    CodexHindsightDesired,
    HookCommand,
    PiHindsightDesired,
    PiHostBlock,
    parse_codex_hindsight_desired,
    parse_pi_hindsight_desired,
)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig

_SCHEMA_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components" / "memory"
)


# ---------------------------------------------------------------------------
# CodexHindsightDesired — construction and round-trip
# ---------------------------------------------------------------------------


def test_codex_desired_minimal():
    d = CodexHindsightDesired(base_url="http://localhost:8888", bank_id="codex")
    assert d.base_url == "http://localhost:8888"
    assert d.bank_id == "codex"
    assert d.api_key is None
    assert d.hook_commands == ()


def test_codex_desired_full():
    cmds = (
        HookCommand(event="SessionStart", command="python session_start.py", timeout=5),
        HookCommand(event="UserPromptSubmit", command="python recall.py", timeout=12),
        HookCommand(event="Stop", command="python retain.py", timeout=30),
    )
    d = CodexHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="my-bank",
        api_key="secret-key",
        interpreter_path=Path("/usr/bin/python3"),
        script_dir=Path("/home/user/.hindsight/codex/scripts"),
        hook_commands=cmds,
    )
    assert d.api_key == "secret-key"
    assert len(d.hook_commands) == 3
    assert d.hook_commands[0].event == "SessionStart"
    assert d.hook_commands[2].timeout == 30


def test_codex_desired_round_trip():
    cmds = (
        HookCommand(event="SessionStart", command="python session_start.py", timeout=5),
        HookCommand(event="UserPromptSubmit", command="python recall.py", timeout=12),
    )
    d = CodexHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="codex",
        api_key="secret",
        interpreter_path=Path("/usr/bin/python3"),
        script_dir=Path("/home/user/.hindsight/codex/scripts"),
        hook_commands=cmds,
    )
    mapped = d.to_mapping()
    d2 = CodexHindsightDesired.from_mapping(mapped)
    assert d == d2


def test_codex_desired_round_trip_minimal():
    d = CodexHindsightDesired(base_url="http://localhost:8888", bank_id="codex")
    mapped = d.to_mapping()
    d2 = CodexHindsightDesired.from_mapping(mapped)
    assert d == d2


def test_codex_desired_from_backend():
    backend = HindsightBackendConfig(
        base_url="http://localhost:8888",
        api_key="key123",
        bank_id="my-bank",
    )
    d = CodexHindsightDesired.from_backend(backend)
    assert d.base_url == "http://localhost:8888"
    assert d.bank_id == "my-bank"
    assert d.api_key == "key123"


def test_codex_desired_from_backend_no_bank():
    backend = HindsightBackendConfig(
        base_url="http://localhost:8888",
    )
    d = CodexHindsightDesired.from_backend(backend)
    assert d.bank_id == "codex"


def test_codex_desired_frozen():
    d = CodexHindsightDesired(base_url="http://localhost:8888", bank_id="codex")
    with pytest.raises(Exception):
        d.base_url = "http://other"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CodexHindsightDesired — __post_init__ validation
# ---------------------------------------------------------------------------


def test_codex_desired_empty_base_url():
    with pytest.raises(ValueError, match="base_url"):
        CodexHindsightDesired(base_url="", bank_id="codex")


def test_codex_desired_empty_bank_id():
    with pytest.raises(ValueError, match="bank_id"):
        CodexHindsightDesired(base_url="http://localhost:8888", bank_id="")


def test_codex_desired_duplicate_events():
    cmds = (
        HookCommand(event="SessionStart", command="python s.py", timeout=5),
        HookCommand(event="SessionStart", command="python r.py", timeout=12),
    )
    with pytest.raises(ValueError, match="unique"):
        CodexHindsightDesired(
            base_url="http://localhost:8888",
            bank_id="codex",
            hook_commands=cmds,
        )


# ---------------------------------------------------------------------------
# CodexHindsightDesired — schema validation
# ---------------------------------------------------------------------------


def _codex_schema():
    return json.loads(
        (_SCHEMA_DIR / "codex-hindsight-desired.schema.json").read_text(encoding="utf-8")
    )


def test_codex_schema_accepts_valid_minimal():
    data = {"base_url": "http://localhost:8888", "bank_id": "codex"}
    Draft202012Validator(_codex_schema()).validate(data)


def test_codex_schema_accepts_valid_full():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "codex",
        "api_key": "secret",
        "interpreter_path": "/usr/bin/python3",
        "script_dir": "/home/user/.hindsight/codex/scripts",
        "hook_commands": [
            {"event": "SessionStart", "command": "python session_start.py", "timeout": 5},
            {"event": "UserPromptSubmit", "command": "python recall.py", "timeout": 12},
            {"event": "Stop", "command": "python retain.py", "timeout": 30},
        ],
    }
    Draft202012Validator(_codex_schema()).validate(data)


def test_codex_schema_rejects_missing_base_url():
    data = {"bank_id": "codex"}
    with pytest.raises(Exception):
        Draft202012Validator(_codex_schema()).validate(data)


def test_codex_schema_rejects_missing_bank_id():
    data = {"base_url": "http://localhost:8888"}
    with pytest.raises(Exception):
        Draft202012Validator(_codex_schema()).validate(data)


def test_codex_schema_rejects_extra_property():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "codex",
        "unknown_field": "oops",
    }
    with pytest.raises(Exception):
        Draft202012Validator(_codex_schema()).validate(data)


def test_codex_schema_rejects_wrong_type_hook_timeout():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "codex",
        "hook_commands": [
            {"event": "SessionStart", "command": "python s.py", "timeout": "five"},
        ],
    }
    with pytest.raises(Exception):
        Draft202012Validator(_codex_schema()).validate(data)


def test_codex_to_mapping_validates_schema():
    d = CodexHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="codex",
        hook_commands=(HookCommand(event="SessionStart", command="python s.py", timeout=5),),
    )
    Draft202012Validator(_codex_schema()).validate(d.to_mapping())


# ---------------------------------------------------------------------------
# CodexHindsightDesired — boundary parse function
# ---------------------------------------------------------------------------


def test_parse_codex_accepts_valid():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "codex",
        "hook_commands": [
            {"event": "SessionStart", "command": "python s.py", "timeout": 5},
        ],
    }
    d = parse_codex_hindsight_desired(data)
    assert isinstance(d, CodexHindsightDesired)
    assert d.hook_commands[0].event == "SessionStart"


def test_parse_codex_rejects_invalid():
    data = {"bank_id": "codex"}  # missing base_url
    with pytest.raises(ValueError, match="validation failed"):
        parse_codex_hindsight_desired(data)


def test_parse_codex_rejects_extra_property():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "codex",
        "extra": True,
    }
    with pytest.raises(ValueError, match="validation failed"):
        parse_codex_hindsight_desired(data)


# ---------------------------------------------------------------------------
# PiHostBlock — construction and round-trip
# ---------------------------------------------------------------------------


def test_pi_host_block_defaults():
    b = PiHostBlock()
    assert b.enabled is True
    assert b.recall_mode == "hybrid"
    assert b.auto_recall_tags == ("{project}",)


def test_pi_host_block_round_trip():
    b = PiHostBlock(
        enabled=True,
        recall_mode="full",
        auto_recall_tags=("{project}", "{default}"),
        auto_recall_tags_match="all_strict",
        observation_scopes=(("{project}",), ("{default}",)),
    )
    mapped = b.to_mapping()
    b2 = PiHostBlock.from_mapping(mapped)
    assert b == b2


# ---------------------------------------------------------------------------
# PiHindsightDesired — construction and round-trip
# ---------------------------------------------------------------------------


def test_pi_desired_minimal():
    d = PiHindsightDesired(base_url="http://localhost:8888", bank_id="audiagentic")
    assert d.base_url == "http://localhost:8888"
    assert d.bank_id == "audiagentic"
    assert d.pi_host_block is None


def test_pi_desired_full():
    host = PiHostBlock(enabled=True, recall_mode="full")
    d = PiHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="my-bank",
        pi_host_block=host,
    )
    assert d.pi_host_block is not None
    assert d.pi_host_block.recall_mode == "full"


def test_pi_desired_round_trip():
    host = PiHostBlock(recall_mode="hybrid")
    d = PiHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="audiagentic",
        pi_host_block=host,
    )
    mapped = d.to_mapping()
    d2 = PiHindsightDesired.from_mapping(mapped)
    assert d == d2


def test_pi_desired_round_trip_minimal():
    d = PiHindsightDesired(base_url="http://localhost:8888", bank_id="audiagentic")
    mapped = d.to_mapping()
    d2 = PiHindsightDesired.from_mapping(mapped)
    assert d == d2


def test_pi_desired_from_backend():
    backend = HindsightBackendConfig(
        base_url="http://localhost:8888",
        bank_id="my-bank",
    )
    d = PiHindsightDesired.from_backend(backend)
    assert d.bank_id == "my-bank"


def test_pi_desired_from_backend_no_bank():
    backend = HindsightBackendConfig(base_url="http://localhost:8888")
    d = PiHindsightDesired.from_backend(backend)
    assert d.bank_id == "audiagentic"


def test_pi_desired_frozen():
    d = PiHindsightDesired(base_url="http://localhost:8888", bank_id="audiagentic")
    with pytest.raises(Exception):
        d.base_url = "http://other"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# PiHindsightDesired — __post_init__ validation
# ---------------------------------------------------------------------------


def test_pi_desired_empty_base_url():
    with pytest.raises(ValueError, match="base_url"):
        PiHindsightDesired(base_url="", bank_id="audiagentic")


def test_pi_desired_empty_bank_id():
    with pytest.raises(ValueError, match="bank_id"):
        PiHindsightDesired(base_url="http://localhost:8888", bank_id="")


# ---------------------------------------------------------------------------
# PiHindsightDesired — schema validation
# ---------------------------------------------------------------------------


def _pi_schema():
    return json.loads(
        (_SCHEMA_DIR / "pi-hindsight-desired.schema.json").read_text(encoding="utf-8")
    )


def test_pi_schema_accepts_valid_minimal():
    data = {"base_url": "http://localhost:8888", "bank_id": "audiagentic"}
    Draft202012Validator(_pi_schema()).validate(data)


def test_pi_schema_accepts_valid_full():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "audiagentic",
        "bank_strategy": "manual",
        "pi_host_block": {
            "enabled": True,
            "recall_mode": "hybrid",
            "auto_recall_tags": ["{project}"],
            "auto_recall_tags_match": "any_strict",
            "observation_scopes": [["{project}"]],
        },
    }
    Draft202012Validator(_pi_schema()).validate(data)


def test_pi_schema_rejects_missing_base_url():
    data = {"bank_id": "audiagentic"}
    with pytest.raises(Exception):
        Draft202012Validator(_pi_schema()).validate(data)


def test_pi_schema_rejects_missing_bank_id():
    data = {"base_url": "http://localhost:8888"}
    with pytest.raises(Exception):
        Draft202012Validator(_pi_schema()).validate(data)


def test_pi_schema_rejects_extra_property():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "audiagentic",
        "unknown_field": "oops",
    }
    with pytest.raises(Exception):
        Draft202012Validator(_pi_schema()).validate(data)


def test_pi_to_mapping_validates_schema():
    d = PiHindsightDesired(
        base_url="http://localhost:8888",
        bank_id="audiagentic",
        pi_host_block=PiHostBlock(recall_mode="hybrid"),
    )
    Draft202012Validator(_pi_schema()).validate(d.to_mapping())


# ---------------------------------------------------------------------------
# PiHindsightDesired — boundary parse function
# ---------------------------------------------------------------------------


def test_parse_pi_accepts_valid():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "audiagentic",
        "pi_host_block": {
            "enabled": True,
            "recall_mode": "hybrid",
            "auto_recall_tags": ["{project}"],
            "auto_recall_tags_match": "any_strict",
            "observation_scopes": [["{project}"]],
        },
    }
    d = parse_pi_hindsight_desired(data)
    assert isinstance(d, PiHindsightDesired)
    assert d.pi_host_block is not None
    assert d.pi_host_block.recall_mode == "hybrid"


def test_parse_pi_rejects_invalid():
    data = {"bank_id": "audiagentic"}  # missing base_url
    with pytest.raises(ValueError, match="validation failed"):
        parse_pi_hindsight_desired(data)


def test_parse_pi_rejects_extra_property():
    data = {
        "base_url": "http://localhost:8888",
        "bank_id": "audiagentic",
        "extra": True,
    }
    with pytest.raises(ValueError, match="validation failed"):
        parse_pi_hindsight_desired(data)


# ---------------------------------------------------------------------------
# HookCommand — round-trip
# ---------------------------------------------------------------------------


def test_hook_command_round_trip():
    hc = HookCommand(event="SessionStart", command="python s.py", timeout=5)
    mapped = hc.to_mapping()
    hc2 = HookCommand.from_mapping(mapped)
    assert hc == hc2
