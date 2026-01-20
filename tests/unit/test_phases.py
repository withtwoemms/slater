"""
Tests for PhaseEnum factory.

These tests ensure phase creation is validated and consistent.
"""

import pytest
from enum import Enum

from slater.phases import PhaseEnum


# ----------------------------------------------------------------------------
# Valid phase creation
# ----------------------------------------------------------------------------


class TestPhaseEnumCreate:
    def test_create_simple_phases(self):
        """Create phases from simple names."""
        Phase = PhaseEnum.create("START", "DONE")

        assert hasattr(Phase, "START")
        assert hasattr(Phase, "DONE")
        assert Phase.START.name == "START"
        assert Phase.DONE.name == "DONE"

    def test_create_returns_enum_class(self):
        """Created class is a proper Enum."""
        Phase = PhaseEnum.create("START", "DONE")

        assert issubclass(Phase, Enum)
        assert isinstance(Phase.START, Phase)

    def test_create_with_underscores(self):
        """Phase names can contain underscores."""
        Phase = PhaseEnum.create("READY_TO_CONTINUE", "NEEDS_USER_INPUT")

        assert Phase.READY_TO_CONTINUE.name == "READY_TO_CONTINUE"
        assert Phase.NEEDS_USER_INPUT.name == "NEEDS_USER_INPUT"

    def test_create_with_numbers(self):
        """Phase names can contain numbers."""
        Phase = PhaseEnum.create("STEP1", "STEP2", "PHASE_3")

        assert Phase.STEP1.name == "STEP1"
        assert Phase.STEP2.name == "STEP2"
        assert Phase.PHASE_3.name == "PHASE_3"

    def test_create_custom_class_name(self):
        """Custom class name is applied."""
        MyPhases = PhaseEnum.create("A", "B", class_name="MyPhases")

        assert MyPhases.__name__ == "MyPhases"

    def test_create_preserves_order(self):
        """Phase values are assigned in order."""
        Phase = PhaseEnum.create("FIRST", "SECOND", "THIRD")

        assert Phase.FIRST.value < Phase.SECOND.value
        assert Phase.SECOND.value < Phase.THIRD.value


# ----------------------------------------------------------------------------
# from_list and from_set
# ----------------------------------------------------------------------------


class TestPhaseEnumFromList:
    def test_from_list_creates_phases(self):
        """from_list creates phases from a list."""
        names = ["START", "PROCESSING", "DONE"]
        Phase = PhaseEnum.from_list(names)

        assert Phase.START.name == "START"
        assert Phase.PROCESSING.name == "PROCESSING"
        assert Phase.DONE.name == "DONE"

    def test_from_list_preserves_order(self):
        """from_list preserves list order."""
        Phase = PhaseEnum.from_list(["Z_LAST", "A_FIRST", "M_MIDDLE"])

        values = [p.value for p in Phase]
        # Z_LAST should be first (lowest value) since it's first in list
        assert Phase.Z_LAST.value < Phase.A_FIRST.value


class TestPhaseEnumFromSet:
    def test_from_set_creates_phases(self):
        """from_set creates phases from a set."""
        names = {"START", "PROCESSING", "DONE"}
        Phase = PhaseEnum.from_set(names)

        assert hasattr(Phase, "START")
        assert hasattr(Phase, "PROCESSING")
        assert hasattr(Phase, "DONE")

    def test_from_set_sorts_alphabetically(self):
        """from_set sorts names alphabetically for determinism."""
        Phase = PhaseEnum.from_set({"ZEBRA", "ALPHA", "MIDDLE"})

        values = [(p.name, p.value) for p in Phase]
        names = [name for name, _ in values]

        assert names == ["ALPHA", "MIDDLE", "ZEBRA"]


# ----------------------------------------------------------------------------
# Validation errors
# ----------------------------------------------------------------------------


class TestPhaseEnumValidation:
    def test_empty_names_raises(self):
        """Empty names list raises ValueError."""
        with pytest.raises(ValueError, match="At least one phase name"):
            PhaseEnum.create()

    def test_lowercase_raises(self):
        """Lowercase names raise ValueError."""
        with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
            PhaseEnum.create("start")

    def test_mixed_case_raises(self):
        """Mixed case names raise ValueError."""
        with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
            PhaseEnum.create("Start")

    def test_leading_number_raises(self):
        """Names starting with numbers raise ValueError."""
        with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
            PhaseEnum.create("1STEP")

    def test_spaces_raise(self):
        """Names with spaces raise ValueError."""
        with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
            PhaseEnum.create("MY PHASE")

    def test_hyphens_raise(self):
        """Names with hyphens raise ValueError."""
        with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
            PhaseEnum.create("MY-PHASE")

    def test_reserved_name_none_raises(self):
        """Reserved name NONE raises ValueError."""
        with pytest.raises(ValueError, match="Reserved phase name"):
            PhaseEnum.create("NONE")

    def test_reserved_name_default_raises(self):
        """Reserved name DEFAULT raises ValueError."""
        with pytest.raises(ValueError, match="Reserved phase name"):
            PhaseEnum.create("DEFAULT")

    def test_reserved_name_all_raises(self):
        """Reserved name ALL raises ValueError."""
        with pytest.raises(ValueError, match="Reserved phase name"):
            PhaseEnum.create("ALL")

    def test_duplicate_names_raise(self):
        """Duplicate names raise ValueError."""
        with pytest.raises(ValueError, match="Duplicate phase name"):
            PhaseEnum.create("START", "START")

    def test_multiple_errors_reported(self):
        """Multiple validation errors are reported together."""
        with pytest.raises(ValueError) as exc_info:
            PhaseEnum.create("start", "NONE", "START", "START")

        error_msg = str(exc_info.value)
        assert "UPPER_SNAKE_CASE" in error_msg  # lowercase
        assert "Reserved" in error_msg  # NONE
        assert "Duplicate" in error_msg  # START twice

    def test_non_string_raises(self):
        """Non-string names raise ValueError."""
        with pytest.raises(ValueError, match="must be string"):
            PhaseEnum.create("VALID", 123)


# ----------------------------------------------------------------------------
# validate() method
# ----------------------------------------------------------------------------


class TestPhaseEnumValidateMethod:
    def test_validate_returns_true_for_valid(self):
        """validate() returns True for valid names."""
        assert PhaseEnum.validate(["START", "DONE"]) is True

    def test_validate_returns_false_for_invalid(self):
        """validate() returns False for invalid names."""
        assert PhaseEnum.validate(["start"]) is False
        assert PhaseEnum.validate(["NONE"]) is False
        assert PhaseEnum.validate([]) is False

    def test_validate_does_not_raise(self):
        """validate() returns False instead of raising."""
        # Should not raise, just return False
        result = PhaseEnum.validate(["invalid", "NONE", "duplicate", "duplicate"])
        assert result is False


# ----------------------------------------------------------------------------
# Integration with PhaseRule
# ----------------------------------------------------------------------------


class TestPhaseEnumWithPhaseRule:
    def test_dynamic_phase_works_with_phase_rule(self):
        """Dynamically created phases work with PhaseRule."""
        from slater.phases import PhaseRule

        Phase = PhaseEnum.create("START", "PROCESSING", "DONE")

        rule = PhaseRule(
            enter=Phase.DONE,
            when_all=frozenset({"task_complete"}),
        )

        assert rule.enter == Phase.DONE
        assert rule.matches({"task_complete", "other_fact"})
        assert not rule.matches({"other_fact"})
