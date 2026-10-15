"""Error hierarchy for every failure this package raises on purpose.

Each error carries a stable machine-readable ``code``, a human-readable
``message`` that says what failed and what to do next, and read-only
``context`` facts for callers that branch or log without parsing prose.
Raise these from the code that owns the failing boundary and re-raise with
``from`` so the original exception stays attached as ``__cause__``.

The hierarchy::

    SafetyJudgeError
    ├── ConfigurationError
    └── InvalidValueError
"""

from types import MappingProxyType
from typing import ClassVar
lazy from collections.abc import Mapping

type ErrorContextValue = str | int | float | bool | None
"""A scalar fact attached to an error; scalars keep every context loggable as JSON."""


class SafetyJudgeError(Exception):
    """Base class of every error this package raises on purpose.

    Catch this class to handle any deliberate failure from the package and a
    subclass to handle one named boundary. Defects such as a wrong argument
    type raise built-in exceptions and are not instances of this class.

    Attributes:
        code: Stable identifier of the error kind, unique per subclass.
        message: What failed, why, and what the caller can do next.
        context: Read-only facts about the failure, such as the offending value.
    """

    code: ClassVar[str] = "safety_judge_error"

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, ErrorContextValue] | None = None,
    ) -> None:
        """Construct an error from its explanation and supporting facts.

        Args:
            message: What failed, why it failed, and what the caller can do next.
            context: Facts that explain the failure; copied so later mutation
                of the argument cannot change the error.
        """
        super().__init__(message)
        self.message: str = message
        self.context: Mapping[str, ErrorContextValue] = MappingProxyType(
            dict(context or {}),
        )


class ConfigurationError(SafetyJudgeError):
    """The process configuration could not be turned into valid settings.

    Raised by ``select_application_settings`` when an environment variable or
    ``.env`` entry holds a value outside its allowed set or names a setting
    that does not exist. The ``invalid_fields`` context entry lists them.
    """

    code: ClassVar[str] = "configuration_invalid"


class InvalidValueError(SafetyJudgeError):
    """A raw value violated the constraint of the domain type it was parsed into.

    Raised by the ``create_*`` functions that turn untrusted input into an
    invariant-bearing value. The context names the constraint and the value
    that violated it, so callers can show the user what to change.
    """

    code: ClassVar[str] = "invalid_value"
