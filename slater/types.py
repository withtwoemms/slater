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

# Type alias for scope literals
Scope = Literal["iteration", "session", "persistent"]


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


# ----------------------------------------------------------------------------
# EmissionSpec - Declarative emission contract for actions
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Emission:
    """
    Declaration of a single fact emission.

    Defines the scope and type of a fact that an action emits.
    Used within EmissionSpec to declare the emission contract.

    Args:
        scope: The persistence scope ("iteration", "session", "persistent")
        fact_type: The Fact subclass to use (default: Fact)
        required: If False, this emission may be omitted in build().
                  Use required=False for conditional emissions that depend
                  on action outcome (e.g., error facts only emitted on failure).
    """
    scope: Scope = "session"
    fact_type: type[Fact] = Fact
    required: bool = True


# Type for EmissionSpec entries: either a leaf Emission or nested EmissionSpec
EmissionEntry = Union[Emission, "EmissionSpec"]


class EmissionSpec:
    """
    Declarative specification of facts an action emits.

    EmissionSpec is the single source of truth for what an action produces.
    The build() method validates that actual emissions match declarations,
    eliminating drift between declared and actual behavior.

    Supports nested specs for hierarchical fact grouping (maps to DB tables):

        class AnalyzeRepo(SlaterAction):
            emits = EmissionSpec(
                repo=EmissionSpec(
                    file_count=Emission("session", KnowledgeFact),
                    languages=Emission("session", KnowledgeFact),
                ),
                analysis_ready=Emission("session", ProgressFact),
            )

            def instruction(self) -> Facts:
                return self.emits.build(
                    repo={"file_count": 42, "languages": ["python"]},
                    analysis_ready=True,
                )

    The build() method:
    - Raises if a key is passed that isn't declared
    - Raises if a required key is missing
    - Constructs Facts with correct scope and fact_type from declaration
    - Recursively builds nested Facts for nested EmissionSpecs
    """

    def __init__(self, *, required: bool = True, **emissions: EmissionEntry):
        """
        Args:
            required: If False, this entire spec group may be omitted when nested.
            **emissions: Mapping of keys to Emission or nested EmissionSpec.
        """
        self._emissions: dict[str, EmissionEntry] = emissions
        self.required = required

    def __contains__(self, key: str) -> bool:
        """Check if key exists (supports dot-notation for nested keys)."""
        if "." in key:
            parts = key.split(".", 1)
            if parts[0] in self._emissions:
                nested = self._emissions[parts[0]]
                if isinstance(nested, EmissionSpec):
                    return parts[1] in nested
            return False
        return key in self._emissions

    def __iter__(self):
        return iter(self._emissions)

    def items(self):
        """Iterate over (key, EmissionEntry) pairs (top-level only)."""
        return self._emissions.items()

    def keys(self) -> set[str]:
        """Return top-level declared emission keys."""
        return set(self._emissions.keys())

    def flat_keys(self, prefix: str = "") -> set[str]:
        """Return all keys flattened with dot-notation for nested specs."""
        result: set[str] = set()
        for key, entry in self._emissions.items():
            fq_key = f"{prefix}.{key}" if prefix else key
            if isinstance(entry, EmissionSpec):
                result.update(entry.flat_keys(prefix=fq_key))
            else:
                result.add(fq_key)
        return result

    def get(self, key: str) -> EmissionEntry | None:
        """Get emission declaration by key (supports dot-notation)."""
        if "." in key:
            parts = key.split(".", 1)
            if parts[0] in self._emissions:
                nested = self._emissions[parts[0]]
                if isinstance(nested, EmissionSpec):
                    return nested.get(parts[1])
            return None
        return self._emissions.get(key)

    def build(self, **values: Any) -> Facts:
        """
        Build Facts from values, validating against declarations.

        Args:
            **values: Key-value pairs where keys must match declared emissions.
                      For nested EmissionSpecs, pass a dict as the value.

        Returns:
            Facts object with properly typed and scoped facts

        Raises:
            ValueError: If undeclared key is passed or required key is missing
        """
        # Check for undeclared keys
        undeclared = set(values.keys()) - self.keys()
        if undeclared:
            raise ValueError(
                f"Undeclared emission keys: {undeclared}. "
                f"Declared keys are: {self.keys()}"
            )

        # Check for missing required keys
        missing = set()
        for key, entry in self._emissions.items():
            is_required = entry.required if isinstance(entry, (Emission, EmissionSpec)) else True
            if is_required and key not in values:
                missing.add(key)

        if missing:
            raise ValueError(
                f"Missing required emission keys: {missing}"
            )

        # Build Facts with correct types and scopes
        facts_kwargs = {}
        for key, value in values.items():
            entry = self._emissions[key]

            if isinstance(entry, EmissionSpec):
                # Nested spec: expect dict, recursively build
                if not isinstance(value, dict):
                    raise TypeError(
                        f"Expected dict for nested EmissionSpec '{key}', "
                        f"got {type(value).__name__}"
                    )
                nested_facts = entry.build(**value)
                facts_kwargs[key] = nested_facts
            else:
                # Leaf emission: build Fact
                fact = entry.fact_type(
                    key=key,
                    value=value,
                    scope=entry.scope,
                )
                facts_kwargs[key] = fact

        return Facts(**facts_kwargs)

    def to_dict(self, prefix: str = "") -> dict[str, Scope]:
        """
        Export as flattened dict for static validation.

        Returns dict mapping fully-qualified key -> scope.
        Nested specs are flattened with dot-notation keys.
        """
        result: dict[str, Scope] = {}
        for key, entry in self._emissions.items():
            fq_key = f"{prefix}.{key}" if prefix else key
            if isinstance(entry, EmissionSpec):
                result.update(entry.to_dict(prefix=fq_key))
            else:
                result[fq_key] = entry.scope
        return result


# ----------------------------------------------------------------------------
# IterationFacts - Provenance-preserving iteration record
# ----------------------------------------------------------------------------


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
