# Issue 003: Agent Stuck in PROCEDURE_SUCCEEDED Phase

**Status:** Open
**Severity:** High
**Discovered:** 2026-01-20
**Affects:** `slater/actions.py` (ApplyPatch, Validate), `slater/__main__.py` (TransitionPolicy)

## Summary

After fixing Issues 001 and 002, the agent successfully transitions to `PROCEDURE_SUCCEEDED` but becomes stuck there, repeatedly executing `ApplyPatch` and `Validate`. This is caused by two compounding problems:

1. **Scope bug**: Facts emitted by `ApplyPatch` and `Validate` use iteration scope
2. **FSM design gap**: No transition rule exists to move from `PROCEDURE_SUCCEEDED` to `TASK_COMPLETE`

## Observed Behavior

```
Iteration 1: phase=NEEDS_CONTEXT, actions=['GatherContext', 'AnalyzeRepo']
Iteration 2: phase=READY_TO_CONTINUE, actions=['ProposePlan']
Iteration 3: phase=PROCEDURE_SUCCEEDED, actions=['ApplyPatch', 'Validate']
Iteration 4: phase=PROCEDURE_SUCCEEDED, actions=['ApplyPatch', 'Validate']  ← stuck
```

Facts emitted but not persisted:

```
ApplyPatch.patch_applied: scope=iteration
ApplyPatch.patch_summary: scope=iteration
Validate.validation_passed: scope=iteration
```

## Root Cause

### Problem 1: Iteration-Scoped Facts

Both `ApplyPatch` and `Validate` emit facts with the default `iteration` scope:

```python
# slater/actions.py - ApplyPatch.instruction()
return Facts(
    patch_applied=ProgressFact(key="patch_applied", value=True),  # iteration scope
    patch_summary=KnowledgeFact(key="patch_summary", value=...),  # iteration scope
)

# slater/actions.py - Validate.instruction()
return Facts(
    validation_passed=ProgressFact(key="validation_passed", value=True),  # iteration scope
)
```

### Problem 2: Missing Transition Rule

The transition policy has no rule to exit `PROCEDURE_SUCCEEDED`:

```python
# Current rules in slater/__main__.py
PhaseRule(enter=Phase.PROCEDURE_SUCCEEDED, when_all=frozenset({"plan_ready"}))
PhaseRule(enter=Phase.TASK_COMPLETE, when_all=frozenset({"task_complete"}))
```

The only path to `TASK_COMPLETE` requires `task_complete`, which is emitted by `Finalize`—but `Finalize` only runs in the `TASK_COMPLETE` phase. This is a **chicken-and-egg problem**.

### Combined Effect

1. `PROCEDURE_SUCCEEDED` runs `ApplyPatch` + `Validate`
2. `validation_passed` emitted but discarded (iteration scope)
3. No transition rule matches based on durable facts
4. `plan_ready` still present → `PROCEDURE_SUCCEEDED` rule matches again
5. Infinite loop

## Proposed Fix

### Fix 1: Update Fact Scopes

```python
# ApplyPatch.instruction()
return Facts(
    patch_applied=ProgressFact(key="patch_applied", value=True, scope="session"),
    patch_summary=KnowledgeFact(key="patch_summary", value=..., scope="session"),
)

# Validate.instruction()
return Facts(
    validation_passed=ProgressFact(key="validation_passed", value=True, scope="session"),
)
```

### Fix 2: Add Transition Rule

```python
# In TransitionPolicy rules
PhaseRule(
    enter=Phase.TASK_COMPLETE,
    when_all=frozenset({"validation_passed"}),
)
```

This allows the FSM to progress: `validation_passed` (durable) → `TASK_COMPLETE` → `Finalize` → `task_complete` → completion.

## Pattern Recognition

This is the **third instance** of the iteration-scope bug:

| Issue | Action | Fact | Impact |
|-------|--------|------|--------|
| 001 | ProposePlan | `plan_ready` | Infinite loop in READY_TO_CONTINUE |
| 002 | ProposePlan | `plan` | KeyError in ApplyPatch |
| 003 | ApplyPatch | `patch_applied`, `patch_summary` | Stuck in PROCEDURE_SUCCEEDED |
| 003 | Validate | `validation_passed` | Stuck in PROCEDURE_SUCCEEDED |

**Recommendation**: Audit all actions for appropriate fact scopes. Consider changing the default scope for `ProgressFact` and `KnowledgeFact` to `"session"`.

## Affected Files

| File | Change Needed |
|------|---------------|
| `slater/actions.py` | Update scopes in `ApplyPatch` and `Validate` |
| `slater/__main__.py` | Add transition rule for `validation_passed` → `TASK_COMPLETE` |

## Related

- Issue 001: `plan_ready` Fact Scope Causes Infinite Loop
- Issue 002: `plan` Fact Scope Causes KeyError
- ADR-002: Eager Fact Application Within Iterations
