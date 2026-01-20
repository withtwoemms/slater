import pytest

from slater.types import Fact, Facts, IterationFacts, KnowledgeFact


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
