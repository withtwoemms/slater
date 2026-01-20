from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from slater.types import LLMClient


@dataclass
class IterationContext:
    """
    Controller-owned context assembled at the start of an agent iteration.

    Mutable only by the controller.
    Exposed to Actions via IterationContextView.
    """

    # 1. Static configuration (agent startup)
    config: Dict[str, Any]

    # 2. External / ephemeral inputs for this iteration
    inputs: Dict[str, Any] = field(default_factory=dict)

    # 3. Iteration metadata
    meta: Dict[str, Any] = field(default_factory=dict)

    # 4. LLM client (injected dependency)
    llm: LLMClient | None = field(default=None)

    def as_view(self) -> "IterationContextView":
        """
        Produce a read-only view for Actions.
        """
        return IterationContextView(
            config=self.config,
            inputs=self.inputs,
            meta=self.meta,
            llm=self.llm,
        )


class IterationContextView:
    """
    Read-only view over iteration context.
    """

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        inputs: Mapping[str, Any],
        meta: Mapping[str, Any],
        llm: LLMClient | None = None,
    ):
        self._config = dict(config)
        self._inputs = dict(inputs)
        self._meta = dict(meta)
        self._llm = llm

    # explicit accessors — no dict-style mutation
    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    @property
    def inputs(self) -> Mapping[str, Any]:
        return self._inputs

    @property
    def meta(self) -> Mapping[str, Any]:
        return self._meta

    @property
    def llm(self) -> LLMClient | None:
        return self._llm

    def get(self, key: str, *, default=None):
        if key in self._inputs:
            return self._inputs[key]
        if key in self._config:
            return self._config[key]
        return default
