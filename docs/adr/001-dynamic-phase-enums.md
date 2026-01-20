# ADR-001: Dynamic Phase Enums via PhaseEnum Factory

**Status:** Accepted
**Date:** 2026-01-12
**Authors:** slater contributors

## Context

Slater agents are finite state machines (FSMs) where **Phases** represent discrete states. The original implementation used a single, hardcoded `Phase` enum defined in `slater/phases.py`:

```python
class Phase(Enum):
    PROCEDURE_SUCCEEDED = auto()
    PROCEDURE_FAILED = auto()
    NEEDS_CONTEXT = auto()
    NEEDS_USER_INPUT = auto()
    READY_TO_CONTINUE = auto()
    TASK_COMPLETE = auto()
    TERMINAL_FAILURE = auto()
```

This design had several limitations:

1. **Inflexibility**: All agents shared the same phase vocabulary, even when their FSMs had different structures
2. **Coupling**: Adding a new phase for one agent required modifying shared code
3. **Validation gap**: No enforcement of phase naming conventions (UPPER_SNAKE_CASE)
4. **AgentSpec impedance**: The `AgentSpec` abstraction bundles an agent's complete definition, but phases were globally defined rather than spec-scoped

## Decision

Introduce a `PhaseEnum` factory class that creates agent-specific Phase enums at runtime:

```python
class PhaseEnum:
    @classmethod
    def create(cls, *names: str, class_name: str = "Phase") -> Type[Enum]:
        cls._validate(names)
        return Enum(class_name, {name: auto() for name in names})
```

### Key design choices:

1. **Validation at creation time**: Phase names must be UPPER_SNAKE_CASE, unique, and not reserved words (NONE, ANY, ALL, DEFAULT, etc.)

2. **Multiple creation patterns**:
   - `PhaseEnum.create("START", "DONE")` - varargs for inline definition
   - `PhaseEnum.from_list(["START", "DONE"])` - for YAML/JSON loading
   - `PhaseEnum.from_set({"START", "DONE"})` - alphabetically sorted for determinism

3. **Type system updates**: All phase-typed fields changed from `Phase` to `Enum`:
   - `PhaseRule.enter: Enum`
   - `TransitionPolicy.default: Enum`
   - `AgentSpec.phases: Set[Enum]`
   - `AgentSpec.procedures: Dict[Enum, ProcedureTemplate]`
   - `IterationFacts.phase: Enum`

4. **No hardcoded terminal phases**: `AgentController` no longer references `Phase.TASK_COMPLETE` or `Phase.TERMINAL_FAILURE` directly. Completion/failure detection relies solely on `ControlPolicy.completion_keys` and `ControlPolicy.failure_keys`.

## Consequences

### Positive

- **Per-agent phase vocabularies**: Each `AgentSpec` defines exactly the phases it needs
- **Declarative validation**: Invalid phase names are caught at spec construction, not runtime
- **YAML-friendly**: Phases can be loaded from configuration files
- **Cleaner AgentSpec**: Phases are now part of the spec, not a global dependency

### Negative

- **Type hints are less specific**: `Enum` is broader than a specific `Phase` type; static analyzers lose some precision
- **Migration burden**: Existing code using the legacy `Phase` enum must be updated
- **Runtime enum creation**: Phases are created at import/construction time rather than being statically defined

### Neutral

- **Legacy Phase preserved**: The original `Phase` enum remains (marked for deletion) to support incremental migration
- **Test compatibility**: Tests can continue using the legacy `Phase` or create their own via `PhaseEnum`

## Example Usage

```python
# In __main__.py or agent definition module
from slater.phases import PhaseEnum, PhaseRule
from slater.spec import AgentSpec

# Define agent-specific phases
Phase = PhaseEnum.create(
    "NEEDS_CONTEXT",
    "READY_TO_CONTINUE",
    "PROCEDURE_SUCCEEDED",
    "PROCEDURE_FAILED",
    "TASK_COMPLETE",
    class_name="Phase",
)

# Use in policies and procedures
transition_policy = TransitionPolicy(
    rules=[
        PhaseRule(enter=Phase.NEEDS_CONTEXT, when_all=frozenset({"context_required"})),
        PhaseRule(enter=Phase.TASK_COMPLETE, when_all=frozenset({"task_complete"})),
    ],
    default=Phase.NEEDS_CONTEXT,
)

# Bundle into AgentSpec
spec = AgentSpec(
    name="my-agent",
    version="1.0.0",
    phases=set(Phase),
    control_policy=control_policy,
    transition_policy=transition_policy,
    procedures=procedures,
)
```

## Files Changed

| File | Change |
|------|--------|
| `slater/phases.py` | Added `PhaseEnum` factory; marked legacy `Phase` for deletion |
| `slater/policies.py` | `TransitionPolicy.default` type changed to `Enum` |
| `slater/spec.py` | Types updated to `Set[Enum]`, `Dict[Enum, ...]`; added same-enum validation |
| `slater/controller.py` | Removed hardcoded `Phase` references; type hints use `Enum` |
| `slater/types.py` | `IterationFacts.phase` type changed to `Enum` |
| `slater/__main__.py` | Uses `PhaseEnum.create()` and `AgentSpec` |

## Related

- `AgentSpec` declarative specification pattern
- Category 4 (FSM Safety) from refactoring roadmap
