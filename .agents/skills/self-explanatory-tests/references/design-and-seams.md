# Design Pressure and Test Seams

Use this reference when a test is difficult to write, an invariant is repeatedly checked, or a dependency seems to require a large abstraction.

This reference translates design pressure into testing consequences. Use `designing-trustworthy-functions-and-data` to decide whether and how production types, dependencies, effects, or function boundaries should change. Test difficulty is evidence, not automatic authorization for a refactor.

## Build the Obligation Map

Start from promises, not files. One component may own several obligations, and one obligation may cross several components.

| Obligation | Owner | Enforcement | Test evidence | Remaining gap or status |
| --- | --- | --- | --- | --- |
| A confidence score lies between 0 and 1 | `ConfidenceScore` | Frozen model with a field constraint and a fallible `create_` function | Construction rejection cases plus preservation tests | Covered |
| A misspelled setting fails loudly | `ApplicationSettings` | `extra="forbid"` and a `ConfigurationError` raised at the boundary | Rejection cases for unknown names in the environment file and the process environment | Covered |
| Sessions expire at the deadline | Session policy | Pure comparison using an explicit current time | Boundary cases immediately before, at, and after the deadline | Covered |
| A notification is not duplicated after retry | Delivery workflow | Idempotency key and durable result | Retry test against a hermetic store and recording sink | Covered |
| Concurrent writers preserve ordering | Repository | Not yet established | None | Deferred only with named risk and approval |

The map is not paperwork for every helper. Use it when the work has multiple promises, state, external effects, safety implications, or meaningful failure modes. Its purpose is to reveal obligations that otherwise disappear between unit tests.

## Move Invariants into the Design

Suppose several functions accept a `float` but require a confidence score between 0 and 1. Repeating `if not 0.0 <= score <= 1.0` in callers and tests leaves the invariant distributed and easy to forget.

Prefer a `ConfidenceScore` frozen model whose field constraint rejects every other value, built through a `create_confidence_score` function that raises a repository error. Downstream functions accept `ConfidenceScore`, making the requirement visible and preventing unchecked construction through the ordinary API.

The type does not eliminate testing. It changes the test obligations:

- valid scores, including both bounds, are accepted
- out-of-range, non-finite, or otherwise invalid values are rejected as the contract requires
- every successfully constructed value satisfies the invariant
- operations that return `ConfidenceScore` preserve the invariant
- parsing and deserialization (`model_validate`, `model_validate_json`) cannot bypass the constraint
- unchecked construction such as `model_construct`, which skips validation, is isolated to the module that owns the type if it is genuinely necessary

The design enforces the invariant. The tests prove that the enforcement and preservation are correct.

Do not assume a stronger type is automatically safer. First verify the mathematical, lifecycle, or domain claim and confirm that every operation and restoration path can preserve it. For example, the sum of two confidence scores is not necessarily a confidence score, while their mean is. The honest return type of a sum is a plain `float`, unless the operation performs a separately named fallible conversion.

Pyright cannot see a value's range, so the annotation `ConfidenceScore` carries the promise only if every construction path validates. That is why the tests, not the annotation, show that the boundary cannot be bypassed.

## Inject the Value Before the Service

If a decision only needs the current time, pass the current time:

```python
status = create_session_status(session.expires_at, deadline)
assert status is SessionStatus.EXPIRED
```

This is dependency injection without an interface. It keeps the domain decision pure and gives the test exact control. Under the repository's function verbs, a function that reads the clock performs IO and would be a `select_` function, while a function that compares supplied values is a `create_` derivation; passing the value keeps the decision on the pure side.

Introduce a clock capability only when the component itself legitimately owns the act of obtaining time across multiple operations. Do not add a `Clock` protocol merely because one function reads one timestamp, and do not patch `datetime` to make that one read deterministic.

Use the same progression for randomness and identifiers: inject the resulting value first, a narrow generator function second, and a `Protocol` only when a coherent capability actually needs an owner.

## Make Capability Seams Consumer-Owned

When a workflow must perform an external effect, define the smallest capability the workflow needs in domain terms. For example, a reminder workflow may need `insert_reminder(reminder)`, not an entire HTTP client, SMTP client, provider SDK, or application context.

A good seam:

- names a stable domain capability
- makes failure explicit
- has no methods used only by tests
- can be implemented by the real adapter and a faithful fake
- does not expose transport choreography to the core
- is wired to the real implementation at a visible composition boundary

Do not invent a broad repository, manager, provider, or service abstraction before the consumer contract is known.

An explicit capability may still be nondeterministic, stateful, or unfaithful to production. Keep transaction, lock, ordering, cancellation, and backpressure behavior at the boundary that owns it. A repository mock does not prove database uniqueness, isolation, rollback, or query behavior.

## Choose the Double by Evidence Quality

- Use the real local implementation when it is safe and deterministic: `tmp_path` for files, `monkeypatch.setenv` for environment variables the code documents as input.
- Use a hermetic service or maintained fake when real wiring matters but remote effects do not.
- Use a fixture or stub when only a returned result matters.
- Use a recording fake or mock when the external interaction is itself the promise, for example when a dangerous charge must not be issued twice.

If the fake owns behavior such as uniqueness, transactions, ordering, or retry semantics, run the same contract suite against the fake and real implementation. A fixture declared with `@pytest.fixture(params=[...], ids=[...])` runs every test that requests it once per implementation. Otherwise the fake may make tests green by behaving more conveniently than production.

Prefer passing the capability as an argument over patching it into place. A patch ties the test to the name production happens to import, so a harmless move of that import breaks the test while behavior is unchanged. Control a documented seam instead: the process environment through `monkeypatch.setenv`, or a module-level constant or hook the module documents as replaceable through `monkeypatch.setattr`.

## Diagnose Test Pain

When testing is difficult, classify the pressure before adding an abstraction:

| Pressure | Likely response |
| --- | --- |
| Invalid values flow through many functions | Introduce a trusted domain type or boundary parser. |
| Time, randomness, or IDs make results unstable | Inject the value or narrow generator. |
| External effects are inseparable from decisions | Separate the pure decision from the effectful adapter. |
| A test patches a name inside the module under test | Pass the capability as an argument, or control the documented seam. |
| A mock needs many ordered expectations | Test a higher-level outcome or reduce choreography exposed by the seam. |
| The fixture requires unrelated system state | Reconsider component ownership or split the boundary by responsibility. |
| A fake repeatedly disagrees with production | Add shared contract tests or replace it with a higher-fidelity dependency. |

Test pain is evidence, not automatic authorization for a refactor. Keep redesign within the requested scope; otherwise preserve the behavior with a test and report the design debt.

Before separating a decision from an effect, verify that doing so does not create a time-of-check/time-of-use gap or break atomicity. The correct response may be a deterministic inner calculation called from inside a real transaction rather than moving the entire decision outside it.
