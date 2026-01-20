"""
Tests for AgentController execution.

These tests verify:
- Eager fact application within iterations
- Fact scope semantics (iteration vs session/persistent)
- State persistence at iteration boundaries
- Phase transitions via TransitionPolicy
- Completion/failure detection via ControlPolicy
- Cycle detection
"""

import pytest

from slater.actions import SlaterAction
from slater.config import BootstrapConfig, LLMConfig
from slater.controller import AgentController
from slater.phases import PhaseEnum, PhaseRule
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.spec import AgentSpec
from slater.state import InMemoryStateStore
from slater.types import Facts, KnowledgeFact, ProgressFact


# ----------------------------------------------------------------------------
# Test Actions
# ----------------------------------------------------------------------------


class EmitSessionFact(SlaterAction):
    """Action that emits a session-scoped fact."""
    requires_state = True

    def __init__(self, key: str = "data", value: str = "test_value"):
        self._key = key
        self._value = value

    def _clone(self):
        clone = EmitSessionFact(key=self._key, value=self._value)
        clone.name = self.name or self.__class__.__name__
        return clone

    def instruction(self):
        return Facts(**{
            self._key: KnowledgeFact(
                key=self._key,
                value=self._value,
                scope="session",
            )
        })


class EmitIterationFact(SlaterAction):
    """Action that emits an iteration-scoped fact (ephemeral)."""
    requires_state = True

    def __init__(self, key: str = "temp", value: str = "ephemeral"):
        self._key = key
        self._value = value

    def _clone(self):
        clone = EmitIterationFact(key=self._key, value=self._value)
        clone.name = self.name or self.__class__.__name__
        return clone

    def instruction(self):
        return Facts(**{
            self._key: KnowledgeFact(
                key=self._key,
                value=self._value,
                scope="iteration",
            )
        })


class EmitCompletionFact(SlaterAction):
    """Action that emits a completion signal."""
    requires_state = True

    def instruction(self):
        return Facts(
            task_complete=ProgressFact(
                key="task_complete",
                value=True,
                scope="session",
            )
        )


class ReadAndEmit(SlaterAction):
    """Action that reads a fact from state and emits a new fact."""
    requires_state = True

    def __init__(self, read_key: str, emit_key: str):
        self._read_key = read_key
        self._emit_key = emit_key

    def _clone(self):
        clone = ReadAndEmit(read_key=self._read_key, emit_key=self._emit_key)
        clone.name = self.name or self.__class__.__name__
        return clone

    def instruction(self):
        # Read from state (tests eager fact application)
        value = self.state[self._read_key]
        return Facts(**{
            self._emit_key: KnowledgeFact(
                key=self._emit_key,
                value=f"read_{value}",
                scope="session",
            )
        })


class AssertFactExists(SlaterAction):
    """Action that asserts a fact exists in state."""
    requires_state = True

    def __init__(self, key: str, expected_value=None):
        self._key = key
        self._expected = expected_value

    def _clone(self):
        clone = AssertFactExists(key=self._key, expected_value=self._expected)
        clone.name = self.name or self.__class__.__name__
        return clone

    def instruction(self):
        assert self._key in self.state, f"Expected fact '{self._key}' not in state"
        if self._expected is not None:
            assert self.state[self._key] == self._expected, \
                f"Expected {self._key}={self._expected}, got {self.state[self._key]}"
        return Facts()


class AssertFactNotInStore(SlaterAction):
    """Action that asserts a fact is NOT yet in the persistent store."""
    requires_state = True

    def __init__(self, store, agent_id: str, key: str):
        self._store = store
        self._agent_id = agent_id
        self._key = key

    def _clone(self):
        clone = AssertFactNotInStore(
            store=self._store, agent_id=self._agent_id, key=self._key
        )
        clone.name = self.name or self.__class__.__name__
        return clone

    def instruction(self):
        loaded = self._store.load(self._agent_id)
        assert self._key not in loaded, \
            f"Fact '{self._key}' should not be in store mid-iteration"
        return Facts()


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest.fixture
def phase():
    """Create a simple Phase enum for tests."""
    return PhaseEnum.create("START", "DONE")


@pytest.fixture
def minimal_bootstrap_config():
    """Minimal config without LLM (for tests that don't need it)."""
    return BootstrapConfig(
        llm=LLMConfig(provider="fake", model="fake-model"),
    )


# ----------------------------------------------------------------------------
# Eager Fact Application
# ----------------------------------------------------------------------------


class TestEagerFactApplication:
    def test_later_action_sees_earlier_action_facts(self, phase, minimal_bootstrap_config):
        """Actions can read facts emitted by earlier actions in the same iteration."""
        store = InMemoryStateStore()
        agent_id = "test-eager-fact"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="eager_test",
                actions=[
                    EmitSessionFact(key="first", value="hello"),
                    ReadAndEmit(read_key="first", emit_key="second"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-eager",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        # Verify second action read first action's fact
        final_state = store.load(agent_id)
        assert "second" in final_state
        assert final_state["second"].value == "read_hello"

    def test_iteration_facts_visible_within_iteration(self, phase, minimal_bootstrap_config):
        """Iteration-scoped facts are visible to later actions in the same iteration."""
        store = InMemoryStateStore()
        agent_id = "test-iteration-visible"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="iteration_test",
                actions=[
                    EmitIterationFact(key="temp_data", value="temporary"),
                    AssertFactExists(key="temp_data", expected_value="temporary"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-iteration-visible",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        # Should not raise - iteration fact is visible within iteration
        controller.run()


# ----------------------------------------------------------------------------
# Fact Scope Semantics
# ----------------------------------------------------------------------------


class TestFactScopes:
    def test_iteration_facts_not_persisted(self, phase, minimal_bootstrap_config):
        """Iteration-scoped facts are NOT persisted to StateStore."""
        store = InMemoryStateStore()
        agent_id = "test-iteration-not-persisted"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="scope_test",
                actions=[
                    EmitIterationFact(key="ephemeral", value="gone"),
                    EmitSessionFact(key="durable", value="persisted"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-scope",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        final_state = store.load(agent_id)
        assert "durable" in final_state
        assert "ephemeral" not in final_state

    def test_session_facts_persist_across_iterations(self, minimal_bootstrap_config):
        """Session-scoped facts persist and are visible in subsequent iterations."""
        store = InMemoryStateStore()
        agent_id = "test-session-persist"

        Phase = PhaseEnum.create("FIRST", "SECOND", "DONE")

        procedures = {
            Phase.FIRST: ProcedureTemplate(
                name="first_phase",
                actions=[
                    EmitSessionFact(key="from_first", value="carried_over"),
                ],
            ),
            Phase.SECOND: ProcedureTemplate(
                name="second_phase",
                actions=[
                    AssertFactExists(key="from_first", expected_value="carried_over"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-session-persist",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(
                rules=[
                    PhaseRule(
                        enter=Phase.SECOND,
                        when_all=frozenset({"from_first"}),
                    ),
                ],
                default=Phase.FIRST,
            ),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        # Should complete without assertion errors
        controller.run()


# ----------------------------------------------------------------------------
# State Persistence Boundaries
# ----------------------------------------------------------------------------


class TestStatePersistenceBoundaries:
    def test_state_not_persisted_mid_iteration(self, phase, minimal_bootstrap_config):
        """Facts are NOT written to StateStore until iteration completes."""
        store = InMemoryStateStore()
        agent_id = "test-mid-iteration"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="mid_iteration_test",
                actions=[
                    EmitSessionFact(key="mid_check", value="not_yet"),
                    AssertFactNotInStore(store, agent_id, key="mid_check"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-mid-iteration",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        # Should not raise - fact not in store mid-iteration
        controller.run()

        # But after iteration completes, it should be there
        final_state = store.load(agent_id)
        assert "mid_check" in final_state


# ----------------------------------------------------------------------------
# Iteration History
# ----------------------------------------------------------------------------


class TestIterationHistory:
    def test_history_records_iterations(self, phase, minimal_bootstrap_config):
        """StateStore.history() records each iteration."""
        store = InMemoryStateStore()
        agent_id = "test-history"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="history_test",
                actions=[
                    EmitSessionFact(key="data", value="recorded"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-history",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        history = store.history(agent_id)
        assert len(history) == 1

        iteration_record = history[0]
        assert iteration_record.iteration == 1
        assert iteration_record.phase == Phase.START
        assert "EmitSessionFact" in iteration_record.by_action
        assert "EmitCompletionFact" in iteration_record.by_action


# ----------------------------------------------------------------------------
# Cycle Detection
# ----------------------------------------------------------------------------


class TestCycleDetection:
    def test_cycle_detection_raises_on_stuck_phase(self, minimal_bootstrap_config):
        """Controller raises RuntimeError when stuck in the same phase."""
        store = InMemoryStateStore()
        agent_id = "test-cycle"

        Phase = PhaseEnum.create("STUCK")

        # Procedure that emits a fact but never completion keys
        procedures = {
            Phase.STUCK: ProcedureTemplate(
                name="stuck",
                actions=[
                    EmitSessionFact(key="still_going", value="yes"),
                ],
            ),
        }

        spec = AgentSpec(
            name="test-cycle",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"never_emitted"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(
                rules=[
                    # Rule that always matches once still_going is present,
                    # keeping the agent in STUCK phase
                    PhaseRule(
                        enter=Phase.STUCK,
                        when_all=frozenset({"still_going"}),
                    ),
                ],
                default=Phase.STUCK,
            ),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        with pytest.raises(RuntimeError, match="cycle detected"):
            controller.run(max_same_phase=3)


# ----------------------------------------------------------------------------
# Phase Transitions
# ----------------------------------------------------------------------------


class TestPhaseTransitions:
    def test_transition_via_phase_rule(self, minimal_bootstrap_config):
        """PhaseRule triggers transition when conditions match."""
        store = InMemoryStateStore()
        agent_id = "test-transition"

        Phase = PhaseEnum.create("GATHERING", "PROCESSING", "DONE")

        procedures = {
            Phase.GATHERING: ProcedureTemplate(
                name="gather",
                actions=[
                    EmitSessionFact(key="data_ready", value=True),
                ],
            ),
            Phase.PROCESSING: ProcedureTemplate(
                name="process",
                actions=[
                    AssertFactExists(key="data_ready"),
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-transition",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(
                rules=[
                    PhaseRule(
                        enter=Phase.PROCESSING,
                        when_all=frozenset({"data_ready"}),
                    ),
                ],
                default=Phase.GATHERING,
            ),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        # Verify both phases executed
        history = store.history(agent_id)
        phases_executed = [h.phase for h in history]
        assert Phase.GATHERING in phases_executed
        assert Phase.PROCESSING in phases_executed


# ----------------------------------------------------------------------------
# Completion and Failure
# ----------------------------------------------------------------------------


class TestCompletionAndFailure:
    def test_completion_keys_trigger_termination(self, phase, minimal_bootstrap_config):
        """Agent terminates when completion_keys are present in durable facts."""
        store = InMemoryStateStore()
        agent_id = "test-completion"

        Phase = phase
        procedures = {
            Phase.START: ProcedureTemplate(
                name="complete",
                actions=[
                    EmitCompletionFact(),
                ],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-completion",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys={"task_complete"},
                failure_keys=set(),
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        # Should complete after one iteration
        history = store.history(agent_id)
        assert len(history) == 1

    def test_failure_keys_trigger_termination(self, phase, minimal_bootstrap_config):
        """Agent terminates when failure_keys are present in durable facts."""
        store = InMemoryStateStore()
        agent_id = "test-failure"

        Phase = phase

        class EmitFailure(SlaterAction):
            requires_state = True

            def instruction(self):
                return Facts(
                    blocked=ProgressFact(key="blocked", value=True, scope="session")
                )

        procedures = {
            Phase.START: ProcedureTemplate(
                name="fail",
                actions=[EmitFailure()],
            ),
            Phase.DONE: ProcedureTemplate(name="done", actions=[]),
        }

        spec = AgentSpec(
            name="test-failure",
            version="1.0.0",
            phases=set(Phase),
            control_policy=ControlPolicy(
                required_state_keys=set(),
                user_required_keys=set(),
                completion_keys=set(),
                failure_keys={"blocked"},
            ),
            transition_policy=TransitionPolicy(rules=[], default=Phase.START),
            procedures=procedures,
        )

        controller = AgentController(
            spec=spec,
            agent_id=agent_id,
            bootstrap_config=minimal_bootstrap_config,
            state_store=store,
        )

        controller.run()

        # Should terminate after one iteration due to failure
        history = store.history(agent_id)
        assert len(history) == 1
