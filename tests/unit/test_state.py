"""
Unit tests for Category 1 refactoring: Type System Violations

These tests lock in the fixes that ensure:
1. IterationState stores Fact objects (not serialized dicts)
2. apply_facts() correctly routes Facts by scope
3. InMemoryStateStore.save() uses iter_facts() for type-safe iteration
4. TransitionPolicy.derive_phase() receives keys (AbstractSet[str])
"""

import pytest

from slater.phases import Phase, PhaseRule
from slater.policies import TransitionPolicy
from slater.state import InMemoryStateStore, IterationState
from slater.types import Fact, Facts, IterationFacts, KnowledgeFact


# ----------------------------------------------------------------------------
# Issue 1: IterationState.__init__ stores Fact objects, not dicts
# ----------------------------------------------------------------------------


class TestIterationStateInit:
    def test_persistent_contains_fact_objects(self):
        """_persistent dict should contain Fact objects, not serialized dicts."""
        base = Facts(
            foo=Fact(key="foo", value="bar", scope="persistent"),
        )
        state = IterationState(base)

        # Access internal _persistent directly to verify type
        assert "foo" in state._persistent
        stored = state._persistent["foo"]

        # Must be a Fact object, not a dict
        assert isinstance(stored, Fact), f"Expected Fact, got {type(stored)}"
        assert stored.key == "foo"
        assert stored.value == "bar"
        assert stored.scope == "persistent"

    def test_persistent_excludes_iteration_scoped_facts(self):
        """Iteration-scoped facts should not be stored in _persistent."""
        base = Facts(
            durable=Fact(key="durable", value=1, scope="session"),
            ephemeral=Fact(key="ephemeral", value=2, scope="iteration"),
        )
        state = IterationState(base)

        assert "durable" in state._persistent
        assert "ephemeral" not in state._persistent

    def test_nested_facts_flattened_correctly(self):
        """Nested Facts should be flattened with dot-notation keys."""
        base = Facts(
            repo=Facts(
                root=Fact(key="root", value="/path", scope="session"),
            ),
        )
        state = IterationState(base)

        assert "repo.root" in state._persistent
        stored = state._persistent["repo.root"]
        assert isinstance(stored, Fact)
        assert stored.value == "/path"


# ----------------------------------------------------------------------------
# Issue 2b: apply_facts() correctly stores Fact objects by scope
# ----------------------------------------------------------------------------


class TestIterationStateApplyFacts:
    def test_apply_iteration_scoped_fact(self):
        """Iteration-scoped facts go to _iteration dict."""
        state = IterationState(Facts())
        facts = Facts(
            temp=Fact(key="temp", value="ephemeral", scope="iteration"),
        )

        state.apply_facts(facts)

        assert "temp" in state._iteration
        stored = state._iteration["temp"]
        assert isinstance(stored, Fact)
        assert stored.scope == "iteration"

    def test_apply_persistent_scoped_fact(self):
        """Persistent-scoped facts go to _persistent dict."""
        state = IterationState(Facts())
        facts = Facts(
            perm=Fact(key="perm", value="durable", scope="persistent"),
        )

        state.apply_facts(facts)

        assert "perm" in state._persistent
        stored = state._persistent["perm"]
        assert isinstance(stored, Fact)
        assert stored.scope == "persistent"

    def test_apply_session_scoped_fact(self):
        """Session-scoped facts go to _persistent dict."""
        state = IterationState(Facts())
        facts = Facts(
            sess=Fact(key="sess", value="session-data", scope="session"),
        )

        state.apply_facts(facts)

        assert "sess" in state._persistent
        stored = state._persistent["sess"]
        assert isinstance(stored, Fact)
        assert stored.scope == "session"

    def test_fact_scope_attribute_accessible(self):
        """Stored facts must have accessible .scope attribute (not dicts)."""
        state = IterationState(Facts())
        facts = Facts(
            a=Fact(key="a", value=1, scope="iteration"),
            b=Fact(key="b", value=2, scope="persistent"),
        )

        state.apply_facts(facts)

        # These would raise AttributeError if storing dicts
        assert state._iteration["a"].scope == "iteration"
        assert state._persistent["b"].scope == "persistent"


# ----------------------------------------------------------------------------
# Issue 2 & 4: InMemoryStateStore.save() signature and behavior
# ----------------------------------------------------------------------------


class TestInMemoryStateStoreSave:
    def test_save_stores_persistent_facts(self):
        """save() should store the provided persistent_facts."""
        store = InMemoryStateStore()
        store._persistent["agent1"] = Facts()

        iteration_facts = IterationFacts(
            iteration=1,
            phase=Phase.READY_TO_CONTINUE,
            by_action={},
        )
        persistent_facts = Facts(
            keep=Fact(key="keep", value="durable", scope="persistent"),
        )

        store.save("agent1", iteration_facts, persistent_facts)

        result = store.load("agent1")
        assert "keep" in result
        assert result["keep"].value == "durable"

    def test_save_stores_facts_with_correct_types(self):
        """save() stores Fact objects that are retrievable with correct types."""
        store = InMemoryStateStore()
        store._persistent["agent1"] = Facts()

        iteration_facts = IterationFacts(
            iteration=1,
            phase=Phase.READY_TO_CONTINUE,
            by_action={},
        )
        persistent_facts = Facts(
            data=KnowledgeFact(key="data", value={"nested": "dict"}, scope="session"),
        )

        store.save("agent1", iteration_facts, persistent_facts)

        result = store.load("agent1")
        assert "data" in result
        assert isinstance(result["data"], Fact)
        assert result["data"].value == {"nested": "dict"}

    def test_save_records_iteration_history(self):
        """save() should record iteration_facts in history."""
        store = InMemoryStateStore()
        store._persistent["agent1"] = Facts()

        iteration_facts = IterationFacts(
            iteration=1,
            phase=Phase.READY_TO_CONTINUE,
            by_action={
                "ActionA": Facts(
                    result=Fact(key="result", value="done", scope="persistent"),
                ),
            },
        )
        persistent_facts = Facts(
            result=Fact(key="result", value="done", scope="persistent"),
        )

        store.save("agent1", iteration_facts, persistent_facts)

        history = store.history("agent1")
        assert len(history) == 1
        assert history[0].iteration == 1
        assert "ActionA" in history[0].by_action

    def test_save_signature_matches_protocol(self):
        """save() must accept (agent_id, iteration_facts, persistent_facts)."""
        store = InMemoryStateStore()
        store._persistent["agent1"] = Facts()

        # This call pattern must work (matches StateStore protocol)
        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(iteration=1, phase=Phase.READY_TO_CONTINUE, by_action={}),
            persistent_facts=Facts(),
        )


# ----------------------------------------------------------------------------
# Issue 4: FileSystemStateStore signature matches protocol
# ----------------------------------------------------------------------------


class TestFileSystemStateStoreSave:
    def test_save_signature_matches_protocol(self, tmp_path):
        """save() must accept (agent_id, iteration_facts, persistent_facts)."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        # This call pattern must work (matches StateStore protocol)
        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(iteration=1, phase=Phase.READY_TO_CONTINUE, by_action={}),
            persistent_facts=Facts(
                goal=Fact(key="goal", value="test", scope="session"),
            ),
        )

    def test_save_persists_facts_to_disk(self, tmp_path):
        """save() should write persistent_facts to JSON file."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)
        persistent_facts = Facts(
            goal=KnowledgeFact(key="goal", value="test goal", scope="session"),
        )

        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(iteration=1, phase=Phase.READY_TO_CONTINUE, by_action={}),
            persistent_facts=persistent_facts,
        )

        # Verify file exists and can be loaded
        result = store.load("agent1")
        assert "goal" in result
        assert result["goal"].value == "test goal"


# ----------------------------------------------------------------------------
# Issue 6: FileSystemStateStore persists iteration history
# ----------------------------------------------------------------------------


class TestFileSystemStateStoreHistory:
    def test_save_creates_history_file(self, tmp_path):
        """save() should create/append to {agent_id}_history.jsonl."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        iteration_facts = IterationFacts(
            iteration=1,
            phase=Phase.READY_TO_CONTINUE,
            by_action={
                "ActionA": Facts(
                    result=Fact(key="result", value="done", scope="persistent"),
                ),
            },
        )

        store.save(
            agent_id="agent1",
            iteration_facts=iteration_facts,
            persistent_facts=Facts(
                result=Fact(key="result", value="done", scope="persistent"),
            ),
        )

        # History file should exist
        history_path = tmp_path / "agent1_history.jsonl"
        assert history_path.exists()

    def test_history_contains_iteration_data(self, tmp_path):
        """history() returns IterationFacts with expected fields."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        iteration_facts = IterationFacts(
            iteration=1,
            phase=Phase.READY_TO_CONTINUE,
            by_action={
                "ActionA": Facts(
                    result=Fact(key="result", value="done", scope="persistent"),
                ),
            },
        )

        store.save(
            agent_id="agent1",
            iteration_facts=iteration_facts,
            persistent_facts=Facts(),
        )

        history = store.history("agent1")

        assert len(history) == 1
        record = history[0]
        assert record.iteration == 1
        assert record.phase == "READY_TO_CONTINUE"  # String after deserialization
        assert record.timestamp is not None
        assert "ActionA" in record.by_action

    def test_history_appends_multiple_iterations(self, tmp_path):
        """save() appends to history, preserving all iterations."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        # Iteration 1
        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(
                iteration=1,
                phase=Phase.READY_TO_CONTINUE,
                by_action={},
            ),
            persistent_facts=Facts(),
        )

        # Iteration 2
        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(
                iteration=2,
                phase=Phase.TASK_COMPLETE,
                by_action={},
            ),
            persistent_facts=Facts(),
        )

        history = store.history("agent1")

        assert len(history) == 2
        assert history[0].iteration == 1
        assert history[0].phase == "READY_TO_CONTINUE"
        assert history[1].iteration == 2
        assert history[1].phase == "TASK_COMPLETE"

    def test_history_empty_for_new_agent(self, tmp_path):
        """history() returns empty list for agent with no history."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        history = store.history("nonexistent")

        assert history == []

    def test_history_facts_are_deserialized(self, tmp_path):
        """by_action contains deserialized Facts objects."""
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)

        store.save(
            agent_id="agent1",
            iteration_facts=IterationFacts(
                iteration=1,
                phase=Phase.READY_TO_CONTINUE,
                by_action={
                    "ActionA": Facts(
                        data=KnowledgeFact(key="data", value={"nested": "value"}, scope="session"),
                    ),
                },
            ),
            persistent_facts=Facts(),
        )

        history = store.history("agent1")
        facts = history[0].by_action["ActionA"]
        data_fact = facts["data"]

        # Should be deserialized Fact object
        assert isinstance(data_fact, Fact)
        assert data_fact.key == "data"
        assert data_fact.value == {"nested": "value"}
        assert data_fact.scope == "session"


# ----------------------------------------------------------------------------
# Issue 4: StateStore implementations are interchangeable
# ----------------------------------------------------------------------------


class TestStateStoreInterchangeability:
    """Both InMemoryStateStore and FileSystemStateStore must be drop-in replacements."""

    def test_both_stores_accept_same_save_signature(self, tmp_path):
        """Both implementations accept identical save() arguments."""
        from slater.state import FileSystemStateStore

        stores = [
            InMemoryStateStore(),
            FileSystemStateStore(root=tmp_path),
        ]

        for store in stores:
            # Initialize
            if isinstance(store, InMemoryStateStore):
                store._persistent["agent1"] = Facts()

            # Same call must work for both
            store.save(
                agent_id="agent1",
                iteration_facts=IterationFacts(iteration=1, phase=Phase.READY_TO_CONTINUE, by_action={}),
                persistent_facts=Facts(
                    data=Fact(key="data", value="value", scope="persistent"),
                ),
            )

            # Both must return Facts with same structure
            result = store.load("agent1")
            assert "data" in result
            assert isinstance(result["data"], Fact)
            assert result["data"].value == "value"


# ----------------------------------------------------------------------------
# Issue 5: Bootstrap handles partial config gracefully
# ----------------------------------------------------------------------------


class TestBootstrapNullSafety:
    """Both StateStore implementations handle missing config fields."""

    def test_inmemory_bootstrap_with_empty_config(self):
        """InMemoryStateStore.bootstrap() handles empty config."""
        from slater.config import BootstrapConfig

        store = InMemoryStateStore()
        config = BootstrapConfig()  # All fields None

        # Should not raise
        store.bootstrap("agent1", config)

        result = store.load("agent1")
        assert isinstance(result, Facts)

    def test_inmemory_bootstrap_with_goal_only(self):
        """InMemoryStateStore.bootstrap() handles config with only goal."""
        from slater.config import BootstrapConfig

        store = InMemoryStateStore()
        config = BootstrapConfig(goal="test goal")

        store.bootstrap("agent1", config)

        result = store.load("agent1")
        assert "goal" in result
        assert result["goal"].value == "test goal"
        assert "repo_root" not in result

    def test_filesystem_bootstrap_with_empty_config(self, tmp_path):
        """FileSystemStateStore.bootstrap() handles empty config."""
        from slater.config import BootstrapConfig
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)
        config = BootstrapConfig()  # All fields None

        # Should not raise
        store.bootstrap("agent1", config)

        result = store.load("agent1")
        assert isinstance(result, Facts)

    def test_filesystem_bootstrap_with_goal_only(self, tmp_path):
        """FileSystemStateStore.bootstrap() handles config with only goal."""
        from slater.config import BootstrapConfig
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)
        config = BootstrapConfig(goal="test goal")

        store.bootstrap("agent1", config)

        result = store.load("agent1")
        assert "goal" in result
        assert result["goal"].value == "test goal"
        assert "repo_root" not in result

    def test_filesystem_bootstrap_with_repo_no_ignore(self, tmp_path):
        """FileSystemStateStore.bootstrap() handles repo config without ignore."""
        from slater.config import BootstrapConfig, RepoConfig
        from slater.state import FileSystemStateStore

        store = FileSystemStateStore(root=tmp_path)
        config = BootstrapConfig(
            repo=RepoConfig(root="/path/to/repo")
        )

        store.bootstrap("agent1", config)

        result = store.load("agent1")
        assert "repo_root" in result
        assert result["repo_root"].value == "/path/to/repo"
        assert "repo_ignore" not in result

    def test_both_stores_bootstrap_identically(self, tmp_path):
        """Both implementations produce same Facts for same config."""
        from slater.config import BootstrapConfig, RepoConfig
        from slater.state import FileSystemStateStore

        config = BootstrapConfig(
            goal="test goal",
            repo=RepoConfig(root="/path", ignore=["*.pyc"]),
        )

        inmemory = InMemoryStateStore()
        inmemory.bootstrap("agent1", config)
        inmemory_result = inmemory.load("agent1")

        filesystem = FileSystemStateStore(root=tmp_path)
        filesystem.bootstrap("agent1", config)
        filesystem_result = filesystem.load("agent1")

        # Same keys
        assert set(inmemory_result.flatten().keys()) == set(filesystem_result.flatten().keys())

        # Same values
        assert inmemory_result["goal"].value == filesystem_result["goal"].value
        assert inmemory_result["repo_root"].value == filesystem_result["repo_root"].value
        assert inmemory_result["repo_ignore"].value == filesystem_result["repo_ignore"].value


# ----------------------------------------------------------------------------
# Issue 3: TransitionPolicy.derive_phase() receives keys, not Facts
# ----------------------------------------------------------------------------


class TestTransitionPolicyDerivePhase:
    def test_derive_phase_accepts_set_of_strings(self):
        """derive_phase() must accept AbstractSet[str], not Facts."""
        policy = TransitionPolicy(
            rules=[
                PhaseRule(
                    enter=Phase.READY_TO_CONTINUE,
                    when_all=frozenset({"goal", "repo_root"}),
                ),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        # Pass a set of keys (correct usage after fix)
        keys = {"goal", "repo_root", "extra_key"}
        result = policy.derive_phase(keys)

        assert result == Phase.READY_TO_CONTINUE

    def test_derive_phase_returns_none_when_no_match(self):
        """derive_phase() returns None when no rules match."""
        policy = TransitionPolicy(
            rules=[
                PhaseRule(
                    enter=Phase.READY_TO_CONTINUE,
                    when_all=frozenset({"required_key"}),
                ),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        keys = {"other_key"}
        result = policy.derive_phase(keys)

        assert result is None

    def test_derive_phase_raises_on_non_determinism(self):
        """derive_phase() raises when multiple rules match."""
        policy = TransitionPolicy(
            rules=[
                PhaseRule(enter=Phase.READY_TO_CONTINUE, when_all=frozenset({"a"})),
                PhaseRule(enter=Phase.TASK_COMPLETE, when_all=frozenset({"a"})),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        keys = {"a", "b"}

        with pytest.raises(ValueError, match="Non-deterministic"):
            policy.derive_phase(keys)


# ----------------------------------------------------------------------------
# Integration: End-to-end type safety
# ----------------------------------------------------------------------------


class TestFactsRoundTrip:
    def test_facts_survive_iteration_state_round_trip(self):
        """Facts → IterationState → persistent_facts() → Facts preserves types."""
        original = Facts(
            goal=KnowledgeFact(key="goal", value="test goal", scope="session"),
            repo_root=KnowledgeFact(key="repo_root", value="/path/to/repo", scope="session"),
        )

        state = IterationState(original)
        recovered = state.persistent_facts()

        # Verify structure preserved
        assert "goal" in recovered
        assert "repo_root" in recovered

        # Verify types preserved (not dicts)
        assert isinstance(recovered["goal"], Fact)
        assert isinstance(recovered["repo_root"], Fact)

        # Verify values preserved
        assert recovered["goal"].value == "test goal"
        assert recovered["repo_root"].value == "/path/to/repo"


# ----------------------------------------------------------------------------
# Issue 7: Cycle detection in AgentController
# ----------------------------------------------------------------------------


class TestCycleDetection:
    """Tests for AgentController._detect_cycle()."""

    def test_detect_cycle_returns_false_when_history_too_short(self):
        """No cycle if history shorter than max_same_phase."""
        from slater.controller import AgentController

        # Create minimal controller to access _detect_cycle
        # We'll test the method directly
        history = [Phase.READY_TO_CONTINUE, Phase.READY_TO_CONTINUE]
        max_same_phase = 3

        # Use the function directly (it's a static-like method)
        result = AgentController._detect_cycle(None, history, max_same_phase)

        assert result is False

    def test_detect_cycle_returns_true_when_stuck(self):
        """Cycle detected when same phase repeats max_same_phase times."""
        from slater.controller import AgentController

        history = [
            Phase.READY_TO_CONTINUE,
            Phase.READY_TO_CONTINUE,
            Phase.READY_TO_CONTINUE,
        ]
        max_same_phase = 3

        result = AgentController._detect_cycle(None, history, max_same_phase)

        assert result is True

    def test_detect_cycle_returns_false_when_phases_vary(self):
        """No cycle when phases change."""
        from slater.controller import AgentController

        history = [
            Phase.READY_TO_CONTINUE,
            Phase.TASK_COMPLETE,
            Phase.READY_TO_CONTINUE,
        ]
        max_same_phase = 3

        result = AgentController._detect_cycle(None, history, max_same_phase)

        assert result is False

    def test_detect_cycle_checks_only_recent_history(self):
        """Cycle detection only looks at most recent entries."""
        from slater.controller import AgentController

        history = [
            Phase.READY_TO_CONTINUE,
            Phase.READY_TO_CONTINUE,
            Phase.READY_TO_CONTINUE,
            Phase.TASK_COMPLETE,  # Changed!
            Phase.TASK_COMPLETE,
            Phase.TASK_COMPLETE,  # Now stuck in TASK_COMPLETE
        ]
        max_same_phase = 3

        result = AgentController._detect_cycle(None, history, max_same_phase)

        assert result is True  # Stuck in TASK_COMPLETE
