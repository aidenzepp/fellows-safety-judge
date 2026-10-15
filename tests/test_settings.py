"""Settings load from the environment and file, and reject anything invalid."""

from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from safety_judge.errors import ConfigurationError
from safety_judge.settings import (
    ENVIRONMENT_VARIABLE_PREFIX,
    ApplicationSettings,
    LoggingLevel,
    RuntimeEnvironment,
    select_application_settings,
)

ENVIRONMENT_EXAMPLE_PATH: Final = Path(__file__).resolve().parents[1] / ".env.example"


def insert_environment_file(directory: Path, text: str) -> Path:
    environment_file_path = directory / ".env"
    _ = environment_file_path.write_text(text, encoding="utf-8")
    return environment_file_path


def test_settings_default_to_development_with_info_logging() -> None:
    settings = select_application_settings(environment_file_path=None)

    assert settings.runtime_environment is RuntimeEnvironment.DEVELOPMENT
    assert settings.logging_level is LoggingLevel.INFO


def test_process_environment_supplies_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_JUDGE_RUNTIME_ENVIRONMENT", "production")
    monkeypatch.setenv("SAFETY_JUDGE_LOGGING_LEVEL", "ERROR")

    settings = select_application_settings(environment_file_path=None)

    assert settings.runtime_environment is RuntimeEnvironment.PRODUCTION
    assert settings.logging_level is LoggingLevel.ERROR


def test_environment_file_supplies_values_the_process_environment_lacks(
    tmp_path: Path,
) -> None:
    environment_file_path = insert_environment_file(
        tmp_path,
        "SAFETY_JUDGE_LOGGING_LEVEL=DEBUG\n",
    )

    settings = select_application_settings(environment_file_path=environment_file_path)

    assert settings.logging_level is LoggingLevel.DEBUG


def test_process_environment_wins_over_the_environment_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_file_path = insert_environment_file(
        tmp_path,
        "SAFETY_JUDGE_LOGGING_LEVEL=DEBUG\n",
    )
    monkeypatch.setenv("SAFETY_JUDGE_LOGGING_LEVEL", "WARNING")

    settings = select_application_settings(environment_file_path=environment_file_path)

    assert settings.logging_level is LoggingLevel.WARNING


def test_a_missing_environment_file_leaves_the_defaults(tmp_path: Path) -> None:
    settings = select_application_settings(
        environment_file_path=tmp_path / "does-not-exist.env",
    )

    assert settings.logging_level is LoggingLevel.INFO


def test_a_value_outside_the_allowed_set_raises_a_configuration_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_JUDGE_LOGGING_LEVEL", "LOUD")

    with pytest.raises(ConfigurationError) as raised:
        _ = select_application_settings(environment_file_path=None)

    assert raised.value.context["invalid_fields"] == "logging_level"
    assert "logging_level" in raised.value.message
    assert isinstance(raised.value.__cause__, ValidationError)


def test_an_unknown_prefixed_entry_in_the_environment_file_is_rejected(
    tmp_path: Path,
) -> None:
    environment_file_path = insert_environment_file(
        tmp_path,
        "SAFETY_JUDGE_LOGGING_LEVL=DEBUG\n",
    )

    with pytest.raises(ConfigurationError) as raised:
        _ = select_application_settings(environment_file_path=environment_file_path)

    invalid_fields = str(raised.value.context["invalid_fields"])
    assert "logging_levl" in invalid_fields, (
        "the misspelled name should be reported so the typo is easy to find; "
        f"context was {dict(raised.value.context)}"
    )


def test_the_example_environment_file_names_every_setting_and_loads() -> None:
    example_text = ENVIRONMENT_EXAMPLE_PATH.read_text(encoding="utf-8")

    for field_name in ApplicationSettings.model_fields:
        variable_name = f"{ENVIRONMENT_VARIABLE_PREFIX}{field_name.upper()}"
        assert f"{variable_name}=" in example_text, (
            f".env.example should document {variable_name} for the "
            f"{field_name!r} setting"
        )

    settings = select_application_settings(
        environment_file_path=ENVIRONMENT_EXAMPLE_PATH,
    )

    assert settings.runtime_environment is RuntimeEnvironment.DEVELOPMENT


def test_settings_are_immutable() -> None:
    settings = select_application_settings(environment_file_path=None)

    with pytest.raises(ValidationError):
        settings.logging_level = LoggingLevel.DEBUG
