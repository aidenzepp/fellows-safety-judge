# Parse, Don't Validate

Use this guide when code checks raw input but keeps using the same weak representation afterward.

## The Information Test

Validation and parsing may perform the same runtime check. Their contracts differ.

### NEGATIVE — The validator discards what it learned

```python
lazy from collections.abc import Sequence

from safety_judge.errors import InvalidValueError


def validate_non_empty(values: Sequence[object]) -> None:
    """Raise when ``values`` is empty, then forget that it was checked.

    Args:
        values: The values to check.

    Raises:
        InvalidValueError: When ``values`` is empty.
    """
    if not values:
        message = "At least one value is required. Provide a non-empty sequence."
        raise InvalidValueError(message, context={"actual_length": 0})


def create_first_value[T](values: Sequence[T]) -> T:
    """Create the first of ``values``, trusting an earlier check that is not visible.

    Args:
        values: The values, assumed to have passed ``validate_non_empty``.

    Returns:
        The first value.
    """
    return values[0]
```

`validate_non_empty` is named for what is criticised; the verb `validate` is outside the repository's vocabulary, so `tests/test_naming_conventions.py` would reject it in the package. The function returns `None` and the caller keeps the original sequence, so `create_first_value` cannot know the check ran. It either trusts undocumented history and fails with `IndexError`, or repeats the check. An `is_valid_*` function that returns a `bool` discards the same information.

### POSITIVE — The parser returns a representation that preserves the fact

```python
from typing import Annotated
lazy from collections.abc import Sequence

from pydantic import BaseModel, Field, ValidationError

from safety_judge.errors import InvalidValueError


class NonEmptyValues[T](BaseModel, frozen=True, extra="forbid"):
    """A tuple that is never empty, so taking its first item cannot fail.

    Attributes:
        items: The values, with at least one present.
    """

    items: Annotated[tuple[T, ...], Field(min_length=1)]

    @property
    def first_item(self) -> T:
        """The first item, which exists because ``items`` is never empty.

        Returns:
            The first value of ``items``.
        """
        return self.items[0]


def create_non_empty_values[T](values: Sequence[T]) -> NonEmptyValues[T]:
    """Create a never-empty tuple of values from an untrusted sequence.

    Args:
        values: The values to keep, at least one.

    Returns:
        The values as a tuple that is guaranteed to be non-empty.

    Raises:
        InvalidValueError: When ``values`` is empty; ``__cause__`` holds the
            underlying validation error.
    """
    try:
        return NonEmptyValues(items=tuple(values))
    except ValidationError as validation_error:
        message = "At least one value is required. Provide a non-empty sequence."
        raise InvalidValueError(
            message,
            context={"actual_length": len(values)},
        ) from validation_error
```

The validator returns `None` and discards what it learned. The parser returns a representation that preserves the fact. Downstream code accepting `NonEmptyValues[T]` can read `first_item` without a failure path because emptiness is no longer representable.

Treat parsing as the conversion of less-structured data into more-structured data. Its input need not be text. Useful parse boundaries include:

- primitive to domain value
- raw collection to invariant-bearing collection
- deserialized record to domain entity
- database row to restored aggregate
- framework request to application command
- bytes or foreign values to safe native representations

## Boundary Shape

Keep weak data and fallibility at the edge. Signatures only; docstrings are omitted from this sketch.

```python
def create_request(raw_request: Mapping[str, object]) -> Request: ...


def create_execution_result(request: Request, state: State) -> ExecutionResult: ...
```

Do not spread the original parse error through `create_execution_result` when `Request` already proves the relevant facts. A different operational error may still be legitimate. `select_application_settings` in `safety_judge.settings` is the repository's worked boundary: it turns environment text into a frozen `ApplicationSettings`, wraps pydantic's `ValidationError` in a `ConfigurationError`, and every other function receives the trusted value.

In this repository, common parser shapes are:

- `Model.model_validate(raw_mapping)` for a mapping or object from a deserializer, and `Model.model_validate_json(text)` for JSON text
- `TypeAdapter(...).validate_python(raw)` and `.validate_json(text)` for types that are not models, such as a constrained primitive, a list of models, or a union
- `pydantic-settings` `BaseSettings` for environment variables and dotenv files, as in `select_application_settings`
- a named `create_*` function that wraps `ValidationError` in `InvalidValueError`, as `create_text_label` does, when callers need the repository's error `code` and `context`
- validators (`AfterValidator`, `field_validator`, `model_validator`) on the model itself, so `model_validate_json` and direct construction run the same parser

Configure the model to refuse what the domain does not allow: `extra="forbid"` rejects unknown fields instead of dropping them, and `frozen=True` forbids reassignment after validation. Do not add an alternate path that skips validation for an invariant-bearing type, such as a `from_raw` classmethod, `model_construct`, or `model_copy(update=...)`.

Pydantic's default lax mode is itself a coercion policy: it turns `"8080"` into `8080` and `True` into `1`. Use strict mode where the domain says those are different values.

### POSITIVE — A strict boundary rejects ambiguous input

```python
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, ValidationError

type PortNumber = Annotated[int, Field(strict=True, ge=1_024, le=65_535)]
"""An unprivileged TCP port number; strict, so text and booleans are not coerced."""


class ListenAddress(BaseModel, frozen=True, extra="forbid"):
    """Where a server listens.

    Attributes:
        port: The unprivileged TCP port number.
    """

    port: PortNumber


@pytest.mark.parametrize(
    "raw_text",
    [
        '{"port": "8080"}',
        '{"port": 80}',
        '{"port": 8080, "host": "localhost"}',
    ],
)
def test_an_ambiguous_listen_address_is_rejected(raw_text: str) -> None:
    with pytest.raises(ValidationError):
        _ = ListenAddress.model_validate_json(raw_text)
```

The first input is text where a number belongs, the second is a privileged port, and the third carries an unknown field.

## Choose the Right Proof Owner

### Value owns the proof

Use a domain value when the fact is intrinsic and should travel. Signatures only; docstrings are omitted from this sketch.

```python
def create_reflection(incident: Vector3, normal: UnitVector3) -> Vector3: ...


def create_pool_with_released_port(
    free_ports: frozenset[NonPrivilegedPort],
    port: NonPrivilegedPort,
) -> frozenset[NonPrivilegedPort]: ...


def create_asset_type_match(
    catalog: Mapping[AssetName, AssetType],
    name: AssetName,
    expected: AssetType,
) -> bool: ...
```

These signatures remove invalid calls and corresponding error branches from trusted code. The types are defined in [examples.md](examples.md) and in the normalization section below.

### Aggregate owns the proof

Use a frozen aggregate when the rule is meaningful only inside the aggregate:

```python
from collections.abc import Mapping
from typing import Annotated, NewType

from pydantic import AfterValidator, BaseModel

NodeIdentifier = NewType("NodeIdentifier", str)
"""The identity of one node in a dependency graph."""

type EdgeTable = Mapping[NodeIdentifier, frozenset[NodeIdentifier]]
"""The nodes that each node depends on."""


def create_edges_with_known_targets(edges: EdgeTable) -> EdgeTable:
    """Check that every dependency points at a node the graph contains.

    Args:
        edges: The dependencies of each node.

    Returns:
        ``edges`` unchanged, which is the shape a pydantic validator returns.

    Raises:
        ValueError: When a dependency names a node that is not a key of
            ``edges``; pydantic reports it as a ``ValidationError``.
    """
    targets = {target for node_targets in edges.values() for target in node_targets}
    unknown_targets = sorted(targets - edges.keys())
    if unknown_targets:
        message = f"edges point at unknown nodes: {unknown_targets}"
        raise ValueError(message)
    return edges


class DependencyGraph(BaseModel, frozen=True, extra="forbid"):
    """Nodes and the dependencies between them, validated as a whole.

    Attributes:
        edges: The dependencies of each node; every target is also a key.
    """

    edges: Annotated[EdgeTable, AfterValidator(create_edges_with_known_targets)]
```

If every construction path validates membership and raw edges never escape as proof-bearing values, a separate `ValidatedEdge` may add nothing. `frozen=True` stops code from reassigning `edges`, and the `Mapping` annotation makes pyright reject item assignment, but the dict it holds at runtime is still mutable; keep the aggregate's data behind read-only types.

### Live state owns the proof

Some facts are observations, not durable value properties:

- a username is currently available
- an account currently has sufficient funds
- a row still has a particular version
- a caller currently holds a permission

Do not parse these into timeless wrappers that can become stale. Keep the check and action in the same transaction (`with connection:`), lock (`with lock:`), version-checked write (`UPDATE ... WHERE version = ?`), or store constraint such as a unique index whose violation the `insert_*` function reports.

## Normalize Only When the Domain Defines It

Parsing may establish a canonical representation when equivalence is part of the domain:

```python
from typing import Annotated, Final

from pydantic import BaseModel, StringConstraints, ValidationError

from safety_judge.errors import InvalidValueError

MAXIMUM_ASSET_NAME_LENGTH: Final = 128
"""The most characters an asset name holds."""

type AssetNameText = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9_.-]+$",
        to_lower=True,
        max_length=MAXIMUM_ASSET_NAME_LENGTH,
    ),
]
"""ASCII letters, digits, underscores, dots, and hyphens, lowercased."""


class AssetName(BaseModel, frozen=True, extra="forbid"):
    """A canonical, lowercase asset name; names differing only in case are equal.

    Attributes:
        text: The lowercase name.
    """

    text: AssetNameText


def create_asset_name(raw_text: str) -> AssetName:
    """Create an asset name from untrusted text, lowercasing ASCII letters.

    Args:
        raw_text: A name as supplied by a file, database, or user.

    Returns:
        The canonical name.

    Raises:
        InvalidValueError: When the text is empty, too long, or contains a
            character outside ASCII letters, digits, underscores, dots, and
            hyphens; ``__cause__`` holds the underlying validation error.
    """
    try:
        return AssetName(text=raw_text)
    except ValidationError as validation_error:
        message = (
            f"An asset name must be 1 to {MAXIMUM_ASSET_NAME_LENGTH} ASCII letters, "
            "digits, underscores, dots, or hyphens. Provide a name in that form."
        )
        raise InvalidValueError(
            message,
            context={"actual_length": len(raw_text)},
        ) from validation_error
```

The pattern is the explicit policy: only ASCII passes, so `to_lower` is ASCII lowercasing and never applies a Unicode rule.

Do not silently repair ambiguous input. Trimming, case folding, path resolution, Unicode normalization, unit conversion, and lossy coercion require an explicit policy.

## Construction Is Not the Only Boundary

Preserve the invariant across:

- updates: a frozen model has no mutators, but `model_copy(update=...)` replaces fields without validating them
- parsing and deserialization: `model_validate` and `model_validate_json` run the model's validators
- database restoration
- migrations and bulk imports
- unvalidated construction, such as `model_construct`, which skips validation by design
- containers: `frozen=True` forbids reassigning a field, not mutating a `dict` or `list` stored in it
- arithmetic and transformations

An operation must return the strongest type it can actually prove. A cross product of two unit vectors is not necessarily a unit vector. A previously available username is not necessarily still available.

## Review Procedure

1. Search for `validate_*`, `is_valid_*`, `check_*`, repeated guard clauses that raise the same error, primitive-heavy signatures, and exceptions whose messages say a case "cannot happen".
2. State exactly what each check learns.
3. Decide whether the fact belongs to a value, aggregate, or live consistency boundary.
4. Make the boundary return that proof owner.
5. Change trusted function signatures to accept the stronger representation.
6. Remove redundant checks and impossible error branches.
7. Test rejection at the parse boundary and preservation through every public operation and restoration path.

## Sources

- [Parse, don't validate — Alexis King](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/) — the original type-driven-design explanation: parsing preserves information that validation returning nothing discards.
- [Pydantic: Models](https://docs.pydantic.dev/latest/concepts/models/) — `model_validate`, `model_validate_json`, `model_construct` (creates models without running validation), and `model_copy` (its updates are not validated).
- [Pydantic: Strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) — lax mode coerces compatible input such as `"123"` to `123`; strict mode rejects it.
