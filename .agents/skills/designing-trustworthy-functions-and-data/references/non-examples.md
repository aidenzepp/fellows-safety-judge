# Trustworthy Function Non-Examples

These patterns often look modular or strongly typed while making behavior less truthful, less testable, or harder to understand.

For paired before-and-after Python refactors, read [design-transformations.md](design-transformations.md).

Every excerpt under a `NEGATIVE` heading is the flawed shape; a `POSITIVE` heading marks its repair. Types that an excerpt does not define, such as `Item` or `ApplicationContext`, stand for ordinary domain types.

## Dishonest Hidden Ambient State

### NEGATIVE — The shared random generator is hidden input

```python
import random

from pydantic import BaseModel


class Particle(BaseModel, frozen=True, extra="forbid"):
    """A particle moving at a velocity."""

    velocity: float


def create_particles(count: int) -> tuple[Particle, ...]:
    """Create particles with random velocities.

    Args:
        count: How many particles to create.

    Returns:
        The new particles.
    """
    return tuple(Particle(velocity=random.random()) for _ in range(count))
```

The result depends on mutable state absent from the signature, and the `create_` verb promises an in-memory function while the module-level `random` functions read shared process state. Other callers or threads can change behavior at a distance. Passing a `Random` instance explicitly would make the effect honest, not pure.

### NEGATIVE — A mutable default argument keeps state between calls

```python
def create_flag_list(flag: str, flags: list[str] = []) -> list[str]:
    """Create a list of flags that includes ``flag``.

    Args:
        flag: The flag to add.
        flags: The flags already collected.

    Returns:
        The flags, including ``flag``.
    """
    flags.append(flag)
    return flags
```

The default list is created once, so every call that omits `flags` appends to the same list and sees the flags of earlier callers. The signature shows no such shared state, and the function also mutates its argument without saying so. Ruff reports the default as `B006`; do not silence it.

### POSITIVE — An immutable default and a new value

```python
lazy from collections.abc import Sequence


def create_flag_list(flag: str, flags: Sequence[str] = ()) -> list[str]:
    """Create a new list of flags that includes ``flag``.

    Args:
        flag: The flag to add.
        flags: The flags already collected; never modified.

    Returns:
        A new list holding ``flags`` followed by ``flag``.
    """
    return [*flags, flag]
```

## Service Locator Disguised as Injection

### NEGATIVE — The context hands out the global-shaped object

```python
def create_particles(
    context: ApplicationContext,
    count: int,
) -> tuple[Particle, ...]:
    """Create particles with velocities from the context's shared generator.

    Args:
        context: The application-wide bag of services.
        count: How many particles to create.

    Returns:
        The new particles.
    """
    random_source = context.services.randomness.select_shared_random()
    return tuple(Particle(velocity=random_source.random()) for _ in range(count))
```

Passing the global-shaped object does not reveal the function's actual requirements and grants access to unrelated authority.

## Protocol per Deterministic Helper

### NEGATIVE — Protocols that manufacture mocks

```python
from typing import Protocol


class AdditionService(Protocol):
    """A service that adds integers."""

    def create_sum(self, left: int, right: int) -> int:
        """Create the sum of two integers.

        Args:
            left: The first integer.
            right: The second integer.

        Returns:
            The sum.
        """
        ...


class StringTrimmer(Protocol):
    """A service that trims text."""

    def create_trimmed_text(self, value: str) -> str:
        """Create the text without surrounding whitespace.

        Args:
            value: The text to trim.

        Returns:
            The trimmed text.
        """
        ...
```

These `Protocol`s manufacture mocks rather than express real substitution or external authority. Call deterministic operations directly (`left + right`, `value.strip()`) and test their results.

## A False Type-Level Guarantee

### NEGATIVE — The return type certifies a mathematical falsehood

```python
def create_cross_product(left: UnitVector3, right: UnitVector3) -> UnitVector3:
    """Create the cross product of two unit vectors.

    Args:
        left: The first unit vector.
        right: The second unit vector.

    Returns:
        A vector claimed to have length one.
    """
    # Incorrect: the cross product has magnitude sin(theta).
    ...
```

Parallel unit vectors produce zero. A strong return type would certify a mathematical falsehood, and `UnitVector3` validates its length on construction, so the body could only fail at runtime or bypass validation. Return `Vector3`, or make normalization a separately named fallible operation.

## Validate and Forget

### NEGATIVE — The check returns nothing and the raw value travels on

```python
from safety_judge.errors import InvalidValueError


def validate_port(port: int) -> None:
    """Raise when ``port`` is privileged, then forget that it was checked.

    Args:
        port: The port number to check.

    Raises:
        InvalidValueError: When ``port`` is below 1024.
    """
    if port < 1_024:
        message = f"Port {port} is privileged. Provide a port from 1024 upward."
        raise InvalidValueError(message, context={"port": port})


def create_pool_with_released_port(
    free_ports: frozenset[int],
    port: int,
) -> frozenset[int]:
    """Create a pool that also holds ``port``.

    Args:
        free_ports: The ports currently free.
        port: The port to release into the pool.

    Returns:
        A new pool containing ``port``.

    Raises:
        InvalidValueError: When ``port`` is below 1024.
    """
    validate_port(port)
    return free_ports | {port}
```

The check learns that the port is non-privileged, returns `None`, and keeps the original `int`. Every later function must either trust undocumented history, repeat the check, or retain an error case that should already be impossible. Parse the primitive into a `NonPrivilegedPort` and make trusted operations accept that type. As in [parse-dont-validate.md](parse-dont-validate.md), the name `validate_port` is shown because it is the thing criticised; the repository's naming test would reject it.

Do not mechanically wrap every checked value. If the fact is temporary, contextual, or owned completely by one aggregate, preserve it in that boundary instead. The problem is discarded knowledge, not the spelling of the helper.

## A Stale Proof Token

### NEGATIVE — An empty receipt that anyone can construct

```python
class InitializationCompleted:
    """An empty receipt claiming that initialization happened."""


def update_system_initialization() -> InitializationCompleted:
    """Initialize the system and return a receipt.

    Returns:
        A receipt that carries no information about the initialized state.
    """
    return InitializationCompleted()


def update_resource(token: InitializationCompleted) -> None:
    """Use the resource, assuming it is still initialized.

    Args:
        token: The receipt from initialization, which proves nothing.
    """
```

An empty token proves nothing if it can be copied, constructed elsewhere (`InitializationCompleted()` is valid anywhere), or outlive the state it represents. Proof-bearing values must carry the live condition itself, such as the initialized resource, rather than a receipt that merely claims it. See [design-transformations.md](design-transformations.md#7-must-call-a-before-b).

## Effects Moved Outside Their Consistency Boundary

### NEGATIVE — Read, decide, and write in separate transactions

```python
lazy import sqlite3


def update_accounts_with_transfer(
    connection: sqlite3.Connection,
    command: TransferCommand,
) -> TransferBalances:
    """Move money between accounts without a transaction around the decision.

    Args:
        connection: An open database connection.
        command: The transfer to apply.

    Returns:
        The balances after the transfer.
    """
    current_balances = select_transfer_balances(connection, command)
    new_balances = create_balances_after_transfer(current_balances, command)
    update_transfer_balances(connection, command, new_balances)
    return new_balances
```

Another writer may change the accounts between the check and the write. Purity has introduced a time-of-check/time-of-use bug. Load or lock, decide, write, and commit inside the required transaction, as shown in [examples.md](examples.md#preserve-the-transaction-boundary).

## Parameter Bag Instead of a Concept

### NEGATIVE — Unrelated fields grouped only to shorten a signature

```python
import logging
from pathlib import Path

from pydantic import BaseModel


class DoEverythingOptions(
    BaseModel,
    frozen=True,
    extra="forbid",
    arbitrary_types_allowed=True,
):
    """Everything one operation might need."""

    user_identifier: str
    raw_sql: str
    retry_count: int
    send_email: bool
    output_path: Path
    logger: logging.Logger
```

The fields do not form one coherent value. The bag hides excessive responsibility and permits combinations that may not make sense.

## Primitive and Boolean Soup

### NEGATIVE — The call site hides units and boolean meaning

```python
insert_timer(None, "refresh", 5.0, True, False, True)
```

The call site does not communicate units or boolean meaning. Use semantic types, keyword-only parameters, or one cohesive options model when the configuration is genuinely one concept.

## Mechanical Helper Explosion

### NEGATIVE — Helpers that add navigation and nothing else

```python
def create_user_name(user: User) -> str:
    """Create the name of ``user``.

    Args:
        user: The user to read.

    Returns:
        The user's name.
    """
    return user.name


def create_user_name_is_blank(user: User) -> bool:
    """Create whether the name of ``user`` is empty.

    Args:
        user: The user to read.

    Returns:
        ``True`` when the name is empty.
    """
    return not create_user_name(user)
```

The helpers add navigation without adding vocabulary, policy, safety, reuse, or a meaningful testing boundary. Read `user.name` directly.

## Wrapper Ladder

### NEGATIVE — Pass-through layers

```python
def create_handled_response(request: Request) -> Response:
    """Create the response for ``request``.

    Args:
        request: The request to answer.

    Returns:
        The response.
    """
    return create_processed_response(request)


def create_processed_response(request: Request) -> Response:
    """Create the response for ``request``.

    Args:
        request: The request to answer.

    Returns:
        The response.
    """
    return create_executed_response(request)
```

Pass-through layers make local reasoning worse unless they translate a boundary, own policy, or create an actual contract.

## Weakest Syntax, Missing Semantics

### NEGATIVE — The loosest accepted type hides a two-pass algorithm

```python
lazy from collections.abc import Iterable


def create_value_range(values: Iterable[float]) -> tuple[float, float]:
    """Create the smallest and largest of ``values``.

    Args:
        values: The numbers to compare.

    Returns:
        The minimum and maximum.
    """
    return min(values), max(values)
```

The algorithm needs two passes. A generator passed as `values` is exhausted by `min`, so `max` raises a confusing `ValueError`. The weakest type the checker accepts is not automatically the most truthful. Ask for a `Collection` or `Sequence` when the algorithm genuinely needs repeated passes or stable indexing.

## Callback as Accidental Authority

### NEGATIVE — The callback may do anything

```python
lazy from collections.abc import Callable, Sequence


def update_items_with_callback(
    items: Sequence[Item],
    callback: Callable[[Item], None],
) -> None:
    """Call ``callback`` for each item in order.

    Args:
        items: The items to visit.
        callback: The operation to run for each item. It may block, re-enter this
            function, retain references to the items, or perform I/O.
    """
    for item in items:
        callback(item)
```

A callback makes the authority explicit but does not make the operation pure. Specify cancellation, re-entrancy, error, ordering, and backpressure semantics when they matter; prefer a generator when caller-controlled consumption is the better contract.

## Mocked External Semantics

### NEGATIVE — A mock stands in for a database

```python
from unittest.mock import MagicMock

repository = MagicMock()
repository.insert_record.return_value = None
```

This cannot prove uniqueness constraints, transaction isolation, SQL behavior, rollback, ordering, or connection failures. Use real hermetic adapters (`tmp_path`, an in-memory SQLite database) and shared contract tests where those behaviors matter.

## Common Rationalizations

| Rationalization | Reality |
| --- | --- |
| "Everything should be injectable." | Inject caller-owned policy, nondeterminism, or external authority; keep ordinary implementation details local. |
| "A `Protocol` makes it testable." | Deterministic concrete code is already testable through inputs and outputs. |
| "Invalid states should always be impossible." | Only encode invariants the type can establish and preserve without making legitimate restoration or evolution impossible. |
| "Effects belong at the top." | Effects belong at the narrowest boundary that preserves consistency, ownership, and lifecycle semantics. |
| "The weakest interface is most reusable." | The truthful interface includes semantic and performance guarantees, not only methods called today. |
| "Small functions are easier to read." | Functions are easier to read when they encapsulate meaningful concepts; wrapper ladders increase cognitive load. |
| "The mock passed." | A mock proves agreement with the mock, not the external system. |
