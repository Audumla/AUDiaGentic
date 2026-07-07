from audiagentic.foundation.workflow.transition_engine import TransitionConfig, TransitionEngine


def _engine() -> TransitionEngine:
    return TransitionEngine(
        TransitionConfig(
            transitions={
                "draft": frozenset({"active", "cancelled"}),
                "active": frozenset({"done", "cancelled"}),
            },
            terminal_states=frozenset({"done", "cancelled"}),
        )
    )


def test_allows_legal_transition() -> None:
    assert _engine().is_legal("draft", "active") is True
    assert _engine().check("draft", "active") is None


def test_rejects_illegal_transition() -> None:
    assert _engine().is_legal("draft", "done") is False
    assert _engine().check("draft", "done") == "illegal-transition"


def test_rejects_unknown_current_state() -> None:
    assert _engine().check("missing", "active") == "unknown-current"


def test_rejects_unknown_target_state() -> None:
    assert _engine().check("draft", "missing") == "unknown-target"


def test_detects_terminal_states() -> None:
    engine = _engine()
    assert engine.is_terminal("done") is True
    assert engine.is_terminal("active") is False
    assert engine.is_terminal(None) is False


def test_values_override_derived_states() -> None:
    engine = TransitionEngine(
        TransitionConfig(
            transitions={"draft": frozenset({"active"})},
            values=frozenset({"draft"}),
        )
    )

    assert engine.check("draft", "active") == "unknown-target"


def test_empty_terminal_set() -> None:
    engine = TransitionEngine(TransitionConfig(transitions={"draft": frozenset({"done"})}))

    assert engine.is_terminal("done") is False
