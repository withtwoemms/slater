# Proposal 001: Pausing Slater Agents for User Input

**Status:** Draft
**Created:** 2026-01-20
**Authors:** slater contributors

## Overview

This document proposes, demonstrates, and explains how **Slater agents pause to receive user input** in a principled, durable, and inspectable way.

The core idea is simple but powerful:

> **A Slater agent pauses not by blocking execution, but by becoming ineligible to proceed until required Facts are present.**

User input is treated as *data*, not *control flow*, and is mediated by a runtime that is explicitly separate from the agent itself.

This design enables:
- long-lived, resumable agents
- human-in-the-loop workflows
- deterministic replay and inspection
- multiple runtime implementations (CLI, REST, event-driven, etc.)

An addendum will later specify a concrete REST API runtime.

---

## Motivation

Traditional agent systems typically handle user input by:
- blocking on synchronous I/O
- embedding prompts in text output
- tightly coupling UI logic to reasoning logic

These approaches make it difficult to:
- pause for long periods
- resume across restarts
- audit why input was requested
- reason about agent correctness

Slater instead treats user input as **explicit state** governed by policy.

---

## Core Concepts

### Facts

Facts are the sole control surface for Slater agents.

They represent:
- knowledge
- progress signals
- user input
- uncertainty

Facts are persisted in state and evaluated by policy.

---

### Scope Definitions

Slater defines three Fact scopes, each with precise semantics.

#### Iteration Scope

Facts scoped to a *single attempt to advance the agent*.

- Created during one controller advancement
- Cleared before the next advancement attempt
- Ephemeral and non-durable

Used for transient progress signals only.

Example:
```python
ProgressFact("analysis_complete", scope="iteration")
```

---

#### Session Scope

Facts scoped to a **single task execution** of an agent.

- Persist across controller invocations
- Survive process restarts
- Cleared only when the task reaches a terminal Phase

Session-scoped Facts explain *why the agent is paused or progressing*.

Example:
```python
UserPrompt("issue_category", scope="session")
KnowledgeFact("issue_category", value="performance", scope="session")
```

---

#### Persistent Scope

Facts scoped to the **agent instance itself**, independent of any task.

- Persist across tasks
- Cleared only explicitly
- Used for configuration and long-term knowledge

Example:
```python
KnowledgeFact("repo_root", scope="persistent")
```

---

## Session ID (First-Class Concept)

A **session** represents a single execution of an AgentSpec toward a terminal Phase.

Crucially:

> **A session is a semantic construct, not a runtime construct.**

It is independent of:
- controller invocations
- processes
- threads
- user interaction windows

### Session Identity

Each session is identified by a stable `session_id`.

The minimal identity model is:

```text
(agent_id, session_id)
```

Where:
- `agent_id` identifies the AgentSpec / agent instance
- `session_id` identifies a single task execution

---

### Why `session_id` Is Required

Introducing `session_id` enables:

- Durable pause/resume across restarts
- Multiple concurrent tasks per agent
- Precise attribution of user input
- Runtime inspection of paused vs active sessions

Without an explicit session identifier, pausing semantics become ambiguous and unsafe.

---

### Session Lifecycle

1. Runtime creates a new `session_id` when starting a task
2. Session-scoped Facts are written under that identifier
3. Controller operates on `(agent_id, session_id)`
4. Session ends only when a terminal Phase is reached
5. Session-scoped Facts are cleared or archived

---

## UserPrompt Fact

A **UserPrompt** is a structured Fact emitted by an Action (often backed by an LLM) to solicit clarification or input.

Example:

```python
UserPrompt(
    key="issue_category",
    message="Is this issue about performance or correctness?",
    scope="session",
)
```

Key properties:
- persisted beyond a single run
- inspectable by the runtime
- non-blocking
- decoupled from UI concerns

A UserPrompt does *not* pause the agent by itself.

---

## ControlPolicy and Pausing

Pausing is enforced by **ControlPolicy**, not by Actions or the runtime.

Example:

```python
ControlPolicy(
    user_required_keys={"issue_category"},
)
```

If required user keys are missing:
- the agent is ineligible to proceed
- no Procedures are run
- the controller exits cleanly

This makes pausing deterministic and enforceable.

---

## Execution Model

### Normal Progression

1. AgentController loads state for `(agent_id, session_id)`
2. Policies are evaluated
3. A Procedure is selected
4. Actions run and emit Facts
5. State is persisted

---

### Pausing for User Input

1. An Action emits a UserPrompt
2. Required user Fact is still missing
3. ControlPolicy forbids progression
4. AgentController exits
5. Session state (including prompts) is persisted

At this point:
- the agent is *paused*
- no threads are blocked
- the process may exit safely

---

### Resumption

Resumption occurs when new Facts are added to a session.

Example user input:

```python
KnowledgeFact(
    key="issue_category",
    value="performance",
    scope="session",
)
```

On the next controller invocation:
- required keys are now present
- policy allows progression
- the agent resumes naturally

No special resume logic is required.

---

## InputAdapter Abstraction

The **InputAdapter** is responsible for:
- collecting user input
- translating it into Facts
- persisting those Facts under a `session_id`

It does *not*:
- control agent flow
- decide when to run the agent
- embed business logic

Example interface:

```python
class InputAdapter(Protocol):
    def submit(self, agent_id: str, session_id: str, fact: Fact) -> None:
        ...
```

---

## The Runtime (Critical Separation)

Slater intentionally separates:
- **agent behavior** from
- **runtime orchestration**

The runtime is responsible for:
- creating sessions
- invoking the AgentController
- persisting session state
- accepting external input
- deciding *when* to attempt progression

The agent:
- never blocks
- never waits
- never polls
- never assumes a specific runtime

---

## Example Walkthrough: Issue Triage

1. Runtime creates a new session
2. Agent analyzes an issue
3. LLM determines category is unclear
4. Emits UserPrompt("issue_category")
5. ControlPolicy blocks progression
6. Controller exits
7. Runtime surfaces prompt to user
8. User submits input tied to session_id
9. Controller resumes agent

---

## Design Invariants

1. Every session has a stable identifier
2. Session-scoped Facts persist across runs
3. UserPrompts always live in session scope
4. Agents pause by policy, not by blocking
5. Runtimes remain interchangeable

---

## Non-Goals

This design does *not* attempt to:
- define a single runtime
- mandate a UI
- embed auth or tenancy
- optimize for chat-style agents

---

## Conclusion

By introducing session-scoped Facts and a first-class `session_id`, Slater enables durable, inspectable, and safe human-in-the-loop agents.

The separation between agent and runtime is foundational: it allows agents to pause, resume, and explain themselves without entangling execution with infrastructure.

---

## Next: Runtime API Addendum

A subsequent addendum will specify a concrete REST API runtime that:
- manages sessions
- accepts user input
- persists agent state
- invokes the AgentController
- exposes inspection endpoints

This addendum will build directly on the abstractions defined here.
