"""Pure transition predicates shared by workflow hosts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

TransitionFailure = str


@dataclass(frozen=True)
class TransitionConfig:
    transitions: Mapping[str, frozenset[str]]
    terminal_states: frozenset[str] = field(default_factory=frozenset)
    values: frozenset[str] | None = None

    def known_states(self) -> frozenset[str]:
        if self.values is not None:
            return self.values
        out: set[str] = set(self.transitions)
        for dests in self.transitions.values():
            out.update(dests)
        return frozenset(out)


class TransitionEngine:
    def __init__(self, config: TransitionConfig):
        self.config = config

    def is_known_state(self, state: str) -> bool:
        return state in self.config.known_states()

    def is_legal(self, current: str, new: str) -> bool:
        return self.check(current, new) is None

    def is_terminal(self, state: str | None) -> bool:
        return state in self.config.terminal_states

    def check(self, current: str, new: str) -> TransitionFailure | None:
        if not self.is_known_state(current):
            return "unknown-current"
        if not self.is_known_state(new):
            return "unknown-target"
        if new not in self.config.transitions.get(current, frozenset()):
            return "illegal-transition"
        return None
