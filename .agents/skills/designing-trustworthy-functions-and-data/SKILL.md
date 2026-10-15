---
name: designing-trustworthy-functions-and-data
description: Use when designing, implementing, refactoring, or reviewing Python functions, pydantic domain models, and APIs in this repository that have hidden dependencies (module globals, the clock, random sources, environment variables), discarded validation knowledge, invalid states, mixed abstraction levels, excessive mocking or Protocols, unclear I/O boundaries, primitive-heavy signatures, or code that is difficult to test and understand locally.
---

# Designing Trustworthy Functions and Data

A trustworthy design makes functions and data tell the same truth. Functions expose what they need, can change, return, and may fail to do. Data preserves facts the system has already established so downstream functions do not re-check them or carry impossible error branches.

The governing balance is:

> Parse raw input into the smallest representation that preserves what was learned, then make every function ask for exactly the data, authority, and guarantees it requires.

## Know Whether the Function Is Honest

“Honest” and “dishonest” are the source video's pragmatic terms, not moral judgments and not standard Python terminology.

An **honest function** exposes every operationally meaningful input, output, mutation, and external capability through its signature. A caller can see what determines the result and what the operation may affect without opening the body.

A **dishonest function** reaches beyond its signature for meaningful state or authority: a module-level global, the shared `random` generator, the system clock, `os.environ`, a service locator, process state, a hidden cache, the filesystem, the network, or a mutable singleton. Its apparent contract is smaller than its real contract.

Honesty is related to purity, but they ask different questions:

| Question | Concern |
| --- | --- |
| Pure or impure? | Does evaluation have observable side effects, and is the result referentially transparent? |
| Honest or dishonest? | Does the signature reveal the operation's real inputs, outputs, effects, and authority? |

Therefore:

- `def create_total(values: Sequence[int]) -> int` can be pure and honest.
- `def remove_disabled_accounts(accounts: list[Account]) -> int` is impure but honest when its mutable parameter type, its returned count, and its docstring state what changes. `values.sort()` is the same idea: the receiver is the only thing it changes.
- `def insert_event_line(output: TextIO, event: Event) -> None` is impure but honest about where it writes.
- `def select_current_time() -> datetime` is dishonest under this model because the clock input is hidden.
- `def create_populated_world(world, count, random_source: Random)` is honest but not pure: it advances `random_source`. The same function calling the module-level `random.random()` is dishonest, because shared generator state is absent from the signature.

Python has no `&mut` marker, so hidden mutation is easy: a parameter typed `Sequence[...]` or `Mapping[...]` promises read-only use, and a function that mutates it anyway is dishonest. Prefer returning a new value. When mutation is the contract, type the parameter as `list`, `dict`, or `MutableSequence`, return `None` or a count, and say so in the docstring.

Honesty does not guarantee determinism, safety, correctness, or faithful tests. An explicitly passed HTTP client, clock, `Random` instance, callback, or database connection still performs real effects. Honesty makes those effects visible so ownership, testing, and reasoning can be deliberate.

Dishonesty is also contagious: a function that calls a hidden clock or global service acquires that undeclared dependency itself. Move the dependency into the signature or keep the call inside a deliberately effectful boundary.

Do not try to eliminate all dishonesty. Programs must eventually read clocks, receive framework calls, access files, use networks, and affect the world. Contain that necessary dishonesty in small boundary adapters, then pass explicit values or capabilities inward—unless a transaction, lock, stream, retry, or durable workflow requires the effect and decision to stay together. `select_application_settings` in `safety_judge.settings` is the repository's model of such an adapter: it alone reads the process environment and the `.env` file, and everything else receives the frozen `ApplicationSettings` it returns.

Draw the line at operationally meaningful dependencies. Do not pollute signatures with incidental physical influences such as allocation behavior, garbage-collection timing, scheduler timing that is irrelevant to the contract, or CPU temperature.

Common Python tells and their visible replacements:

| Hidden input or change | Visible replacement |
| --- | --- |
| `datetime.now()`, `time.time()`, `time.monotonic()` | A `now: datetime` value, or a `Clock = Callable[[], datetime]` parameter when the function legitimately reads time repeatedly |
| `random.random()` and the other module-level `random` functions | A `random.Random` parameter: `SystemRandom()` in production, a small fake in tests |
| `uuid.uuid4()` | An identifier passed in, or a `Callable[[], UUID]` when the function creates many |
| `os.environ`, `os.getenv` | A `Mapping[str, str]` or the parsed `ApplicationSettings` |
| `Path.cwd()`, `Path.home()`, relative paths | A `Path` resolved at the boundary |
| Module-level mutable state, or a hidden cache whose contents change the result | A parameter, or the aggregate that owns the state |
| A mutable default argument such as `items: list[str] = []` | A required parameter, an immutable default such as `()`, or `None` replaced by a fresh value inside the function |
| `print(...)` to the process's standard output | A `TextIO` parameter, or return the text |
| Mutating an argument the signature presents as read-only | Return a new collection, or declare the mutation as described above |

- Read [references/examples.md](references/examples.md) when implementing or refactoring.
- Read [references/non-examples.md](references/non-examples.md) when reviewing abstractions, dependency injection, strong types, parameter objects, or function extraction.
- Read [references/decision-guide.md](references/decision-guide.md) when the correct effect boundary, input shape, invariant owner, or extraction boundary is uncertain.
- Read [references/design-transformations.md](references/design-transformations.md) for paired Python refactors from misleading or overpowered functions to trustworthy designs.
- Read [references/parse-dont-validate.md](references/parse-dont-validate.md) when a validator returns `None` or a `bool`, checks recur, domain functions retain impossible error cases, or raw primitives cross trusted boundaries.
- Read [references/video-notes.md](references/video-notes.md) for the source video, timestamped notes, qualifications, and corrections behind this skill.
- Use `type-design` for the shape of models, identifiers, and absence, `function-decomposition` for extraction mechanics, and `error-messages` for the wording of the errors raised at a parse boundary.

## Design the Contract Before the Body

Start with the call site that should exist. State the operation in one sentence, then inventory:

- required values and semantic guarantees
- mutable inputs and observable outputs
- errors, absence, and partial failure
- preconditions, postconditions, and preserved invariants
- time, randomness, environment, filesystem, network, process, framework, or global state
- resource lifetime (who closes it), ordering, transaction, cancellation, backpressure, and performance requirements

Do not make the signature describe the current implementation by accident. Make it describe the durable contract a caller must understand.

## Make Dependencies and Effects Visible

Keep deterministic domain decisions separate from environmental work when that separation preserves the real semantics. Framework callbacks and entry points should translate framework-owned control flow into application-owned operations quickly.

Prefer the smallest honest input:

1. Pass an ordinary value when the function only needs a snapshot such as `now`, an identifier, or settings.
2. Pass a callable for one narrow operation that genuinely varies, such as a `Clock`.
3. Use an existing capability such as `Iterable`, `TextIO`, `Random`, `Path`, or a `Mapping` of environment variables when its semantics fit.
4. Keep a concrete collaborator when substitution adds no useful control.
5. Define a consumer-owned `Protocol` only when a stable multi-operation capability has two real implementations. One implementation plus a test fake is a concrete class or a plain function parameter, not a `Protocol`.

Wire environmental implementations at a visible composition boundary. A service locator, application context, or dependency bag hides dependencies even when it is passed as an argument.

Place effects at the narrowest correct consistency boundary—not mechanically at the root of the call tree. Keep reads, decisions, and writes together when a transaction, lock, stream, retry, or durable workflow requires their ordering or shared lifetime.

## Name Which Side of the Boundary a Function Is On

The repository's function-name vocabulary doubles as an honesty signal. `tests/test_naming_conventions.py` requires the first word of every module-level function in the package to be one of seven verbs:

| Verbs | Side | Meaning |
| --- | --- | --- |
| `select_`, `insert_`, `delete_`, `update_`, `rename_` | Edge | I/O against a store or the environment: a file, database, network, environment variable, the clock, or a random source |
| `create_`, `remove_` | Core | In-memory construction or derivation from the arguments |

- A function that mixes both usually splits into an edge and a core. The edge gathers raw inputs, calls the core to decide, and applies the result: `select_session_status_response` reads the clock, calls `create_session_status`, and builds the response.
- The verb is a promise about the body. A `create_` function that calls `datetime.now()`, `random.random()`, or `os.environ` lies by name. Pass the value in, or rename the function `select_` and keep it at the edge.
- The verb says an edge exists, not which capabilities it uses. `select_current_session_status(session)` is named honestly and still has a dishonest signature, because the clock is not a parameter.
- A function that draws from a passed `Random` instance can stay `create_`: the generator is in-memory state the caller supplies. A function that calls a passed `Clock`, writes to a passed `TextIO`, reads a `Path`, or runs SQL on a passed connection reaches outside the process, so it is an edge.
- Queries over in-memory data derive an answer, so they are `create_` too: `create_asset_type_match`, `remove_expired_entries`.
- A `create_` or `remove_` function is in-memory, not necessarily pure: `remove_disabled_accounts` mutates its argument, and a function that advances a `Random` is not referentially transparent. Honesty still requires that the change be visible.

## Ask for the Right Amount of Power

Ask for the least powerful interface that still communicates the real semantic and performance contract:

- an `Iterable` when only one-pass traversal is required
- a `Sequence` when indexing, `len`, or repeated passes over read-only data are required (a `Collection` when only `len` and repeated iteration are needed)
- a `Mapping` for read-only lookup
- a concrete collection such as `list` or `dict` when retention, mutation, capacity, or representation is part of the operation
- a cohesive frozen domain model when its behavior or invariants matter
- individual values when passing the whole object would expose unrelated authority

Do not generalize a parameter merely because today's loop happens to pass the type checker against a weaker type. Repeated passes, stable indexing, ordering, allocation, and asymptotic cost are legitimate requirements. A generator passed as an `Iterable` is exhausted by its first pass, so a function that iterates twice must ask for a `Collection` or `Sequence`.

Use a parameter model when its fields form one coherent concept or meaningful option set. Keyword-only parameters (`*`) are enough when a few arguments only need readable call sites. Neither is a cure for an operation that owns too many unrelated responsibilities.

## Parse at Boundaries and Preserve What You Learn

Treat parsing broadly: it transforms less-structured input into more-structured data or fails. The input may be text, but it may also be a primitive, collection, deserialized record, database row, framework object, or foreign type.

Prefer:

```text
raw input -> fallible parser -> invariant-bearing value -> infallible domain operations
```

over:

```text
raw input -> validate and return None (or a bool) -> keep using raw input -> re-check or propagate impossible errors
```

A `validate_*` or `is_valid_*` function that returns no refined value is a design smell when the caller continues using the original weak type. The check learned something, but the program discarded the proof. Return a type that preserves the fact, or parse directly into the aggregate that owns it.

Choose the proof owner deliberately:

- Use a value type when the guarantee is intrinsic to the value, appears across functions, or should travel through returns, fields, collections, and APIs.
- Use a frozen aggregate model when the rule is meaningful only as membership or state inside that aggregate and every construction path validates it.
- Use a transaction, lock, lease, version-checked write, or stateful operation when the fact depends on mutable external state and can become stale. Do not encode a temporary observation as a permanent value guarantee.

Keep fallibility at raw boundaries such as CLI parsing, settings, HTTP, files, databases, JSON deserialization, and framework input. Once parsing succeeds, core operations should not retain the same validation error unless they genuinely accept weaker input again.

Parsing does not justify a wrapper automatically. The parsed representation must remove checks, prevent misuse, clarify meaning, or make downstream operations total. Avoid generic `Validated[T]` markers that fail to name the established fact.

## Encode Only Invariants the Design Can Preserve

A dedicated type is earned when an invariant is consequential, stable, repeatedly needed, and enforceable through every construction and mutation path.

For an invariant-bearing type:

- make it a frozen pydantic model so no code reassigns a field after validation
- make every construction path validate: field constraints and validators live on the model, not in a separate check callers may skip
- define failure precisely: a documented `SafetyJudgeError` subclass raised at the `create_*` boundary, chained from pydantic's `ValidationError`
- route `model_validate`, `model_validate_json`, database restoration, and foreign input through the same model
- expose only operations that preserve the invariant, or return a weaker type
- make legitimate access to the underlying value ergonomic, such as a plain field
- test construction, rejection, preservation, and bypass paths, including `model_construct` and `model_copy(update=...)`, which skip validation

An `Annotated[str, StringConstraints(...)]` alias constrains parsing inside a model or `TypeAdapter`, but pyright reads it as plain `str`. When downstream signatures must carry the proof, accept the frozen model (like `TextLabel`). Use `typing.NewType` for identity, not for validation: it separates kinds of identifiers but anyone can call it on any value.

The parser should return the invariant-bearing type rather than `None`. Once constructed, functions should accept that type and omit redundant checks and corresponding impossible error branches.

Never strengthen a parameter or return type because a theorem, lifecycle fact, or domain assumption merely sounds plausible. Verify that the implementation can prove and preserve the claim. Prefer runtime validation or a weaker result when the type system would encode a lie.

## Keep One Conceptual Level Per Function

A function may orchestrate several sibling operations or implement one detailed operation. It should not repeatedly alternate between domain intent and low-level bytes, indices, protocol mechanics, storage representation, or handwritten algorithms.

Extract a cohesive block when the new function:

- names a real operation or policy
- encapsulates an invariant or representation rule
- isolates a meaningful effect
- removes distracting lower-level machinery
- creates a useful contract or testing seam
- has meaningful reuse

Keep short local control flow together when extraction would only add navigation. A helper whose name restates its body has not created an abstraction.

Prefer standard-library and established repository operations over reimplementing algorithms inside domain code. Repeated normalization, ordering, lookup, or parsing rules may reveal a missing data structure rather than a need for more scattered helpers.

## Let the Representation Enforce the Contract

Do not assume the current representation deserves to survive the refactor. Before improving its helpers or algorithms, separate:

- behavior the domain actually requires
- constraints imposed only by the current representation
- per-value invariants such as validity, canonical form, or units
- relationship invariants such as uniqueness, association, ordering, or queue discipline

Choose the smallest natural owner for each real invariant. A frozen model can make each value valid by construction. A standard collection can provide relationships and operations such as unique-key lookup. Compose those owners when the contract contains both kinds of invariant; solving one does not solve the other.

For example, replacing a sorted list with a `dict` can remove sorting and search policy, but a `dict[str, AssetType]` still does not prove that its keys are valid or canonical. Conversely, a validated key model does not by itself provide association or efficient lookup. A `dict` keyed by the validated model lets both structures do the work they naturally own.

Prefer this structural composition over comments, call-site conventions, duplicated normalization, defensive checks, wrapper ladders, or custom algorithms. Add an outer domain collection class only when it owns additional behavior or policy beyond what its field types already guarantee.

Judge simplicity by the total policy burden left in the system, not by the number of types. One small invariant-bearing model plus one standard collection may eliminate more complexity than a primitive collection surrounded by helpers.

## Make Every Abstraction Earn Its Cost

Before keeping a new function, wrapper class, `Protocol`, generic, parameter model, callback, fake, or plan type, name what it buys:

- a truthful contract
- prevention of an important invalid state
- controlled nondeterminism or external authority
- preservation of ownership or consistency
- reusable policy
- materially better local reasoning or testing

If it buys none of these, remove it. Test deterministic code by calling it with values and checking results before adding fakes, and prefer a hand-written fake or a plain function parameter over `unittest.mock`. Test databases, networks, filesystems, transactions, and framework wiring with the highest-fidelity safe implementation practical, such as `tmp_path` or an in-memory SQLite database; an injected `Protocol` or a `Mock` does not reproduce external semantics.

## Review the Result

Before completion:

1. Read the call site without opening the implementation. Confirm that intent and required guarantees are apparent.
2. Confirm every meaningful dependency and effect is visible without a service locator or hidden global.
3. Confirm each function's verb (`select_`, `insert_`, `delete_`, `update_`, `rename_` versus `create_`, `remove_`) matches which side of the boundary its body is on.
4. Confirm the function receives no unrelated authority.
5. Confirm every strong type states a true invariant and all construction paths preserve it.
6. Search for validators returning `None`, `bool` validity checks, and repeated guard clauses. Confirm each learned fact is either preserved in a type or intentionally confined to an aggregate or live consistency boundary.
7. Confirm errors occur where weak input becomes strong data, not throughout functions that already receive proven values.
8. Name the owner of every remaining invariant. Reject invariants owned only by comments, duplicated helpers, or caller discipline.
9. Confirm the representation does not preserve accidental requirements such as sorting or indexing when the domain only needs association or lookup.
10. Confirm transaction, lock, resource lifetime, ordering, cancellation, and performance behavior survived decomposition.
11. Remove mechanical helpers, speculative `Protocol`s, wrapper ladders, and interaction-only test seams.
12. Use `self-explanatory-tests` to prove the contract, invariant boundaries, deterministic core, and effectful adapters at appropriate fidelity.
13. Run the repository's focused checks (`ruff`, `pyright`, `pytest`) and normal verification commands.
