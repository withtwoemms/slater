"""
Tests for AgentSpec validation.

These tests lock in Category 4 (FSM Safety) validation that occurs
at AgentSpec construction time.
"""

import pytest
import warnings

from slater.phases import Phase, PhaseRule
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.spec import AgentSpec


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest.fixture
def minimal_control_policy():
    return ControlPolicy(
        required_state_keys=set(),
        user_required_keys=set(),
        completion_keys={"done"},
        failure_keys=set(),
    )


@pytest.fixture
def minimal_transition_policy():
    return TransitionPolicy(
        rules=[],
        default=Phase.READY_TO_CONTINUE,
    )


@pytest.fixture
def minimal_procedures():
    return {
        Phase.READY_TO_CONTINUE: ProcedureTemplate(name="ready", actions=[]),
        Phase.TASK_COMPLETE: ProcedureTemplate(name="complete", actions=[]),
    }


@pytest.fixture
def minimal_phases():
    return {Phase.READY_TO_CONTINUE, Phase.TASK_COMPLETE}


# ----------------------------------------------------------------------------
# Valid AgentSpec construction
# ----------------------------------------------------------------------------


class TestAgentSpecValid:
    def test_minimal_valid_spec(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """A minimal valid AgentSpec should construct without error."""
        spec = AgentSpec(
            name="test-agent",
            version="1.0.0",
            phases=minimal_phases,
            control_policy=minimal_control_policy,
            transition_policy=minimal_transition_policy,
            procedures=minimal_procedures,
        )

        assert spec.name == "test-agent"
        assert spec.version == "1.0.0"

    def test_describe_returns_string(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """describe() should return a human-readable summary."""
        spec = AgentSpec(
            name="test-agent",
            version="1.0.0",
            phases=minimal_phases,
            control_policy=minimal_control_policy,
            transition_policy=minimal_transition_policy,
            procedures=minimal_procedures,
        )

        description = spec.describe()

        assert "test-agent" in description
        assert "1.0.0" in description
        assert "Phases" in description

    def test_to_mermaid_returns_diagram(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """to_mermaid() should return a valid Mermaid diagram."""
        spec = AgentSpec(
            name="test-agent",
            version="1.0.0",
            phases=minimal_phases,
            control_policy=minimal_control_policy,
            transition_policy=minimal_transition_policy,
            procedures=minimal_procedures,
        )

        diagram = spec.to_mermaid()

        assert "stateDiagram-v2" in diagram
        assert "[*]" in diagram


# ----------------------------------------------------------------------------
# Name and version validation
# ----------------------------------------------------------------------------


class TestAgentSpecNameVersionValidation:
    def test_empty_name_raises(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """Empty name should raise ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            AgentSpec(
                name="",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures=minimal_procedures,
            )

    def test_whitespace_name_raises(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """Whitespace-only name should raise ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            AgentSpec(
                name="   ",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures=minimal_procedures,
            )

    def test_empty_version_raises(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """Empty version should raise ValueError."""
        with pytest.raises(ValueError, match="version cannot be empty"):
            AgentSpec(
                name="test-agent",
                version="",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures=minimal_procedures,
            )


# ----------------------------------------------------------------------------
# Phase validation
# ----------------------------------------------------------------------------


class TestAgentSpecPhaseValidation:
    def test_empty_phases_raises(
        self, minimal_control_policy, minimal_transition_policy
    ):
        """Empty phases set should raise ValueError."""
        with pytest.raises(ValueError, match="must define at least one Phase"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=set(),
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures={},
            )

    def test_non_phase_in_phases_raises(
        self, minimal_control_policy, minimal_transition_policy, minimal_procedures
    ):
        """Non-Phase items in phases should raise TypeError."""
        with pytest.raises(TypeError, match="must contain only Enum members"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases={"not-a-phase", Phase.READY_TO_CONTINUE},
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures=minimal_procedures,
            )


# ----------------------------------------------------------------------------
# Procedure validation
# ----------------------------------------------------------------------------


class TestAgentSpecProcedureValidation:
    def test_missing_procedure_raises(
        self, minimal_phases, minimal_control_policy, minimal_transition_policy
    ):
        """Missing Procedure for a Phase should raise ValueError."""
        incomplete_procedures = {
            Phase.READY_TO_CONTINUE: ProcedureTemplate(name="ready", actions=[]),
            # Missing Phase.TASK_COMPLETE
        }

        with pytest.raises(ValueError, match="missing Procedures for Phases"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=minimal_transition_policy,
                procedures=incomplete_procedures,
            )

    def test_extra_procedure_warns(
        self, minimal_control_policy, minimal_transition_policy
    ):
        """Extra Procedure for undefined Phase should warn."""
        phases = {Phase.READY_TO_CONTINUE}
        procedures = {
            Phase.READY_TO_CONTINUE: ProcedureTemplate(name="ready", actions=[]),
            Phase.TASK_COMPLETE: ProcedureTemplate(name="extra", actions=[]),
        }

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=phases,
                control_policy=minimal_control_policy,
                transition_policy=TransitionPolicy(rules=[], default=Phase.READY_TO_CONTINUE),
                procedures=procedures,
            )

            # Check that at least one warning is about undefined Phases
            # (other warnings may come from fact scope validation)
            extra_proc_warnings = [
                warning for warning in w
                if "undefined Phases" in str(warning.message)
            ]
            assert len(extra_proc_warnings) == 1


# ----------------------------------------------------------------------------
# TransitionPolicy validation
# ----------------------------------------------------------------------------


class TestAgentSpecTransitionPolicyValidation:
    def test_unknown_default_phase_raises(
        self, minimal_phases, minimal_control_policy, minimal_procedures
    ):
        """TransitionPolicy.default referencing unknown Phase should raise."""
        transition_policy = TransitionPolicy(
            rules=[],
            default=Phase.TERMINAL_FAILURE,  # Not in minimal_phases
        )

        with pytest.raises(ValueError, match="unknown Phase"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=transition_policy,
                procedures=minimal_procedures,
            )

    def test_rule_references_unknown_phase_raises(
        self, minimal_phases, minimal_control_policy, minimal_procedures
    ):
        """PhaseRule.enter referencing unknown Phase should raise."""
        transition_policy = TransitionPolicy(
            rules=[
                PhaseRule(
                    enter=Phase.TERMINAL_FAILURE,  # Not in minimal_phases
                    when_all=frozenset({"some_fact"}),
                ),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        with pytest.raises(ValueError, match="PhaseRule.*references unknown Phase"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=transition_policy,
                procedures=minimal_procedures,
            )

    def test_overlapping_rules_raises(
        self, minimal_phases, minimal_control_policy, minimal_procedures
    ):
        """Overlapping PhaseRules (non-deterministic) should raise."""
        transition_policy = TransitionPolicy(
            rules=[
                PhaseRule(
                    enter=Phase.READY_TO_CONTINUE,
                    when_all=frozenset({"fact_a"}),
                ),
                PhaseRule(
                    enter=Phase.TASK_COMPLETE,
                    when_all=frozenset({"fact_a"}),  # Same when_all = overlap
                ),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        with pytest.raises(ValueError, match="non-deterministic"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=minimal_control_policy,
                transition_policy=transition_policy,
                procedures=minimal_procedures,
            )

    def test_non_overlapping_rules_allowed(
        self, minimal_phases, minimal_control_policy, minimal_procedures
    ):
        """Different when_all conditions should not raise."""
        transition_policy = TransitionPolicy(
            rules=[
                PhaseRule(
                    enter=Phase.READY_TO_CONTINUE,
                    when_all=frozenset({"fact_a"}),
                ),
                PhaseRule(
                    enter=Phase.TASK_COMPLETE,
                    when_all=frozenset({"fact_b"}),  # Different = no overlap
                ),
            ],
            default=Phase.READY_TO_CONTINUE,
        )

        # Should not raise
        AgentSpec(
            name="test-agent",
            version="1.0.0",
            phases=minimal_phases,
            control_policy=minimal_control_policy,
            transition_policy=transition_policy,
            procedures=minimal_procedures,
        )


# ----------------------------------------------------------------------------
# ControlPolicy validation
# ----------------------------------------------------------------------------


class TestAgentSpecControlPolicyValidation:
    def test_completion_and_failure_overlap_raises(
        self, minimal_phases, minimal_transition_policy, minimal_procedures
    ):
        """Keys in both completion_keys and failure_keys should raise."""
        control_policy = ControlPolicy(
            required_state_keys=set(),
            user_required_keys=set(),
            completion_keys={"done", "shared_key"},
            failure_keys={"error", "shared_key"},  # Overlap!
        )

        with pytest.raises(ValueError, match="both completion_keys and failure_keys"):
            AgentSpec(
                name="test-agent",
                version="1.0.0",
                phases=minimal_phases,
                control_policy=control_policy,
                transition_policy=minimal_transition_policy,
                procedures=minimal_procedures,
            )
