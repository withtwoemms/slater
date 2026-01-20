"""Define policies for handling events in the agent controller.

Might introduce more policies later, e.g.:
    * ValidationPolicy -- Fact schemas, cross-fact constraints, immutability rules, etc.
    * ExecutionPolicy -- retry limits, timeouts, resource constraints, etc.
    * EscalationPolicy -- global timeouts, stuck detection, confidence thresholds, etc.
    * AuditPolicy -- retention rules, logging levels, redaction rules, etc.
    * RecoveryPolicy -- restart semantics, state reconciliation, stale session handling, etc.
"""
from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet

from slater.phases import PhaseRule


@dataclass
class ControlPolicy:
    # keys that must exist in state to proceed autonomously
    required_state_keys: set[str]

    # keys that, if missing, require user input
    user_required_keys: set[str]

    # keys that, if present, signal task completion
    completion_keys: set[str]

    # keys that, if present, signal irrecoverable task failure
    failure_keys: set[str]


@dataclass
class TransitionPolicy:
    rules: list[PhaseRule]
    default: Enum  # Phase enum member (no default - must be specified)

    def derive_phase(self, fact_keys: AbstractSet[str]) -> Enum | None:
        matches = [r for r in self.rules if r.matches(fact_keys)]

        if not matches:
            return None

        if len(matches) > 1:
            raise ValueError(
                f"Non-deterministic phase derivation: {[r.enter for r in matches]}"
            )

        return matches[0].enter
