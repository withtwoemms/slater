import json
from dataclasses import dataclass, field
from enum import Enum
from openai import OpenAI
from typing import (
    Any,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Literal,
    Union,
)


# Phase enum is now dynamically created per agent via PhaseEnum


@dataclass(frozen=True)
class StateFragment:
    data: dict[str, Any]
    scope: Literal["iteration", "session"] = "iteration"


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    scope: Literal["iteration", "session", "persistent"] = "iteration"

    def serialize(self) -> dict:
        # enforce JSON-serializable value
        try:
            json.dumps(self.value)
        except TypeError as e:
            raise TypeError(
                f"Fact '{self.key}' has non-JSON-serializable value: {self.value!r}"
            ) from e

        return {
            "key": self.key,
            "value": self.value,
            "scope": self.scope,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "Fact":
        return cls(
            key=data["key"],
            value=data["value"],
            scope=data["scope"],
        )


class ProgressFact(Fact): ...
class AuthorizationFact(Fact): ...
class KnowledgeFact(Fact): ...
class ArtifactFact(Fact): ...
class DiagnosticFact(Fact): ...


class FactType(Enum):
    PROGRESS = ProgressFact
    AUTHORIZATION = AuthorizationFact
    KNOWLEDGE = KnowledgeFact
    ARTIFACT = ArtifactFact
    DIAGNOSTIC = DiagnosticFact

FactsValue = Union["Fact", "Facts"]


class Facts(dict[str, FactsValue]):
    """
    A keyed collection of Facts.

    Supports nesting:
      Facts(foo=Fact(...), repo=Facts(...))

    Invariants:
    - Each mapping key must be a valid identifier-like string.
    - Leaf Facts must have fact.key == mapping key.
    - Nested Facts are allowed and represent namespaces/groups.
    """

    def __init__(self, **facts: FactsValue):
        super().__init__()

        for key, item in facts.items():
            # allow nested Facts
            if isinstance(item, Facts):
                # store nested group as-is
                self[key] = item
                continue

            # allow leaf Fact
            if not isinstance(item, Fact):
                raise TypeError(
                    f"Facts values must be Fact or Facts instances; got {type(item)} for '{key}'"
                )

            # enforce key alignment on leaf facts
            if item.key != key:
                raise ValueError(
                    f"Fact key mismatch: mapping key '{key}' != fact.key '{item.key}'"
                )

            self[key] = item

    @classmethod
    def empty(cls) -> "Facts":
        return cls()

    def iter_facts(self, prefix: str = "") -> Iterator[tuple[str, Fact]]:
        """
        Yield all leaf Facts as (fully_qualified_key, Fact).

        Example:
          Facts(repo=Facts(file_count=Fact(...))).iter_facts()
          -> ("repo.file_count", Fact(...))
        """
        for key, item in self.items():
            fq = f"{prefix}.{key}" if prefix else key
            if isinstance(item, Facts):
                yield from item.iter_facts(prefix=fq)
            else:
                # item is Fact
                yield (fq, item)

    def serialize(self) -> dict[str, dict]:
        """
        Flatten nested Facts into fully-qualified keys -> serialized Fact dicts (JSON-safe).
        """
        flat: dict[str, dict] = {}

        def walk(prefix: str, node: "Facts"):
            for key, item in node.items():
                fq_key = f"{prefix}.{key}" if prefix else key

                if isinstance(item, Facts):
                    walk(fq_key, item)
                else:
                    # item is a Fact (or subclass)
                    flat[fq_key] = item.serialize()

        walk("", self)
        return flat

    def flatten(self) -> Dict[str, Fact]:
        """
        Structure transformation: nested Facts tree -> flat dict with dot-notation keys.

        This is a pure structural operation - returns Fact objects (not serialized).
        """
        return {fq: fact for fq, fact in self.iter_facts()}

    @classmethod
    def unflatten(cls, flat: Dict[str, Fact]) -> "Facts":
        """
        Structure transformation: flat dict with dot-notation keys -> nested Facts tree.

        This is a pure structural operation - values must already be Fact objects.
        """
        root = Facts()

        for fq_key, fact in flat.items():
            parts = fq_key.split(".")
            current = root
            for part in parts[:-1]:
                if part not in current:
                    current[part] = Facts()
                current = current[part]  # type: ignore
            current[parts[-1]] = fact

        return root

    @classmethod
    def deserialize(cls, flat: Dict[str, dict]) -> "Facts":
        """
        Reconstitute Facts from serialized form (inverse of serialize).

        Composes: Fact.deserialize (type transform) + unflatten (structure transform)
        """
        return cls.unflatten({k: Fact.deserialize(v) for k, v in flat.items()})


@dataclass(frozen=True)
class IterationFacts:
    """
    Provenance-preserving record of Facts asserted in a single iteration.

    The `phase` field accepts both Enum members (in-memory) and strings
    (when deserialized from storage). This allows consistent return types
    from both InMemoryStateStore and FileSystemStateStore.
    """
    iteration: int = 0
    phase: Union[Enum, str, None] = None
    by_action: Mapping[str, Facts] = field(default_factory=dict)
    timestamp: Optional[float] = None

    def serialize(self) -> dict:
        """
        Serialize to JSON-safe dict for storage.

        Phase enum members are converted to their string names.
        """
        return {
            "iteration": self.iteration,
            "phase": self.phase.name if isinstance(self.phase, Enum) else self.phase,
            "timestamp": self.timestamp,
            "by_action": {
                action: facts.serialize()
                for action, facts in self.by_action.items()
            },
        }

    @classmethod
    def deserialize(cls, data: dict) -> "IterationFacts":
        """
        Reconstitute from serialized form.

        Note: Phase is stored as string name (enum cannot be reconstructed
        without access to the original enum class).
        """
        return cls(
            iteration=data["iteration"],
            phase=data.get("phase"),  # string or None
            timestamp=data.get("timestamp"),
            by_action={
                action: Facts.deserialize(facts_dict)
                for action, facts_dict in data.get("by_action", {}).items()
            },
        )


class LLMClient(Protocol):
    """Minimal LLM client: take messages, return model text."""
    def chat(self, *, model: str, messages: Sequence[Dict[str, str]]) -> str: ...


class OpenAIClient:
    """
    Adapter implementing Slater's LLMClient protocol
    using the OpenAI Python SDK.
    """

    def __init__(
        self,
        # *,
        api_key: str,
        default_model: str = "gpt-3.5-turbo",
        temperature: float = 0.2,
        **kwargs,
    ):
        self._client = OpenAI(api_key=api_key)
        self._default_model = default_model
        self._temperature = temperature

    def chat(
        self,
        *,
        model: str | None = None,
        messages: Sequence[Dict[str, str]],
    ) -> str:
        response = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=list(messages),
            temperature=self._temperature,
        )

        return response.choices[0].message.content
