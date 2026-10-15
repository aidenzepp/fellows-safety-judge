# Design Transformations

These paired Python examples show how to turn misleading, overpowered, or mixed-level function designs into truthful contracts.

The snippets are independent shapes, not one module. Adapt domain names and error types, but preserve the contract distinction each pair demonstrates. `NEGATIVE` marks the flawed shape and `POSITIVE` its repair. Function names follow the repository vocabulary: `select_`, `insert_`, `delete_`, `update_`, and `rename_` mark the I/O edge, and `create_` and `remove_` mark in-memory cores.

There is no pair for “the lock must be held before calling this”: Python types cannot prove that a lock is held, so the lifetime-tied guard idea has no honest Python counterpart here.

## 1. Honest Does Not Mean Pure

A function can mutate and still be honest when the mutation is declared:

### POSITIVE — Declared mutation, and the pure alternative

```python
lazy from collections.abc import Sequence

from pydantic import BaseModel


class Account(BaseModel, frozen=True, extra="forbid"):
    """A customer account that may be disabled."""

    is_enabled: bool


def remove_disabled_accounts(accounts: list[Account]) -> int:
    """Remove every disabled account from ``accounts`` in place.

    Args:
        accounts: The list to modify; disabled accounts are deleted from it.

    Returns:
        The number of accounts removed.
    """
    previous_length = len(accounts)
    accounts[:] = [account for account in accounts if account.is_enabled]
    return previous_length - len(accounts)


def create_enabled_accounts(accounts: Sequence[Account]) -> tuple[Account, ...]:
    """Create the enabled accounts without modifying the input.

    Args:
        accounts: The accounts to filter; not modified.

    Returns:
        The enabled accounts in their original order.
    """
    return tuple(account for account in accounts if account.is_enabled)
```

Both functions are honest. `remove_disabled_accounts` is impure because it mutates; its `list` parameter type, its returned count, and its docstring declare exactly what it may change. Python has no `&mut` marker, so those three signals carry that weight, and a `Sequence` parameter would be a promise not to mutate. The count shows that mutation and a return value can be separate, visible output channels. `values.clear()` and `values.sort()` are the same idea: the receiver is the visible subject. `create_enabled_accounts` is pure and is usually the better default.

By contrast, a function whose purpose is to read a hidden environmental input is necessarily dishonest. Keep that operation at a boundary and pass its result inward:

### POSITIVE — The dishonest read stays at the edge

```python
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel


class SessionStatus(StrEnum):
    """Whether a session may still be used."""

    ACTIVE = "active"
    EXPIRED = "expired"


class Session(BaseModel, frozen=True, extra="forbid"):
    """A login session that expires at a fixed moment."""

    expires_at: AwareDatetime


class StatusResponse(BaseModel, frozen=True, extra="forbid"):
    """The answer sent back for a status request."""

    status: SessionStatus


def select_current_time() -> datetime:
    """Select the current moment from the system clock.

    Returns:
        The current moment as a timezone-aware datetime.
    """
    return datetime.now(UTC)


def create_session_status(session: Session, now: datetime) -> SessionStatus:
    """Create the status ``session`` has at the moment ``now``.

    Args:
        session: The session whose deadline is compared.
        now: The moment to evaluate, supplied by the caller.

    Returns:
        ``EXPIRED`` at or after the deadline, otherwise ``ACTIVE``.
    """
    if now >= session.expires_at:
        return SessionStatus.EXPIRED
    return SessionStatus.ACTIVE


def select_session_status_response(session: Session) -> StatusResponse:
    """Select the response describing ``session`` at the current moment.

    Args:
        session: The session the request asks about.

    Returns:
        The response carrying the session's current status.
    """
    now = select_current_time()
    status = create_session_status(session, now)
    return StatusResponse(status=status)
```

Under this skill's vocabulary, `select_current_time` is necessarily dishonest: the clock that determines its result is absent from the signature. Its `select_` verb correctly marks it as an edge. The edge `select_session_status_response` remains deliberately effectful, while the domain decision `create_session_status` becomes honest and deterministic. If obtaining time is itself a caller-owned policy, pass a narrow `Clock` callable to this adapter; do not pass an application-wide context merely to reach a clock.

Environment variables follow the same split:

### POSITIVE — Parse the environment mapping, read `os.environ` once

```python
import os
from pathlib import Path
lazy from collections.abc import Mapping


def create_database_path(environment: Mapping[str, str]) -> Path:
    """Create the database path an environment configures.

    Args:
        environment: The environment variables to read, usually ``os.environ``.

    Returns:
        The configured path, or ``judge.sqlite3`` when none is set.
    """
    return Path(environment.get("SAFETY_JUDGE_DATABASE_PATH", "judge.sqlite3"))


def select_database_path() -> Path:
    """Select the database path from the process environment.

    Returns:
        The path the process environment configures.
    """
    return create_database_path(os.environ)
```

A test calls `create_database_path({"SAFETY_JUDGE_DATABASE_PATH": "/tmp/judge.db"})` with no `monkeypatch`. In this repository, process configuration goes through `select_application_settings`, which is the edge that reads the environment and `.env` file.

## 2. An Accessor with Hidden Global State

### NEGATIVE — The name promises requirements, the body filters by a global

```python
from typing import Final, NewType
lazy from collections.abc import Iterator

from pydantic import BaseModel

AssetIdentifier = NewType("AssetIdentifier", str)
"""The identity of one asset; a distinct kind of string."""

LOADED_ASSET_IDENTIFIERS: Final[set[AssetIdentifier]] = set()
"""Every asset the process has loaded so far; mutated by the loader."""


class Manifest(BaseModel, frozen=True, extra="forbid"):
    """The assets a scene needs.

    Attributes:
        required_asset_identifiers: Every asset the scene requires.
    """

    required_asset_identifiers: tuple[AssetIdentifier, ...]


def create_required_asset_identifiers(manifest: Manifest) -> Iterator[AssetIdentifier]:
    """Create the identifiers of the assets ``manifest`` requires.

    Args:
        manifest: The scene's manifest.

    Yields:
        Each required identifier that has not been loaded yet.
    """
    for identifier in manifest.required_asset_identifiers:
        if identifier not in LOADED_ASSET_IDENTIFIERS:
            yield identifier
```

A caller cannot tell that global load state changes the result.

### POSITIVE — The distinction and the dependency are explicit

```python
lazy from collections.abc import Set as AbstractSet


def create_missing_asset_identifiers(
    manifest: Manifest,
    loaded_identifiers: AbstractSet[AssetIdentifier],
) -> tuple[AssetIdentifier, ...]:
    """Create the required identifiers that are not loaded yet.

    Args:
        manifest: The scene's manifest.
        loaded_identifiers: The assets already loaded; not modified.

    Returns:
        The missing identifiers in manifest order.
    """
    return tuple(
        identifier
        for identifier in manifest.required_asset_identifiers
        if identifier not in loaded_identifiers
    )
```

The caller chooses whether it needs the complete requirement, which is `manifest.required_asset_identifiers`, or the currently missing subset. No accessor wraps the attribute, because it would add navigation without vocabulary.

## 3. Permutations Mixed with I/O

### NEGATIVE — The algorithm chooses where results go

```python
def insert_permutation_lines_to_standard_output(input_text: str) -> None:
    """Print every permutation of ``input_text``.

    Args:
        input_text: The characters to arrange.
    """
    for permutation in create_permutations(input_text):
        print(permutation)
```

The permutation logic cannot be reused for a file, network stream, search, or test without capturing process output, and the destination, standard output, is hidden global state.

### POSITIVE — Bounded materialization when the complete result is the contract

```python
from typing import ClassVar, Final
lazy from typing import TextIO

from safety_judge.errors import SafetyJudgeError

PERMUTATION_RESULT_LIMIT: Final = 10_000
"""The most permutations written in one call."""


class TooManyPermutationsError(SafetyJudgeError):
    """An input has more permutations than the caller allowed."""

    code: ClassVar[str] = "too_many_permutations"


def create_all_permutations(input_text: str, result_limit: int) -> list[str]:
    """Create every permutation of ``input_text`` as a list.

    Args:
        input_text: The characters to arrange.
        result_limit: The most permutations the caller will accept.

    Returns:
        Every permutation.

    Raises:
        TooManyPermutationsError: When there are more than ``result_limit``.
    """
    results: list[str] = []
    for permutation in create_permutations(input_text):
        if len(results) == result_limit:
            message = (
                f"Input has more than {result_limit} permutations. "
                "Provide shorter input or stream the results instead."
            )
            raise TooManyPermutationsError(
                message,
                context={"result_limit": result_limit},
            )
        results.append(permutation)
    return results


def insert_all_permutations(input_text: str, output: TextIO) -> None:
    """Write every permutation of ``input_text`` to ``output``, one per line.

    Args:
        input_text: The characters to arrange.
        output: The stream to write to.
    """
    for permutation in create_all_permutations(input_text, PERMUTATION_RESULT_LIMIT):
        _ = output.write(f"{permutation}\n")
```

The algorithm is honest, the output destination is explicit, and the materialization limit is part of the contract. An unbounded `list` may separate calculation from output, but storing every result usually requires `Theta(n * n!)` payload space and should not be presented as generally safe. `create_permutations` is the generator defined below.

### POSITIVE — Stream the results when materialization is too expensive

```python
import itertools
lazy from collections.abc import Iterator
lazy from typing import TextIO


def create_permutations(input_text: str) -> Iterator[str]:
    """Create every ordering of the characters of ``input_text``, one at a time.

    Args:
        input_text: The characters to arrange.

    Yields:
        Each permutation, without storing the others.
    """
    for characters in itertools.permutations(input_text):
        yield "".join(characters)


def insert_permutation_lines(input_text: str, output: TextIO) -> None:
    """Write every permutation of ``input_text`` to ``output``, one per line.

    Args:
        input_text: The characters to arrange.
        output: The stream to write to.
    """
    for permutation in create_permutations(input_text):
        _ = output.write(f"{permutation}\n")
```

A callback parameter is one explicit consumer-injection shape. In Python, a generator often provides the more natural contract because the caller can compose, stop early, and control consumption without allocating all results.

## 4. Populating a World and the Shared Random Generator

`Particle` and `ParticleWorld` are the frozen models from [examples.md](examples.md#pass-a-real-nondeterministic-capability).

### NEGATIVE — The module-level `random` functions are hidden input

```python
import random


def create_populated_world(world: ParticleWorld, count: int) -> ParticleWorld:
    """Create a world with ``count`` more particles.

    Args:
        world: The world to extend; not modified.
        count: How many particles to add.

    Returns:
        A new world holding the old particles followed by the new ones.
    """
    new_particles = tuple(
        Particle(
            position=random.random(),
            velocity=random.random(),
            scale=random.random(),
        )
        for _ in range(count)
    )
    return ParticleWorld(particles=(*world.particles, *new_particles))


world = create_populated_world(ParticleWorld(), 42)
```

`create_populated_world` appears to depend only on the world and count, but it also consumes the shared generator behind the `random` module. Other random calls change its result at a distance, and callers cannot choose reproducibility. Calling `random.seed` in a test would seed that shared state for every other caller rather than for this one.

### POSITIVE — The `Random` instance is a parameter

```python
from random import Random, SystemRandom


def create_populated_world(
    world: ParticleWorld,
    count: int,
    random_source: Random,
) -> ParticleWorld:
    """Create a world with ``count`` more particles drawn from ``random_source``.

    Advances ``random_source``; that is the function's only effect.

    Args:
        world: The world to extend; not modified.
        count: How many particles to add.
        random_source: The generator that supplies every random value.

    Returns:
        A new world holding the old particles followed by the new ones.
    """
    new_particles = tuple(
        Particle(
            position=random_source.random(),
            velocity=random_source.random(),
            scale=random_source.random(),
        )
        for _ in range(count)
    )
    return ParticleWorld(particles=(*world.particles, *new_particles))


world = create_populated_world(ParticleWorld(), 42, SystemRandom())
```

Production selects an unpredictable source at the boundary. Tests pass a generator whose values they control. The fake extends `SystemRandom` because Ruff's `S311` flags both `Random(seed)` calls and `Random` as a base class, and a lint finding is not silenced to make a test pass. A `SystemRandom` subclass is still a `Random`, so the parameter type does not change:

```python
from typing import override


class FixedRandom(SystemRandom):
    """A fake generator whose ``random`` method always returns the same value."""

    @override
    def random(self) -> float:
        """Return the fixed value.

        Returns:
            Always one half.
        """
        return 0.5


def test_every_particle_takes_its_values_from_the_supplied_generator() -> None:
    world = create_populated_world(ParticleWorld(), 2, FixedRandom())

    assert world.particles == (Particle(position=0.5, velocity=0.5, scale=0.5),) * 2
```

This is dependency injection without a DI framework or repository-specific random-source `Protocol`. `create_populated_world` is still impure in the sense that it advances the generator, but that effect is honest. Seeds are a weak replay format: Python documents only that `Random.random()` keeps producing the same sequence for a given seed across versions, so durable replay data must record the generated values or pin the interpreter version.

## 5. Primitive and Boolean Timer Arguments

### NEGATIVE — Positional primitives and booleans

```python
insert_timer(None, "refresh", 5.0, True, False, True)
```

The call site does not identify the time unit or what any boolean means.

### POSITIVE — One cohesive options model with semantic types

```python
from datetime import timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

type TimerIdentifierText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
"""A trimmed, non-empty timer name."""


class FirstTick(StrEnum):
    """When a timer first fires."""

    IMMEDIATELY = "immediately"
    AFTER_INTERVAL = "after_interval"


class Repetition(StrEnum):
    """How often a timer fires."""

    ONCE = "once"
    FOREVER = "forever"


class RetriggerPolicy(StrEnum):
    """What happens when a timer is set while it is already running."""

    RESTART = "restart"
    IGNORE = "ignore"


class TimerOptions(BaseModel, frozen=True, extra="forbid"):
    """One timer's complete configuration.

    Attributes:
        identifier: The timer's name.
        interval: The positive time between firings.
        first_tick: When the first firing happens.
        repetition: Whether the timer fires once or forever.
        retrigger: What to do when the timer is already running.
    """

    identifier: TimerIdentifierText
    interval: Annotated[timedelta, Field(gt=timedelta(0))]
    first_tick: FirstTick
    repetition: Repetition
    retrigger: RetriggerPolicy


insert_timer(
    TimerOptions(
        identifier="refresh",
        interval=timedelta(seconds=5),
        first_tick=FirstTick.AFTER_INTERVAL,
        repetition=Repetition.ONCE,
        retrigger=RetriggerPolicy.RESTART,
    ),
)
```

The options model describes one timer configuration. Semantic types replace positional primitives and boolean blindness: `timedelta` carries the unit and the enums name the choices. When only a few arguments are involved, keyword-only parameters (`def insert_timer(*, identifier, interval, ...)`) give the same readable call site without a new model.

### NEGATIVE — Overcorrection with a context bag

```python
def insert_timer(application: Application) -> TimerHandle:
    """Register a timer from the application's configuration.

    Args:
        application: The whole application, of which six fields are read.

    Returns:
        A handle to the registered timer.
    """
    ...
```

Passing the entire application grants unrelated knowledge and authority. Use a cohesive options model, not a renamed context bag.

## 6. Requiring a Concrete Collection

### NEGATIVE — A `list` where only traversal is needed

```python
def create_total(values: list[int]) -> int:
    """Create the sum of ``values``.

    Args:
        values: The integers to add.

    Returns:
        The sum.
    """
    return sum(values)
```

The implementation only traverses values, but the signature rejects tuples, sets, generators, and other iterables.

### POSITIVE — Traversal only

```python
lazy from collections.abc import Iterable


def create_total(values: Iterable[int]) -> int:
    """Create the sum of ``values``.

    Args:
        values: The integers to add, traversed once.

    Returns:
        The sum, or zero when there are no values.
    """
    return sum(values)
```

### POSITIVE — Contiguous bytes are part of the contract

```python
import zlib
lazy from collections.abc import Buffer


def create_checksum(content: Buffer) -> int:
    """Create the CRC-32 checksum of ``content``.

    Args:
        content: Contiguous bytes, such as ``bytes`` or ``memoryview``.

    Returns:
        The unsigned 32-bit checksum.
    """
    return zlib.crc32(content)
```

Do not choose the weakest type merely because it passes the type checker. Ask for a `Sequence`, a `Collection`, or a concrete `list` when the operation genuinely requires repeated passes, stable indexing, retention, or mutation. A function that iterates twice over an `Iterable` silently loses its input when given a generator.

## 7. “Must Call A Before B”

### NEGATIVE — A comment carries the lifecycle invariant

```python
system = create_system(configuration)
update_system_initialization(system)

# Must call update_system_initialization first.
update_system_run(system)
```

The comment carries a lifecycle invariant the API permits callers to violate.

### POSITIVE — The initialized state is a different type

```python
from pathlib import Path
lazy from typing import TextIO

from pydantic import BaseModel


class UninitializedSystem(BaseModel, frozen=True, extra="forbid"):
    """A system that has only been configured.

    Attributes:
        resource_directory: Where the system's resources live.
    """

    resource_directory: Path


class InitializedSystem(BaseModel, frozen=True, extra="forbid"):
    """A system whose resources have been loaded.

    Attributes:
        resource_names: The names of the loaded resources.
    """

    resource_names: tuple[str, ...]


def select_initialized_system(system: UninitializedSystem) -> InitializedSystem:
    """Select the loaded resources of a configured system.

    Args:
        system: The configured system.

    Returns:
        The system with its resources loaded.
    """
    resource_names = tuple(
        sorted(path.name for path in system.resource_directory.iterdir()),
    )
    return InitializedSystem(resource_names=resource_names)


def insert_system_report(system: InitializedSystem, output: TextIO) -> None:
    """Write the name of every loaded resource to ``output``.

    Args:
        system: The system whose resources are listed.
        output: The stream to write to.
    """
    for resource_name in system.resource_names:
        _ = output.write(f"{resource_name}\n")
```

Initialization returns the state that can run, and only that state is accepted by the operation that needs loaded resources, so pyright rejects `insert_system_report(uninitialized_system, output)`. This is stronger than an empty receipt token, which can be constructed anywhere and prove nothing. Python cannot make a caller discard the old value, so when no caller needs the uninitialized state, drop that type and load the resources at the boundary.

## 8. Normalized Surface Normals

### NEGATIVE — Every call re-checks and re-reports the same failure

```python
import math

from safety_judge.errors import InvalidValueError


def create_reflection(incident: Vector3, normal: Vector3) -> Vector3:
    """Create the reflection of ``incident`` about a surface with ``normal``.

    Args:
        incident: The direction of travel before the bounce.
        normal: The surface normal, which must have length one.

    Returns:
        The direction of travel after the bounce.

    Raises:
        InvalidValueError: When ``normal`` does not have length one.
    """
    length = math.hypot(normal.x, normal.y, normal.z)
    if abs(length - 1.0) > UNIT_LENGTH_TOLERANCE:
        message = (
            f"The surface normal has length {length}, not 1.0. "
            "Provide a unit-length normal."
        )
        raise InvalidValueError(message, context={"actual_length": length})
    projection = 2.0 * create_dot_product(incident, normal)
    return Vector3(
        x=incident.x - projection * normal.x,
        y=incident.y - projection * normal.y,
        z=incident.z - projection * normal.z,
    )
```

Every reflection call accepts invalid normals and must remember the same validation and failure policy.

### POSITIVE — Unit length is a stable domain invariant

```python
def create_reflection(incident: Vector3, normal: UnitVector3) -> Vector3:
    """Create the reflection of ``incident`` about a surface with ``normal``.

    Args:
        incident: The direction of travel before the bounce.
        normal: The surface normal, already known to have length one.

    Returns:
        The direction of travel after the bounce.
    """
    direction = normal.direction
    projection = 2.0 * create_dot_product(incident, direction)
    return Vector3(
        x=incident.x - projection * direction.x,
        y=incident.y - projection * direction.y,
        z=incident.z - projection * direction.z,
    )
```

`UnitVector3` wraps a validated `Vector3` and checks its length on every construction path; `create_unit_vector3` normalizes without overflow. See [examples.md](examples.md#carry-a-proven-invariant) for the constructor.

Do not overstate what the type proves. The cross product of two `UnitVector3` values is a plain `Vector3`:

```python
perpendicular = create_cross_product(left.direction, right.direction)
```

This operation must not return a normalized vector: the magnitude is `sin(theta)`, and parallel unit vectors produce zero. A separately named normalized cross product, `create_normalized_cross_product`, must be fallible.

## 9. One Level of Abstraction in Asset Lookup

### NEGATIVE — Domain intent, normalization, and search mechanics interleaved

```python
from enum import StrEnum
lazy from collections.abc import Sequence

from pydantic import BaseModel


class AssetType(StrEnum):
    """The kind of an asset."""

    TEXTURE = "texture"
    SOUND = "sound"
    MODEL = "model"


class Asset(BaseModel, frozen=True, extra="forbid"):
    """An asset in a list sorted by lowercase name.

    Attributes:
        name: The lowercase asset name.
        asset_type: The kind of the asset.
    """

    name: str
    asset_type: AssetType


def create_asset_type_match(
    assets: Sequence[Asset],
    asset_name: str,
    expected: AssetType,
) -> bool:
    """Create whether the named asset exists and has the expected type.

    Args:
        assets: The assets, sorted by lowercase name.
        asset_name: The name to look up, in any case.
        expected: The type the caller requires.

    Returns:
        ``True`` when the asset exists and has the expected type.
    """
    # Phase 1: representation policy.
    normalized_name = asset_name.lower()

    # Phase 2: search mechanics.
    low = 0
    high = len(assets)
    while low < high:
        middle = low + (high - low) // 2
        asset = assets[middle]
        if asset.name < normalized_name:
            low = middle + 1
        elif asset.name > normalized_name:
            high = middle
        else:
            return asset.asset_type is expected

    return False
```

The function alternates between domain intent, name-normalization policy, index arithmetic, and search implementation. Handwritten binary search also concentrates subtle correctness risk inside a domain operation.

### NEGATIVE — The intermediate improvement still leaves two conventions

```python
from bisect import bisect_left
lazy from collections.abc import Sequence


def create_matching_asset(assets: Sequence[Asset], asset_name: str) -> Asset | None:
    """Create the asset with the given name, if one exists.

    Args:
        assets: The assets, sorted by lowercase name.
        asset_name: The name to look up, in any case.

    Returns:
        The matching asset, or ``None`` when no asset has that name.
    """
    normalized_name = asset_name.lower()
    index = bisect_left(assets, normalized_name, key=lambda asset: asset.name)
    if index < len(assets) and assets[index].name == normalized_name:
        return assets[index]
    return None
```

The standard algorithm removes handwritten search mechanics, but insertion and lookup must still remember the same normalization and ordering policy.

### POSITIVE — Let the representation own both invariants

`AssetName` and `create_asset_name` are defined in [parse-dont-validate.md](parse-dont-validate.md#normalize-only-when-the-domain-defines-it).

```python
from enum import StrEnum
lazy from collections.abc import Mapping


class AssetType(StrEnum):
    """The kind of an asset."""

    TEXTURE = "texture"
    SOUND = "sound"
    MODEL = "model"


def create_asset_catalog(
    raw_entries: Mapping[str, AssetType],
) -> dict[AssetName, AssetType]:
    """Create a catalog keyed by canonical asset name.

    Args:
        raw_entries: Asset types keyed by names as supplied by a file or user.

    Returns:
        The same entries keyed by validated, canonical names. Entries whose names
        differ only in case share a key, and the later entry replaces the earlier.
    """
    return {
        create_asset_name(raw_name): asset_type
        for raw_name, asset_type in raw_entries.items()
    }


def create_asset_type_match(
    catalog: Mapping[AssetName, AssetType],
    name: AssetName,
    expected: AssetType,
) -> bool:
    """Create whether the catalog records ``expected`` as the type of ``name``.

    Args:
        catalog: The asset type of every known asset, keyed by canonical name.
        name: The canonical name to look up.
        expected: The type the caller requires.

    Returns:
        ``True`` when ``name`` is in the catalog with the expected type.
    """
    return catalog.get(name) == expected
```

`AssetName` owns validation and lowercase canonicalization. `dict` owns unique-key association, replacement, and lookup. A catalog class is justified only if it owns additional catalog behavior such as insertion or restoration boundaries; otherwise the composed mapping type may be sufficient. Raw strings from files, databases, or user input must pass through `create_asset_name` before entering the dict, and `create_asset_catalog` is that boundary. Reject colliding names there if silently replacing an entry would be a bug.

Ordering disappears because it was required by the old binary-search representation, not by the domain. The domain operation remains at one conceptual level, and neither callers nor helpers must remember normalization, sorting, or search policy.

This example intentionally uses an ASCII-only policy. The `str.lower()` calls in the NEGATIVE excerpts apply Unicode lowercasing to whatever they are given, which is an accidental policy. Unicode case folding and normalization require a separately specified policy.

## 10. Thin Framework Callbacks

Framework-owned callbacks have a hidden call site. Keep them as small adapters into application-owned functions. This excerpt is a fragment: `Application`, `FrameworkFrame`, and the `create_*` helpers stand for application and framework types.

### POSITIVE — Translate, delegate, render

```python
def update_application_on_frame(
    application: Application,
    frame: FrameworkFrame,
) -> None:
    """Advance the world by one framework frame and render the result.

    Args:
        application: The application that owns the world.
        frame: The framework's description of this frame.
    """
    input_snapshot = create_input_snapshot(frame.input_state)
    elapsed = frame.elapsed
    application.world = create_stepped_world(application.world, input_snapshot, elapsed)
    frame.render(create_world_view(application.world))
```

The callback is not pure, and the framework still controls when it runs. Its job is boundary translation, not domain policy.
