import json
import time
from pathlib import Path
from typing import Any, Protocol

from slater.config import BootstrapConfig
from slater.types import Fact, Facts, IterationFacts, KnowledgeFact


class StateStore(Protocol):
    def save(self, agent_id: str, iteration_facts: IterationFacts, persistent_facts: Facts) -> None: ...
    def load(self, agent_id: str) -> Facts: ...
    def bootstrap(self, agent_id: str, config: BootstrapConfig) -> None:
        """
        Seed initial state from bootstrap config.
        Called once before the first iteration.
        """
        pass


class IterationState:
    """
    Mutable, iteration-local working state.

    - Holds Facts (with scope)
    - Applies Facts eagerly during iteration
    - Evicts iteration-scoped Facts on iteration boundary
    - Projects to plain dict only for read access
    """
    def __init__(self, base_facts: "Facts"):
        # Persistent/session facts carried forward
        self._persistent: dict[str, Fact] = {
            fq_key: fact for fq_key, fact in base_facts.iter_facts() if fact.scope != "iteration"
        }

        # Iteration-scoped facts (cleared each iteration)
        self._iteration: dict[str, Fact] = {}

    # ---- iteration lifecycle ----

    def begin_iteration(self) -> None:
        """
        Evict all iteration-scoped facts.
        Must be called exactly once per iteration.
        """
        self._iteration.clear()

    # ---- update from Facts ----

    def apply_facts(self, facts: "Facts") -> None:
        for fq_key, fact in facts.iter_facts():
            if fact.scope == "iteration":
                self._iteration[fq_key] = fact
            else:
                self._persistent[fq_key] = fact

    # ---- dict-like projection (read-only) ----

    def __getitem__(self, key: str):
        if key in self._iteration:
            return self._iteration[key].value
        return self._persistent[key].value

    def get(self, key: str, default=None):
        if key in self._iteration:
            return self._iteration[key].value
        return self._persistent.get(key, Fact(key, default)).value

    def __contains__(self, key: str) -> bool:
        return key in self._iteration or key in self._persistent

    # ---- snapshots ----

    def snapshot(self) -> dict[str, Any]:
        """
        Value-only projection for debugging / policy checks.
        """
        data = {k: f.value for k, f in self._persistent.items()}
        data.update({k: f.value for k, f in self._iteration.items()})
        return data

    # ---- persistence boundary ----

    def persistent_facts(self) -> "Facts":
        """
        Facts eligible for persistence at iteration end.
        """
        return Facts.unflatten(self._persistent)


BOOTSTRAP_PHASE = "__bootstrap__"

class InMemoryStateStore:
    def __init__(self):
        # agent_id -> persistent Facts
        self._persistent: dict[str, Facts] = {}

        # agent_id -> list of IterationFacts (history)
        self._history: dict[str, list[IterationFacts]] = {}

    # ---- lifecycle ----

    def bootstrap(self, agent_id: str, config: BootstrapConfig) -> None:
        """
        Seed initial persistent facts from bootstrap config.
        """
        facts = {}

        if config.goal is not None:
            facts["goal"] = KnowledgeFact(
                key="goal",
                value=config.goal,
                scope="session",
            )

        # ---- repository context ----
        if config.repo is not None:
            facts["repo_root"] = KnowledgeFact(
                key="repo_root",
                value=str(config.repo.root),
                scope="session",
            )

            if config.repo.ignore:
                facts["repo_ignore"] = KnowledgeFact(
                    key="repo_ignore",
                    value=list(config.repo.ignore),
                    scope="session",
                )    

        self._persistent[agent_id] = Facts(**facts)
        self._history[agent_id] = []

    # ---- persistence ----
    def save(self, agent_id: str, iteration_facts: IterationFacts, persistent_facts: Facts) -> None:
        """
        Persist IterationFacts and update persistent Facts.
        """
        # Record iteration history
        self._history.setdefault(agent_id, []).append(iteration_facts)

        # Store persistent facts directly (already computed by controller)
        self._persistent[agent_id] = persistent_facts

    # ---- loading ----

    def load(self, agent_id: str) -> Facts:
        """
        Return persistent Facts projection.
        """
        return self._persistent.get(agent_id, Facts())

    # ---- introspection helpers (tests / UI) ----

    def history(self, agent_id: str) -> list[IterationFacts]:
        return list(self._history.get(agent_id, []))


class FileSystemStateStore:
    def __init__(self, root: Path | str = ".slater_state"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> Path:
        return self.root / f"{agent_id}.json"

    def load(self, agent_id: str) -> Facts:
        path = self._path(agent_id)
        if not path.exists():
            return Facts()
        return Facts.deserialize(json.loads(path.read_text()))

    def save(self, agent_id: str, iteration_facts: IterationFacts, persistent_facts: Facts) -> None:
        # Save current persistent state (snapshot)
        state_path = self._path(agent_id)
        tmp = state_path.with_suffix(".tmp")
        json.dump(
            persistent_facts.serialize(),
            tmp.open("w"),
            indent=2,
            sort_keys=True,
        )
        tmp.replace(state_path)

        # Append iteration history (audit trail)
        history_path = self._history_path(agent_id)
        with history_path.open("a") as f:
            f.write(json.dumps({
                "iteration": iteration_facts.iteration,
                "phase": iteration_facts.phase.name if iteration_facts.phase else None,
                "timestamp": time.time(),
                "facts_by_action": {
                    action: facts.serialize()
                    for action, facts in iteration_facts.by_action.items()
                }
            }) + "\n")

    def _history_path(self, agent_id: str) -> Path:
        return self.root / f"{agent_id}_history.jsonl"

    def history(self, agent_id: str) -> list[dict]:
        """
        Load iteration history for post-run analysis.

        Returns list of iteration records, each containing:
        - iteration: int
        - phase: str | None
        - timestamp: float
        - facts_by_action: Dict[str, Dict[str, dict]]
        """
        history_path = self._history_path(agent_id)
        if not history_path.exists():
            return []

        records = []
        with history_path.open("r") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def bootstrap(self, agent_id: str, config: BootstrapConfig) -> None:
        """
        Seed initial durable state from bootstrap config.
        Called once before the first iteration.
        """
        path = self._path(agent_id)

        # idempotent bootstrap: if state exists, do nothing
        if path.exists():
            return

        # Translate config -> Facts (gracefully handle partial config)
        seed_facts = {}

        if config.goal is not None:
            seed_facts["goal"] = KnowledgeFact(
                key="goal",
                value=config.goal,
                scope="session",
            )

        if config.repo is not None:
            seed_facts["repo_root"] = KnowledgeFact(
                key="repo_root",
                value=str(config.repo.root),
                scope="session",
            )

            if config.repo.ignore:
                seed_facts["repo_ignore"] = KnowledgeFact(
                    key="repo_ignore",
                    value=list(config.repo.ignore),
                    scope="session",
                )

        seed = Facts(**seed_facts)

        tmp = path.with_suffix(".tmp")
        json.dump(
            seed.serialize(),
            tmp.open("w"),
            indent=2,
            sort_keys=True,
        )
        tmp.replace(path)
