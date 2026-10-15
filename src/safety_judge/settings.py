"""Typed process settings read from environment variables and an optional file.

``pyproject.toml`` and ``.env.example`` document the names; the model here is
the only place that interprets them. Secrets belong in ``SecretStr`` fields and
in an untracked ``.env``, never in ``.env.example``.
"""

from enum import StrEnum
from pathlib import Path
from typing import Final, override

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from safety_judge.errors import ConfigurationError

ENVIRONMENT_VARIABLE_PREFIX: Final = "SAFETY_JUDGE_"
"""The prefix that scopes every setting name, so unrelated variables never collide."""

DEFAULT_ENVIRONMENT_FILE_PATH: Final = Path(".env")
"""The file read when no path is given; resolved against the working directory."""


class RuntimeEnvironment(StrEnum):
    """The deployment context the process runs in."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LoggingLevel(StrEnum):
    """A severity threshold, spelled as the standard library's level names."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ApplicationSettings(BaseSettings):
    """Immutable settings for one process, validated when first constructed.

    Values come only from the process environment and the env file, never from
    constructor arguments. Unknown ``SAFETY_JUDGE_*`` entries are rejected so a
    misspelled name fails loudly instead of silently falling back to a default.
    Pyright rejects ``frozen`` as a class keyword on a ``BaseSettings`` subclass,
    so assignment is forbidden at runtime only.

    Attributes:
        runtime_environment: The deployment context; set by
            ``SAFETY_JUDGE_RUNTIME_ENVIRONMENT``.
        logging_level: The minimum severity to record; set by
            ``SAFETY_JUDGE_LOGGING_LEVEL``.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENVIRONMENT_VARIABLE_PREFIX,
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    runtime_environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    logging_level: LoggingLevel = LoggingLevel.INFO

    @override
    def __init__(
        self,
        *,
        _env_file: Path | None = DEFAULT_ENVIRONMENT_FILE_PATH,
    ) -> None:
        """Read the settings from the process environment and an env file.

        Args:
            _env_file: The dotenv file to read, or ``None`` to read only the
                process environment. The name is the one pydantic-settings
                defines; it is restated here so the type checker accepts it.
        """
        super().__init__(_env_file=_env_file)


def select_application_settings(
    *,
    environment_file_path: Path | None = DEFAULT_ENVIRONMENT_FILE_PATH,
) -> ApplicationSettings:
    """Select validated settings from the process environment and an env file.

    Process environment variables take precedence over the file. This is the
    boundary where weakly typed text becomes ``ApplicationSettings``; callers
    receive a value that needs no further validation.

    Args:
        environment_file_path: The dotenv file to read, or ``None`` to read
            only the process environment. A missing file is not an error.

    Returns:
        The immutable settings for this process.

    Raises:
        ConfigurationError: When any entry is unknown or outside its allowed
            values; ``__cause__`` holds the underlying validation error.
    """
    try:
        return ApplicationSettings(_env_file=environment_file_path)
    except ValidationError as validation_error:
        invalid_fields = sorted(
            {
                ".".join(str(location_part) for location_part in error["loc"])
                for error in validation_error.errors()
            },
        )
        message = (
            f"Settings are invalid: {', '.join(invalid_fields)}. "
            f"Correct the {ENVIRONMENT_VARIABLE_PREFIX}* entries in the process "
            "environment or the env file; .env.example lists every setting "
            "and its allowed values."
        )
        raise ConfigurationError(
            message,
            context={"invalid_fields": ", ".join(invalid_fields)},
        ) from validation_error
