import pytest

from slater.types import (
    DiagnosticFact,
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
        """facts() creates Facts with declared fact types."""
        spec = EmissionSpec(
            plan=Emission("session", KnowledgeFact),
            ready=Emission("session", ProgressFact),
        )

        facts = spec.facts(plan={"steps": []}, ready=True)

        assert isinstance(facts["plan"], KnowledgeFact)
        assert isinstance(facts["ready"], ProgressFact)

    def test_build_creates_facts_with_correct_scopes(self):
        """facts() creates Facts with declared scopes."""
        spec = EmissionSpec(
            data=Emission("session", KnowledgeFact),
            flag=Emission("persistent", ProgressFact),
            temp=Emission("iteration", Fact),
        )

        facts = spec.facts(data="value", flag=True, temp=123)

        assert facts["data"].scope == "session"
        assert facts["flag"].scope == "persistent"
        assert facts["temp"].scope == "iteration"

    def test_build_raises_on_undeclared_key(self):
        """facts() raises ValueError for keys not in spec."""
        spec = EmissionSpec(
            declared=Emission("session", Fact),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.facts(declared="ok", undeclared="oops")

        assert "undeclared" in str(exc_info.value).lower()

    def test_build_raises_on_missing_required_key(self):
        """facts() raises ValueError when required key is missing."""
        spec = EmissionSpec(
            required=Emission("session", Fact),
            also_required=Emission("session", Fact),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.facts(required="present")  # missing also_required

        assert "also_required" in str(exc_info.value)

    def test_build_allows_missing_non_required_key(self):
        """facts() allows omitting keys marked as required=False."""
        spec = EmissionSpec(
            always=Emission("session", Fact),
            conditional=Emission("session", Fact, required=False),
        )

        facts = spec.facts(always="present")

        assert "always" in facts
        assert "conditional" not in facts

    def test_build_includes_non_required_key_when_provided(self):
        """facts() includes non-required keys when provided."""
        spec = EmissionSpec(
            always=Emission("session", Fact),
            conditional=Emission("session", Fact, required=False),
        )

        facts = spec.facts(always="present", conditional="also here")

        assert "always" in facts
        assert "conditional" in facts
        assert facts["conditional"].value == "also here"

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

        facts = spec.facts()

        assert len(facts) == 0

    def test_fact_key_matches_mapping_key(self):
        """facts() creates Facts where fact.key == mapping key."""
        spec = EmissionSpec(
            my_key=Emission("session", Fact),
        )

        facts = spec.facts(my_key="value")

        assert facts["my_key"].key == "my_key"


class TestEmission:
    """Tests for Emission dataclass."""

    def test_emission_defaults(self):
        """Emission has sensible defaults."""
        emission = Emission()

        assert emission.scope == "session"
        assert emission.fact_type == Fact
        assert emission.required is True

    def test_emission_is_frozen(self):
        """Emission is immutable (frozen dataclass)."""
        emission = Emission("session", KnowledgeFact)

        with pytest.raises(Exception):  # FrozenInstanceError
            emission.scope = "iteration"

    def test_emission_with_all_args(self):
        """Emission accepts all arguments."""
        emission = Emission("persistent", ProgressFact, required=False)

        assert emission.scope == "persistent"
        assert emission.fact_type == ProgressFact
        assert emission.required is False


class TestConditionalEmissions:
    """Tests for actions that emit different facts based on outcome."""

    def test_success_path_emissions(self):
        """Action emitting success-path facts only."""
        spec = EmissionSpec(
            result=Emission("session", KnowledgeFact),
            success=Emission("session", ProgressFact),
            error=Emission("session", DiagnosticFact, required=False),
        )

        # Success path - no error emitted
        facts = spec.facts(result={"data": "value"}, success=True)

        assert "result" in facts
        assert "success" in facts
        assert "error" not in facts

    def test_failure_path_emissions(self):
        """Action emitting failure-path facts only."""
        spec = EmissionSpec(
            result=Emission("session", KnowledgeFact, required=False),
            success=Emission("session", ProgressFact),
            error=Emission("session", DiagnosticFact, required=False),
        )

        # Failure path - no result, but error emitted
        facts = spec.facts(success=False, error="Something went wrong")

        assert "result" not in facts
        assert "success" in facts
        assert facts["success"].value is False
        assert "error" in facts

    def test_either_or_emissions(self):
        """Action emitting mutually exclusive facts."""
        spec = EmissionSpec(
            # Always emitted
            attempted=Emission("session", ProgressFact),
            # One of these based on outcome
            patch_summary=Emission("session", KnowledgeFact, required=False),
            patch_errors=Emission("session", DiagnosticFact, required=False),
        )

        # Success case
        success_facts = spec.facts(attempted=True, patch_summary="Applied 3 changes")
        assert "patch_summary" in success_facts
        assert "patch_errors" not in success_facts

        # Failure case
        failure_facts = spec.facts(attempted=True, patch_errors=["File not found"])
        assert "patch_summary" not in failure_facts
        assert "patch_errors" in failure_facts


class TestNestedEmissionSpec:
    """Tests for nested EmissionSpec (hierarchical fact grouping)."""

    def test_nested_build_creates_nested_facts(self):
        """facts() creates nested Facts structure from nested EmissionSpec."""
        spec = EmissionSpec(
            repo=EmissionSpec(
                file_count=Emission("session", KnowledgeFact),
                languages=Emission("session", KnowledgeFact),
            ),
            analysis_ready=Emission("session", ProgressFact),
        )

        facts = spec.facts(
            repo={"file_count": 42, "languages": ["python", "go"]},
            analysis_ready=True,
        )

        assert "repo" in facts
        assert isinstance(facts["repo"], Facts)
        assert facts["repo"]["file_count"].value == 42
        assert facts["repo"]["languages"].value == ["python", "go"]
        assert facts["analysis_ready"].value is True

    def test_nested_preserves_scopes(self):
        """Nested emissions preserve their declared scopes."""
        spec = EmissionSpec(
            group=EmissionSpec(
                persistent_fact=Emission("persistent", KnowledgeFact),
                session_fact=Emission("session", KnowledgeFact),
            ),
        )

        facts = spec.facts(
            group={"persistent_fact": "durable", "session_fact": "temporary"},
        )

        assert facts["group"]["persistent_fact"].scope == "persistent"
        assert facts["group"]["session_fact"].scope == "session"

    def test_nested_preserves_fact_types(self):
        """Nested emissions preserve their declared fact types."""
        spec = EmissionSpec(
            group=EmissionSpec(
                progress=Emission("session", ProgressFact),
                knowledge=Emission("session", KnowledgeFact),
            ),
        )

        facts = spec.facts(
            group={"progress": True, "knowledge": {"data": "value"}},
        )

        assert isinstance(facts["group"]["progress"], ProgressFact)
        assert isinstance(facts["group"]["knowledge"], KnowledgeFact)

    def test_nested_validates_undeclared_keys(self):
        """facts() raises on undeclared keys in nested dict."""
        spec = EmissionSpec(
            group=EmissionSpec(
                declared=Emission("session", Fact),
            ),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.facts(group={"declared": "ok", "undeclared": "oops"})

        assert "undeclared" in str(exc_info.value).lower()

    def test_nested_validates_missing_required_keys(self):
        """facts() raises on missing required keys in nested spec."""
        spec = EmissionSpec(
            group=EmissionSpec(
                required_key=Emission("session", Fact),
            ),
        )

        with pytest.raises(ValueError) as exc_info:
            spec.facts(group={})

        assert "required_key" in str(exc_info.value)

    def test_nested_allows_non_required_nested_spec(self):
        """Nested EmissionSpec with required=False can be omitted."""
        spec = EmissionSpec(
            always=Emission("session", Fact),
            optional_group=EmissionSpec(
                required=False,
                nested_fact=Emission("session", Fact),
            ),
        )

        facts = spec.facts(always="present")

        assert "always" in facts
        assert "optional_group" not in facts

    def test_nested_includes_non_required_when_provided(self):
        """Non-required nested spec is included when provided."""
        spec = EmissionSpec(
            always=Emission("session", Fact),
            optional_group=EmissionSpec(
                required=False,
                nested_fact=Emission("session", Fact),
            ),
        )

        facts = spec.facts(
            always="present",
            optional_group={"nested_fact": "included"},
        )

        assert "always" in facts
        assert "optional_group" in facts
        assert facts["optional_group"]["nested_fact"].value == "included"

    def test_nested_requires_dict_value(self):
        """facts() raises TypeError if non-dict passed for nested spec."""
        spec = EmissionSpec(
            group=EmissionSpec(
                fact=Emission("session", Fact),
            ),
        )

        with pytest.raises(TypeError) as exc_info:
            spec.facts(group="not a dict")

        assert "dict" in str(exc_info.value).lower()

    def test_to_dict_flattens_nested_specs(self):
        """to_dict() returns flattened keys with dot-notation."""
        spec = EmissionSpec(
            repo=EmissionSpec(
                file_count=Emission("session", KnowledgeFact),
                languages=Emission("persistent", KnowledgeFact),
            ),
            ready=Emission("session", ProgressFact),
        )

        result = spec.to_dict()

        assert result == {
            "repo.file_count": "session",
            "repo.languages": "persistent",
            "ready": "session",
        }

    def test_flat_keys_returns_all_nested_keys(self):
        """flat_keys() returns all keys with dot-notation."""
        spec = EmissionSpec(
            repo=EmissionSpec(
                file_count=Emission("session", Fact),
                languages=Emission("session", Fact),
            ),
            ready=Emission("session", Fact),
        )

        assert spec.flat_keys() == {"repo.file_count", "repo.languages", "ready"}

    def test_contains_with_dot_notation(self):
        """__contains__ supports dot-notation for nested keys."""
        spec = EmissionSpec(
            repo=EmissionSpec(
                file_count=Emission("session", Fact),
            ),
        )

        assert "repo" in spec
        assert "repo.file_count" in spec
        assert "repo.undeclared" not in spec

    def test_get_with_dot_notation(self):
        """get() supports dot-notation for nested keys."""
        spec = EmissionSpec(
            repo=EmissionSpec(
                file_count=Emission("session", KnowledgeFact),
            ),
        )

        emission = spec.get("repo.file_count")
        assert emission is not None
        assert emission.fact_type == KnowledgeFact

        assert spec.get("repo.undeclared") is None

    def test_deeply_nested_specs(self):
        """EmissionSpec supports multiple levels of nesting."""
        spec = EmissionSpec(
            level1=EmissionSpec(
                level2=EmissionSpec(
                    deep_fact=Emission("session", KnowledgeFact),
                ),
            ),
        )

        facts = spec.facts(
            level1={"level2": {"deep_fact": "deep value"}},
        )

        assert facts["level1"]["level2"]["deep_fact"].value == "deep value"
        assert "level1.level2.deep_fact" in spec
        assert spec.to_dict() == {"level1.level2.deep_fact": "session"}
