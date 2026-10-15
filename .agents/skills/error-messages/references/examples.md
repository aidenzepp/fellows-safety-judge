# Error Message Examples

These examples combine guidance from Wix UX, Google Technical Writing, Google AIP-193, and Material Design.

## UI Modal

Weak:

```text
Whoops! Something went wrong.
The third-party you are trying to connect to is not responding, so we can't fetch your data. Try again later.
```

Problems:

- cute tone
- passes blame to another provider
- uses implementation wording like "fetch"
- gives no confidence about saved state
- offers no fallback if retry fails

Better:

```text
Unable to connect your account
Your changes were saved, but we could not connect the account because the provider is unavailable. Try again later, or contact support if this keeps happening.
```

Why it works:

- says what happened
- explains why at the right level
- reassures the user
- offers a fix and fallback

## Inline Form Validation

Weak:

```text
Invalid postal code.
```

Better:

```text
Enter a 5-digit ZIP code
```

Better when the surface can show more detail:

```text
The ZIP code must be 5 digits. You entered 4872953.
```

Do not show the error before the user interacts with the field or submits the form. Preserve the user's input so they can fix it.

## Permissions

Weak:

```text
Permission denied.
```

Better for an end-user UI:

```text
You need billing access to download invoices. Ask an account owner to update your role.
```

Better for an API:

```json
{
  "error": {
    "code": 403,
    "status": "PERMISSION_DENIED",
    "message": "You need billing.viewer access to download invoice inv_123.",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "MISSING_REQUIRED_ROLE",
        "domain": "billing.example.com",
        "metadata": {
          "resource": "invoices/inv_123",
          "requiredRole": "billing.viewer"
        }
      }
    ]
  }
}
```

## Quota Or Limit

Weak:

```text
Quota exceeded.
```

Better:

```text
You requested 2 CPUs, which exceeds your quota of 1 CPU in us-central-1. Request a quota increase or choose a region with available quota.
```

## CLI Error

Weak:

```text
Could not read config.
```

Better:

```text
Cannot read config file at /app/config.yml: permission denied. Give the current user read access or pass --config with a readable file.
```

Code shape:

```python
from typing import ClassVar
lazy from pathlib import Path

from safety_judge.errors import ConfigurationError


class ConfigurationFileUnreadableError(ConfigurationError):
    """A configuration file exists but the current user cannot read it."""

    code: ClassVar[str] = "configuration_file_unreadable"


def select_configuration_text(configuration_path: Path) -> str:
    """Select the text of the configuration file.

    Args:
        configuration_path: The file to read.

    Returns:
        The file's text.

    Raises:
        ConfigurationFileUnreadableError: When the operating system denies read
            access.
    """
    try:
        return configuration_path.read_text(encoding="utf-8")
    except PermissionError as permission_error:
        message = (
            f"Cannot read config file at {configuration_path}: permission denied. "
            "Give the current user read access or pass --config with a readable file."
        )
        raise ConfigurationFileUnreadableError(
            message,
            context={
                "configuration_path": str(configuration_path),
                "reason": "permission denied",
            },
        ) from permission_error
```

## API Validation Code Pattern

Prefer distinct, structured violations over one generic validation message.

Weak:

```python
from http import HTTPStatus

lazy from safety_judge.error_payload import JsonValue


def create_weak_invalid_request_response() -> tuple[dict[str, JsonValue], int]:
    """Create the response for an invalid request.

    Returns:
        The response body and its HTTP status.
    """
    return {"error": "Invalid request"}, HTTPStatus.BAD_REQUEST
```

Better:

```python
from http import HTTPStatus

lazy from safety_judge.error_payload import JsonValue


def create_invalid_request_response() -> tuple[dict[str, JsonValue], int]:
    """Create the response that names each invalid field and its constraint.

    Returns:
        The response body and its HTTP status.
    """
    body: dict[str, JsonValue] = {
        "error": {
            "code": "INVALID_ARGUMENT",
            "message": "The request has 2 invalid fields.",
            "details": [
                {
                    "reason": "FIELD_VIOLATION",
                    "field_violations": [
                        {
                            "field": "email",
                            "description": (
                                "Enter an email address that includes @ and a domain."
                            ),
                        },
                        {
                            "field": "seat_count",
                            "description": (
                                "Seat count must be between 1 and 50. You entered 72."
                            ),
                            "context": {"min": 1, "max": 50, "actual": 72},
                        },
                    ],
                },
            ],
        },
    }
    return body, HTTPStatus.BAD_REQUEST
```

## Separate Project Example: Billing CSV Import

Scenario: a SaaS billing app lets account admins upload a CSV of customer invoices.

Before:

```text
Upload failed. Invalid file.
```

```text
Bad date.
```

```json
{
  "error": "CSV validation failed"
}
```

Problems:

- generic
- no row or field location
- no preserved-state reassurance
- no constraint
- no stable machine-readable detail for branching or automation

Better UI summary:

```text
We couldn't import 12 invoices because some rows need fixes. Your file is saved as a draft.
```

Better inline row error near `due_date`:

```text
Due date must be after the invoice date. Change row 8 to a date after May 14, 2026.
```

Recovery actions:

```text
Fix rows in draft
Download error report
Cancel import
```

Better API response:

```json
{
  "code": "invoice_import_validation_failed",
  "message": "Some invoice rows need fixes before import.",
  "details": [
    {
      "code": "due_date_before_invoice_date",
      "row": 8,
      "field": "due_date",
      "message": "Due date must be after the invoice date.",
      "context": {
        "min_exclusive": "2026-05-14"
      }
    }
  ],
  "context": {
    "draft_import_id": "imp_7x92",
    "uploaded_file_name": "may-invoices.csv",
    "rejected_rows": 12,
    "available_actions": ["edit_draft", "download_report"]
  }
}
```

Code representation:

```python
from pydantic import BaseModel

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)
"""Any value that survives a round trip through JSON."""


class ErrorPayload[DetailT: BaseModel](BaseModel, frozen=True, extra="forbid"):
    """The error shape sent across an API, UI, CLI, or SDK boundary.

    Attributes:
        code: Stable machine-readable category.
        message: Safe, audience-appropriate human text for this boundary.
        details: Repeated or item-specific repair data, such as fields, rows,
            missing permissions, or violated limits.
        context: Curated whole-error state, such as preserved draft identifiers,
            the affected resource, a retry time, or available actions.
    """

    code: str
    message: str
    details: tuple[DetailT, ...]
    context: dict[str, JsonValue] | None = None
```

```python
lazy from datetime import date

from pydantic import BaseModel

from safety_judge.error_payload import ErrorPayload, JsonValue


class ImportErrorDetail(BaseModel, frozen=True, extra="forbid"):
    """One invoice row that needs a fix before the import can finish."""

    code: str
    row: int
    field: str
    message: str
    context: dict[str, JsonValue] | None = None


type ImportErrorResponse = ErrorPayload[ImportErrorDetail]
"""The payload returned when an invoice import fails on specific rows."""


def create_due_date_before_invoice_date_detail(
    row: int,
    invoice_date: date,
) -> ImportErrorDetail:
    """Create the detail for a due date that does not follow its invoice date.

    Args:
        row: The one-based row of the invoice in the uploaded file.
        invoice_date: The date the due date must come after.

    Returns:
        The row-level repair data.
    """
    return ImportErrorDetail(
        code="due_date_before_invoice_date",
        row=row,
        field="due_date",
        message="Due date must be after the invoice date.",
        context={"min_exclusive": invoice_date.isoformat()},
    )


def create_import_error_summary(error: ImportErrorResponse) -> str:
    """Create the text shown above the rows that need fixes.

    Args:
        error: The import failure, including its preserved draft.

    Returns:
        A summary line, the saved draft, and one line per row that needs a fix.
    """
    draft_name = error.context["uploaded_file_name"] if error.context else "unknown"
    lines = [error.message, f"Your file is saved as a draft: {draft_name}."]
    lines.extend(
        f"Row {detail.row}, {detail.field}: {detail.message}"
        for detail in error.details
    )
    return "\n".join(lines)
```

Why it works:

- says what happened: some invoice rows could not be imported
- says why: the due date violates a specific constraint
- says what was preserved: the upload is saved as a draft
- says how to fix it: edit row 8 and choose a due date after the invoice date
- gives a way out: download the report or cancel the import
- keeps prose human-facing while giving machines stable `code`, `field`, `row`, and contextual constraint values

## Boundary Payload Pattern

Use a small payload at presentation boundaries rather than making every internal error type carry every possible field:

```python
from pydantic import BaseModel

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)
"""Any value that survives a round trip through JSON."""


class ErrorPayload[DetailT: BaseModel](BaseModel, frozen=True, extra="forbid"):
    """The error shape sent across an API, UI, CLI, or SDK boundary.

    Attributes:
        code: Stable machine-readable category.
        message: Safe, audience-appropriate human text for this boundary.
        details: Repeated or item-specific repair data, such as fields, rows,
            missing permissions, or violated limits.
        context: Curated whole-error state, such as preserved draft identifiers,
            the affected resource, a retry time, or available actions.
    """

    code: str
    message: str
    details: tuple[DetailT, ...]
    context: dict[str, JsonValue] | None = None
```

Example:

```python
from pydantic import BaseModel

from safety_judge.error_payload import ErrorPayload, JsonValue


class FieldViolation(BaseModel, frozen=True, extra="forbid"):
    """One field that failed validation and why."""

    field: str
    reason: str
    message: str
    context: dict[str, JsonValue] | None = None


def create_invoice_import_error() -> ErrorPayload[FieldViolation]:
    """Create the payload for an invoice import that needs fixes.

    Returns:
        The boundary payload for the failed import.
    """
    return ErrorPayload[FieldViolation](
        code="invoice_import_validation_failed",
        message=(
            "We couldn't import 12 invoices because some rows need fixes. "
            "Your file is saved as a draft."
        ),
        details=(
            FieldViolation(
                field="due_date",
                reason="before_invoice_date",
                message="Due date must be after the invoice date.",
                context={"row": 8, "min_exclusive": "2026-05-14"},
            ),
        ),
        context={
            "draft_import_id": "imp_7x92",
            "uploaded_file_name": "may-invoices.csv",
            "rejected_rows": 12,
            "available_actions": ["edit_draft", "download_report"],
        },
    )
```

Use `details` for repeated or item-specific repair facts. Use `context` for facts that apply to the whole error. Do not add optional top-level fields unless the API already standardizes them.

## Python Boundary Example

In Python, raise ordinary exceptions from the `SafetyJudgeError` hierarchy where the failure is found, and render the boundary payload later.

```python
from http import HTTPStatus
from typing import ClassVar, override
lazy from collections.abc import Collection, Sequence

from pydantic import BaseModel

from safety_judge.error_payload import ErrorPayload
from safety_judge.errors import InvalidValueError, SafetyJudgeError


class FieldViolation(BaseModel, frozen=True, extra="forbid"):
    """One field that failed validation and why."""

    field: str
    reason: str
    message: str


class WorkspaceValidationError(SafetyJudgeError):
    """Workspace details failed validation.

    Attributes:
        violations: Every field that needs a fix, for the boundary to render.
    """

    code: ClassVar[str] = "workspace_validation_failed"

    @override
    def __init__(self, violations: Sequence[FieldViolation]) -> None:
        """Create the error from the violations found.

        Args:
            violations: Every field that needs a fix.
        """
        super().__init__("Workspace details need fixes.")
        self.violations = tuple(violations)


class WorkspaceNameTakenError(InvalidValueError):
    """The requested workspace name already belongs to another workspace."""

    code: ClassVar[str] = "workspace_name_taken"


def create_workspace_name(name: str, existing_names: Collection[str]) -> str:
    """Create the trimmed name of a new workspace.

    Args:
        name: The name as entered.
        existing_names: Names already in use.

    Returns:
        The trimmed name.

    Raises:
        WorkspaceValidationError: When the name is blank.
        WorkspaceNameTakenError: When another workspace already uses the name.
    """
    trimmed_name = name.strip()
    if not trimmed_name:
        blank_name = FieldViolation(
            field="name",
            reason="required",
            message="Enter a workspace name.",
        )
        raise WorkspaceValidationError([blank_name])
    if trimmed_name in existing_names:
        message = f"Workspace name {trimmed_name!r} is already in use."
        raise WorkspaceNameTakenError(message, context={"name": trimmed_name})
    return trimmed_name


def create_workspace_problem(
    error: Exception,
) -> tuple[HTTPStatus, ErrorPayload[FieldViolation]]:
    """Create the HTTP status and payload that present a failure to the caller.

    Args:
        error: The failure raised while creating a workspace.

    Returns:
        The status and the boundary payload.
    """
    if isinstance(error, WorkspaceValidationError):
        return HTTPStatus.BAD_REQUEST, ErrorPayload[FieldViolation](
            code=error.code,
            message="Workspace details need fixes.",
            details=error.violations,
        )
    if isinstance(error, WorkspaceNameTakenError):
        return HTTPStatus.CONFLICT, ErrorPayload[FieldViolation](
            code=error.code,
            message="Workspace name is already in use. Choose a different name.",
            details=(),
        )
    return HTTPStatus.INTERNAL_SERVER_ERROR, ErrorPayload[FieldViolation](
        code="unexpected_error",
        message="Unable to create workspace. Try again later.",
        details=(),
    )
```

The service code raises compact errors that carry facts (`violations`, `context`) and a stable `code`. Only `create_workspace_problem` knows about HTTP statuses and human sentences, so a CLI or SDK boundary can render the same errors differently.

## Quick Rewrite Table

| Weak | Better |
| --- | --- |
| Something went wrong | We could not save the report. Your edits are still open. Try saving again. |
| Invalid input | Enter a date in MM/DD/YYYY format |
| Failed | Upload failed because the file is larger than 10 MB |
| Network error | You are offline. Reconnect to keep editing shared documents. |
| Access denied | Only workspace admins can invite new members |
| Try again later | The payment provider is unavailable. Try again in a few minutes or use a different payment method. |
