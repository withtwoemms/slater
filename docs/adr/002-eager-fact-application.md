# ADR-002: Eager Fact Application Within Iterations

**Status:** Accepted
**Date:** 2026-01-20
**Authors:** slater contributors

## Context

Slater agents execute **Procedures**—sequences of Actions—for each Phase. Actions emit **Facts** that represent knowledge gained during execution. A key design question emerged:

*When should Facts emitted by an Action become visible to subsequent Actions?*

Two approaches were considered:

### Option A: Batch Application (End-of-Iteration)
Actions execute, collecting Facts into a pending batch. After all Actions complete, Facts are applied atomically to state. No Action can see Facts from earlier Actions in the same iteration.

```
Iteration N:
  Action1.execute() → emits {repo_root: "/path"}  (pending)
  Action2.execute() → cannot see repo_root        (reads stale state)
  Action3.execute() → cannot see repo_root        (reads stale state)
  [all actions done]
  apply_facts({repo_root, ...})                   (batch commit)
```

### Option B: Eager Application (Immediate)
Facts are applied to `IterationState` immediately after each Action completes. Subsequent Actions see accumulated facts from all prior Actions.

```
Iteration N:
  Action1.execute() → emits {repo_root: "/path"}
  apply_facts({repo_root})                        (immediate)
  Action2.execute() → can read repo_root          (sees fresh state)
  Action3.execute() → can read repo_root + more   (sees accumulated state)
```

## Decision

**Adopt eager fact application within iterations.**

Facts emitted by an Action are immediately applied to `IterationState` before the next Action executes. This creates **sequential visibility** within a Procedure:

```python
# In AgentController.run()
for action, result in procedure.execute(should_raise=True):
    results.append((action, result))

    if result.successful and isinstance(result.value, Facts):
        iteration_state.apply_facts(result.value)  # ← Eager application
```

### Persistence Boundary

Eager application affects only the in-memory `IterationState`. Persistence to `StateStore` occurs once at iteration end, and **only durable facts** (session + persistent scope) are persisted:

```
Iteration N:
  [Action1] → emit iteration-scoped fact "temp"   → applied to _iteration dict
  [Action2] → emit session-scoped fact "data"     → applied to _persistent dict
  [Action3] → reads both "temp" and "data"
  [end of iteration]
  StateStore.save(persistent_facts)               → only "data" persisted

Iteration N+1:
  [loads state] → "data" available, "temp" gone
```

### Phase Transition Boundary

Phase transitions are derived **only from durable facts** at iteration boundaries. This ensures deterministic FSM behavior—if the agent crashes and restarts, it will derive the same phase from the same persisted facts:

```python
# After all Actions complete
durable_facts = iteration_state.persistent_facts()
durable_keys = set(durable_facts.serialize().keys())

next_phase = self.transition_policy.derive_phase(durable_keys)
```

## Consequences

### Positive

1. **Natural data flow**: Actions can build on each other's work within an iteration, enabling pipelines like:
   ```python
   Procedure([
       GatherContext(),    # emits: repo_root, file_count
       AnalyzeStructure(), # reads repo_root, emits: entry_points
       PlanChanges(),      # reads entry_points, emits: change_plan
   ])
   ```

2. **Simpler Action design**: Actions don't need to re-fetch information that a prior Action already discovered. Reduces redundant work and API calls.

3. **Explicit scope semantics**: The three-tier scope system (iteration/session/persistent) gives Procedure authors precise control over fact lifetime:
   - `iteration`: Scratch data for intra-iteration communication
   - `session`: Durable within agent run, but not across restarts
   - `persistent`: Survives agent restarts

4. **Deterministic recovery**: Since phase transitions depend only on persisted facts, an agent that crashes mid-iteration will resume from a consistent state.

### Negative

1. **Action order matters**: The same set of Actions in different orders may produce different results. This is intentional but requires Procedure authors to think sequentially.

2. **Failure short-circuits**: If Action2 fails, Action3 never executes and never sees Action1's facts. Partial progress within an iteration is lost (only prior iterations' facts persist).

3. **Testing complexity**: Testing an Action in isolation may not reveal bugs that only manifest when prior Actions have (or haven't) emitted certain facts.

### Neutral

1. **No parallelism within Procedures**: Actions execute sequentially. Parallel Action execution would require a different visibility model (explicit dependencies, barriers, etc.). This is a future consideration, not a current limitation.

## Implications for Procedure Authors

| Guideline | Rationale |
|-----------|-----------|
| **Order Actions by data dependency** | Later Actions can depend on earlier Actions' facts |
| **Use `iteration` scope for intermediates** | Avoids polluting persistent state with scratch data |
| **Idempotent Actions are safer** | If an iteration fails partway, re-running should be safe |
| **Check for required facts explicitly** | Don't assume a prior Action succeeded; check `state.get(key)` |

## Example: Context-Gathering Procedure

```python
class GatherRepoRoot(SlaterAction):
    """Discovers repository root and emits it as a session fact."""

    def instruction(self) -> Facts:
        root = find_git_root()
        return Facts(
            repo_root=KnowledgeFact(
                key="repo_root",
                value=str(root),
                scope="session",  # persists across iterations
            )
        )


class CountFiles(SlaterAction):
    """Counts files in repo. Depends on repo_root from prior Action."""
    requires_state = True

    def instruction(self) -> Facts:
        # Can read repo_root immediately—eager application
        root = self.state["repo_root"].value
        count = len(list(Path(root).rglob("*.py")))

        return Facts(
            file_count=KnowledgeFact(
                key="file_count",
                value=count,
                scope="iteration",  # only needed within this iteration
            )
        )


# Procedure definition
gather_context = ProcedureTemplate(
    name="gather-context",
    actions=[GatherRepoRoot, CountFiles],
)
```

## Alternatives Considered

### Explicit Dependency Declaration

Actions could declare which facts they require and produce:

```python
class CountFiles(SlaterAction):
    requires = {"repo_root"}
    produces = {"file_count"}
```

**Rejected because:** Adds boilerplate without clear benefit. The current model is simpler—just read what you need and fail gracefully if it's missing.

### Transactional Semantics

All Facts in an iteration could be applied atomically at the end, with rollback on failure.

**Rejected because:** Increases complexity without solving a real problem. Iteration-scoped facts are already ephemeral, and persistent facts represent committed progress.

## Related

- ADR-001: Dynamic Phase Enums
- `IterationState` class in `slater/state.py`
- `AgentController.run()` in `slater/controller.py`
- Fact scope documentation in `slater/types.py`
