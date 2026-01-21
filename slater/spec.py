"""
AgentSpec: Declarative specification of a Slater agent.

An AgentSpec is a versioned, immutable description of an agent's
behavior that can be validated, visualized, and executed.
"""

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, Type

from slater.phases import PhaseRule
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.validation import FactScopeError, validate_fact_scopes


@dataclass
class AgentSpec:
    """
    Declarative specification of a Slater agent.

    An AgentSpec is a versioned, immutable description of an agent's
    behavior that can be validated, visualized, and executed.

    Validation occurs at construction time to ensure:
    - All Phases have Procedures
    - TransitionPolicy references valid Phases
    - PhaseRules are deterministic (no overlaps)
    - ControlPolicy keys are consistent with expected fact types
    - Facts referenced in policies are emitted with durable scope (if enabled)
    """

    name: str
    version: str
    phases: Set[Enum]
    control_policy: ControlPolicy
    transition_policy: TransitionPolicy
    procedures: Dict[Enum, ProcedureTemplate]

    # Enable fact scope validation (validates that policy-referenced facts
    # are declared in action `emits` with durable scope)
    validate_emissions: bool = True

    def __post_init__(self):
        """Validate the spec at construction."""
        self._validate()

    def _validate(self):
        """Run all validation checks."""
        self._validate_name_and_version()
        self._validate_phases()
        self._validate_procedures()
        self._validate_transition_policy()
        self._validate_control_policy()

        if self.validate_emissions:
            self._validate_fact_scopes()

    def _validate_name_and_version(self):
        """Ensure name and version are valid."""
        if not self.name or not self.name.strip():
            raise ValueError("AgentSpec.name cannot be empty")

        if not self.version or not self.version.strip():
            raise ValueError("AgentSpec.version cannot be empty")

    def _validate_phases(self):
        """Ensure phases are defined."""
        if not self.phases:
            raise ValueError(
                f"AgentSpec '{self.name}' must define at least one Phase"
            )

        if not all(isinstance(p, Enum) for p in self.phases):
            raise TypeError(
                "AgentSpec.phases must contain only Enum members"
            )

        # Ensure all phases are from the same enum class
        phase_types = {type(p) for p in self.phases}
        if len(phase_types) > 1:
            raise TypeError(
                f"AgentSpec.phases must contain members from a single Enum class, "
                f"got: {phase_types}"
            )

    def _validate_procedures(self):
        """Ensure every Phase has a Procedure."""
        missing = self.phases - set(self.procedures.keys())
        if missing:
            raise ValueError(
                f"AgentSpec '{self.name}' missing Procedures for Phases: {missing}"
            )

        # Check for extra procedures (warning, not error)
        extra = set(self.procedures.keys()) - self.phases
        if extra:
            warnings.warn(
                f"AgentSpec '{self.name}' has Procedures for undefined Phases: {extra}"
            )

    def _validate_transition_policy(self):
        """Ensure TransitionPolicy references valid Phases."""
        # Check default Phase
        if self.transition_policy.default not in self.phases:
            raise ValueError(
                f"TransitionPolicy.default references unknown Phase: "
                f"{self.transition_policy.default}"
            )

        # Check all rules reference valid Phases
        for i, rule in enumerate(self.transition_policy.rules):
            if rule.enter not in self.phases:
                raise ValueError(
                    f"PhaseRule[{i}] references unknown Phase: {rule.enter}"
                )

        # Check for determinism (no overlapping rules)
        self._check_rule_determinism()

    def _check_rule_determinism(self):
        """
        Ensure PhaseRules don't overlap (non-deterministic behavior).

        Two rules overlap if they could both match the same fact set.
        This is a simplified check; full coverage would require SAT solving.
        """
        rules = self.transition_policy.rules

        for i, rule_a in enumerate(rules):
            for j, rule_b in enumerate(rules[i + 1 :], start=i + 1):
                # Simple overlap check: identical when_all
                if rule_a.when_all == rule_b.when_all:
                    # If when_any/when_none differ, might still be deterministic
                    if (
                        not rule_a.when_any
                        and not rule_a.when_none
                        and not rule_b.when_any
                        and not rule_b.when_none
                    ):
                        raise ValueError(
                            f"PhaseRules overlap (non-deterministic):\n"
                            f"  Rule {i}: enter={rule_a.enter}, when_all={rule_a.when_all}\n"
                            f"  Rule {j}: enter={rule_b.enter}, when_all={rule_b.when_all}"
                        )

    def _validate_control_policy(self):
        """
        Validate ControlPolicy key sets.

        Could cross-reference with FactRegistry if implemented,
        ensuring completion_keys are ProgressFacts, etc.
        """
        # Check for key overlap (may or may not be desired)
        completion_and_failure = (
            self.control_policy.completion_keys & self.control_policy.failure_keys
        )
        if completion_and_failure:
            raise ValueError(
                f"ControlPolicy has keys in both completion_keys and failure_keys: "
                f"{completion_and_failure}"
            )

    def _validate_fact_scopes(self):
        """
        Validate that facts referenced in policies are emitted with durable scope.

        This catches scope bugs at spec construction time:
        - Transition rules referencing iteration-scoped facts (infinite loops)
        - Control policy referencing undeclared facts (KeyError at runtime)

        Actions must declare emissions via EmissionSpec for this validation to work.
        """
        issues = validate_fact_scopes(
            procedures=self.procedures,
            transition_policy=self.transition_policy,
            control_policy=self.control_policy,
        )

        # Only raise on errors, not warnings
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise FactScopeError(errors)

        # Log warnings but don't fail
        warnings_list = [i for i in issues if i.severity == "warning"]
        for issue in warnings_list:
            warnings.warn(str(issue), UserWarning, stacklevel=3)

    # ---- Introspection / Debugging ----

    def describe(self) -> str:
        """Generate a human-readable description of this spec."""
        lines = [
            f"AgentSpec: {self.name} (v{self.version})",
            f"Phases: {len(self.phases)}",
            f"  {', '.join(p.name for p in self.phases)}",
            f"TransitionPolicy: {len(self.transition_policy.rules)} rules",
            f"  Default: {self.transition_policy.default.name}",
            f"ControlPolicy:",
            f"  Required: {self.control_policy.required_state_keys}",
            f"  User-required: {self.control_policy.user_required_keys}",
            f"  Completion: {self.control_policy.completion_keys}",
            f"  Failure: {self.control_policy.failure_keys}",
        ]
        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """
        Generate a Mermaid state diagram.

        This enables visualization without running the agent.
        """
        lines = [
            "stateDiagram-v2",
            f"    [*] --> {self.transition_policy.default.name}",
        ]

        # Add rule-based transitions
        for rule in self.transition_policy.rules:
            condition = self._format_condition(rule)
            # Note: We don't know the source Phase from the rule alone
            # Would need to track which Phase emits which facts
            lines.append(f"    ... --> {rule.enter.name} : {condition}")

        # Add ControlPolicy transitions
        if self.control_policy.completion_keys:
            lines.append("    state ANY <<choice>>")
            lines.append("    ANY --> [*] : completion_keys present")

        return "\n".join(lines)

    def _format_condition(self, rule: PhaseRule) -> str:
        """Format PhaseRule conditions for display."""
        parts = []
        if rule.when_all:
            parts.append(" & ".join(rule.when_all))
        if rule.when_any:
            parts.append(f"({' | '.join(rule.when_any)})")
        if rule.when_none:
            parts.append(f"!{' & !'.join(rule.when_none)}")
        return " & ".join(parts) if parts else "true"
