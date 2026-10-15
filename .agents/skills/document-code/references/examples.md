# Code Documentation Examples

Use these examples as labeled acceptance data. The text immediately above each snippet states the evidence that determines its label.

## Models, callbacks, and services

### NEGATIVE — Polished restatement leaves the contract undocumented

**Decisive evidence:** The class and attribute entries merely repeat their names. The function repeats annotations in its `Args:` and `Returns:` entries, says nothing about what the label looks like, and adds a `See Also:` entry that conveys nothing beyond the signature.

```python
class ProfileSettings(BaseModel, frozen=True, extra="forbid"):
    """The ProfileSettings model.

    Attributes:
        display_name: The display name.
        username: The username.
    """

    display_name: str
    username: str


def create_username_label(profile: ProfileSettings) -> str:
    """Create the username label.

    Args:
        profile (ProfileSettings): The profile.

    Returns:
        str: The label.

    See Also:
        ``ProfileSettings``
    """
    return f"@{profile.username}"
```

### POSITIVE — The class docstring owns the model's constructor contract

**Decisive evidence:** The model has a generated constructor, so its class docstring is where callers learn what each keyword argument means, and no second constructor description exists. Each `Attributes:` entry adds domain meaning that the summary does not already establish. The constant names the layers that must agree, and the alias states the normalization it applies.

```python
from typing import Annotated, Final

from pydantic import BaseModel, StringConstraints

MAXIMUM_USERNAME_LENGTH: Final = 32
"""The largest username accepted by both profile validation and the account table."""

type Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=MAXIMUM_USERNAME_LENGTH,
    ),
]
"""A trimmed, lowercase handle that fits within ``MAXIMUM_USERNAME_LENGTH``."""


class ProfileSettings(BaseModel, frozen=True, extra="forbid"):
    """The public identity a person chooses to show on their profile.

    The constructor is generated, so the attributes are its keyword arguments, and
    every construction path validates them.

    Attributes:
        display_name: The name shown to others; it need not be unique.
        username: The handle others use to mention the person, already lowercase.
    """

    display_name: str
    username: Username
```

### POSITIVE — A callback type states its capability and completion guarantee

**Decisive evidence:** A `Callable[...]` alias has no `Args:` section, so the attribute docstring defines the capability, the meaning of each argument in order, and what completing the awaited call guarantees to every caller that supplies the callback.

```python
lazy from collections.abc import Awaitable, Callable

from pydantic import BaseModel


class ProfileSettings(BaseModel, frozen=True, extra="forbid"):
    """The public identity a person chooses to show on their profile."""

    display_name: str
    username: str


type ProfileWriter = Callable[[str, ProfileSettings], Awaitable[None]]
"""The capability to store a validated profile for one person.

The first argument identifies the person whose profile is changing, and the second
is the validated identity to store. Awaiting the call completes once later reads can
observe the saved values.
"""
```

### POSITIVE — A standalone class owns its reusable boundary

**Decisive evidence:** This protocol is consumed independently of any one caller. Its docstring defines the persistence boundary, while the method docstring records the non-obvious completion guarantee once for every caller. The method returns `None`, so it has no `Returns:` section.

```python
from typing import Protocol

from pydantic import BaseModel


class ProfileSettings(BaseModel, frozen=True, extra="forbid"):
    """The public identity a person chooses to show on their profile."""

    display_name: str
    username: str


class ProfileRepository(Protocol):
    """The persistence operations available for a person's public profile."""

    async def update_profile(
        self,
        user_identifier: str,
        profile: ProfileSettings,
    ) -> None:
        """Update the stored public identity of one person.

        When the awaited call returns, later reads observe the saved values.

        Args:
            user_identifier: The person whose public identity is changing.
            profile: The validated name and username to store.
        """
```

## Private helpers and module constants

### NEGATIVE — Documentation decorates names without adding a contract

**Decisive evidence:** These docstrings only turn identifiers into sentences. They do not state which layers share the limit or what normalization guarantees. Ruff accepts both: it checks that the helper's sections are present but not what they say, and it never inspects the constant's docstring, so only review rejects them.

```python
MAXIMUM_USERNAME_LENGTH: Final = 32
"""The maximum username length."""


def _create_normalized_username(raw_text: str) -> str:
    """Normalize a username.

    Args:
        raw_text: The username.

    Returns:
        The normalized username.
    """
    return raw_text.strip().lower()
```

### POSITIVE — Concise docstrings explain system role and guarantee

**Decisive evidence:** The constant identifies the consumers that must agree. The helper documents its input meaning and exact semantic result without optional section filler, and its own name does not already say any of it.

```python
from typing import Final

MAXIMUM_USERNAME_LENGTH: Final = 32
"""The largest username accepted by both profile validation and the account table."""


def _create_normalized_username(raw_text: str) -> str:
    """Create the comparison form of a username.

    Args:
        raw_text: The username exactly as entered by the person.

    Returns:
        The trimmed, lowercase username used for validation and uniqueness.
    """
    return raw_text.strip().lower()


def remove_oversized_usernames(raw_texts: list[str]) -> list[str]:
    """Remove the usernames that exceed the length limit and normalize the rest.

    Args:
        raw_texts: Usernames exactly as entered by people.

    Returns:
        The normalized usernames within ``MAXIMUM_USERNAME_LENGTH``, in input order.
    """
    normalized_usernames = [
        _create_normalized_username(raw_text) for raw_text in raw_texts
    ]
    return [
        username
        for username in normalized_usernames
        if len(username) <= MAXIMUM_USERNAME_LENGTH
    ]
```

## Overloaded functions

### NEGATIVE — Stub docstrings obscure distinct contracts and leave the implementation bare

**Decisive evidence:** Ruff D418 rejects a docstring on each `@overload` stub, and D103 rejects the undocumented implementation. Even without lint, the two identical docstrings never say which form accepts what or which result each guarantees.

```python
@overload
def create_profile(value: str) -> Profile:
    """Create a profile."""


@overload
def create_profile(value: Mapping[str, str]) -> PartialProfile:
    """Create a profile."""


def create_profile(value: str | Mapping[str, str]) -> Profile | PartialProfile: ...
```

### POSITIVE — The implementation docstring owns each public form's contract

**Decisive evidence:** The stubs stay bare because ruff forbids documenting them, so the implementation docstring is the one place callers read. It states each form's accepted input, its result guarantee, and the failure that escapes, once each. It does not describe the union signature as a third contract.

```python
from typing import overload
lazy from collections.abc import Mapping

from pydantic import BaseModel

from safety_judge.errors import InvalidValueError


class Profile(BaseModel, frozen=True, extra="forbid"):
    """A person's public identity with every field present."""

    name: str
    username: str


class PartialProfile(BaseModel, frozen=True, extra="forbid"):
    """The profile fields a person submitted; a field not submitted is ``None``."""

    name: str | None = None
    username: str | None = None


@overload
def create_profile(value: str) -> Profile: ...


@overload
def create_profile(value: Mapping[str, str]) -> PartialProfile: ...


def create_profile(value: str | Mapping[str, str]) -> Profile | PartialProfile:
    """Create a profile from its compact serialized form or from submitted fields.

    Each public form has its own contract, and both lowercase the username:

    * ``str``: A pipe-delimited ``name|username`` pair. Both parts are required.
    * ``Mapping[str, str]``: Submitted form fields. A missing field is not an error.

    Args:
        value: The serialized pair or the submitted fields.

    Returns:
        A complete ``Profile`` for a string, or a ``PartialProfile`` holding only
        the non-empty fields for a mapping.

    Raises:
        InvalidValueError: When a string lacks the name or the username.
    """
    if isinstance(value, str):
        name, _, username = value.partition("|")
        if not name or not username:
            message = (
                "A serialized profile must be 'name|username' with both parts "
                f"present, but received {value!r}. Provide both parts."
            )
            raise InvalidValueError(message, context={"constraint": "name|username"})
        return Profile(name=name, username=username.lower())
    submitted_username = value.get("username")
    return PartialProfile(
        name=value.get("name") or None,
        username=submitted_username.lower() if submitted_username else None,
    )
```

## Optional sections

### NEGATIVE — Optional sections are present only to look complete

**Decisive evidence:** The relationship is already obvious from the parameter annotation, the usage is ordinary, and nothing is raised, so `Raises: Never.` documents a failure that does not exist. These sections add no navigation or contract information.

````python
def create_label_length(label: TextLabel) -> int:
    """Create the length of a label.

    Args:
        label: The label.

    Returns:
        The length.

    See Also:
        ``TextLabel``

    Example:
        ```python
        length = create_label_length(label)
        ```

    Raises:
        Never.
    """
    return len(label.text)
````

### POSITIVE — Optional sections appear only where they change understanding

**Decisive evidence:** The `See Also:` entry names the parser that enforces the stored text's bounds, a real composition relationship. Ordinary usage needs no `Example:`. A missing file is described as a `None` result rather than a fictional exception. The failure that merely propagates from the callee is stated in prose, because ruff DOC502 rejects a `Raises:` entry for an exception the body does not raise itself.

```python
lazy from pathlib import Path

from safety_judge.example_text_label import TextLabel, create_text_label


def select_stored_text_label(label_path: Path) -> TextLabel | None:
    """Select the label stored in a text file.

    A missing file is an expected outcome, so it is reported as ``None``. A file
    whose text violates the label bounds raises ``InvalidValueError`` from
    ``create_text_label`` unchanged.

    Args:
        label_path: The file that holds the label text.

    Returns:
        The stored label, or ``None`` when the file does not exist.

    See Also:
        ``safety_judge.example_text_label.create_text_label``: Parses the stored
            text and enforces the label bounds.
    """
    if not label_path.is_file():
        return None
    return create_text_label(label_path.read_text(encoding="utf-8"))
```

## Consequential learned constraints

### NEGATIVE — Incident history assumes context the reader does not have

**Decisive evidence:** The docstring names an earlier module-level instance and a bug instead of explaining the two current lifecycle rules that make call-time construction necessary. Even with useful links, a first-time reader must reconstruct the causal chain.

```python
def select_judge_endpoint_settings() -> JudgeEndpointSettings:
    """Replace the module-level settings that went stale in tests.

    This fixes the missing-variable bug by constructing the settings later.

    Returns:
        The judge endpoint settings read from the process environment.

    See Also:
        https://docs.pydantic.dev/latest/concepts/pydantic_settings/
        https://github.com/pydantic/pydantic-settings/blob/v2.16.0/pydantic_settings/sources/providers/env.py#L87-L97
    """
    return JudgeEndpointSettings()
```

### POSITIVE — Present facts make the current design self-contained

**Decisive evidence:** The docstring states when pydantic-settings reads the environment and what that requires of the construction site, without referring to any earlier implementation. Canonical documentation and pinned source let the reader verify the external rule.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class JudgeEndpointSettings(BaseSettings):
    """Settings for the judge endpoint, read from ``SAFETY_JUDGE_ENDPOINT_*``."""

    model_config = SettingsConfigDict(env_prefix="SAFETY_JUDGE_ENDPOINT_", frozen=True)

    deployment_name: str = "judge-small"


def select_judge_endpoint_settings() -> JudgeEndpointSettings:
    """Select the judge endpoint settings from the environment as it is at call time.

    ``pydantic-settings`` reads the process environment while a settings model is
    constructed, not when its class is defined. Constructing the model on every call
    lets a variable set by a test fixture or an entry point apply, whereas a
    module-level instance would keep the values present at import.

    Returns:
        Immutable settings that reflect the environment at the time of the call.

    See Also:
        https://docs.pydantic.dev/latest/concepts/pydantic_settings/
        https://github.com/pydantic/pydantic-settings/blob/v2.16.0/pydantic_settings/sources/providers/env.py#L87-L97
    """
    return JudgeEndpointSettings()
```

### NEGATIVE — A local comment repeats policy already owned elsewhere

**Decisive evidence:** `Path` makes the selected primitive visible, while ruff's PTH rules already enforce that choice. The inline comment adds no local constraint or causal knowledge.

```python
from pathlib import Path

# Uses pathlib because ruff forbids os.path.
environment_file_path = Path(".env")
```

### POSITIVE — Self-evident, enforced policy needs no local commentary

**Decisive evidence:** The `Path` primitive is directly visible and no unusual local behavior depends on the choice, so the code is the clearest explanation.

```python
from pathlib import Path

environment_file_path = Path(".env")
```

## Authoritative source links

### NEGATIVE — A generic homepage does not explain the sourced behavior

**Decisive evidence:** The docstring claims a vocabulary owned by the standard library but links only to a homepage. A reader still has to rediscover the relevant documentation and cannot verify which release the local values mirror.

```python
class LoggingLevel(StrEnum):
    """The logging levels.

    See Also:
        https://www.python.org
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
```

### POSITIVE — Documentation and versioned source make provenance verifiable

**Decisive evidence:** The canonical documentation explains the supported public behavior. The versioned source permalink proves the exact names mirrored by this repository, including the aliases and the sentinel that the enum deliberately omits.

```python
from enum import StrEnum


class LoggingLevel(StrEnum):
    """A severity threshold, spelled as the standard library's level names.

    The members are the five severities that ``logging`` predefines. ``FATAL`` and
    ``WARN`` are omitted because they alias members, and ``NOTSET`` is omitted
    because it asks a logger to defer to its parent instead of naming a severity.

    See Also:
        https://docs.python.org/3/library/logging.html#logging-levels
        https://github.com/python/cpython/blob/v3.15.0/Lib/logging/__init__.py#L95-L121
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
```

## Docstring format

### NEGATIVE — A multi-line docstring hides the one-sentence shape

**Decisive evidence:** Even a correct sentence uses the three-line form, which makes docstrings visually inconsistent. Ruff D200 and D212 reject the same shape on a function or class docstring; ruff does not inspect attribute docstrings, so review is the check here.

```python
MAXIMUM_USERNAME_LENGTH: Final = 32
"""
The largest username accepted by the authentication boundary.
"""
```

### POSITIVE — One sentence stays on one line

**Decisive evidence:** The docstring is one sentence, so it is one line. Sections appear only when a contract needs them, as in the helper and function examples above.

```python
from typing import Final

MAXIMUM_USERNAME_LENGTH: Final = 32
"""The largest username accepted by the authentication boundary."""
```
