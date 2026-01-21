# Proposal 002: Fact Scope Validator

**Status:** Draft
**Created:** 2026-01-20
**Authors:** slater contributors

## Motivation

Issues 001, 002, and 003 revealed a recurring bug pattern: actions emit facts with `iteration` scope, but transition rules and downstream actions expect those facts to persist. This causes:

- **Infinite loops**: Transition rules never match (Issues 001, 003)
- **KeyError crashes**: Downstream actions can't read discarded facts (Issue 002)

These bugs are subtle because:
1. The default scope is `iteration` (easy to forget explicit scope)
2. Eager fact application within iterations masks the problem during development
3. Failures only manifest at iteration boundaries

A static validator could catch these issues at `AgentSpec` construction time, before the agent runs.

## Requirements

### Must Have

1. **Transition rule validation**: Facts referenced in `PhaseRule.when_all` and `when_none` must be emitted with durable scope (`session` or `persistent`)

2. **Control policy validation**: Facts referenced in `ControlPolicy.completion_keys`, `failure_keys`, `required_state_keys`, and `user_required_keys` must be emitted with durable scope

3. **Clear error messages**: Validator should report which fact, which action emits it, and what scope it has

### Should Have

4. **Cross-action dataflow validation**: If Action B reads `state["foo"]`, some Action A (that runs before B) must emit `foo` with durable scope

5. **Reachability analysis**: Warn if a phase has no path to completion (no rule leads to a phase with completion keys)

### Could Have

6. **Scope suggestions**: Recommend appropriate scopes based on usage patterns
7. **IDE integration**: Export diagnostics in LSP-compatible format

## Design

### Approach: Declarative Action Metadata

Actions declare what they emit via a class attribute:

```python
class ProposePlan(SlaterAction):
    emits = {
        "plan": "session",
        "plan_ready": "session",
    }

    def instruction(self) -> Facts:
        ...
```

**Pros:**
- Simple to implement
- Easy to validate statically
- Self-documenting

**Cons:**
- Requires discipline to keep metadata in sync with implementation
- Doesn't catch dynamic emission patterns

### Alternative: AST Analysis

Parse action source code to extract `Facts(...)` return statements and infer emitted keys/scopes.

**Pros:**
- No metadata to maintain
- Catches actual emission

**Cons:**
- Complex to implement reliably
- Struggles with dynamic patterns (conditional emission, computed keys)
- Fragile across code changes

### Alternative: Runtime Dry-Run

Execute each procedure with mock state, capture emitted facts.

**Pros:**
- Accurate (tests real code paths)
- No metadata needed

**Cons:**
- Requires valid mock state for each phase
- May have side effects
- Slower than static analysis

### Recommended: Hybrid Approach

1. **Primary**: Declarative `emits` metadata on actions (static validation)
2. **Secondary**: Runtime check that actual emissions match declared metadata (catches drift)

## Validator API

### Static Validation at AgentSpec Construction

```python
@dataclass
class AgentSpec:
    def __post_init__(self):
        self._validate_name_version()
        self._validate_phases()
        self._validate_procedures()
        self._validate_transition_policy()
        self._validate_control_policy()
        self._validate_fact_scopes()  # NEW

    def _validate_fact_scopes(self) -> None:
        """
        Validate that facts referenced in policies are emitted with durable scope.
        """
        issues = validate_fact_scopes(
            procedures=self.procedures,
            transition_policy=self.transition_policy,
            control_policy=self.control_policy,
        )
        if issues:
            raise FactScopeError(issues)
```

### Validation Function

```python
@dataclass
class FactScopeIssue:
    fact_key: str
    expected_scope: Literal["session", "persistent"]
    actual_scope: Literal["iteration", "session", "persistent"] | None
    emitting_action: str | None
    referenced_by: str  # e.g., "PhaseRule(enter=TASK_COMPLETE).when_all"
    severity: Literal["error", "warning"]
    message: str


def validate_fact_scopes(
    procedures: dict[Enum, ProcedureTemplate],
    transition_policy: TransitionPolicy,
    control_policy: ControlPolicy,
) -> list[FactScopeIssue]:
    """
    Cross-reference policy requirements with action emissions.

    Returns list of issues (empty if valid).
    """
    issues = []

    # 1. Collect all emitted facts from all actions
    emissions: dict[str, tuple[str, str]] = {}  # key -> (action_name, scope)
    for phase, template in procedures.items():
        for action_cls in template.actions:
            if hasattr(action_cls, 'emits'):
                for key, scope in action_cls.emits.items():
                    emissions[key] = (action_cls.__name__, scope)

    # 2. Check transition policy requirements
    for rule in transition_policy.rules:
        for key in rule.when_all:
            issues.extend(_check_fact_scope(key, emissions, f"PhaseRule(enter={rule.enter}).when_all"))
        for key in rule.when_none:
            issues.extend(_check_fact_scope(key, emissions, f"PhaseRule(enter={rule.enter}).when_none"))

    # 3. Check control policy requirements
    for key in control_policy.completion_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.completion_keys"))
    for key in control_policy.failure_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.failure_keys"))
    for key in control_policy.required_state_keys:
        issues.extend(_check_fact_scope(key, emissions, "ControlPolicy.required_state_keys"))

    return issues


def _check_fact_scope(
    key: str,
    emissions: dict[str, tuple[str, str]],
    referenced_by: str,
) -> list[FactScopeIssue]:
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
            message=f"Fact '{key}' emitted by {action_name} has scope='{scope}' but is referenced by {referenced_by} (requires durable scope)",
        )]

    return []
```

### Runtime Drift Detection

Add a check in `AgentController` after each action executes:

```python
# In AgentController.run(), after action execution
if result.successful and isinstance(result.value, Facts):
    action_cls = type(action)
    if hasattr(action_cls, 'emits'):
        _check_emission_drift(action_cls, result.value)
    iteration_state.apply_facts(result.value)
```

```python
def _check_emission_drift(action_cls: type, facts: Facts) -> None:
    """Warn if actual emissions don't match declared `emits`."""
    declared = getattr(action_cls, 'emits', {})
    actual = {key: fact.scope for key, fact in facts.iter_facts()}

    for key, declared_scope in declared.items():
        if key not in actual:
            warnings.warn(f"{action_cls.__name__} declares emits['{key}'] but didn't emit it")
        elif actual[key] != declared_scope:
            warnings.warn(
                f"{action_cls.__name__} declares emits['{key}']={declared_scope!r} "
                f"but emitted scope={actual[key]!r}"
            )

    for key in actual:
        if key not in declared:
            warnings.warn(f"{action_cls.__name__} emitted '{key}' but doesn't declare it in `emits`")
```

## CLI Integration

Add a lint command:

```bash
# Validate agent spec without running
slater lint --config slater.yaml

# Output
ERROR: Fact 'plan_ready' emitted by ProposePlan has scope='iteration'
       but is referenced by PhaseRule(enter=PROCEDURE_SUCCEEDED).when_all
       (requires durable scope)

ERROR: Fact 'plan' emitted by ProposePlan has scope='iteration'
       but is read by ApplyPatch (requires durable scope)

Found 2 errors, 0 warnings
```

## Migration Path

### Phase 1: Add `emits` to Existing Actions

Update all actions with `emits` declarations:

```python
class ProposePlan(SlaterAction):
    emits = {
        "plan": "session",
        "plan_ready": "session",
    }

class ApplyPatch(SlaterAction):
    emits = {
        "patch_applied": "session",
        "patch_summary": "session",
        "patch_errors": "session",
    }
    reads = {"plan", "repo_root"}  # Optional: for dataflow validation

class Validate(SlaterAction):
    emits = {
        "validation_passed": "session",
        "validation_errors": "session",
    }
```

### Phase 2: Add Validation to AgentSpec

Enable validation with a flag initially:

```python
spec = AgentSpec(
    ...,
    validate_fact_scopes=True,  # Opt-in during migration
)
```

### Phase 3: Make Validation Default

After migration complete, enable by default with opt-out:

```python
spec = AgentSpec(
    ...,
    validate_fact_scopes=False,  # Explicit opt-out only
)
```

## Open Questions

1. **Should `emits` be enforced?** (Error if action emits undeclared fact, or just warn?)

2. **How to handle conditional emissions?** (Action emits `error` OR `success` depending on outcome)

3. **Should we validate `reads` declarations?** (Ensure read facts are emitted by prior actions)

4. **What about dynamically constructed keys?** (e.g., `f"file_{i}"`)

## Related

- Issue 001: `plan_ready` Fact Scope Causes Infinite Loop
- Issue 002: `plan` Fact Scope Causes KeyError
- Issue 003: Agent Stuck in PROCEDURE_SUCCEEDED Phase
- ADR-002: Eager Fact Application Within Iterations
