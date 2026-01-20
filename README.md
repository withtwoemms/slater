# slater

A Fact-governed agent framework for building deterministic and auditable autonomous systems.

## Overview

Slater is a Python framework for building **state-driven AI agents** whose behavior is:

- **Deterministic** — Given the same facts, agents always make the same transitions
- **Inspectable** — Every decision is traceable to explicit rules and facts
- **Replayable** — Complete iteration history enables post-run debugging
- **Explainable** — Agent behavior is specified declaratively before execution

Instead of writing imperative loops that decide "what to do next," you **describe the structure of an agent** via an `AgentSpec`, and Slater executes that structure safely.

## Features

### Declarative Agent Specification

Bundle your agent's complete behavior into a single, validated `AgentSpec`:

```python
from slater.phases import PhaseEnum, PhaseRule
from slater.policies import ControlPolicy, TransitionPolicy
from slater.procedures import ProcedureTemplate
from slater.spec import AgentSpec

Phase = PhaseEnum.create("START", "PROCESSING", "DONE")

spec = AgentSpec(
    name="my-agent",
    version="1.0.0",
    phases=set(Phase),
    control_policy=ControlPolicy(...),
    transition_policy=TransitionPolicy(rules=[...], default=Phase.START),
    procedures={Phase.START: ProcedureTemplate(...), ...},
)
```

### Dynamic Phase Enums

Define agent-specific phases with validation:

```python
from slater.phases import PhaseEnum

# Names must be UPPER_SNAKE_CASE, no reserved words
Phase = PhaseEnum.create(
    "NEEDS_CONTEXT",
    "READY_TO_CONTINUE",
    "TASK_COMPLETE",
)
```

### Fact-Based State Management

Facts are typed, scoped, and flow through the system with clear semantics:

| Scope | Visibility | Persistence |
|-------|------------|-------------|
| `iteration` | Current iteration only | Not persisted |
| `session` | All iterations | Agent lifetime |
| `persistent` | All iterations | Across restarts |

### FSM Safety

- **Cycle detection** — Agents fail fast if stuck in the same phase
- **Rule validation** — Overlapping PhaseRules caught at construction time
- **Deterministic transitions** — Phase changes derived only from durable facts

### Complete Audit Trail

Two-file persistence pattern:
- `{agent_id}.json` — Current state snapshot
- `{agent_id}_history.jsonl` — Append-only iteration log

## Core Concepts

| Concept | Purpose |
|---------|---------|
| **Phase** | Where the agent is in its lifecycle |
| **Fact** | A typed piece of knowledge emitted by Actions |
| **Action** | A unit of work that reads state and emits Facts |
| **Procedure** | A sequence of Actions executed for a Phase |
| **PhaseRule** | Declares when to transition between Phases |
| **ControlPolicy** | Global constraints (completion, failure, pause) |
| **TransitionPolicy** | Rules for FSM progression |
| **AgentSpec** | The complete, validated agent definition |

## Local Development

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (installed automatically by Makefile)

### Setup

```bash
# Create virtual environment and install dependencies
make venv

# Activate the environment
source .venv/bin/activate
```

### Running Tests

```bash
# Run all tests
make tests

# Run unit tests only
make unit-tests

# Run integration tests only
make integration-tests
```

### Other Commands

```bash
# Show available commands
make help

# Export dependencies to requirements.txt
make requirements

# Clean build artifacts
make clean
```

### Project Structure

```
slater/
├── slater/              # Main package
│   ├── __main__.py      # CLI entrypoint
│   ├── controller.py    # AgentController (execution engine)
│   ├── phases.py        # PhaseEnum factory, PhaseRule
│   ├── policies.py      # ControlPolicy, TransitionPolicy
│   ├── procedures.py    # ProcedureTemplate
│   ├── spec.py          # AgentSpec (declarative specification)
│   ├── state.py         # StateStore implementations
│   └── types.py         # Fact, Facts, core types
├── tests/
│   ├── unit/            # Unit tests
│   └── integration/     # Integration tests
├── docs/                # Documentation
│   ├── adr/             # Architecture Decision Records
│   └── user-guide.md
├── pyproject.toml
├── Makefile
└── README.md
```

## Documentation

- [User Guide](docs/user-guide.md) — Comprehensive guide to designing agents
- [ADR-001: Dynamic Phase Enums](docs/adr/001-dynamic-phase-enums.md) — PhaseEnum design rationale

## License

MIT
