---
name: type-design
description: Use when creating, changing, or reviewing Python data models, public function inputs, domain identifiers, state unions, error and absence handling, or types adapted from pydantic models and external libraries in this repository.
---

# Type Design

Model data so invalid values and states are rejected at the highest boundary that can establish them. Optimize for the narrowest truthful contract, not the fewest type declarations.

## Work From The Owner

Before declaring a type, search for the model, primitive, schema, or upstream type that already owns the fact.

Derive in the direction of semantic ownership:

1. A pydantic model (or `TypeAdapter`) owns the data it validates; annotate with the model rather than redeclaring a parallel type.
2. A `StrEnum` or `Literal` owns a finite vocabulary; derive other types with enum members, `Literal[...]`, and `typing.get_args` instead of repeating the values.
3. A repository model or primitive owns shared semantics; import it instead of recreating it. Failures belong to the `SafetyJudgeError` hierarchy in `safety_judge.errors`, and process configuration and its vocabularies (`RuntimeEnvironment`, `LoggingLevel`) belong to `safety_judge.settings`.
4. An external library type owns only the guarantees its API actually makes. When the application owns a stricter invariant, define the application model and adapt it once at that boundary.

Python has no `satisfies`. `Final` keeps the narrowest inferred type of a constant, `typing.assert_type` pins what the checker infers, and passing a value where a `Protocol` is expected proves structural conformance without widening the value. Use them only when they state the real contract. Do not derive a domain contract from an incidental implementation, such as the inferred return type of a helper or `type(value)` of a sample object, merely because it is easy to reference.

## Constrain The Entry Point

Put an invariant on the highest public input that can establish it, then preserve that type through the dependency cone. Do not accept a broad value, process it, and cast or reject it in a leaf.

When a foreign API is intentionally broader:

- expose a narrow application wrapper;
- derive downstream types from the application model; and
- widen or assert only inside the foreign adapter, with the reason documented.

Use an exhaustive `typing.assert_never` default once a discriminant reaches internal control flow. A fallback is not a substitute for constraining an application-owned caller.

## Model Meaning, Identity, And State

- Give durable domain identifiers a distinct `typing.NewType` by default when equal runtime primitives are not interchangeable. `UserIdentifier` and `ProductIdentifier` must not both reduce to plain `str` aliases.
- Construct identity types at centralized validation or hydration boundaries, such as a pydantic model field or a `TypeAdapter`. Never scatter `UserIdentifier(...)` wraps of raw strings.
- Keep identity types distinct from validated values: an identifier answers “which kind of entity?”, while an `Annotated[str, ...]` constrained value answers “which invariant has this value passed?”
- Use discriminated unions when fields vary by state: frozen pydantic models that each carry a `Literal` discriminator, combined as `Annotated[A | B, Field(discriminator="kind")]`. Each branch contains exactly the data valid in that state; consume the union with `match`.
- Signal failure by raising the narrowest fitting subclass of `SafetyJudgeError`, chained with `from` and documented under `Raises:`. This repository has no `Result` type.

Model absence deliberately; this repository has no `Option` type, so absence is `X | None`:

| Meaning | Shape |
| --- | --- |
| The caller may omit the argument or field | default `None` (or a default value): `field: T | None = None` |
| The field is part of the stable model but may have no value | required `field: T | None` with no default |
| Explicit empty differs from missing | a documented sentinel, or `model_fields_set` for pydantic models |

## Use Python's Vocabulary

Prefer built-ins when they preserve the model:

| Need | Tools |
| --- | --- |
| Describe a mapping with known keys and per-key requiredness or mutability | `TypedDict` with `Required`, `NotRequired`, `ReadOnly` |
| Declare a constant that must not be rebound | `Final` |
| Close a set of values | `Literal`, `StrEnum` |
| Narrow in a reusable check | `TypeIs`, `TypeGuard` |
| Describe a structural contract | `Protocol` |
| Return the receiver's own type | `Self` |
| Mark an unreachable branch | `Never`, `typing.assert_never` |
| Keep identities distinct | `NewType` |
| Attach a constraint to a type | `Annotated` |
| Hold an immutable record | frozen `dataclass(slots=True, kw_only=True)` or a frozen pydantic model |
| Forward a callable's signature | `ParamSpec`, `Unpack` |
| Accept a subset of fields | a separate update model whose fields are all optional |

An all-optional update model is correct only when every independently omitted field is a valid value for that boundary. Python has no `Partial`, and copying every field of another model into optional fields is the same mistake. Otherwise define the operation's actual input as an explicit model holding only the fields the operation owns.

## Verify The Contract

Add compile-time usage tests for consequential boundaries: accepted examples use `typing.assert_type`, and rejected examples carry `# pyright: ignore[reportArgumentType]` (or the precise rule) followed by `-- reason`. This repository disables `# type: ignore` and reports unnecessary pyright ignores (`reportUnnecessaryTypeIgnoreComment`), so an ignore that stops being needed fails exactly like a stale expected-error directive. Add runtime tests with `pytest.raises` when a model or constructor validates real input. Re-run pyright for immediate consumers after changing a shared model.

## Stop Signs

| Rationalization | Required response |
| --- | --- |
| “Keep the public type broad; narrow it where it is consumed.” | Move the invariant to the caller boundary that can establish it. |
| “A cast is the smallest diff.” | Model the source correctly; isolate an unavoidable `cast` at an adapter. |
| “A local result tuple or status flag is faster.” | Raise from the repository's `SafetyJudgeError` hierarchy and use `X | None` for absence. |
| “Making every field optional keeps this flexible.” | Name the exact fields the operation accepts. |

## Labeled Examples

**REQUIRED REFERENCE:** Read [references/examples.md](references/examples.md) before making a consequential type-model decision. Treat each `POSITIVE` and `NEGATIVE` label as acceptance data and follow its decisive evidence rather than copying its surface syntax.

Apply `function-decomposition` to functions using the model and `document-code` to the resulting program units.
