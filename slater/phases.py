import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import AbstractSet, FrozenSet, List, Set, Type


class PhaseEnum:
    """
    Factory for creating validated Phase enum classes.

    Phases represent discrete states in a Slater agent's FSM.
    Phase names must be UPPER_SNAKE_CASE and unique.

    Example:
        # From list (order preserved)
        Phase = PhaseEnum.create("START", "PROCESSING", "DONE")

        # From YAML data
        Phase = PhaseEnum.from_list(["START", "PROCESSING", "DONE"])

        # Usage
        phase = Phase.START
        phase.name  # "START"
        phase.value  # 1
    """

    # Validation pattern
    _NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

    # Reserved names
    _RESERVED: FrozenSet[str] = frozenset(
        {"NONE", "ANY", "ALL", "DEFAULT", "UNKNOWN", "TRUE", "FALSE", "NULL"}
    )

    @classmethod
    def create(cls, *names: str, class_name: str = "Phase") -> Type[Enum]:
        """
        Create a Phase enum from names.

        Args:
            *names: Phase names (UPPER_SNAKE_CASE)
            class_name: Name for the generated enum class

        Returns:
            A new Enum class with the given phases

        Raises:
            ValueError: If names are invalid, reserved, or duplicated

        Example:
            Phase = PhaseEnum.create("START", "PROCESSING", "DONE")
            assert Phase.START.name == "START"
        """
        cls._validate(names)
        return Enum(class_name, {name: auto() for name in names})

    @classmethod
    def from_list(cls, names: List[str], class_name: str = "Phase") -> Type[Enum]:
        """
        Create a Phase enum from a list of names.

        Useful when loading from YAML/JSON.

        Example:
            phases_from_yaml = ["START", "PROCESSING", "DONE"]
            Phase = PhaseEnum.from_list(phases_from_yaml)
        """
        return cls.create(*names, class_name=class_name)

    @classmethod
    def from_set(cls, names: Set[str], class_name: str = "Phase") -> Type[Enum]:
        """
        Create a Phase enum from a set of names.

        Names are sorted alphabetically for deterministic ordering.

        Example:
            Phase = PhaseEnum.from_set({"DONE", "START", "PROCESSING"})
            # Order: DONE, PROCESSING, START (alphabetical)
        """
        return cls.create(*sorted(names), class_name=class_name)

    @classmethod
    def _validate(cls, names: tuple[str, ...]) -> None:
        """Validate phase names."""
        if not names:
            raise ValueError("At least one phase name is required")

        seen: Set[str] = set()
        errors: List[str] = []

        for name in names:
            # Type check
            if not isinstance(name, str):
                errors.append(
                    f"Phase name must be string, got {type(name).__name__}: {name!r}"
                )
                continue

            # Format check
            if not cls._NAME_PATTERN.match(name):
                errors.append(
                    f"Invalid phase name: '{name}' "
                    f"(must be UPPER_SNAKE_CASE, e.g., 'READY_TO_CONTINUE')"
                )
                continue

            # Reserved check
            if name in cls._RESERVED:
                errors.append(
                    f"Reserved phase name: '{name}' "
                    f"(cannot use: {', '.join(sorted(cls._RESERVED))})"
                )
                continue

            # Duplicate check
            if name in seen:
                errors.append(f"Duplicate phase name: '{name}'")
                continue

            seen.add(name)

        if errors:
            error_list = "\n  - ".join(errors)
            raise ValueError(f"Invalid phase names:\n  - {error_list}")

    @classmethod
    def validate(cls, names: List[str]) -> bool:
        """
        Check if names are valid without raising.

        Returns:
            True if all names are valid

        Example:
            if PhaseEnum.validate(["START", "DONE"]):
                Phase = PhaseEnum.from_list(["START", "DONE"])
        """
        try:
            cls._validate(tuple(names))
            return True
        except ValueError:
            return False


# MARKED FOR DELETION: Default Phase enum for backward compatibility
# Use PhaseEnum.create() to define agent-specific phases instead
class Phase(Enum):
    PROCEDURE_SUCCEEDED = auto()
    PROCEDURE_FAILED = auto()
    NEEDS_CONTEXT = auto()
    NEEDS_USER_INPUT = auto()
    READY_TO_CONTINUE = auto()
    TASK_COMPLETE = auto()
    TERMINAL_FAILURE = auto()


@dataclass(frozen=True)
class PhaseRule:
    """
    Declarative rule for entering a Phase based on durable Facts.
    """

    enter: Enum  # Phase enum member

    when_all: FrozenSet[str] = field(default_factory=frozenset)
    when_any: FrozenSet[str] = field(default_factory=frozenset)
    when_none: FrozenSet[str] = field(default_factory=frozenset)

    def matches(self, fact_keys: AbstractSet[str]) -> bool:
        # ALL
        if not self.when_all.issubset(fact_keys):
            return False

        # ANY (if specified)
        if self.when_any and not self.when_any.intersection(fact_keys):
            return False

        # NONE
        if self.when_none.intersection(fact_keys):
            return False

        return True
