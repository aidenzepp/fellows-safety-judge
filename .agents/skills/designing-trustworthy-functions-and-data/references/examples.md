# Trustworthy Function Examples

Use these as reasoning patterns, not APIs to copy mechanically. Preserve the project's actual domain, ownership, error, and performance contracts.

For paired before-and-after Python refactors, read [design-transformations.md](design-transformations.md).

Excerpts are `POSITIVE` unless a comment or heading labels them `NEGATIVE`. Function names follow the repository vocabulary: `select_`, `insert_`, `delete_`, `update_`, and `rename_` mark the I/O edge, and `create_` and `remove_` mark in-memory cores.

## Classify the Real Contract

```python
from datetime import UTC, datetime
from enum import StrEnum
lazy from collections.abc import Sequence
lazy from typing import TextIO

from pydantic import AwareDatetime, BaseModel


class Account(BaseModel, frozen=True, extra="forbid"):
    """A customer account that may be disabled."""

    is_enabled: bool


class Receipt(BaseModel, frozen=True, extra="forbid"):
    """Proof that a payment was taken."""

    identifier: str
    total_in_cents: int


class SessionStatus(StrEnum):
    """Whether a session may still be used."""

    ACTIVE = "active"
    EXPIRED = "expired"


class Session(BaseModel, frozen=True, extra="forbid"):
    """A login session that expires at a fixed moment."""

    expires_at: AwareDatetime


# POSITIVE — pure and honest: all inputs and the returned output are visible.
def create_total(values: Sequence[int]) -> int:
    """Create the sum of ``values``.

    Args:
        values: The integers to add.

    Returns:
        The sum, or zero when there are no values.
    """
    return sum(values)


# POSITIVE — impure and honest: the mutable parameter type, the returned count,
# and the docstring all say that ``accounts`` changes.
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


# POSITIVE — impure and honest: external output is an explicit capability.
def insert_receipt_line(output: TextIO, receipt: Receipt) -> None:
    """Write one line describing ``receipt`` to ``output``.

    Args:
        output: The stream to write to.
        receipt: The receipt to describe.
    """
    _ = output.write(f"{receipt.identifier}\t{receipt.total_in_cents}\n")


# NEGATIVE — dishonest: the signature hides time as a real input.
def select_current_session_status(session: Session) -> SessionStatus:
    """Select the status of ``session`` at the moment of the call.

    Args:
        session: The session to evaluate.

    Returns:
        The status according to the system clock.
    """
    return create_session_status(session, datetime.now(UTC))
```

“Honest” does not mean “pure.” It means the signature tells the truth about the operation. The `select_` verb marks `select_current_session_status` as an edge, but the clock is still not a parameter. The boundary adapter may obtain the current time, then pass that value to an honest domain decision.

## Pass the Value the Decision Needs

A domain rule that compares a deadline needs a timestamp, not permanent access to a clock:

```python
from datetime import UTC, datetime
lazy from collections.abc import Callable


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


type Clock = Callable[[], datetime]
"""A capability that reports the current moment as a timezone-aware datetime."""


def select_session_status_from_clock(
    clock: Clock,
    session: Session,
) -> SessionStatus:
    """Select the status of ``session`` at the moment ``clock`` reports.

    Args:
        clock: The capability that supplies the current moment.
        session: The session to evaluate.

    Returns:
        The status at the reported moment.
    """
    return create_session_status(session, clock())


def test_the_status_uses_the_moment_the_clock_reports() -> None:
    session = Session(expires_at=datetime(2026, 1, 1, tzinfo=UTC))

    status = select_session_status_from_clock(
        lambda: datetime(2026, 6, 1, tzinfo=UTC),
        session,
    )

    assert status is SessionStatus.EXPIRED
```

The environmental adapter owns obtaining time: production passes `lambda: datetime.now(UTC)` and a test passes a function that returns a fixed moment. The rule `create_session_status` receives an ordinary controlled value and needs no clock at all.

## Pass a Real Nondeterministic Capability

A generator that consumes randomness across many operations legitimately accepts a `Random` instance:

```python
from random import Random, SystemRandom
from typing import override

from pydantic import BaseModel


class Particle(BaseModel, frozen=True, extra="forbid"):
    """A particle in the simulation."""

    position: float
    velocity: float
    scale: float


class ParticleWorld(BaseModel, frozen=True, extra="forbid"):
    """The particles currently in the simulation."""

    particles: tuple[Particle, ...] = ()


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


def select_populated_world(count: int) -> ParticleWorld:
    """Select an empty world populated from the operating system's entropy.

    Args:
        count: How many particles to add.

    Returns:
        A world with ``count`` unpredictable particles.
    """
    return create_populated_world(ParticleWorld(), count, SystemRandom())


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

Production chooses an unpredictable source. Tests pass a generator whose values they control, such as the small `FixedRandom` fake above. The fake extends `SystemRandom` because Ruff's `S311` flags both `Random(seed)` calls and `Random` as a base class, and a lint finding is not silenced to make a test pass. A `SystemRandom` subclass is still a `Random`, so the parameter type does not change. No repository-specific `RandomService` `Protocol` is necessary.

Seeds are a weak replay format. Python documents only that `Random.random()` keeps producing the same sequence for a given seed across versions, so durable replay data should record the generated values or pin the interpreter version.

## Carry a Proven Invariant

```python
import math
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, Field

from safety_judge.errors import InvalidValueError

UNIT_LENGTH_TOLERANCE: Final = 1e-9
"""How far a unit vector's length may differ from 1.0 after rounding."""

type FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
"""A float that is neither infinite nor NaN."""


class Vector3(BaseModel, frozen=True, extra="forbid"):
    """A three-dimensional vector whose components are finite numbers."""

    x: FiniteNumber
    y: FiniteNumber
    z: FiniteNumber


def create_checked_unit_direction(direction: Vector3) -> Vector3:
    """Check that a direction has length one within the tolerance.

    Args:
        direction: The vector to check.

    Returns:
        ``direction`` unchanged, which is the shape a pydantic validator returns.

    Raises:
        ValueError: When the length differs from one by more than the tolerance;
            pydantic reports it as a ``ValidationError``.
    """
    length = math.hypot(direction.x, direction.y, direction.z)
    if abs(length - 1.0) > UNIT_LENGTH_TOLERANCE:
        message = f"length {length} is not 1.0 within {UNIT_LENGTH_TOLERANCE}"
        raise ValueError(message)
    return direction


type UnitDirection = Annotated[
    Vector3,
    AfterValidator(create_checked_unit_direction),
]
"""A vector whose length is one within the tolerance."""


class UnitVector3(BaseModel, frozen=True, extra="forbid"):
    """A direction of length one; no instance can hold any other length.

    Attributes:
        direction: The underlying vector, available for ordinary arithmetic.
    """

    direction: UnitDirection


def create_unit_vector3(raw_vector: Vector3) -> UnitVector3:
    """Create the unit vector that points the same way as ``raw_vector``.

    Args:
        raw_vector: A vector of finite components.

    Returns:
        A vector of length one with the direction of ``raw_vector``.

    Raises:
        InvalidValueError: When every component is zero, so no direction exists.
    """
    # Scale by the largest component first so components near the float limits
    # cannot overflow or underflow while the length is calculated.
    scale = max(abs(raw_vector.x), abs(raw_vector.y), abs(raw_vector.z))
    if scale == 0.0:
        message = (
            "A zero vector has no direction. "
            "Provide a vector with at least one non-zero component."
        )
        raise InvalidValueError(message, context={"constraint": "non-zero length"})
    scaled_x = raw_vector.x / scale
    scaled_y = raw_vector.y / scale
    scaled_z = raw_vector.z / scale
    scaled_length = math.hypot(scaled_x, scaled_y, scaled_z)
    return UnitVector3(
        direction=Vector3(
            x=scaled_x / scaled_length,
            y=scaled_y / scaled_length,
            z=scaled_z / scaled_length,
        ),
    )


def create_dot_product(left: Vector3, right: Vector3) -> float:
    """Create the dot product of two vectors.

    Args:
        left: The first vector.
        right: The second vector.

    Returns:
        The sum of the products of matching components.
    """
    return left.x * right.x + left.y * right.y + left.z * right.z


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

`Vector3` rejects NaN and infinity when it is parsed, so `create_unit_vector3` carries no non-finite branch. `UnitVector3` owns a stable mathematical requirement and prevents every downstream caller from remembering it independently: its validator runs on every construction path, and `create_reflection` omits the check and its error. Rounding means the invariant is a length within `UNIT_LENGTH_TOLERANCE`, an explicit policy rather than exact equality.

An operation must return the type it can prove:

```python
def create_cross_product(left: Vector3, right: Vector3) -> Vector3:
    """Create the cross product of two vectors, whose length is not necessarily one.

    Args:
        left: The first vector.
        right: The second vector.

    Returns:
        A vector perpendicular to both inputs.
    """
    return Vector3(
        x=left.y * right.z - left.z * right.y,
        y=left.z * right.x - left.x * right.z,
        z=left.x * right.y - left.y * right.x,
    )


def create_normalized_cross_product(
    left: UnitVector3,
    right: UnitVector3,
) -> UnitVector3:
    """Create the unit vector perpendicular to two unit vectors.

    Parallel inputs have a zero cross product, so ``create_unit_vector3`` rejects
    them with its documented error.

    Args:
        left: The first unit vector.
        right: The second unit vector.

    Returns:
        A unit vector perpendicular to both inputs.
    """
    return create_unit_vector3(create_cross_product(left.direction, right.direction))
```

The ordinary cross product is not necessarily unit length. Parallel unit vectors produce zero.

## Parse a Primitive into a Domain Value

```python
from typing import Annotated, Final

from pydantic import BaseModel, Field, ValidationError

from safety_judge.errors import InvalidValueError

MINIMUM_NON_PRIVILEGED_PORT: Final = 1_024
"""The lowest port number that needs no special privilege."""

MAXIMUM_PORT: Final = 65_535
"""The highest TCP port number."""

type PortNumber = Annotated[
    int,
    Field(strict=True, ge=MINIMUM_NON_PRIVILEGED_PORT, le=MAXIMUM_PORT),
]
"""An unprivileged port number; strict, so text and booleans are not coerced."""


class NonPrivilegedPort(BaseModel, frozen=True, extra="forbid"):
    """A TCP port that needs no special privilege to bind.

    Attributes:
        number: The port number.
    """

    number: PortNumber


type FreePorts = frozenset[NonPrivilegedPort]
"""The ports currently available for allocation."""


def create_non_privileged_port(raw_port: int) -> NonPrivilegedPort:
    """Create a port from an untrusted number.

    Args:
        raw_port: A port number from configuration, a CLI, or the network.

    Returns:
        The port, proven to be within the unprivileged range.

    Raises:
        InvalidValueError: When the number is outside the unprivileged range;
            ``__cause__`` holds the underlying validation error.
    """
    try:
        return NonPrivilegedPort(number=raw_port)
    except ValidationError as validation_error:
        message = (
            f"Port {raw_port} is outside {MINIMUM_NON_PRIVILEGED_PORT} to "
            f"{MAXIMUM_PORT}. Provide an unprivileged port number."
        )
        raise InvalidValueError(
            message,
            context={"actual_port": raw_port},
        ) from validation_error


def create_pool_with_released_port(
    free_ports: FreePorts,
    port: NonPrivilegedPort,
) -> FreePorts:
    """Create a pool that also holds ``port``.

    Args:
        free_ports: The ports currently free; not modified.
        port: The port to release.

    Returns:
        A new pool containing every free port and ``port``.
    """
    return free_ports | {port}


def remove_lowest_free_port(
    free_ports: FreePorts,
) -> tuple[NonPrivilegedPort, FreePorts] | None:
    """Remove the lowest-numbered free port from a pool.

    Args:
        free_ports: The ports currently free; not modified.

    Returns:
        The allocated port and the remaining pool, or ``None`` when no port is free.
    """
    if not free_ports:
        return None
    lowest_port = min(free_ports, key=lambda port: port.number)
    return lowest_port, free_ports - {lowest_port}
```

The raw `int` is parsed once at configuration, CLI, database, or network boundaries. The parser returns the proof-bearing value. Pool operations no longer repeat the check or raise `InvalidValueError`, and an allocated value retains the guarantee when passed elsewhere. Absence is `None`, not an exception.

If the rule were meaningful only inside the pool and elements never crossed its boundary, an aggregate that parses raw ports itself could own the invariant without a separate element type. Here the element is both accepted and returned, so preserving the guarantee is useful.

## Preserve the Transaction Boundary

```python
from typing import Annotated, ClassVar, NewType
lazy import sqlite3

from pydantic import BaseModel, Field

from safety_judge.errors import SafetyJudgeError

AccountIdentifier = NewType("AccountIdentifier", str)
"""The identity of one account; a distinct kind of string."""


class InsufficientFundsError(SafetyJudgeError):
    """The source account cannot cover the requested transfer."""

    code: ClassVar[str] = "insufficient_funds"


class TransferCommand(BaseModel, frozen=True, extra="forbid"):
    """A request to move money between two accounts.

    Attributes:
        source_account_identifier: The account that pays.
        destination_account_identifier: The account that receives.
        amount_in_cents: The positive amount to move.
    """

    source_account_identifier: AccountIdentifier
    destination_account_identifier: AccountIdentifier
    amount_in_cents: Annotated[int, Field(gt=0)]


class TransferBalances(BaseModel, frozen=True, extra="forbid"):
    """The balances of the two accounts in a transfer.

    Attributes:
        source_balance_in_cents: The balance of the paying account.
        destination_balance_in_cents: The balance of the receiving account.
    """

    source_balance_in_cents: int
    destination_balance_in_cents: int


def create_balances_after_transfer(
    current_balances: TransferBalances,
    command: TransferCommand,
) -> TransferBalances:
    """Create the balances that result from applying a transfer.

    Args:
        current_balances: The balances read inside the transaction.
        command: The transfer to apply.

    Returns:
        The balances after the money moves.

    Raises:
        InsufficientFundsError: When the source balance is below the amount.
    """
    if current_balances.source_balance_in_cents < command.amount_in_cents:
        message = (
            f"Account {command.source_account_identifier} holds "
            f"{current_balances.source_balance_in_cents} cents, which cannot cover "
            f"{command.amount_in_cents}. Transfer a smaller amount."
        )
        raise InsufficientFundsError(
            message,
            context={"amount_in_cents": command.amount_in_cents},
        )
    return TransferBalances(
        source_balance_in_cents=(
            current_balances.source_balance_in_cents - command.amount_in_cents
        ),
        destination_balance_in_cents=(
            current_balances.destination_balance_in_cents + command.amount_in_cents
        ),
    )


def update_accounts_with_transfer(
    connection: sqlite3.Connection,
    command: TransferCommand,
) -> TransferBalances:
    """Move money between two accounts as one atomic transaction.

    Args:
        connection: An open connection to the accounts database.
        command: The transfer to apply.

    Returns:
        The balances after the transfer was committed.
    """
    with connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        current_balances = select_transfer_balances(connection, command)
        new_balances = create_balances_after_transfer(current_balances, command)
        update_transfer_balances(connection, command, new_balances)
        insert_ledger_entry(connection, command)
    return new_balances
```

`select_transfer_balances`, `update_transfer_balances`, and `insert_ledger_entry` run ordinary SQL on the same connection; their bodies are omitted. `create_balances_after_transfer` can be deterministic, but acquiring the write lock, deciding from current state, writing, and committing remain inside one consistency boundary: `with connection:` commits when the block ends and rolls back if any step raises. Hoisting all effects to the program entry point would make the design less correct. Test it with a real in-memory `sqlite3` connection rather than a mock.

## Request the Capability Actually Used

```python
import zlib
lazy from collections.abc import Buffer, Iterable


def create_total(values: Iterable[int]) -> int:
    """Create the sum of ``values``.

    Args:
        values: The integers to add, traversed once.

    Returns:
        The sum, or zero when there are no values.
    """
    return sum(values)


def create_checksum(content: Buffer) -> int:
    """Create the CRC-32 checksum of ``content``.

    Args:
        content: Contiguous bytes, such as ``bytes`` or ``memoryview``.

    Returns:
        The unsigned 32-bit checksum.
    """
    return zlib.crc32(content)
```

The first operation only traverses values. The second honestly asks for contiguous bytes.

## Use a Cohesive Parameter Object

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


class TimerOptions(BaseModel, frozen=True, extra="forbid"):
    """One timer's complete schedule.

    Attributes:
        identifier: The timer's name.
        interval: The positive time between firings.
        first_tick: When the first firing happens.
        repetition: Whether the timer fires once or forever.
    """

    identifier: TimerIdentifierText
    interval: Annotated[timedelta, Field(gt=timedelta(0))]
    first_tick: FirstTick
    repetition: Repetition


insert_timer(
    TimerOptions(
        identifier="refresh",
        interval=timedelta(seconds=5),
        first_tick=FirstTick.AFTER_INTERVAL,
        repetition=Repetition.FOREVER,
    ),
)
```

`insert_timer` registers the timer with a scheduler and is not defined here. The fields describe one timer policy. `timedelta` carries the unit, and enums replace positional booleans and rule out ambiguous combinations.

## Keep Domain Intent at One Level

`AssetName` is the canonical-name model from [parse-dont-validate.md](parse-dont-validate.md#normalize-only-when-the-domain-defines-it), and `AssetType` is a `StrEnum` of asset kinds.

```python
lazy from collections.abc import Mapping


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

`AssetName` owns validation and canonical casing. The `dict` behind `Mapping[AssetName, AssetType]` owns unique-key association and lookup. The domain function does not lowercase text, preserve a sorted list, or implement binary search.

## Stream Results That Should Not Be Materialized

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

A generator preserves separation and caller control without allocating every factorial-sized result at once.
