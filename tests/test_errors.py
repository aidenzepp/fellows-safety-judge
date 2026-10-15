"""The error hierarchy keeps one root, distinct codes, and immutable context."""

import pytest

from safety_judge.errors import SafetyJudgeError


def select_error_classes() -> list[type[SafetyJudgeError]]:
    error_classes: list[type[SafetyJudgeError]] = []
    pending_classes = [SafetyJudgeError]
    while pending_classes:
        error_class = pending_classes.pop()
        error_classes.append(error_class)
        pending_classes.extend(error_class.__subclasses__())
    return error_classes


def test_the_hierarchy_contains_the_root_and_every_documented_subclass() -> None:
    error_names = {error_class.__name__ for error_class in select_error_classes()}

    assert error_names == {
        "SafetyJudgeError",
        "ConfigurationError",
        "InvalidValueError",
    }, "a new error was added without updating this inventory and its docstring"


def test_every_error_kind_has_its_own_code() -> None:
    codes = [error_class.code for error_class in select_error_classes()]

    assert len(codes) == len(set(codes)), f"error codes must be unique, got {codes}"


def test_the_message_is_the_exception_text() -> None:
    error = SafetyJudgeError("Provide a smaller value.")

    assert str(error) == "Provide a smaller value."
    assert error.message == "Provide a smaller value."


def test_context_copies_the_facts_it_was_given() -> None:
    supplied_facts = {"actual_length": 70}
    error = SafetyJudgeError("Too long.", context=supplied_facts)

    supplied_facts["actual_length"] = 0

    assert error.context["actual_length"] == 70


def test_context_rejects_mutation() -> None:
    error = SafetyJudgeError("Too long.", context={"actual_length": 70})

    with pytest.raises(TypeError):
        error.context["actual_length"] = 0  # pyright: ignore[reportIndexIssue] -- proves the runtime guard the type already forbids


def test_context_is_empty_when_no_facts_are_given() -> None:
    assert dict(SafetyJudgeError("Failed.").context) == {}
