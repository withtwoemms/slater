"""
AgentController: Executes Slater agent iterations.

Execution Model
---------------
Slater uses **eager fact application** within iterations:

1. Each iteration executes a Procedure (sequence of Actions) for the current Phase
2. As each Action completes, its emitted Facts are immediately applied to IterationState
3. Subsequent Actions in the same Procedure can read facts from prior Actions
4. At iteration end, only persistent/session-scoped facts are persisted to StateStore

This creates **sequential visibility** within a Procedure:

    Procedure([
        GatherContext(),   # Emits: {repo_root: "/path", context_ready: true}
        AnalyzeRepo(),     # Can read repo_root immediately
    ])

Implications for Procedure Authors
----------------------------------
- **Action order matters**: Later Actions can depend on earlier Actions' facts
- **Iteration-scoped facts are ephemeral**: Only visible within the current iteration
- **Persistent facts accumulate**: Visible across iterations until explicitly cleared
- **Failure short-circuits**: If an Action fails, subsequent Actions don't execute

Fact Scopes
-----------
- `iteration`: Visible only within current iteration (not persisted)
- `session`: Persisted, visible for agent's lifetime
- `persistent`: Persisted, visible across agent restarts

Phase Transitions
-----------------
Phase transitions are derived **only from durable facts** (session + persistent)
at iteration boundaries. This ensures deterministic FSM behavior:

    iteration N: Actions emit facts → persist durable facts → derive next phase
    iteration N+1: Load durable facts → execute Procedure for derived phase
"""

import os
import time
from enum import Enum
from typing import Any, Optional

from actionpack.action import Result

from slater.config import BootstrapConfig
from slater.context import IterationContext
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.spec import AgentSpec
from slater.state import IterationState, StateStore
from slater.types import Facts, IterationFacts, LLMClient, OpenAIClient, StateFragment


class AgentController:
    def __init__(
        self,
        *,
        spec: AgentSpec,
        agent_id: str,
        bootstrap_config: BootstrapConfig,
        state_store: StateStore,
    ):
        self.spec = spec
        self.agent_id = agent_id
        self.bootstrap_config = bootstrap_config
        self.state_store = state_store

        # Extract from spec
        self.procedure_templates = spec.procedures
        self.control_policy = spec.control_policy
        self.transition_policy = spec.transition_policy

        # Initialize canonical persistent state
        self.state_store.bootstrap(self.agent_id, bootstrap_config)

        self.iteration = 0
        self.last_phase: Enum = self.transition_policy.default
        self._terminate_after_iteration = False

    def run(self, max_iterations: int = 100, max_same_phase: int = 3):
        """
        Execute agent iterations until completion, pause, or failure.

        Each iteration:
        1. Loads persistent state from StateStore
        2. Selects Procedure for current Phase
        3. Executes Actions sequentially with eager fact application
        4. Persists durable facts (session + persistent scope)
        5. Evaluates ControlPolicy for completion/failure/pause
        6. Derives next Phase from TransitionPolicy rules

        Termination Conditions:
        - **Completion**: `completion_keys` present in durable facts → break
        - **Failure**: `failure_keys` present in durable facts → break
        - **Pause (user input)**: `user_required_keys` missing → return
        - **Pause (state)**: `required_state_keys` missing → return
        - **No transition**: No PhaseRule matches → return
        - **Cycle detected**: Same phase for `max_same_phase` iterations → raise
        - **Max iterations**: Exceeded `max_iterations` → raise

        Args:
            max_iterations: Maximum total iterations before failing.
            max_same_phase: Maximum consecutive iterations in the same phase
                            before detecting a cycle.

        Raises:
            RuntimeError: If cycle detected or max iterations exceeded.
        """
        phase_history: list[Enum] = []

        while self.iteration < max_iterations:
            self.iteration += 1
            print(f"\n--- Iteration {self.iteration} [{self.last_phase}] ---")

            # ---- cycle detection ----
            phase_history.append(self.last_phase)
            if self._detect_cycle(phase_history, max_same_phase):
                raise RuntimeError(
                    f"Phase cycle detected: stuck in {self.last_phase} "
                    f"for {max_same_phase}+ consecutive iterations"
                )

            # ---- assemble iteration context (capabilities only) ----
            ctx = self._build_iteration_context()
            view = ctx.as_view()

            # ---- load persistent state and start iteration ----
            persistent = self.state_store.load(self.agent_id)
            iteration_state = IterationState(persistent)

            iteration_state.begin_iteration()

            # ---- select + materialize procedure ----
            template = self._select_procedure_template(self.last_phase)
            procedure = template.materialize(iteration_state, view)

            # ---- execute procedure with eager fact application ----
            results: list[tuple[str, Result]] = []

            for action, result in procedure.execute(should_raise=True):
                results.append((action, result))

                if result.successful and isinstance(result.value, Facts):
                    iteration_state.apply_facts(result.value)

            # ---- finalize iteration (persist persistent facts only) ----
            self._finalize_iteration(
                phase=self.last_phase,
                results=results,
                iteration_state=iteration_state,
            )

            # 🔑 FROM HERE ON, USE DURABLE STATE ONLY
            durable_facts = iteration_state.persistent_facts()
            durable_keys = set(durable_facts.serialize().keys())

            # ---- 1. ControlPolicy (global overrides) ----

            if self.control_policy.completion_keys & durable_keys:
                # Completion detected - break without phase transition
                # (the current phase already produced completion keys)
                break

            if self.control_policy.failure_keys & durable_keys:
                # Failure detected - break without phase transition
                # (the current phase already produced failure keys)
                break

            if self.control_policy.user_required_keys - durable_keys:
                return  # pause for user input

            if self.control_policy.required_state_keys - durable_keys:
                return  # pause until more info exists

            # ---- 2. TransitionPolicy (deterministic FSM edge) ----
            next_phase = self.transition_policy.derive_phase(durable_keys)

            if next_phase is None:
                # No further progress possible in this invocation
                return

            self.last_phase = next_phase

        else:
            # Loop completed without break = max iterations exceeded
            raise RuntimeError(
                f"Agent exceeded max iterations ({max_iterations})"
            )

    def _detect_cycle(self, phase_history: list[Enum], max_same_phase: int) -> bool:
        """
        Detect if agent is stuck in the same phase.

        Returns True if the last `max_same_phase` entries are all the same phase.
        """
        if len(phase_history) < max_same_phase:
            return False

        recent = phase_history[-max_same_phase:]
        return len(set(recent)) == 1

    # ---- internal helpers ----

    def _build_iteration_context(self) -> IterationContext:
        return IterationContext(
            config=self.bootstrap_config,
            inputs=self._read_external_inputs(),
            llm=self._build_llm_client(),
            meta={
                "agent_id": self.agent_id,
                "iteration": self.iteration,
                "started_at": time.time(),
            },
        )

    def _build_llm_client(self) -> Optional[LLMClient]:
        llm_config = self.bootstrap_config.llm

        # No LLM config = no client
        if llm_config is None:
            return None

        # Skip client creation for fake/test providers
        if llm_config.provider in ("fake", "test", "mock"):
            return None

        api_key = os.getenv("OPENAI_API_KEY")
        return OpenAIClient(api_key=api_key, **llm_config.model_dump())

    def _select_procedure_template(self, event: Enum) -> "ProcedureTemplate":
        try:
            return self.procedure_templates[event]
        except KeyError:
            raise RuntimeError(f"No ProcedureTemplate registered for event {event}")

    def _finalize_iteration(
        self,
        *,
        phase: Enum,
        results: list[tuple[str, Result]],
        iteration_state: IterationState,
    ) -> None:
        by_action: dict[str, Facts] = {}

        for action_name, result in results:
            if not result.successful:
                continue

            if isinstance(result.value, Facts):
                by_action[action_name] = result.value

        if not by_action:
            return

        iteration_facts = IterationFacts(
            iteration=self.iteration,
            phase=phase,
            by_action=by_action,
        )

        # 🔑 StateStore persists ONLY persistent facts
        self.state_store.save(
            agent_id=self.agent_id,
            iteration_facts=iteration_facts,
            persistent_facts=iteration_state.persistent_facts(),
        )

    def _read_external_inputs(self) -> dict:
        # stub: CLI, stdin, sockets, etc.
        return {}
