# ADR-004: EmissionSpec Builder Pattern for Drift-Free Validation

**Status:** Accepted
**Date:** 2026-01-21
**Authors:** slater contributors

## Context

Proposal 002 (Fact Scope Validator) identified a recurring bug pattern: actions emit facts with `iteration` scope, but transition rules and downstream actions expect those facts to persist. The proposal recommended a hybrid approach:

1. **Primary**: Declarative `emits` metadata on actions (static validation)
2. **Secondary**: Runtime check that actual emissions match declared metadata (catches drift)

However, the hybrid approach has an inherent weakness: **drift**. When `emits` is merely declarative metadata separate from the actual `instruction()` implementation, nothing prevents them from getting out of sync:

```python
class ProposePlan(SlaterAction):
    # Declaration says we emit these:
    emits = {
        "plan": "session",
        "plan_ready": "session",
    }

    def instruction(self) -> Facts:
        # But implementation might:
        # - Emit different keys
        # - Use different scopes
        # - Forget to emit declared facts
        # - Emit undeclared facts
        return Facts(
            plan=KnowledgeFact(key="plan", value=..., scope="iteration"),  # Wrong scope!
            status=ProgressFact(key="status", value=..., scope="session"),  # Undeclared!
        )
```

Runtime drift detection can catch these issues, but only at execution time—after the agent is already running. This violates the proposal's goal of catching issues at `AgentSpec` construction time.

## Decision

**Replace declarative `emits` metadata with `EmissionSpec`, a builder that is the single source of truth for both declaration AND construction of emitted Facts.**

The key insight: instead of declaring emissions separately and hoping the implementation matches, make the declaration the mechanism by which emissions are constructed.

```python
class ProposePlan(SlaterAction):
    # EmissionSpec is both declaration AND builder
    emits = EmissionSpec(
        plan=Emission("session", KnowledgeFact),
        plan_ready=Emission("session", ProgressFact),
    )

    def instruction(self) -> Facts:
        # build() validates and constructs—impossible to drift
        return self.emits.build(
            plan={"summary": goal, "steps": steps},
            plan_ready=True,
        )
```

### How It Eliminates Drift

`EmissionSpec.build()` enforces the contract at call time:

1. **Undeclared keys are rejected**: If `instruction()` passes a key not in `emits`, `build()` raises immediately
2. **Missing required keys are rejected**: If a required emission is missing, `build()` raises immediately
3. **Scope and type are automatic**: The declaration controls how Facts are constructed—no opportunity for mismatch

```python
# This will RAISE at call time:
return self.emits.build(
    plan=...,
    plan_ready=True,
    status=True,  # ValueError: Undeclared emission keys: {'status'}
)

# This will also RAISE at call time:
return self.emits.build(
    plan=...,
    # Missing plan_ready → ValueError: Missing required emission keys: {'plan_ready'}
)
```

### Conditional Emissions

Actions often emit different facts based on outcome (success vs. failure). The `required` parameter handles this:

```python
class ApplyPatch(SlaterAction):
    emits = EmissionSpec(
        patch_applied=Emission("session", ProgressFact),           # Always required
        patch_summary=Emission("session", KnowledgeFact, required=False),  # Success only
        patch_errors=Emission("session", KnowledgeFact, required=False),   # Failure only
    )

    def instruction(self) -> Facts:
        try:
            # ... apply patch ...
            return self.emits.build(
                patch_applied=True,
                patch_summary=f"Wrote plan to {path}",
            )
        except Exception as exc:
            return self.emits.build(
                patch_applied=False,
                patch_errors=[str(exc)],
            )
```

### Nested Emissions for Hierarchical Data

Some actions emit logically grouped facts that map to database tables. Nested `EmissionSpec` supports this with dot-notation flattening:

```python
class AnalyzeRepo(SlaterAction):
    emits = EmissionSpec(
        repo=EmissionSpec(
            file_count=Emission("session", KnowledgeFact),
            languages=Emission("session", KnowledgeFact),
            has_tests=Emission("session", KnowledgeFact),
            entrypoints=Emission("session", KnowledgeFact),
            build_system=Emission("session", KnowledgeFact),
            notes=Emission("session", KnowledgeFact),
        ),
        analysis_ready=Emission("session", ProgressFact),
    )

    def instruction(self) -> Facts:
        return self.emits.build(
            repo={
                "file_count": 42,
                "languages": ["python"],
                "has_tests": True,
                "entrypoints": ["main.py"],
                "build_system": "python",
                "notes": [],
            },
            analysis_ready=True,
        )
```

The nested structure is flattened with dot-notation for validation (`repo.file_count`, `repo.languages`, etc.) and can be used for database schema mapping where subordination implies table membership.

### Static Validation Integration

`validate_fact_scopes()` uses `EmissionSpec.to_dict()` to extract declared emissions with their scopes, then cross-references against `TransitionPolicy` and `ControlPolicy` requirements:

```python
# In AgentSpec.__post_init__()
def _validate_fact_scopes(self) -> None:
    issues = validate_fact_scopes(
        procedures=self.procedures,
        transition_policy=self.transition_policy,
        control_policy=self.control_policy,
    )

    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise FactScopeError(issues)
```

This catches scope mismatches at agent construction time, before any code runs.

## Consequences

### Positive

1. **Drift is impossible by construction**: Since `build()` is the only way to construct emissions, and it validates against the declaration, there's no way for implementation to diverge from declaration.

2. **Fail-fast behavior**: Invalid emissions fail immediately at the `build()` call site with clear error messages, not later when the fact is used.

3. **Self-documenting actions**: The `emits` class attribute serves as both documentation and implementation contract.

4. **Static validation enabled**: `EmissionSpec.to_dict()` provides a reliable source of emission metadata for `validate_fact_scopes()`.

5. **Type safety**: `Emission` specifies the `fact_type`, ensuring correct Fact subclass construction.

6. **Conditional emissions are explicit**: `required=False` documents which emissions depend on action outcome.

7. **Hierarchical grouping supported**: Nested `EmissionSpec` enables logical fact grouping for database schema mapping.

### Negative

1. **Migration required**: Existing actions with raw `Facts()` construction must be updated to use `EmissionSpec`.

2. **Slightly more verbose**: Declaring `emits = EmissionSpec(...)` is more verbose than a simple dict.

3. **Learning curve**: Developers must understand the builder pattern and `Emission` configuration.

### Neutral

1. **Runtime drift detection removed**: The hybrid approach from Proposal 002 included runtime drift detection. With EmissionSpec, this is unnecessary—drift is prevented by design. The `_check_emission_drift()` function has been removed.

2. **No change to Fact semantics**: EmissionSpec is purely a construction mechanism. The underlying `Facts`, `Fact`, and scope semantics are unchanged.

## Implementation

### Core Types (slater/types.py)

```python
@dataclass(frozen=True)
class Emission:
    """Declaration of a single fact emission."""
    scope: Scope = "session"
    fact_type: type[Fact] = Fact
    required: bool = True


class EmissionSpec:
    """
    Declarative specification of facts an action emits.

    Single source of truth: build() validates and constructs.
    """
    def __init__(self, *, required: bool = True, **emissions: EmissionEntry):
        self._emissions: dict[str, EmissionEntry] = emissions
        self.required = required

    def build(self, **values: Any) -> Facts:
        """Build Facts, validating against declarations."""
        # Check for undeclared keys
        undeclared = set(values.keys()) - self.keys()
        if undeclared:
            raise ValueError(f"Undeclared emission keys: {undeclared}")

        # Check for missing required keys
        missing = {k for k, e in self._emissions.items()
                   if e.required and k not in values}
        if missing:
            raise ValueError(f"Missing required emission keys: {missing}")

        # Build Facts with declared scope and type
        return Facts(**{
            key: self._build_entry(key, value)
            for key, value in values.items()
        })

    def to_dict(self, prefix: str = "") -> dict[str, Scope]:
        """Flatten for static validation (fully-qualified key -> scope)."""
        ...
```

### Base Action (slater/actions.py)

```python
class SlaterAction(Action):
    # Emission declaration - subclasses override with their EmissionSpec
    emits: EmissionSpec | None = None

    def instruction(self) -> Facts:
        # Subclasses use: return self.emits.build(...)
        raise NotImplementedError
```

### Validation (slater/validation.py)

```python
def validate_fact_scopes(
    procedures: Mapping[Enum, ProcedureTemplate],
    transition_policy: TransitionPolicy,
    control_policy: ControlPolicy,
) -> list[FactScopeIssue]:
    """Cross-reference policy requirements with action emissions."""

    # Collect emissions from EmissionSpec.to_dict()
    for action in all_actions:
        if hasattr(action, 'emits') and action.emits is not None:
            if isinstance(action.emits, EmissionSpec):
                emits_dict = action.emits.to_dict()
            # ... validate against policies
```

## Answers to Proposal 002 Open Questions

1. **Should `emits` be enforced?** → Yes. `build()` raises on undeclared emissions.

2. **How to handle conditional emissions?** → Use `required=False` for outcome-dependent facts.

3. **Should we validate `reads` declarations?** → Eventually. EmissionSpec focuses on emissions; `reads` validation could be the separate concern of IngestSpec. Having both allows complete dataflow declaration. That would unlock _a priori_ Action ordering, reachability analysis, concurrency, etc.

4. **What about dynamically constructed keys?** → Not supported. Dynamic keys should be rare; if needed, use a wrapper fact with a dict value.

## Related

- Proposal 002: Fact Scope Validator (this ADR implements it)
- ADR-002: Eager Fact Application Within Iterations
- `EmissionSpec` class in `slater/types.py`
- `validate_fact_scopes()` in `slater/validation.py`
- Issue 001, 002, 003: Scope-related bugs that motivated this work
