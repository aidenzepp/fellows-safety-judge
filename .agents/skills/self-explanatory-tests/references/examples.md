# Testing Examples

Use these examples as shapes, not as domain requirements. Preserve the repository's real types and contracts.

## Unit Contract

Production behavior lives in a source module, and its unit contract lives in the matching `tests/test_<module>.py`, which imports the module through its public path:

```python
"""Accounts and the rules for choosing among them."""

lazy from collections.abc import Sequence

from pydantic import BaseModel


class Account(BaseModel, frozen=True, extra="forbid"):
    """An account that may be enabled or disabled.

    Attributes:
        identifier: Stable identifier of the account.
        enabled: Whether the account may currently be used.
    """

    identifier: str
    enabled: bool


def remove_disabled_accounts(accounts: Sequence[Account]) -> list[Account]:
    """Remove the disabled accounts, keeping the enabled ones in their order.

    Args:
        accounts: Accounts in the order the caller supplied them.

    Returns:
        The enabled accounts in the original order.
    """
    return [account for account in accounts if account.enabled]
```

```python
"""Removing disabled accounts keeps the enabled ones in their original order."""

from safety_judge.accounts import Account, remove_disabled_accounts


def test_removing_disabled_accounts_keeps_the_enabled_ones_in_order() -> None:
    accounts = [
        Account(identifier="disabled", enabled=False),
        Account(identifier="first", enabled=True),
        Account(identifier="second", enabled=True),
    ]

    enabled_accounts = remove_disabled_accounts(accounts)

    assert [account.identifier for account in enabled_accounts] == ["first", "second"]
```

The test names the behavior, uses visible setup, asserts the observable result, and compares whole lists so pytest shows the differing items when it fails.

## Diagnostic Assertion

When the default assertion would hide the useful command output, include it:

```python
"""A command given an invalid limit fails and explains the accepted range."""

lazy import pytest

from safety_judge.command_line import update_command_run


def test_an_invalid_limit_fails_and_explains_the_accepted_range(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_status = update_command_run(["--limit", "500"])

    captured = capsys.readouterr()
    assert exit_status != 0, (
        "an invalid limit should fail, but the command succeeded; "
        f"stdout: {captured.out!r}; stderr: {captured.err!r}"
    )
    assert "limit must be between 1 and 100" in captured.err, (
        f"stderr should explain the accepted range; stderr: {captured.err!r}"
    )
```

The failure explains the contract, observed status, and captured evidence. It does not merely say that `1 != 0` or that a boolean was false.

## Error Contract and Test Diagnostic

Keep the product error contract separate from the message that helps a developer repair a failed test:

```python
"""A logging level outside the allowed set is reported with its field name."""

import pytest

from safety_judge.errors import ConfigurationError
from safety_judge.settings import select_application_settings


def test_a_logging_level_outside_the_allowed_set_is_reported_by_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_JUDGE_LOGGING_LEVEL", "LOUD")

    with pytest.raises(ConfigurationError, match="logging_level") as excinfo:
        _ = select_application_settings(environment_file_path=None)

    assert excinfo.value.code == "configuration_invalid", (
        "the settings boundary should preserve the stable machine-readable code"
    )
    assert excinfo.value.context["invalid_fields"] == "logging_level", (
        "the context should name the offending setting so callers can branch "
        "without parsing the message"
    )
```

The asserted code, field name, and message fragment belong to the product contract. If `match` fails, pytest prints both the pattern and the actual message. The assertion messages explain to a developer which part of the contract changed.

## Bug Regression

Protect the violated behavior rather than the internal helper that caused it. Suppose a misspelled `SAFETY_JUDGE_LOGGING_LEVL` entry in the environment file was silently ignored and the default level applied:

```python
"""A misspelled setting in the environment file fails instead of being ignored."""

lazy from pathlib import Path

import pytest

from safety_judge.errors import ConfigurationError
from safety_judge.settings import select_application_settings


def test_a_misspelled_setting_in_the_environment_file_is_rejected(
    tmp_path: Path,
) -> None:
    environment_file_path = tmp_path / ".env"
    _ = environment_file_path.write_text(
        "SAFETY_JUDGE_LOGGING_LEVL=DEBUG\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="logging_levl"):
        _ = select_application_settings(environment_file_path=environment_file_path)
```

Before fixing the bug, run this test and confirm it fails because the misspelled entry is accepted, with `DID NOT RAISE` in the output, not because the fixture or an import is broken.

## Invariant-Carrying Type

When many callers require the same precondition, move it into a type and test the enforcement boundary. Suppose `create_confidence_score` returns a frozen `ConfidenceScore` for finite values from 0 to 1 and raises `InvalidValueError` for anything else:

```python
"""A confidence score is finite and between 0 and 1 however it is created."""

import math

import pytest

from safety_judge.confidence_scores import create_confidence_score
from safety_judge.errors import InvalidValueError


@pytest.mark.parametrize(
    "raw_value",
    [0.0, 0.25, 1.0],
    ids=["lower bound", "inside the interval", "upper bound"],
)
def test_a_value_inside_the_unit_interval_is_accepted(raw_value: float) -> None:
    score = create_confidence_score(raw_value)

    assert 0.0 <= score.value <= 1.0, (
        "every successfully created score should satisfy the documented unit "
        f"interval, but {raw_value} produced {score.value}"
    )


@pytest.mark.parametrize(
    "raw_value",
    [-0.01, 1.01, math.nan, math.inf, -math.inf],
    ids=["below", "above", "not a number", "positive infinity", "negative infinity"],
)
def test_a_value_that_cannot_be_a_score_is_rejected(raw_value: float) -> None:
    with pytest.raises(InvalidValueError, match="from 0 to 1"):
        _ = create_confidence_score(raw_value)
```

Also test every operation that claims to preserve the type and every parsing or restoration path, such as `model_validate` and `model_validate_json`, that can construct it. The model enforces a documented numeric invariant; the tests prove that its enforcement is correct and cannot be bypassed.

## Injected Value

Prefer passing the needed value over inventing an interface:

```python
"""A session expires at its deadline, decided from a supplied current time."""

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from safety_judge.sessions import SessionStatus, create_session_status

DEADLINE: Final = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("current_time", "expected_status"),
    [
        (DEADLINE - timedelta(seconds=1), SessionStatus.ACTIVE),
        (DEADLINE, SessionStatus.EXPIRED),
        (DEADLINE + timedelta(seconds=1), SessionStatus.EXPIRED),
    ],
    ids=["one second before", "exactly at", "one second after"],
)
def test_a_session_expires_exactly_at_its_deadline(
    current_time: datetime,
    expected_status: SessionStatus,
) -> None:
    status = create_session_status(DEADLINE, current_time)

    assert status is expected_status, (
        f"a session expiring at {DEADLINE.isoformat()} should be "
        f"{expected_status} at {current_time.isoformat()}, but was {status}"
    )
```

The test controls time directly and patches nothing. A clock protocol is unnecessary unless obtaining time is itself a coherent dependency owned by the component.

## Narrow Capability Seam

A workflow that sends reminders may depend on a small `ReminderSink` capability that the workflow's own module defines. Production wires it to the real adapter at the composition boundary:

```python
"""Deliver the reminders that have not been delivered yet."""

from typing import Protocol
lazy from collections.abc import Sequence

from pydantic import BaseModel


class Reminder(BaseModel, frozen=True, extra="forbid"):
    """A reminder for one recipient.

    Attributes:
        identifier: Stable identifier of the reminder.
        recipient: Who the reminder is for.
        delivered: Whether the reminder has already been delivered.
    """

    identifier: str
    recipient: str
    delivered: bool


class ReminderSink(Protocol):
    """The one capability the reminder workflow needs from a delivery channel."""

    def insert_reminder(self, reminder: Reminder) -> None:
        """Deliver one reminder."""
        ...


def insert_undelivered_reminders(
    sink: ReminderSink,
    reminders: Sequence[Reminder],
) -> list[Reminder]:
    """Deliver every undelivered reminder and report which ones were sent.

    Args:
        sink: The channel that delivers one reminder.
        reminders: Every reminder, delivered or not.

    Returns:
        The reminders passed to ``sink``, in their original order.
    """
    undelivered_reminders = [
        reminder for reminder in reminders if not reminder.delivered
    ]
    for reminder in undelivered_reminders:
        sink.insert_reminder(reminder)
    return undelivered_reminders
```

Tests use a small, hand-written in-memory sink and assert the workflow result and the delivered reminders:

```python
"""Only undelivered reminders reach the delivery channel."""

from dataclasses import dataclass, field

from safety_judge.reminders import Reminder, insert_undelivered_reminders


@dataclass
class InMemoryReminderSink:
    reminders: list[Reminder] = field(default_factory=list[Reminder])

    def insert_reminder(self, reminder: Reminder) -> None:
        self.reminders.append(reminder)


def test_only_undelivered_reminders_are_sent() -> None:
    sink = InMemoryReminderSink()
    sent = Reminder(identifier="sent", recipient="a@example.test", delivered=True)
    pending = Reminder(
        identifier="pending",
        recipient="b@example.test",
        delivered=False,
    )

    delivered_reminders = insert_undelivered_reminders(sink, [sent, pending])

    assert delivered_reminders == [pending]
    assert sink.reminders == [pending], (
        "the sink should receive exactly the reminders that were not yet "
        f"delivered, but it received {[item.identifier for item in sink.reminders]}"
    )
```

This is stronger than injecting an HTTP client or an application-wide service container. The seam describes what the workflow needs, not how one provider currently performs it.

## Justified Interaction Test

An interaction assertion is appropriate when the interaction is the promise:

```python
"""A completed payment is never charged a second time."""

from dataclasses import dataclass, field

from safety_judge.payments import (
    PaymentStatus,
    create_payment_fixture,
    update_payment_after_retry,
)


@dataclass
class RecordingPaymentGateway:
    charge_attempts: list[str] = field(default_factory=list[str])

    def insert_charge(self, payment_identifier: str) -> None:
        self.charge_attempts.append(payment_identifier)


def test_retrying_a_completed_payment_issues_no_second_charge() -> None:
    gateway = RecordingPaymentGateway()
    payment = create_payment_fixture(
        identifier="payment-1",
        status=PaymentStatus.COMPLETED,
    )

    result = update_payment_after_retry(gateway, payment)

    assert result is PaymentStatus.ALREADY_COMPLETED
    assert gateway.charge_attempts == [], (
        "a completed payment must not issue another external charge; "
        f"attempts recorded for {payment.identifier}: {gateway.charge_attempts}"
    )
```

The non-interaction protects a dangerous external effect. It is not asserting incidental helper order or internal call count.

## Test Module Contract

Every file under `tests/` is its own module, imported by path under `--import-mode=importlib`. Start it with a one-line docstring that states the contract it exercises, and import the package by its public path:

```python
"""The settings boundary reports every failure as a package error."""

import pytest

from safety_judge.errors import ConfigurationError, SafetyJudgeError
from safety_judge.settings import select_application_settings


def test_an_invalid_setting_can_be_caught_as_the_package_root_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_JUDGE_LOGGING_LEVEL", "LOUD")

    with pytest.raises(SafetyJudgeError) as excinfo:
        _ = select_application_settings(environment_file_path=None)

    assert isinstance(excinfo.value, ConfigurationError), (
        "the settings boundary should raise ConfigurationError, the documented "
        f"subclass, but raised {type(excinfo.value).__name__}"
    )
```

Test the public contract through its public import path, not by importing private names merely because Python allows it.

## Repository Rule Test

Some contracts are rules about the code rather than behavior of one module. `tests/test_naming_conventions.py` is a good example of testing such a rule: it parses every source file with `ast`, collects the offending names, and fails with the vocabulary to use:

```python
assert checked_names > 0, (
    f"no functions found under {PACKAGE_SOURCE_DIRECTORY}; the scan path is wrong"
)
assert not offenders, (
    "start these functions with one of "
    f"{sorted(PERMITTED_FUNCTION_VERBS)}: {offenders}"
)
```

The first assertion makes a wrong scan path fail at once instead of passing over an empty list. The second names every offender and the repair, so the failure needs no explanation from the author.

## Deterministic Fixture Builder

A builder should make important state explicit and reject incomplete fixtures early:

```python
"""Reminder fixtures state the facts a test depends on and fix the rest."""

from typing import Final

from safety_judge.reminders import Reminder

FIXTURE_RECIPIENT: Final = "recipient@example.test"


def create_reminder_fixture(*, identifier: str, delivered: bool) -> Reminder:
    return Reminder(
        identifier=identifier,
        recipient=FIXTURE_RECIPIENT,
        delivered=delivered,
    )
```

A test calls `create_reminder_fixture(identifier="reminder-1", delivered=False)`. Omitting `delivered` raises `TypeError` while the test is arranged, and an invalid value raises the model's `ValidationError` at construction, so neither surfaces later as a confusing assertion failure. The builder removes hidden defaults from each test without hiding the scenario that matters. It calls the validating constructor rather than `model_construct`, so a fixture cannot hold a state production could never create.

## Dependency Fidelity

For a settings contract, prefer a real temporary file and a real, isolated process environment over patched file reads:

```python
"""The process environment wins over the environment file."""

lazy from pathlib import Path

lazy import pytest

from safety_judge.settings import LoggingLevel, select_application_settings


def insert_environment_file(directory: Path, text: str) -> Path:
    environment_file_path = directory / ".env"
    _ = environment_file_path.write_text(text, encoding="utf-8")
    return environment_file_path


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

    assert settings.logging_level is LoggingLevel.WARNING, (
        "the process environment should win over the file; "
        f"the file at {environment_file_path} set DEBUG and the level was "
        f"{settings.logging_level}"
    )
```

This proves the value read from a real file and a real process environment. `tests/conftest.py` already removes inherited `SAFETY_JUDGE_*` variables, so the developer's shell cannot change the outcome. The helper writes a file, so it uses the IO verb `insert`. The test does not freeze which internal reader or parser produced the value.
