"""
Fact scope validation for Slater agents.

This module provides static validation to catch scope-related bugs before runtime:
- Facts referenced in transition rules must be emitted with durable scope
- Facts referenced in control policy must be emitted with durable scope
- Runtime drift detection warns when actual emissions don't match declarations

See: docs/proposals/002-fact-scope-validator.md
"""

import warnings
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Mapping

from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.types import Facts


Scope = Literal["iteration", "session", "persistent"]


@dataclass
class FactScopeIssue:
    """A single fact scope validation issue."""
    fact_key: str
    expected_scope: Literal["session", "persistent"]
    actual_scope: Scope | None
    emitting_action: str | None
    referenced_by: str  # e.g., "PhaseRule(enter=TASK_COMPLETE).when_all"
    severity: Literal["error", "warning"]
    message: str

    def __str__(self) -> str:
        prefix = "ERROR" if self.severity == "error" else "WARNING"
        return f"{prefix}: {self.message}"


class FactScopeError(Exception):
    """Raised when fact scope validation fails."""

    def __init__(self, issues: list[FactScopeIssue]):
        self.issues = issues
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        lines = ["Fact scope validation failed:"]
        for issue in issues:
            lines.append(f"  {issue}")
        lines.append(f"\nFound {len(errors)} error(s), {len(warnings)} warning(s)")

        super().__init__("\n".join(lines))


def validate_fact_scopes(
    procedures: Mapping[Enum, ProcedureTemplate],
    transition_policy: TransitionPolicy,
    control_policy: ControlPolicy,
) -> list[FactScopeIssue]:
    """
    Cross-reference policy requirements with action emissions.

    Validates that:
    1. Facts in PhaseRule.when_all/when_none are emitted with durable scope
    2. Facts in ControlPolicy.*_keys are emitted with durable scope

    Actions must declare an `emits` class attribute:
        class MyAction(SlaterAction):
            emits = {"my_fact": "session"}

    Returns list of issues (empty if valid).
    """
    issues: list[FactScopeIssue] = []

    # 1. Collect all emitted facts from all actions
    emissions: dict[str, tuple[str, Scope]] = {}  # key -> (action_name, scope)

    for phase, template in procedures.items():
        for action in template.actions:
            # Handle both class and instance
            action_cls = action if isinstance(action, type) else type(action)

            if hasattr(action_cls, 'emits'):
                emits = action_cls.emits
                for key, scope in emits.items():
                    emissions[key] = (action_cls.__name__, scope)

    # 2. Check transition policy requirements
    for rule in transition_policy.rules:
        for key in rule.when_all:
            issues.extend(_check_fact_scope(
                key, emissions,
                f"PhaseRule(enter={rule.enter.name}).when_all"
            ))
        if rule.when_none:
            for key in rule.when_none:
                issues.extend(_check_fact_scope(
                    key, emissions,
                    f"PhaseRule(enter={rule.enter.name}).when_none"
                ))

    # 3. Check control policy requirements
    for key in control_policy.completion_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.completion_keys"))

    for key in control_policy.failure_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.failure_keys"))

    for key in control_policy.required_state_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.required_state_keys"))

    for key in control_policy.user_required_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.user_required_keys"))

    return issues


def _check_fact_scope(
    key: str,
    emissions: dict[str, tuple[str, Scope]],
    referenced_by: str,
) -> list[FactScopeIssue]:
    """Check if a single fact key has appropriate scope."""
    if key not in emissions:
        return [FactScopeIssue(
            fact_key=key,
            expected_scope="session",
            actual_scope=None,
            emitting_action=None,
            referenced_by=referenced_by,
            severity="warning",
            message=f"Fact '{key}' referenced by {referenced_by} is not declared in any action's `emits`",
        )]

    action_name, scope = emissions[key]
    if scope == "iteration":
        return [FactScopeIssue(
            fact_key=key,
            expected_scope="session",
            actual_scope=scope,
            emitting_action=action_name,
            referenced_by=referenced_by,
            severity="error",
            message=(
                f"Fact '{key}' emitted by {action_name} has scope='{scope}' "
                f"but is referenced by {referenced_by} (requires durable scope)"
            ),
        )]

    return []


def check_emission_drift(action_cls: type, facts: Facts) -> None:
    """
    Warn if actual emissions don't match declared `emits`.

    Call this after an action executes to catch drift between
    declared and actual emissions.
    """
    declared: dict[str, Scope] = getattr(action_cls, 'emits', {})
    actual: dict[str, Scope] = {key: fact.scope for key, fact in facts.iter_facts()}

    action_name = action_cls.__name__

    # Check declared facts are emitted with correct scope
    for key, declared_scope in declared.items():
        if key not in actual:
            # Declared but not emitted - might be conditional, just warn
            warnings.warn(
                f"{action_name} declares emits['{key}'] but didn't emit it",
                UserWarning,
                stacklevel=3,
            )
        elif actual[key] != declared_scope:
            warnings.warn(
                f"{action_name} declares emits['{key}']='{declared_scope}' "
                f"but emitted with scope='{actual[key]}'",
                UserWarning,
                stacklevel=3,
            )

    # Check for undeclared emissions
    for key in actual:
        if key not in declared:
            warnings.warn(
                f"{action_name} emitted '{key}' but doesn't declare it in `emits`",
                UserWarning,
                stacklevel=3,
            )
