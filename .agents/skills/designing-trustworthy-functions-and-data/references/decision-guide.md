# Function Design Decision Guide

Use this guide when several designs appear reasonable. The goal is not maximum purity, abstraction, or type strength. The goal is the smallest truthful contract that preserves the system's real semantics.

## Parse or Validate?

Ask what information the check learns and where that information must remain available.

| Situation | Default design |
| --- | --- |
| Raw input becomes a reusable domain value | A `create_*` parser that returns an invariant-bearing frozen model |
| A collection has a stable structural invariant | A frozen aggregate model whose validators check the structure, built by a `create_*` function |
| The fact matters only during one local calculation | Local checked branch; do not invent a durable type |
| The fact depends on mutable external state | Transaction, lock, lease, version-checked write, or stateful operation that keeps proof tied to reality |
| The type cannot preserve the claimed property | Return a weaker type or keep an explicit runtime check that raises |

Prefer `Model.model_validate`, `TypeAdapter.validate_python` or `validate_json`, `pydantic-settings`, or a named `create_*` function that wraps pydantic's `ValidationError` into a `SafetyJudgeError` subclass. A function such as `validate_value(value) -> None`, or `is_valid_value(value) -> bool`, is usually incomplete if callers continue passing `value` around in its original weak form.

Before adding a value type, ask:

- Does the guarantee travel through several functions, fields, returns, or collections?
- Will accepting the stronger type remove checks or error branches downstream?
- Is the property intrinsic and stable for the value's lifetime?
- Do all construction, deserialization, restoration, and mutation paths validate? Python has no private fields, so a frozen model plus the absence of `model_construct` and `model_copy(update=...)` on that type is the seal.

If the guarantee exists only inside one aggregate, parsing directly into that aggregate may be simpler. If an operation returns the element and downstream code benefits from knowing the guarantee, an element type is usually earned.

## Dependency Shape

| What the operation needs | Default shape | Escalate when |
| --- | --- | --- |
| One current fact | Ordinary value such as `now`, an identifier, or settings | The component legitimately obtains it repeatedly or owns its policy. |
| One narrow behavior | Callable parameter such as a `Clock`, or a plain function | It has a stable multi-operation capability or stateful lifecycle. |
| Standard traversal, I/O, or randomness | Existing `Iterable`, `TextIO`, `Random`, `Path`, or `Mapping[str, str]` for an environment | Domain semantics require a smaller consumer-owned contract. |
| Deterministic in-process collaborator | Concrete class or direct function | Two real implementations or ownership boundaries exist. |
| External authority or durable capability | Concrete adapter at the boundary | Two real implementations exist, and the consumer needs one stable contract: define a consumer-owned `Protocol`. |

Prefer values over services and existing interfaces over new `Protocol`s. Do not make a dependency substitutable unless substitution improves control or evidence. A test double alone is not a second implementation; a function parameter or a hermetic real adapter (`tmp_path`, in-memory SQLite) usually serves better.

## Effect Placement

Ask these questions in order:

1. Can the domain decision be expressed from ordinary supplied values?
2. Which component owns acquiring those values?
3. Must a read and later write observe the same transaction, lock, version, stream, or workflow state?
4. Can cancellation, retries, partial failure, or re-entry occur between the proposed layers?
5. Does moving the effect change ordering, atomicity, resource lifetime, or performance?

Separate deterministic calculation from action when the answers permit it. Name the halves by the repository vocabulary: the edge that reads and writes is a `select_`, `insert_`, `delete_`, `update_`, or `rename_` function, and the decision it delegates is a `create_` or `remove_` function. Otherwise keep the decision inside the narrow effectful boundary and test that boundary honestly.

## Invariant Type Test

Introduce a dedicated type only when most answers are yes:

- Would violating the invariant cause a meaningful bug or security/correctness failure?
- Is the invariant stable in the domain rather than incidental to one algorithm?
- Can all ordinary constructors establish it?
- Can every exposed operation preserve it or return a weaker type?
- Can parsing, deserialization, persistence restoration, and foreign input validate it?
- Will downstream code become materially simpler or safer?
- Is construction and access ergonomic enough that callers will not seek bypasses?
- Has the mathematical, lifecycle, or domain claim been independently verified?
- Does construction return the stronger type rather than merely reporting that the weaker input passed?
- Will downstream signatures use the stronger type so the proof is not immediately erased?

Use a checked function that raises a `SafetyJudgeError` subclass at an honest boundary, or an explicit validation result, when a wrapper would proliferate states, block legitimate restoration, or certify a condition that can become stale.

## Input Strength

Choose from semantic requirements, not abstract generality:

| Requirement | Likely Python shape |
| --- | --- |
| One-pass consumption | `Iterable[T]` |
| Repeated passes, `len`, or membership on read-only data | `Collection[T]` |
| Indexing or stable order on read-only data | `Sequence[T]` |
| Read-only lookup | `Mapping[K, V]` |
| Mutation of the caller's collection | `list[T]`, `dict[K, V]`, or `MutableSequence[T]`, documented, returning `None` or a count |
| Retention or growth | A concrete collection such as `list[T]` or `dict[K, V]` |
| Domain behavior and invariants | A cohesive frozen model |
| A small subset of unrelated state | Individual values or a narrow callable |
| Many coherent options | A frozen parameter model with required fields and `StrEnum` fields, or keyword-only parameters for a few |

Do not require a concrete collection out of habit. Do not erase requirements such as repeated traversal, stable indexing, or retention merely to accept more callers: a generator passed where two passes are needed silently yields nothing on the second pass.

## Extraction Test

A new function is usually justified when at least one is true:

- Its name adds domain or algorithmic vocabulary.
- It centralizes a policy or invariant.
- It separates a meaningful boundary or effect.
- It hides lower-level mechanics from a higher-level operation.
- It forms a stable independently testable contract.
- It replaces repeated logic whose copies could diverge.

Keep the code local when the proposed helper only:

- aliases an attribute access or obvious expression
- forwards arguments unchanged
- exists to reduce line count
- exposes private choreography for a mock
- requires a reader to chase files to understand one short operation

Comments that divide a function into phases are a review signal, not automatic proof of bad design. A transaction, parser, protocol, or performance-sensitive loop may be clearer as one auditable scope.

## Representation and Invariant Ownership

Before extracting helpers around an existing representation:

1. State the operation the domain needs without naming the current container or algorithm.
2. List every policy the implementation must remember: validation, canonicalization, uniqueness, ordering, searching, indexing, synchronization, or restoration.
3. Remove policies that exist only because of the current representation.
4. Assign each remaining invariant to the smallest natural owner.
5. Prefer a frozen model for per-value validity and a standard data structure for relationships between values.
6. Compose those owners when neither can enforce the complete contract alone.
7. Recheck every construction and restoration path; the representation must not be bypassed by deserialization, database loading, or bulk import.

Do not stop at the first local improvement. A standard search can remove handwritten index arithmetic while leaving normalization and sorting as conventions. A `dict` can remove sorting while leaving primitive keys invalid. A validated key can eliminate invalid names while leaving lookup encoded as a scan. Continue until each meaningful invariant has an explicit owner and the obsolete policy machinery can be deleted.

Do not add a wrapper merely to hide a standard collection. An outer domain collection class is earned when it owns additional operations, cross-entry invariants, persistence validation, or authority. Otherwise, composing an invariant-bearing key directly with the standard collection may be the clearest complete design.

## Output and Materialization

- Return a complete value when it naturally represents a bounded result.
- Return an iterator (often a generator function) when the result can be large, incremental, cancellable, or composable.
- Accept a callback when inversion of consumption is intentional and its error, re-entry, and cancellation behavior is defined.
- Mutate an explicitly supplied object when mutation is part of the honest contract and avoids misleading copies or allocations; declare it in the parameter type, the return value, and the docstring.

Check asymptotic payload size as well as container count. Storing all permutations of an `n`-item input requires `n!` results and usually `Theta(n * n!)` payload storage.

## Final Complexity Budget

For every new abstraction, complete this sentence:

> This exists because it ______, and a direct implementation would ______.

If the answer is only "makes mocking possible," "is cleaner," "might be reused," or "makes the function shorter," the abstraction has not yet justified itself.
