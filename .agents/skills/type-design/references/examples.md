# Type Design Examples

Use these examples as labeled acceptance data. The decisive evidence above each excerpt determines its label.

Every snippet is a complete type-level excerpt. Its program units follow the repository's `document-code` contract so type design is the only labeled axis.

## External Library Boundaries

### NEGATIVE — A leaf claims a constraint the public API does not enforce

**Decisive evidence:** The public manager accepts every string, while the icon consumer casts that open value to a closed `Literal`. Callers can create an unsupported value, and the cast hides rather than establishes the invariant.

```python
from typing import Literal, cast

type ToastIconType = Literal["error", "info", "loading", "success", "warning"]
"""A presentation recognized by the application toast icon."""


def create_toast_icon_type(presentation: str | None) -> ToastIconType | None:
    """Claim an application icon type for a toast emitted by the external manager.

    Args:
        presentation: The unconstrained external presentation name.

    Returns:
        The asserted icon type when the external toast has one.
    """
    return cast("ToastIconType | None", presentation)
```

### POSITIVE — The application constrains its API and widens only at the adapter

**Decisive evidence:** The application owns one canonical presentation `Literal`, its public manager rejects other values, and the icon type is derived from that same model. The external `str` boundary remains visible only in `ExternalToastManager` and `create_toast_manager`.

```python
from typing import Literal, Protocol

type ToastType = Literal["success", "info", "warning", "error", "loading"]
"""A presentation supported by the application toast system."""

type ToastIconType = ToastType
"""The presentation consumed by the toast icon, derived from the same vocabulary."""


class ExternalToastManager(Protocol):
    """The external toast capability supplied by the library."""

    def insert_toast(self, *, title: str, presentation: str | None = None) -> str:
        """Add a toast using the library's extensible presentation name.

        Args:
            title: The external toast content.
            presentation: The open presentation name, or ``None`` for the default.

        Returns:
            The new toast identifier.
        """
        ...


class ToastManager(Protocol):
    """The application-owned view of the external toast manager."""

    def insert_toast(
        self,
        *,
        title: str,
        presentation: ToastType | None = None,
    ) -> str:
        """Add a toast using a presentation the application supports.

        Args:
            title: The toast content.
            presentation: The supported presentation, or ``None`` for the default.

        Returns:
            The new toast identifier.
        """
        ...


def create_toast_manager(external_manager: ExternalToastManager) -> ToastManager:
    """Narrow an external manager to the application contract.

    The external method accepts a superset of the application's presentations, so
    exposing only the narrower input preserves every runtime call it receives.

    Args:
        external_manager: The external manager hidden behind the application API.

    Returns:
        A manager that rejects unsupported presentations from callers.
    """
    return external_manager
```

## Domain Identifiers

### NEGATIVE — Aliases rename strings without making identities distinct

**Decisive evidence:** Both aliases remain structurally identical, so reversing the arguments still passes type checking.

```python
type UserIdentifier = str
"""A user identifier that remains interchangeable with every string."""

type ProductIdentifier = str
"""A product identifier that remains interchangeable with every string."""


def insert_product_assignment(
    user_identifier: UserIdentifier,
    product_identifier: ProductIdentifier,
) -> None:
    """Associate one product with one user.

    Args:
        user_identifier: The user receiving the product.
        product_identifier: The product assigned to the user.
    """
```

### POSITIVE — Adapters own distinct validated identities

**Decisive evidence:** Each adapter both validates the runtime UUID and produces a distinct `NewType`. The API receives named fields of those types, so swapping the values fails pyright before execution. The raw-value boundary is the adapters; no other code wraps a raw value in `UserIdentifier(...)`.

```python
from typing import Final, NewType
from uuid import UUID

from pydantic import BaseModel, TypeAdapter

UserIdentifier = NewType("UserIdentifier", UUID)
"""A validated identifier for one user."""

ProductIdentifier = NewType("ProductIdentifier", UUID)
"""A validated identifier for one product."""

USER_IDENTIFIER_ADAPTER: Final = TypeAdapter(UserIdentifier)
"""Validates user identifiers at their owning input boundary."""

PRODUCT_IDENTIFIER_ADAPTER: Final = TypeAdapter(ProductIdentifier)
"""Validates product identifiers at their owning input boundary."""


class ProductAssignment(BaseModel, frozen=True, extra="forbid"):
    """The identities required to assign a product.

    Attributes:
        product_identifier: The product being assigned.
        user_identifier: The user receiving the product.
    """

    product_identifier: ProductIdentifier
    user_identifier: UserIdentifier


def insert_product_assignment(assignment: ProductAssignment) -> None:
    """Associate one validated product with one validated user.

    Args:
        assignment: The distinct product and user identities.
    """
```

## Failure, State, And Absence

### NEGATIVE — Optional fields permit contradictory states

**Decisive evidence:** The local result can be successful without data, failed without an error, or contain data and an error together. `SaveProfileInput` also permits inputs this operation does not own, and `avatar: str | None = None` conflates an omitted stable field with a known absent value.

```python
from pydantic import BaseModel


class Profile(BaseModel, frozen=True, extra="forbid"):
    """A profile whose stable avatar field can silently default to absent.

    Attributes:
        avatar: The avatar location, or ``None`` when omitted or absent.
        display_name: The name shown to other users.
        identifier: The stable profile identifier.
    """

    display_name: str
    identifier: str
    avatar: str | None = None


class SaveResult(BaseModel, frozen=True, extra="forbid"):
    """A loose local result that permits contradictory branches.

    Attributes:
        data: The saved profile, when present.
        error: The failure description, when present.
        ok: Whether the save is claimed to have succeeded.
    """

    ok: bool
    data: Profile | None = None
    error: str | None = None


class SaveProfileInput(BaseModel, frozen=True, extra="forbid"):
    """An update that accidentally grants access to every profile field.

    Attributes:
        avatar: The avatar location, when supplied.
        display_name: The name shown to other users, when supplied.
        identifier: The stable profile identifier, when supplied.
    """

    avatar: str | None = None
    display_name: str | None = None
    identifier: str | None = None
```

### POSITIVE — Repository primitives express each valid branch

**Decisive evidence:** The stable profile always carries its avatar field, the operation accepts only fields it owns, failure is a documented `InvalidValueError` from the repository hierarchy instead of a result flag, and the tagged state exposes `profile` only where it exists. `create_profile_save_message` ends with `assert_never`, so adding a state fails type checking until it is handled.

```python
from typing import Annotated, Literal, Protocol, assert_never

from pydantic import BaseModel, Field


class Profile(BaseModel, frozen=True, extra="forbid"):
    """A loaded profile with an intentionally absent or present avatar.

    Attributes:
        avatar: The avatar location, or ``None`` when the profile has no avatar.
        display_name: The name shown to other users.
        identifier: The stable profile identifier.
    """

    avatar: str | None
    display_name: str
    identifier: str


class SaveProfileInput(BaseModel, frozen=True, extra="forbid"):
    """The profile fields owned by the save operation.

    Attributes:
        avatar: The avatar location, or ``None`` to save the profile without one.
        display_name: The name shown to other users.
    """

    avatar: str | None
    display_name: str


class IdleProfileSave(BaseModel, frozen=True, extra="forbid"):
    """No save has started."""

    kind: Literal["idle"] = "idle"


class SavingProfileSave(BaseModel, frozen=True, extra="forbid"):
    """A save is in progress."""

    kind: Literal["saving"] = "saving"


class SavedProfileSave(BaseModel, frozen=True, extra="forbid"):
    """A save finished and produced a profile.

    Attributes:
        profile: The profile as persisted.
    """

    kind: Literal["saved"] = "saved"
    profile: Profile


class FailedProfileSave(BaseModel, frozen=True, extra="forbid"):
    """A save failed with a repository error.

    Attributes:
        error_code: The stable ``code`` of the raised error.
        error_message: The ``message`` of the raised error.
    """

    kind: Literal["failed"] = "failed"
    error_code: str
    error_message: str


type ProfileSaveState = Annotated[
    IdleProfileSave | SavingProfileSave | SavedProfileSave | FailedProfileSave,
    Field(discriminator="kind"),
]
"""The complete set of valid profile-save states."""


class ProfileStore(Protocol):
    """The persistence capability for editable profile fields."""

    def update_profile(self, save_input: SaveProfileInput) -> Profile:
        """Persist the editable profile fields.

        Args:
            save_input: The avatar and display name accepted by this operation.

        Returns:
            The saved profile.

        Raises:
            InvalidValueError: When the display name is not accepted.
        """
        ...


def create_profile_save_message(state: ProfileSaveState) -> str:
    """Create the status line for one profile-save state.

    Args:
        state: The current state of the save operation.

    Returns:
        A sentence describing the state.
    """
    match state:
        case IdleProfileSave():
            return "Nothing has been saved."
        case SavingProfileSave():
            return "Saving the profile."
        case SavedProfileSave(profile=profile):
            return f"Saved {profile.display_name}."
        case FailedProfileSave(error_message=error_message):
            return error_message
        case _:
            assert_never(state)
```
