"""A text label is trimmed, bounded, immutable, and impossible to build invalid."""

import pytest
from pydantic import ValidationError

from safety_judge.errors import InvalidValueError
from safety_judge.example_text_label import (
    MAXIMUM_TEXT_LABEL_LENGTH,
    TextLabel,
    create_text_label,
)


@pytest.mark.parametrize(
    ("raw_text", "expected_text"),
    [
        ("label", "label"),
        ("  padded label \n", "padded label"),
        ("x" * MAXIMUM_TEXT_LABEL_LENGTH, "x" * MAXIMUM_TEXT_LABEL_LENGTH),
    ],
)
def test_creating_a_label_keeps_the_trimmed_text(
    raw_text: str,
    expected_text: str,
) -> None:
    assert create_text_label(raw_text).text == expected_text


@pytest.mark.parametrize(
    ("raw_text", "expected_length"),
    [
        ("", 0),
        ("   \t\n", 0),
        ("x" * (MAXIMUM_TEXT_LABEL_LENGTH + 1), MAXIMUM_TEXT_LABEL_LENGTH + 1),
    ],
)
def test_creating_a_label_outside_the_bounds_raises_an_error_with_the_length(
    raw_text: str,
    expected_length: int,
) -> None:
    with pytest.raises(InvalidValueError) as raised:
        _ = create_text_label(raw_text)

    assert raised.value.context["actual_length"] == expected_length
    assert str(expected_length) in raised.value.message
    assert isinstance(raised.value.__cause__, ValidationError)


def test_constructing_a_label_directly_cannot_skip_validation() -> None:
    with pytest.raises(ValidationError):
        _ = TextLabel(text="")


def test_a_label_is_immutable() -> None:
    label = create_text_label("label")

    with pytest.raises(ValidationError):
        label.text = "other"  # pyright: ignore[reportAttributeAccessIssue] -- deliberately violates the type to test the runtime guard
