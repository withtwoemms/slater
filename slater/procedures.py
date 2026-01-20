from typing import Any, Iterable, List

from actionpack.procedure import KeyedProcedure

from slater.actions import SlaterAction
from slater.context import IterationContextView


class ProcedureTemplate:
    """
    A reusable, context-agnostic template for building Actionpack Procedures.

    This object:
    - is immutable after construction
    - owns *template* Actions (never executed directly)
    - materializes a fresh Procedure per iteration
    """

    def __init__(self, name: str, actions: Iterable[SlaterAction]):
        self.name = name
        self._actions: List[SlaterAction] = list(actions)

    def materialize(self, state: dict[str, Any], ctx: IterationContextView) -> KeyedProcedure:
        """
        Produce a concrete Actionpack Procedure for a specific iteration.

        All ContextAwareActions are cloned and bound to the given context.
        Non-context-aware Actions are shallow-cloned only.
        """
        materialized_actions = [action.materialize(state=state, ctx=ctx) for action in self._actions]
        return KeyedProcedure(materialized_actions)

    def __repr__(self) -> str:
        return f"<ProcedureTemplate name={self.name} actions={self._actions}>"
