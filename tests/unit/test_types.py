import pytest

from slater.types import (
    Emission,
    EmissionSpec,
    Fact,
    Facts,
    IterationFacts,
    KnowledgeFact,
    ProgressFact,
)


# ----------------------------------------------------------------------------
# Facts.flatten() / Facts.unflatten() - Structure transformation
# ----------------------------------------------------------------------------


class TestFactsStructureTransformation:
    """Tests for flatten/unflatten (structure-only, Fact objects)."""

    def test_flatten_simple(self):
        """flatten() returns flat Dict[str, Fact] with dot-notation keys."""
        facts = Facts(
            goal=Fact(key="goal", value="test", scope="session"),
            status=Fact(key="status", value="ready", scope="persistent"),
        )

        flat = facts.flatten()

        assert isinstance(flat, dict)
        assert set(flat.keys()) == {"goal", "status"}
        assert isinstance(flat["goal"], Fact)
        assert flat["goal"].value == "test"

    def test_flatten_nested(self):
        """flatten() handles nested Facts with dot-notation keys."""
        facts = Facts(
            repo=Facts(
                root=Fact(key="root", value="/path", scope="session"),
                ignore=Fact(key="ignore", value=["*.pyc"], scope="session"),
            ),
        )

        flat = facts.flatten()

        assert set(flat.keys()) == {"repo.root", "repo.ignore"}
        assert isinstance(flat["repo.root"], Fact)
        assert flat["repo.root"].value == "/path"

    def test_unflatten_simple(self):
        """unflatten() reconstructs nested Facts from flat Dict[str, Fact]."""
        flat = {
            "goal": Fact(key="goal", value="test", scope="session"),
            "status": Fact(key="status", value="ready", scope="persistent"),
        }

        facts = Facts.unflatten(flat)

        assert "goal" in facts
        assert "status" in facts
        assert isinstance(facts["goal"], Fact)
        assert facts["goal"].value == "test"

    def test_unflatten_nested(self):
        """unflatten() reconstructs nested structure from dot-notation keys."""
        flat = {
            "repo.root": Fact(key="root", value="/path", scope="session"),
            "repo.ignore": Fact(key="ignore", value=["*.pyc"], scope="session"),
        }

        facts = Facts.unflatten(flat)

        assert "repo" in facts
        assert isinstance(facts["repo"], Facts)
        assert "root" in facts["repo"]
        assert facts["repo"]["root"].value == "/path"

    def test_flatten_unflatten_roundtrip(self):
        """flatten() and unflatten() are inverses."""
        original = Facts(
            goal=Fact(key="goal", value="test", scope="session"),
            repo=Facts(
                root=Fact(key="root", value="/path", scope="session"),
            ),
        )

        roundtrip = Facts.unflatten(original.flatten())

        assert "goal" in roundtrip
        assert roundtrip["goal"].value == "test"
        assert "repo" in roundtrip
        assert roundtrip["repo"]["root"].value == "/path"


# ----------------------------------------------------------------------------
# Facts.serialize() / Facts.deserialize() - Full transformation
# ----------------------------------------------------------------------------


class TestFactsFullTransformation:
    """Tests for serialize/deserialize (structure + type, JSON-safe)."""

    def test_serialize_returns_json_safe_dicts(self):
        """serialize() returns Dict[str, dict] with serialized Fact dicts."""
        facts = Facts(
            goal=Fact(key="goal", value="test", scope="session"),
        )

        serialized = facts.serialize()

        assert isinstance(serialized, dict)
        assert "goal" in serialized
        assert isinstance(serialized["goal"], dict)
        assert serialized["goal"] == {"key": "goal", "value": "test", "scope": "session"}

    def test_serialize_nested(self):
        """serialize() flattens nested structure with dot-notation keys."""
        facts = Facts(
            repo=Facts(
                root=Fact(key="root", value="/path", scope="session"),
            ),
        )

        serialized = facts.serialize()

        assert "repo.root" in serialized
        assert serialized["repo.root"]["value"] == "/path"

    def test_deserialize_from_json_dicts(self):
        """deserialize() reconstructs Facts from Dict[str, dict]."""
        serialized = {
            "goal": {"key": "goal", "value": "test", "scope": "session"},
            "status": {"key": "status", "value": "ready", "scope": "persistent"},
        }

        facts = Facts.deserialize(serialized)

        assert "goal" in facts
        assert isinstance(facts["goal"], Fact)
        assert facts["goal"].value == "test"
        assert facts["goal"].scope == "session"

    def test_deserialize_nested(self):
        """deserialize() reconstructs nested structure from dot-notation keys."""
        serialized = {
            "repo.root": {"key": "root", "value": "/path", "scope": "session"},
        }

        facts = Facts.deserialize(serialized)

        assert "repo" in facts
        assert isinstance(facts["repo"], Facts)
        assert facts["repo"]["root"].value == "/path"

    def test_serialize_deserialize_roundtrip(self):
        """serialize() and deserialize() are inverses."""
        original = Facts(
            goal=KnowledgeFact(key="goal", value="test goal", scope="session"),
            repo=Facts(
                root=KnowledgeFact(key="root", value="/path/to/repo", scope="session"),
                ignore=KnowledgeFact(key="ignore", value=["*.pyc", "__pycache__"], scope="session"),
            ),
        )

        roundtrip = Facts.deserialize(original.serialize())

        assert roundtrip["goal"].value == "test goal"
        assert roundtrip["repo"]["root"].value == "/path/to/repo"
        assert roundtrip["repo"]["ignore"].value == ["*.pyc", "__pycache__"]

    def test_deserialize_is_flatten_plus_fact_deserialize(self):
        """deserialize() composes Fact.deserialize + unflatten."""
        serialized = {
            "goal": {"key": "goal", "value": "test", "scope": "session"},
        }

        # Manual composition
        manual = Facts.unflatten({k: Fact.deserialize(v) for k, v in serialized.items()})

        # Using deserialize
        via_deserialize = Facts.deserialize(serialized)

        assert manual["goal"].value == via_deserialize["goal"].value
        assert manual["goal"].scope == via_deserialize["goal"].scope


# ----------------------------------------------------------------------------
# Existing tests
# ----------------------------------------------------------------------------


def test_fact_key_mismatch_raises():
    try:
        Facts(
            fact1=Fact(key="wrong_key", value=123),
        )
    except ValueError as e:
        assert str(e) == "Fact key mismatch: mapping key 'fact1' != fact.key 'wrong_key'"
    else:
        assert False, "Expected ValueError was not raised"


def test_iteration_facts_dataclass():
    iteration_facts = IterationFacts(
        iteration=1,
        by_action={
            "Action1": Facts(
                fact1=Fact(key="fact1", value=123),
            ),
            "Action2": Facts(
                fact2=Fact(key="fact2", value="abc"),
            ),
        },
    )

    assert isinstance(iteration_facts, IterationFacts)
    assert isinstance(iteration_facts.by_action, dict)
    assert iteration_facts.by_action["Action1"]["fact1"].value == 123
    assert iteration_facts.by_action["Action2"]["fact2"].value == "abc"


# ----------------------------------------------------------------------------
# EmissionSpec - Declarative emission contract
# ----------------------------------------------------------------------------


class TestEmissionSpec:
    """Tests for EmissionSpec builder pattern."""

    def test_build_creates_facts_with_correct_types(self):
        """build() creates Facts with declared fact types."""
        spec = EmissionSpec(
            plan=Emission("session", KnowledgeFact),
            ready=Emission("session", ProgressFact),
        )

        facts = spec.build(plan={"steps": []}, ready=True)

        assert isinstance(facts["plan"], KnowledgeFact)
        assert isinstance(facts["ready"], ProgressFact)

    def test_build_creates_facts_with_correct_scopes(self):
        """build() creates Facts with declared scopes."""
        spec = EmissionSpec(
            data=Emission("session", KnowledgeFact),
            flag=Emission("persistent", ProgressFact),
            temp=Emission("iteration", Fact),
        )

        facts = spec.build(data="value", flag=True, temp=123)

        assert facts["data"].scope == "session"
        assert facts["flag"].scope == "persistent"
        assert facts["temp"].scope == "iteration"

    def test_build_raises_on_undeclared_key(self):
        """build() raises ValueError for keys not in spec."""
        spec = EmissionSpec(
            declared=Emission("session", Fact),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.build(declared="ok", undeclared="oops")

        assert "undeclared" in str(exc_info.value).lower()

    def test_build_raises_on_missing_required_key(self):
        """build() raises ValueError when required key is missing."""
        spec = EmissionSpec(
            required=Emission("session", Fact),
            also_required=Emission("session", Fact),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.build(required="present")  # missing also_required

        assert "also_required" in str(exc_info.value)

    def test_build_allows_missing_optional_key(self):
        """build() allows omitting keys marked as optional."""
        spec = EmissionSpec(
            required=Emission("session", Fact),
            optional=Emission("session", Fact, optional=True),
        )

        facts = spec.build(required="present")

        assert "required" in facts
        assert "optional" not in facts

    def test_build_includes_optional_key_when_provided(self):
        """build() includes optional keys when provided."""
        spec = EmissionSpec(
            required=Emission("session", Fact),
            optional=Emission("session", Fact, optional=True),
        )

        facts = spec.build(required="present", optional="also here")

        assert "required" in facts
        assert "optional" in facts
        assert facts["optional"].value == "also here"

    def test_to_dict_returns_key_scope_mapping(self):
        """to_dict() returns dict[str, Scope] for validation."""
        spec = EmissionSpec(
            plan=Emission("session", KnowledgeFact),
            ready=Emission("persistent", ProgressFact),
        )

        result = spec.to_dict()

        assert result == {"plan": "session", "ready": "persistent"}

    def test_keys_returns_declared_keys(self):
        """keys() returns set of declared emission keys."""
        spec = EmissionSpec(
            a=Emission("session", Fact),
            b=Emission("session", Fact),
        )

        assert spec.keys() == {"a", "b"}

    def test_contains_checks_key_existence(self):
        """__contains__ checks if key is declared."""
        spec = EmissionSpec(
            declared=Emission("session", Fact),
        )

        assert "declared" in spec
        assert "undeclared" not in spec

    def test_get_returns_emission_or_none(self):
        """get() returns Emission for declared key, None otherwise."""
        spec = EmissionSpec(
            declared=Emission("session", KnowledgeFact),
        )

        assert spec.get("declared") is not None
        assert spec.get("declared").fact_type == KnowledgeFact
        assert spec.get("undeclared") is None

    def test_empty_spec_builds_empty_facts(self):
        """EmissionSpec with no declarations builds empty Facts."""
        spec = EmissionSpec()

        facts = spec.build()

        assert len(facts) == 0

    def test_fact_key_matches_mapping_key(self):
        """build() creates Facts where fact.key == mapping key."""
        spec = EmissionSpec(
            my_key=Emission("session", Fact),
        )

        facts = spec.build(my_key="value")

        assert facts["my_key"].key == "my_key"


class TestEmission:
    """Tests for Emission dataclass."""

    def test_emission_defaults(self):
        """Emission has sensible defaults."""
        emission = Emission()

        assert emission.scope == "session"
        assert emission.fact_type == Fact
        assert emission.optional is False

    def test_emission_is_frozen(self):
        """Emission is immutable (frozen dataclass)."""
        emission = Emission("session", KnowledgeFact)

        with pytest.raises(Exception):  # FrozenInstanceError
            emission.scope = "iteration"

    def test_emission_with_all_args(self):
        """Emission accepts all arguments."""
        emission = Emission("persistent", ProgressFact, optional=True)

        assert emission.scope == "persistent"
        assert emission.fact_type == ProgressFact
        assert emission.optional is True
