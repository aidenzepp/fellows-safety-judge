"""A text label, kept only to show this repository's conventions.

The module demonstrates parse-don't-validate (a frozen model that cannot hold an
invalid value), a documented error, and the ``create_`` verb for in-memory
construction. Delete it and ``tests/test_example_text_label.py`` when the first
real domain module exists.
"""

from typing import Annotated, Final

from pydantic import BaseModel, StringConstraints, ValidationError

from safety_judge.errors import InvalidValueError

MINIMUM_TEXT_LABEL_LENGTH: Final = 1
"""The fewest characters a label holds after surrounding whitespace is trimmed."""

MAXIMUM_TEXT_LABEL_LENGTH: Final = 64
"""The most characters a label holds after surrounding whitespace is trimmed."""

type TextLabelText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=MINIMUM_TEXT_LABEL_LENGTH,
        max_length=MAXIMUM_TEXT_LABEL_LENGTH,
    ),
]
"""Trimmed text whose length is within the label bounds."""


class TextLabel(BaseModel, frozen=True, extra="forbid"):
    """A short, trimmed, non-empty name that cannot be built from invalid text.

    Every construction path validates, so holders of a ``TextLabel`` never
    re-check its text. ``frozen`` is a class keyword because the type checker
    reads only that form to forbid attribute assignment.

    Attributes:
        text: The label text without surrounding whitespace.
    """

    text: TextLabelText


def create_text_label(raw_text: str) -> TextLabel:
    """Create a label from untrusted text by trimming it and checking its length.

    Args:
        raw_text: Text exactly as supplied by a caller, possibly padded.

    Returns:
        The label holding ``raw_text`` without surrounding whitespace.

    Raises:
        InvalidValueError: When the trimmed text is shorter or longer than the
            label bounds; ``__cause__`` holds the underlying validation error.
    """
    try:
        return TextLabel(text=raw_text)
    except ValidationError as validation_error:
        actual_length = len(raw_text.strip())
        message = (
            f"A text label must contain {MINIMUM_TEXT_LABEL_LENGTH} to "
            f"{MAXIMUM_TEXT_LABEL_LENGTH} characters after trimming whitespace, "
            f"but this one has {actual_length}. Provide a label within those bounds."
        )
        raise InvalidValueError(
            message,
            context={
                "constraint": (
                    f"{MINIMUM_TEXT_LABEL_LENGTH} to "
                    f"{MAXIMUM_TEXT_LABEL_LENGTH} characters after trimming"
                ),
                "actual_length": actual_length,
            },
        ) from validation_error
