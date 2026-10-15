---
name: self-explanatory-tests
description: Use when writing, reviewing, organizing, or debugging pytest tests in this repository, assessing test completeness, or shaping types and dependency boundaries so important behavior can be tested honestly in Python.
---

# Self-Explanatory Tests

Tests are executable contracts for future maintainers and agents. A failure should identify the broken behavior without requiring the reader to reconstruct what the original author intended.

- Read [references/examples.md](references/examples.md) when authoring or reorganizing tests.
- Read [references/non-examples.md](references/non-examples.md) when reviewing tests, diagnosing brittle coverage, or considering a mock, a patch, or a lint exception.
- Read [references/design-and-seams.md](references/design-and-seams.md) when tests expose a weak invariant, hidden dependency, awkward abstraction, or uncertain coverage boundary.
- Read [references/sources.md](references/sources.md) when the policy or test strategy is disputed.
- Use `designing-trustworthy-functions-and-data` before changing production types, dependencies, effects, or function boundaries in response to test pressure.

## Name the Contract First

Do not write a test until you can state the behavior it protects and the evidence for that expectation. Ground truth can come from an explicit user decision, public API or CLI contract, schema, verified documentation, existing behavior, or a reproduced bug. Do not encode guessed behavior.

Before RED, identify:

- the behavior contract
- the smallest stable boundary that exposes it
- inputs and observable outputs, effects, or errors
- the highest-fidelity deterministic dependency available
- what the test intentionally does not protect
- the command that will prove RED and GREEN, for example `uv run pytest tests/test_settings.py -k <name>`

For a small unit test, the test name and arrangement may make this packet self-evident. Record it explicitly for bug regressions, integration tests, ambiguous behavior, or mock or patch use.

## Map the Test Obligations

Do not equate completeness with one test per function, method, or module. Completeness means every meaningful promise has an owner, an enforcement mechanism, and credible evidence.

Inventory the obligations relevant to the change or system:

- domain rules, invariants, assumptions, and preconditions
- accepted, rejected, boundary, degenerate, and malformed inputs
- state transitions, lifecycle rules, side effects, and required non-effects
- success, failure, partial failure, retry, recovery, and cancellation
- persistence, serialization, parsing, and round trips
- ordering, duplication, idempotence, concurrency, and resource limits
- permissions, privacy, security, and unsafe boundaries
- time, randomness, environment, filesystem, network, and process behavior
- compatibility, migration, performance, and error contracts when they are part of the promise

Scale the inventory to the work. A small pure function may need only a few cases; a stateful or external workflow needs an explicit obligation map. For consequential work, record:

| Obligation | Owner | Enforcement | Test evidence | Remaining gap or status |
| --- | --- | --- | --- | --- |

An obligation may be covered, not applicable with a reason, or deliberately deferred with a named risk and explicit approval. Do not silently omit it. A type, constructor, parser, database constraint, or static type check may enforce an obligation, but tests should still prove that the enforcement boundary accepts, rejects, and preserves the right states at runtime. Pyright checks annotations before the program runs; it does not check the values that arrive from an environment variable, a file, or a network response.

## Let Tests Pressure the Design

Tests provide evidence that an invariant is enforced; they should not be the only thing enforcing it.

When a test must repeatedly establish or check the same assumption:

1. Name the invariant and the type or component that should own it.
2. Ask whether invalid states can be made unrepresentable with a dedicated type or lifecycle state.
3. Otherwise, validate once at the earliest trustworthy boundary and carry a trusted value inward.
4. Make later APIs accept the trusted type instead of raw input.
5. Test construction, rejection, invariant preservation, and every path that could bypass the boundary, including parsing, deserialization, or direct construction.

Repeated validation, elaborate fixtures, or inaccessible behavior are design evidence. Look for a missing constructor, parser, state machine, domain type, or dependency boundary before adding more test machinery. If redesign is outside the authorized scope, add the best regression test available and record the unenforced assumption as design debt; do not leave both the design and the behavior unprotected.

Test pressure does not authorize a mechanically purer architecture. Preserve transactions, locks, ownership, ordering, cancellation, backpressure, and external-system semantics. Use `designing-trustworthy-functions-and-data` to select the production boundary, then use this skill to prove its contract.

## Choose the Test Boundary

- Write pytest function-style tests under `tests/`, one `test_<module>.py` per source module by default. Put shared fixtures in `tests/conftest.py`.
- Import the package by its public path, for example `from safety_judge.settings import select_application_settings`. `uv sync` installs the package into the virtual environment, so tests exercise the public API. This repository has no in-module unit-test convention; do not put test code under `src/`.
- Test observable behavior. Python does not enforce privacy, so a test can import an underscore-prefixed name; that access is not permission to freeze private helpers, call order, data structures, or module decomposition.
- Choose a boundary that survives a behavior-preserving refactor. If moving or renaming a helper would break the test while behavior stays the same, the test is probably too coupled.
- For a bug, reproduce the symptom, trace it to the deepest violated promise, and protect that promise rather than the first visible workaround.
- When the promise is a rule about the code rather than the behavior of one module, test the rule by scanning the source. `tests/test_naming_conventions.py` does this with `ast`, and it fails with the offending names and the vocabulary to use.

Use the layout shown in [references/examples.md](references/examples.md). Do not create sibling `*_test.py` files, test classes, or a `tests/__init__.py` by default; `--import-mode=importlib` imports each test file by path. Under that mode one test module cannot import another, so share setup through fixtures in `tests/conftest.py` rather than helpers imported from a test file. Extract unusually large shared test support beyond `tests/conftest.py` only when a real project requires it.

## Design Honest Test Seams

Make dependencies explicit when they introduce IO, nondeterminism, external state, dangerous side effects, or a meaningful ownership boundary. Dependency injection is a means of controlling those dependencies, not a requirement to abstract every collaborator.

Honest does not mean pure. A function may mutate an explicit argument, consume a random source, write through a supplied destination, or use a transaction and still be honest because its authority and effects are visible in the signature. Tests must control or observe those declared effects; do not assume explicit injection makes them deterministic or faithful to production.

Prefer the smallest honest seam:

1. Pass a value when the decision only needs data such as the current time or a generated identifier.
2. Pass a function for one narrow operation.
3. Use a small, consumer-owned `Protocol` for a coherent capability that genuinely varies.
4. Keep a concrete type when substitution would add no useful control or clarity.

Wire real implementations at a visible composition boundary. Do not hide dependencies in global state, service locators, generic context objects, or DI containers. Do not create one `Protocol` per class, expose private choreography, or add factories solely so a test can count calls. An abstraction is earned when it expresses a stable capability, ownership boundary, or legitimate substitution, not merely because mocking tools prefer it.

Passing a dependency makes it explicit; it does not make it deterministic or faithful. Prefer an ordinary supplied value when the decision needs only a snapshot, and do not move reads or writes outside the transaction, lock, stream, or workflow boundary that gives them meaning.

Prefer passing a capability as an argument over patching. `monkeypatch.setattr` replaces a name inside a module, so the test then depends on where production looks that name up, which is a call-graph detail rather than a contract. Patch only at a documented seam: `monkeypatch.setenv` for a setting the module documents as read from the process environment, or `monkeypatch.setattr` for a module-level constant or hook the module documents as replaceable. `monkeypatch` undoes every change when the test ends.

Then prefer the highest-fidelity implementation of the seam that remains safe and deterministic:

1. Real local implementation, such as `tmp_path` for the filesystem and `monkeypatch.setenv` for environment variables.
2. Hermetic local service or emulator.
3. Maintained hand-written fake.
4. Recorded fixture.
5. Stub that returns values without asserting interactions.
6. Mock or recording fake, only when the interaction itself is the stable contract.

Dangerous side effects may justify replacing a real dependency, but they do not justify arbitrary interaction assertions. Do not mock because it is easier. A mock that restates the current call graph can pass while production is broken. If a mock is necessary, record why every higher-fidelity option is unsuitable and why the asserted interaction is itself a durable contract. Write fakes by hand rather than reaching for `unittest.mock`, so the substitute has behavior a reader can review. When a fake implements important semantics, run shared contract tests against the fake and real implementation when practical, for example with a parametrized fixture, so the fake cannot quietly become a different system.

## Preserve the Lint Policy

The test-only exceptions are already encoded in `pyproject.toml` as ruff `per-file-ignores` for `tests/**`:

- D100 to D104: tests state their contract in test names, not docstrings.
- INP001: tests are imported by path, so `tests/` has no `__init__.py`.
- PLR2004: a literal expected value is the clearest assertion in a test.
- S101: bare `assert` is how pytest tests state expectations.

Every other ruff rule and pyright strict mode still apply to tests. Pytest runs with `filterwarnings = ["error"]`, `xfail_strict`, `--strict-markers`, and `--strict-config`, so a stray warning, an unregistered marker, or an xfail that unexpectedly passes fails loudly. Fix the cause. Assert an expected warning with `pytest.warns`.

Start each test module with a one-line docstring that states the contract the file exercises. Ruff does not require it for tests; it is there for the reader.

Do not weaken ruff or pytest settings, extend the `tests/**` ignores, or add local `# noqa` comments or warning filters to make tests pass. If a lint appears incompatible with a legitimate test, treat it as a deliberate change to the policy in `pyproject.toml`, reviewed on its own, instead of bypassing it.

## Make Failures Self-Explanatory

Treat a test failure as a developer-facing error message. As directly as the assertion surface allows, it should reveal:

- what behavior or operation failed
- why the result was expected
- what was actually observed or which source error occurred
- which input, fixture, identifier, or state matters for diagnosis

Keep the diagnostic audience distinct from the product audience. When testing a user-facing or machine-readable error contract, assert that boundary output separately; use the test's own assertion message to help a developer diagnose why the contract failed.

A strong test also:

- Names each test as a full sentence for the behavior and condition it proves, such as `test_a_misspelled_setting_is_rejected`.
- Keeps one coherent reason for failure per test.
- Chooses a comparison that explains itself. `assert actual == expected` on a list, set, or dict makes pytest show the differing items; `assert all(...)`, `assert any(...)`, or a bare boolean predicate reports `False` without saying which item or value broke the promise.
- Adds an assertion message when the default assertion output would not identify the broken contract: `assert condition, "message"`.
- Uses `pytest.raises(ErrorType, match=...)` for the message fragment that is part of the contract, then inspects `excinfo.value` for `code`, `context`, and `__cause__`.
- Fails explicitly only when the message identifies the failed operation, fixture, or assumption.
- Gives `pytest.mark.parametrize` cases `ids` so the report names the case that failed.
- Includes relevant inputs or observed output when they are needed to diagnose the failure.
- For stateful workflows, includes whether the expected state or artifact was preserved when that fact changes the diagnosis.
- Never exposes secrets or unnecessarily dumps large payloads merely to add context.

Name helper functions that are neither tests nor fixtures with the repository's function verbs. `insert_environment_file` in `tests/test_settings.py` writes a file, so it uses the IO verb `insert`. Test functions are sentences and are exempt from the verb vocabulary.

Do not wrap test failures in production error types; `SafetyJudgeError` subclasses belong to the package's boundaries. Tests may fail fast with a plain `assert`; the quality requirement is precise diagnostic context.

## Prove Red, Green, and Refactor

For new behavior or a bug fix:

1. Run the focused test before implementation and confirm it fails for the intended missing or broken contract, not malformed setup. An `ERROR` at collection or at setup, such as an import failure or a misspelled fixture name, is not RED; only a `FAILED` on the intended assertion is.
2. Make the smallest implementation change that satisfies the contract.
3. Run the focused test and confirm it passes.
4. Refactor without changing behavior, then rerun the focused and relevant broader tests.

When a test fails, classify it before editing: the test is wrong, the implementation is wrong, the design blocks honest testing, or the environment is broken. Do not turn a wrong test green by changing production behavior, and do not hide an implementation bug by weakening the assertion.

## Keep Tests Reliable

- Use fixed inputs, clocks, identifiers, and ordering when the behavior permits it.
- Use `tmp_path` for the filesystem, `monkeypatch` for environment variables, and `capsys` to observe what code writes to standard output or error, instead of real user data or machine state. The autouse fixture `remove_inherited_safety_judge_variables` in `tests/conftest.py` keeps the developer's environment from leaking into tests; when new code reads another ambient source, isolate that source in `tests/conftest.py` the same way.
- Keep tests safe to run in parallel; do not rely on execution order or shared mutable module globals.
- Exercise real behavior at the narrowest useful boundary.
- Keep reusable fixtures and builder functions explicit about the state they create.
- Prefer readable, behavior-sized setup over abstract helpers that hide the scenario. Repetition is acceptable when it keeps the contract visible.
- Make the correct fixture path the easiest path. If every author must remember a hidden setup rule, encode it in a fixture or builder, or fail at the earliest boundary with specific context. Build fixture values through the validating constructor, not `model_construct`, so a fixture cannot hold a state production could never create.

## Verify

Run the narrowest relevant test while iterating. Before completion, run the repository checks:

```bash
uv run ruff format
uv run ruff check
uv run pyright
uv run pytest
```

Read the actual failure output before reporting success. Warnings fail the run here, so a green run has none; a skipped or deselected test is not evidence that its behavior holds.
