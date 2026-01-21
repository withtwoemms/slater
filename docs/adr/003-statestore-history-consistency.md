# ADR-003: StateStore.history() Returns Consistent Types

**Status:** Accepted
**Date:** 2026-01-20
**Authors:** slater contributors

## Context

Slater provides two `StateStore` implementations:

- **InMemoryStateStore**: For testing and development
- **FileSystemStateStore**: For production persistence

Both implementations had a `history()` method for retrieving iteration records, but they returned different types:

```python
# InMemoryStateStore
def history(self, agent_id: str) -> list[IterationFacts]:
    return list(self._history.get(agent_id, []))

# FileSystemStateStore
def history(self, agent_id: str) -> list[dict]:
    # Returns raw JSON dicts with keys: iteration, phase, timestamp, facts_by_action
    ...
```

This inconsistency violated the Protocol's interchangeability promise. Code written against one store would fail with the other:

```python
# Works with InMemoryStateStore
history[0].iteration
history[0].phase
history[0].by_action

# Works with FileSystemStateStore
history[0]["iteration"]
history[0]["phase"]
history[0]["facts_by_action"]  # Note: different key name!
```

Additionally, `InMemoryStateStore` did not capture timestamps, while `FileSystemStateStore` did—another inconsistency.

## Decision

Standardize both implementations to return `list[IterationFacts]` from `history()`.

### Changes Made

1. **Added `timestamp` field to `IterationFacts`**:
   ```python
   @dataclass(frozen=True)
   class IterationFacts:
       iteration: int = 0
       phase: Union[Enum, str, None] = None
       by_action: Mapping[str, Facts] = field(default_factory=dict)
       timestamp: Optional[float] = None  # NEW
   ```

2. **Relaxed `phase` type to accept strings**:
   ```python
   phase: Union[Enum, str, None] = None
   ```
   This accommodates deserialization from storage where the original enum class is unavailable.

3. **Added serialization methods to `IterationFacts`**:
   ```python
   def serialize(self) -> dict:
       """Serialize to JSON-safe dict for storage."""
       ...

   @classmethod
   def deserialize(cls, data: dict) -> "IterationFacts":
       """Reconstitute from serialized form."""
       ...
   ```

4. **Added `history()` to `StateStore` protocol**:
   ```python
   class StateStore(Protocol):
       def save(...) -> None: ...
       def load(...) -> Facts: ...
       def history(self, agent_id: str) -> list[IterationFacts]: ...  # NEW
       def bootstrap(...) -> None: ...
   ```

5. **Updated both implementations to capture timestamps** when saving iteration facts.

6. **Updated `FileSystemStateStore.history()`** to deserialize JSON records into `IterationFacts` objects.

## Consequences

### Positive

1. **True interchangeability**: Code written against `StateStore` works identically with both implementations.

2. **Type safety**: Consumers get `IterationFacts` objects with known attributes, not untyped dicts.

3. **Consistent timestamps**: Both stores now record when each iteration occurred.

4. **Unified access pattern**: Always use attribute access (`.iteration`, `.phase`, `.by_action`).

### Negative

1. **Phase enum is lost on deserialization**: `FileSystemStateStore.history()` returns `IterationFacts` with `phase` as a string (e.g., `"READY_TO_CONTINUE"`) rather than the original enum member. This is unavoidable without storing enum class metadata.

2. **Slight overhead**: `FileSystemStateStore.history()` now deserializes `Facts` objects instead of returning raw dicts. For large histories, this adds memory/CPU cost.

### Neutral

1. **Backward incompatibility**: Tests written against the old `FileSystemStateStore.history()` dict format required updates. This was a one-time migration.

## Example Usage

```python
# Works identically for both InMemoryStateStore and FileSystemStateStore
store: StateStore = get_store()

history = store.history("my-agent")

for record in history:
    print(f"Iteration {record.iteration} at {record.timestamp}")
    print(f"  Phase: {record.phase}")  # Enum or string depending on store

    for action_name, facts in record.by_action.items():
        print(f"  {action_name}: {list(facts.keys())}")
```

## Phase Type Handling

When comparing phases from history, handle both enum and string forms:

```python
def phase_name(phase: Union[Enum, str, None]) -> str | None:
    """Extract phase name regardless of type."""
    if phase is None:
        return None
    if isinstance(phase, Enum):
        return phase.name
    return phase

# Usage
record = history[0]
if phase_name(record.phase) == "READY_TO_CONTINUE":
    ...
```

## Files Changed

| File | Change |
|------|--------|
| `slater/types.py` | Added `timestamp` field, relaxed `phase` type, added `serialize()`/`deserialize()` |
| `slater/state.py` | Added `history()` to protocol, updated both implementations |
| `tests/unit/test_state.py` | Updated tests to use attribute access, added interchangeability test |

## Related

- ADR-002: Eager Fact Application Within Iterations
- `StateStore` protocol in `slater/state.py`
- `IterationFacts` dataclass in `slater/types.py`
