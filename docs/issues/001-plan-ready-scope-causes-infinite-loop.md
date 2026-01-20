# Issue 001: `plan_ready` Fact Scope Causes Infinite Loop in READY_TO_CONTINUE

**Status:** Open
**Severity:** High
**Discovered:** 2026-01-20
**Affects:** `slater/actions.py` (ProposePlan)

## Summary

The `ProposePlan` action emits `plan_ready` with the default `iteration` scope, causing the agent to loop indefinitely in the `READY_TO_CONTINUE` phase. Phase transitions only consider durable facts (session + persistent), so the iteration-scoped `plan_ready` is never visible to the transition policy.

## Observed Behavior

```
Iteration 1: phase=NEEDS_CONTEXT, actions=['GatherContext', 'AnalyzeRepo']
Iteration 2: phase=READY_TO_CONTINUE, actions=['ProposePlan']
Iteration 3: phase=READY_TO_CONTINUE, actions=['ProposePlan']  ← stuck
Iteration 4: phase=READY_TO_CONTINUE, actions=['ProposePlan']  ← stuck
...
```

The agent repeatedly executes `ProposePlan` without ever transitioning to `PROCEDURE_SUCCEEDED`.

## Root Cause

### 1. Fact emission with default scope

```python
# slater/actions.py:148-151
return Facts(
    plan=KnowledgeFact(key="plan", value=plan),
    plan_ready=ProgressFact(key="plan_ready", value=True),  # ← scope="iteration" (default)
)
```

`ProgressFact` inherits from `Fact`, which defaults to `scope="iteration"`:

```python
# slater/types.py:28-31
@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    scope: Literal["iteration", "session", "persistent"] = "iteration"
```

### 2. Phase transitions use durable facts only

Per ADR-002 (Eager Fact Application), phase transitions are derived **only from durable facts** at iteration boundaries:

```python
# slater/controller.py:158-160
durable_facts = iteration_state.persistent_facts()
durable_keys = set(durable_facts.serialize().keys())
next_phase = self.transition_policy.derive_phase(durable_keys)
```

### 3. Transition rules expect `plan_ready` in durable state

```python
# slater/__main__.py:81-88
PhaseRule(
    enter=Phase.READY_TO_CONTINUE,
    when_all=frozenset({"analysis_ready", "context_ready"}),
    when_none=frozenset({"plan_ready"}),  # ← expects plan_ready to be durable
),
PhaseRule(
    enter=Phase.PROCEDURE_SUCCEEDED,
    when_all=frozenset({"plan_ready"}),   # ← never matches
),
```

### Result

1. `ProposePlan` emits `plan_ready` (iteration scope)
2. Iteration ends, `plan_ready` is discarded (not persisted)
3. Transition policy checks durable facts: `plan_ready` absent
4. `READY_TO_CONTINUE` rule matches (`when_none={"plan_ready"}` passes)
5. Agent re-enters `READY_TO_CONTINUE`, runs `ProposePlan` again
6. Infinite loop

## Proposed Fix

Change the scope of `plan_ready` to `"session"` so it persists across iterations:

```python
# slater/actions.py
return Facts(
    plan=KnowledgeFact(key="plan", value=plan, scope="session"),
    plan_ready=ProgressFact(key="plan_ready", value=True, scope="session"),
)
```

## Broader Implications

This issue reveals a **design hazard**: it's easy to emit facts with the wrong scope, causing subtle FSM bugs. Consider:

1. **Linting/validation**: Warn when transition rules reference fact keys that are only emitted with `iteration` scope
2. **Documentation**: Add guidance on choosing fact scopes to the user guide
3. **Default scope review**: Should `ProgressFact` default to `"session"` since progress typically needs to persist?

## Affected Files

| File | Line | Issue |
|------|------|-------|
| `slater/actions.py` | 150 | `plan_ready` uses default `iteration` scope |
| `slater/actions.py` | 149 | `plan` also uses default `iteration` scope (same issue) |

## Related

- ADR-002: Eager Fact Application Within Iterations
- `slater/types.py`: Fact scope definitions
- `slater/__main__.py`: Transition policy rules
