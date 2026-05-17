from __future__ import annotations

from abc import ABC, abstractmethod

from .context import InvocationContext
from .result import InvocationResult


class InvocationRecipe(ABC):
    @abstractmethod
    def plan(self, context: InvocationContext) -> InvocationResult: ...

    @abstractmethod
    def run(self, context: InvocationContext) -> InvocationResult: ...
