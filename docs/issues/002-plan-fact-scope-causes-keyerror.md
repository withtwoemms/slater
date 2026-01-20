# Issue 002: `plan` Fact Scope Causes KeyError in PROCEDURE_SUCCEEDED

**Status:** Open
**Severity:** High
**Discovered:** 2026-01-20
**Affects:** `slater/actions.py` (ProposePlan)
**Related:** Issue 001

## Summary

The `ProposePlan` action emits `plan` with the default `iteration` scope. When the agent transitions to `PROCEDURE_SUCCEEDED`, the `ApplyPatch` action attempts to read `state["plan"]`, which no longer exists because iteration-scoped facts are not persisted. This causes a `KeyError` and crashes the agent.

## Observed Behavior

```
Iteration 1: phase=NEEDS_CONTEXT, actions=['GatherContext', 'AnalyzeRepo']
Iteration 2: phase=READY_TO_CONTINUE, actions=['ProposePlan']
[agent exits - no iteration 3 recorded]
```

History shows `plan` emitted but not persisted:

```json
{
  "key": "plan",
  "value": { "summary": "...", "steps": [...] },
  "scope": "iteration"
}
```

Persistent state after run:

```json
["analysis_ready", "context_ready", "goal", "plan_ready", "repo_ignore", "repo_root"]
```

Note: `plan_ready` present (fixed in Issue 001), but `plan` is missing.

## Root Cause

### 1. Fact emission with default scope

```python
# slater/actions.py:148-151
return Facts(
    plan=KnowledgeFact(key="plan", value=plan),  # ← scope="iteration" (default)
    plan_ready=ProgressFact(key="plan_ready", value=True, scope="session"),
)
```

After the fix for Issue 001, `plan_ready` has session scope, but `plan` still uses the default iteration scope.

### 2. Downstream action depends on persisted plan

```python
# slater/actions.py:323 (ApplyPatch.instruction)
plan = state["plan"]  # ← KeyError: plan not in durable state
```

### 3. Failure sequence

1. Iteration 2 ends: `plan_ready` persisted, `plan` discarded
2. Transition policy: `plan_ready` present → enter `PROCEDURE_SUCCEEDED`
3. Iteration 3 begins: `ApplyPatch.instruction()` called
4. `state["plan"]` raises `KeyError`
5. Agent crashes without recording iteration 3

## Proposed Fix

Change the scope of `plan` to `"session"`:

```python
# slater/actions.py
return Facts(
    plan=KnowledgeFact(key="plan", value=plan, scope="session"),
    plan_ready=ProgressFact(key="plan_ready", value=True, scope="session"),
)
```

## Design Consideration

This is the second instance of the same bug pattern (see Issue 001). The underlying issue is that:

1. `Fact` defaults to `scope="iteration"`
2. Transition rules and downstream actions often expect facts to persist
3. No validation warns when emitted facts won't survive to be consumed

### Potential Mitigations

| Approach | Description |
|----------|-------------|
| **Change default scope** | Make `KnowledgeFact` default to `"session"` since knowledge typically needs to persist |
| **Static analysis** | Lint rule: warn if action reads a key that's only emitted with iteration scope |
| **Runtime check** | `IterationState.get()` could warn when reading a key that was iteration-scoped in a prior iteration |
| **Explicit scopes** | Require all fact emissions to explicitly specify scope (no defaults) |

## Affected Files

| File | Line | Issue |
|------|------|-------|
| `slater/actions.py` | 149 | `plan` uses default `iteration` scope |

## Related

- Issue 001: `plan_ready` Fact Scope Causes Infinite Loop
- ADR-002: Eager Fact Application Within Iterations
- `slater/types.py`: Fact scope definitions
